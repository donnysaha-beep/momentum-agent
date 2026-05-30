"""
Layer 0: Market Intelligence Agent — 7:30am IST Mon-Fri
Fetches global macro data and outputs layer0.json for downstream agents.

Data sources:
  - US markets close (S&P 500, Nasdaq, Dow) via yfinance
  - US VIX via yfinance
  - Crude oil + Gold via yfinance
  - India VIX via yfinance
  - FII/DII net flows via NSE India
  - GIFT Nifty proxy via SGX Nifty estimate from S&P 500 overnight
"""

import yfinance as yf
import pandas as pd
import requests
import json
import os
from datetime import datetime, date
import warnings
warnings.filterwarnings("ignore")

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
LAYER0_FILE = os.path.join(os.path.dirname(__file__), "layer0.json")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ── Fetch global markets ──────────────────────────────────────────────────────

def fetch_global_markets() -> dict:
    tickers = {
        "sp500":   "^GSPC",
        "nasdaq":  "^IXIC",
        "dow":     "^DJI",
        "us_vix":  "^VIX",
        "india_vix": "^INDIAVIX",
        "crude":   "CL=F",
        "gold":    "GC=F",
        "usd_inr": "USDINR=X",
        "nifty":   "^NSEI",
    }

    result = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or df.empty:
                result[name] = None
                continue
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
            close = df["close"]
            price   = float(close.iloc[-1])
            prev    = float(close.iloc[-2]) if len(close) >= 2 else price
            chg_pct = round((price / prev - 1) * 100, 2)
            result[name] = {"price": round(price, 2), "change_pct": chg_pct}
        except Exception as e:
            result[name] = None

    return result


# ── FII/DII flows from NSE ────────────────────────────────────────────────────

def fetch_fii_dii() -> dict:
    """
    Fetch FII/DII net equity flows from NSE India.
    Returns net buy/sell in crores.
    """
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/market-data/fii-dii-trading-activity",
        }
        session = requests.Session()
        # First hit the main page to get cookies
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        resp = session.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            fii_net = dii_net = None
            for row in data:
                cat = row.get("category", "").upper()
                if "FII" in cat or "FPI" in cat:
                    fii_net = float(str(row.get("netPurchasesSales", "0")).replace(",", ""))
                elif "DII" in cat:
                    dii_net = float(str(row.get("netPurchasesSales", "0")).replace(",", ""))
            return {"fii_net_cr": fii_net, "dii_net_cr": dii_net}
    except Exception as e:
        print(f"  FII/DII fetch failed: {e}")

    return {"fii_net_cr": None, "dii_net_cr": None}


# ── GIFT Nifty proxy ──────────────────────────────────────────────────────────

def estimate_gift_nifty(nifty: dict, sp500: dict) -> dict:
    """
    Estimate GIFT Nifty direction using:
    - S&P 500 overnight change (strong correlation with Nifty futures)
    - Previous Nifty close
    """
    try:
        if not nifty or not sp500:
            return {"estimated_open": None, "bias": "NEUTRAL"}

        nifty_close = nifty["price"]
        sp_chg      = sp500["change_pct"]

        # Rough correlation: Nifty moves ~0.5x S&P 500 overnight
        estimated_chg = sp_chg * 0.5
        estimated_open = round(nifty_close * (1 + estimated_chg / 100), 2)
        bias = "BULLISH" if estimated_chg > 0.3 else "BEARISH" if estimated_chg < -0.3 else "NEUTRAL"

        return {
            "estimated_open": estimated_open,
            "estimated_chg_pct": round(estimated_chg, 2),
            "bias": bias,
            "based_on": f"S&P 500 {sp_chg:+.2f}% overnight"
        }
    except:
        return {"estimated_open": None, "bias": "NEUTRAL"}


# ── Regime determination ──────────────────────────────────────────────────────

def determine_regime(markets: dict, fii_dii: dict, gift: dict) -> dict:
    """
    Weighted regime scoring:
      40% GIFT Nifty direction
      40% India VIX level + change
      20% FII/DII net flow
    """
    score = 0  # positive = bullish, negative = bearish
    confidence_factors = []

    # GIFT Nifty (40%)
    gift_bias = gift.get("bias", "NEUTRAL")
    if gift_bias == "BULLISH":
        score += 40
        confidence_factors.append(f"GIFT Nifty est. {gift.get('estimated_chg_pct',0):+.1f}% (bullish)")
    elif gift_bias == "BEARISH":
        score -= 40
        confidence_factors.append(f"GIFT Nifty est. {gift.get('estimated_chg_pct',0):+.1f}% (bearish)")
    else:
        confidence_factors.append("GIFT Nifty neutral")

    # India VIX (40%)
    vix_data = markets.get("india_vix")
    vix_spike = False
    if vix_data:
        vix_level = vix_data["price"]
        vix_chg   = vix_data["change_pct"]
        vix_spike = vix_chg > 8
        if vix_level < 15 and not vix_spike:
            score += 40
            confidence_factors.append(f"India VIX {vix_level} (calm)")
        elif vix_level < 20 and not vix_spike:
            score += 20
            confidence_factors.append(f"India VIX {vix_level} (normal)")
        elif vix_spike:
            score -= 40
            confidence_factors.append(f"India VIX SPIKE +{vix_chg:.1f}% (fear)")
        else:
            score -= 20
            confidence_factors.append(f"India VIX {vix_level} (elevated)")

    # FII/DII flows (20%)
    fii = fii_dii.get("fii_net_cr")
    dii = fii_dii.get("dii_net_cr")
    if fii is not None:
        if fii > 500:
            score += 20
            confidence_factors.append(f"FII buying Rs {fii:.0f} cr (institutional bullish)")
        elif fii < -500:
            score -= 20
            confidence_factors.append(f"FII selling Rs {abs(fii):.0f} cr (institutional bearish)")
        else:
            confidence_factors.append(f"FII flows neutral (Rs {fii:.0f} cr)")

    # Determine regime
    if score >= 60:
        regime = "BULL"
        size_multiplier = 1.0
    elif score >= 20:
        regime = "NEUTRAL"
        size_multiplier = 0.75
    elif score >= -20:
        regime = "CAUTION"
        size_multiplier = 0.5
    else:
        regime = "DANGER"
        size_multiplier = 0.0

    # Override: VIX spike always = DANGER
    if vix_spike:
        regime = "DANGER"
        size_multiplier = 0.0

    confidence = min(100, abs(score))

    return {
        "regime": regime,
        "confidence": confidence,
        "score": score,
        "size_multiplier": size_multiplier,
        "factors": confidence_factors,
    }


# ── Sector rotation ───────────────────────────────────────────────────────────

def determine_sector_posture(markets: dict, regime: str) -> dict:
    """
    Infer sector rotation from global macro signals.
    """
    prioritize = []
    avoid      = []

    crude = markets.get("crude")
    gold  = markets.get("gold")
    sp500 = markets.get("sp500")

    if crude and crude["change_pct"] > 1.5:
        prioritize.append("Energy")
        avoid.append("Aviation")
    elif crude and crude["change_pct"] < -1.5:
        avoid.append("Energy")
        prioritize.append("Aviation")

    if gold and gold["change_pct"] > 1.0:
        prioritize.append("Metals")

    if sp500 and sp500["change_pct"] > 0.5:
        prioritize.append("IT")  # IT follows US markets
    elif sp500 and sp500["change_pct"] < -0.5:
        avoid.append("IT")

    if regime in ("BULL", "NEUTRAL"):
        prioritize.extend(["Banking", "Infra"])
    elif regime in ("CAUTION", "DANGER"):
        avoid.extend(["Banking", "NewEconomy"])
        prioritize.append("Pharma")  # defensive

    # Deduplicate
    prioritize = list(dict.fromkeys(prioritize))
    avoid      = list(dict.fromkeys([s for s in avoid if s not in prioritize]))

    return {"prioritize": prioritize, "avoid": avoid}


# ── Trend type ────────────────────────────────────────────────────────────────

def determine_trend_type(markets: dict, regime: str) -> str:
    vix = markets.get("india_vix")
    if not vix:
        return "UNKNOWN"
    vix_level = vix["price"]
    vix_chg   = vix["change_pct"]

    if vix_chg > 8:
        return "HIGH_VOLATILITY"
    elif regime == "BULL" and vix_level < 15:
        return "TREND_DAY"
    elif regime in ("CAUTION", "DANGER"):
        return "MEAN_REVERSION"
    elif 15 <= vix_level <= 20:
        return "BREAKOUT_FRIENDLY"
    else:
        return "CHOPPY"


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(markets: dict, fii_dii: dict, gift: dict,
                 regime_data: dict, sector: dict, trend_type: str) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"  MARKET INTELLIGENCE REPORT — {date.today().strftime('%A, %B %d %Y')}")
    lines.append(f"  Layer 0 | Generated: {datetime.now().strftime('%I:%M %p')} IST")
    lines.append("=" * 65)
    lines.append("")
    lines.append(f"MARKET REGIME    : {regime_data['regime']}")
    lines.append(f"CONFIDENCE SCORE : {regime_data['confidence']}/100")
    lines.append(f"TREND TYPE       : {trend_type}")
    lines.append(f"SIZE MULTIPLIER  : {regime_data['size_multiplier']}x")
    lines.append("")

    lines.append("GLOBAL & INDIAN MACRO:")
    def mkt_line(name, label):
        d = markets.get(name)
        if d:
            sign = "+" if d["change_pct"] >= 0 else ""
            lines.append(f"  {label:<18}: {d['price']:>10,.1f}  ({sign}{d['change_pct']:.2f}%)")
        else:
            lines.append(f"  {label:<18}: N/A")

    mkt_line("sp500",     "S&P 500 (US)")
    mkt_line("nasdaq",    "Nasdaq (US)")
    mkt_line("us_vix",   "US VIX")
    mkt_line("india_vix","India VIX")
    mkt_line("crude",    "Crude Oil (WTI)")
    mkt_line("gold",     "Gold")
    mkt_line("usd_inr",  "USD/INR")
    mkt_line("nifty",    "Nifty 50 (prev)")
    lines.append("")

    lines.append("GIFT NIFTY ESTIMATE:")
    lines.append(f"  Estimated open : {gift.get('estimated_open', 'N/A')}")
    lines.append(f"  Est. change    : {gift.get('estimated_chg_pct', 0):+.2f}%")
    lines.append(f"  Bias           : {gift.get('bias', 'NEUTRAL')}")
    lines.append(f"  Based on       : {gift.get('based_on', 'N/A')}")
    lines.append("")

    lines.append("FII/DII FLOWS (prev session):")
    fii = fii_dii.get("fii_net_cr")
    dii = fii_dii.get("dii_net_cr")
    lines.append(f"  FII Net : {'Rs {:,.0f} cr'.format(fii) if fii is not None else 'N/A'}"
                 + (" [BUYING]" if fii and fii > 0 else " [SELLING]" if fii and fii < 0 else ""))
    lines.append(f"  DII Net : {'Rs {:,.0f} cr'.format(dii) if dii is not None else 'N/A'}"
                 + (" [BUYING]" if dii and dii > 0 else " [SELLING]" if dii and dii < 0 else ""))
    lines.append("")

    lines.append("REGIME FACTORS:")
    for f in regime_data["factors"]:
        lines.append(f"  * {f}")
    lines.append("")

    lines.append("SECTOR ROTATION POSTURE:")
    lines.append(f"  Prioritize : {', '.join(sector['prioritize']) if sector['prioritize'] else 'None'}")
    lines.append(f"  Avoid      : {', '.join(sector['avoid']) if sector['avoid'] else 'None'}")
    lines.append("")

    regime = regime_data["regime"]
    if regime == "BULL":
        verdict = "Full position sizing. Favor breakouts and momentum. All sectors open."
    elif regime == "NEUTRAL":
        verdict = "75% position sizing. Trade only A+ setups. Stick to leading sectors."
    elif regime == "CAUTION":
        verdict = "50% position sizing. Only highest conviction trades. Avoid weak sectors."
    else:
        verdict = "NO TRADES TODAY. Capital preservation mode. Stay in cash."

    lines.append(f"TRADING VERDICT: {verdict}")
    lines.append("")
    lines.append("=" * 65)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_intelligence():
    print(f"\n{'='*65}")
    print(f"  LAYER 0: MARKET INTELLIGENCE — {datetime.now().strftime('%I:%M %p IST')}")
    print(f"{'='*65}\n")

    print("Fetching global markets...")
    markets = fetch_global_markets()

    print("Fetching FII/DII flows...")
    fii_dii = fetch_fii_dii()

    print("Estimating GIFT Nifty...")
    gift = estimate_gift_nifty(markets.get("nifty"), markets.get("sp500"))

    print("Determining regime...")
    regime_data = determine_regime(markets, fii_dii, gift)

    print("Determining sector posture...")
    sector = determine_sector_posture(markets, regime_data["regime"])

    trend_type = determine_trend_type(markets, regime_data["regime"])

    # Build and save report
    report = build_report(markets, fii_dii, gift, regime_data, sector, trend_type)

    fname = os.path.join(REPORTS_DIR, f"layer0_intelligence_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    # Save layer0.json for downstream agents
    layer0_payload = {
        "date":             date.today().isoformat(),
        "regime":           regime_data["regime"],
        "confidence":       regime_data["confidence"],
        "trend_type":       trend_type,
        "size_multiplier":  regime_data["size_multiplier"],
        "prioritize_sectors": sector["prioritize"],
        "avoid_sectors":    sector["avoid"],
        "gift_bias":        gift.get("bias", "NEUTRAL"),
        "gift_estimated_chg": gift.get("estimated_chg_pct", 0),
        "india_vix":        markets.get("india_vix", {}).get("price"),
        "india_vix_chg":    markets.get("india_vix", {}).get("change_pct"),
        "fii_net_cr":       fii_dii.get("fii_net_cr"),
        "dii_net_cr":       fii_dii.get("dii_net_cr"),
        "sp500_chg":        markets.get("sp500", {}).get("change_pct"),
        "crude_chg":        markets.get("crude", {}).get("change_pct"),
        "gold_chg":         markets.get("gold", {}).get("change_pct"),
    }

    with open(LAYER0_FILE, "w") as f:
        json.dump(layer0_payload, f, indent=2)

    print(f"\nLayer 0 payload saved: {LAYER0_FILE}")
    print(f"Report saved: {fname}")
    print(f"\nREGIME: {regime_data['regime']} | SIZE: {regime_data['size_multiplier']}x | "
          f"CONFIDENCE: {regime_data['confidence']}%")

    return layer0_payload


if __name__ == "__main__":
    run_intelligence()
