"""
Momentum Scanner v2 — NSE India
Institutional-grade screening with:
  - Market Regime detection (Nifty EMA + India VIX)
  - Relative Strength vs Nifty (55-day RS slope + acceleration)
  - ATR Extension filter (avoids buying parabolic tops)
  - Sector Leadership (only buy leading sectors)
  - 10-point composite score → A/B/C trade grades
"""

import yfinance as yf
import pandas as pd
import numpy as np
import ta
from datetime import datetime, date
import os
import warnings
warnings.filterwarnings("ignore")

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

NIFTY_TICKER = "^NSEI"
VIX_TICKER   = "^INDIAVIX"

# ── Universe: stock → sector ─────────────────────────────────────────────────
UNIVERSE = {
    # Energy & Power
    "RELIANCE.NS":    "Energy",    "ONGC.NS":       "Energy",
    "BPCL.NS":        "Energy",    "IOC.NS":         "Energy",
    "TATAPOWER.NS":   "Energy",    "ADANIGREEN.NS":  "Energy",
    "NTPC.NS":        "Energy",    "POWERGRID.NS":   "Energy",
    "COALINDIA.NS":   "Energy",    "NHPC.NS":        "Energy",
    "SJVN.NS":        "Energy",    "CESC.NS":        "Energy",
    "TORNTPOWER.NS":  "Energy",
    # IT
    "TCS.NS":         "IT",        "HCLTECH.NS":     "IT",
    "WIPRO.NS":       "IT",        "TECHM.NS":       "IT",
    "NAUKRI.NS":      "IT",        "INDIAMART.NS":   "IT",
    "INFY.NS":        "IT",
    # Banking & Finance
    "HDFCBANK.NS":    "Banking",   "ICICIBANK.NS":   "Banking",
    "SBIN.NS":        "Banking",   "KOTAKBANK.NS":   "Banking",
    "AXISBANK.NS":    "Banking",   "BAJFINANCE.NS":  "Banking",
    "BAJAJFINSV.NS":  "Banking",   "AUBANK.NS":      "Banking",
    "IDFCFIRSTB.NS":  "Banking",   "FEDERALBNK.NS":  "Banking",
    "BANDHANBNK.NS":  "Banking",   "RBLBANK.NS":     "Banking",
    "MUTHOOTFIN.NS":  "Finance",   "CHOLAFIN.NS":    "Finance",
    "SHRIRAMFIN.NS":  "Finance",   "MANAPPURAM.NS":  "Finance",
    "IIFL.NS":        "Finance",
    # Industrials / Infra
    "LT.NS":          "Infra",     "SIEMENS.NS":     "Infra",
    "ABB.NS":         "Infra",     "BHEL.NS":        "Infra",
    "RVNL.NS":        "Infra",     "IRB.NS":         "Infra",
    "ADANIPORTS.NS":  "Infra",     "ADANIENT.NS":    "Infra",
    "GMRAIRPORT.NS":  "Infra",
    # Defence
    "HAL.NS":         "Defence",   "BEL.NS":         "Defence",
    # Auto
    "MARUTI.NS":      "Auto",      "BAJAJ-AUTO.NS":  "Auto",
    "EICHERMOT.NS":   "Auto",      "HEROMOTOCO.NS":  "Auto",
    "M&M.NS":         "Auto",      "TATAMOTORS.NS":  "Auto",
    # FMCG
    "HINDUNILVR.NS":  "FMCG",     "ITC.NS":         "FMCG",
    "NESTLEIND.NS":   "FMCG",     "DABUR.NS":       "FMCG",
    "MARICO.NS":      "FMCG",     "COLPAL.NS":      "FMCG",
    "BRITANNIA.NS":   "FMCG",     "GODREJCP.NS":    "FMCG",
    "TATACONSUM.NS":  "FMCG",
    # Pharma & Healthcare
    "SUNPHARMA.NS":   "Pharma",    "DRREDDY.NS":     "Pharma",
    "CIPLA.NS":       "Pharma",    "DIVISLAB.NS":    "Pharma",
    "APOLLOHOSP.NS":  "Pharma",
    # Metals
    "TATASTEEL.NS":   "Metals",    "JSWSTEEL.NS":    "Metals",
    "HINDALCO.NS":    "Metals",    "VEDL.NS":        "Metals",
    "SAIL.NS":        "Metals",    "NMDC.NS":        "Metals",
    "MOIL.NS":        "Metals",    "NATIONALUM.NS":  "Metals",
    "JINDALSTEL.NS":  "Metals",    "APLAPOLLO.NS":   "Metals",
    # Consumer / Retail
    "ASIANPAINT.NS":  "Consumer",  "TITAN.NS":       "Consumer",
    "PIDILITIND.NS":  "Consumer",  "PAGEIND.NS":     "Consumer",
    "DMART.NS":       "Consumer",  "TRENT.NS":       "Consumer",
    "JUBLFOOD.NS":    "Consumer",
    # Cement
    "ULTRACEMCO.NS":  "Cement",    "GRASIM.NS":      "Cement",
    # Electricals
    "HAVELLS.NS":     "Electricals","VOLTAS.NS":     "Electricals",
    "CROMPTON.NS":    "Electricals","POLYCAB.NS":    "Electricals",
    # New Economy
    "NYKAA.NS":       "NewEconomy","ZOMATO.NS":      "NewEconomy",
    "POLICYBZR.NS":   "NewEconomy","PAYTM.NS":       "NewEconomy",
    # PSU / Infra
    "IRCTC.NS":       "PSU",       "IRFC.NS":        "PSU",
}


# ── Market Regime ─────────────────────────────────────────────────────────────

def get_market_regime() -> dict:
    """
    BULL    → Nifty > EMA20 > EMA50, VIX < 20, no spike. Full go.
    NEUTRAL → Nifty > EMA20, VIX < 25, no spike. Trade selectively (score >= 6).
    CAUTION → Nifty < EMA20 OR VIX 20-28. Reduce size, only A-grade.
    DANGER  → Nifty < EMA50 AND VIX > 25 OR VIX spike > 10%. DO NOT TRADE.
    """
    try:
        nifty = yf.download(NIFTY_TICKER, period="1y", interval="1d",
                            progress=False, auto_adjust=True)
        nifty.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                         for c in nifty.columns]
        nc = nifty["close"]
        ema20 = nc.ewm(span=20, adjust=False).mean()
        ema50 = nc.ewm(span=50, adjust=False).mean()
        price     = float(nc.iloc[-1])
        nifty_1d  = round((nc.iloc[-1] / nc.iloc[-2] - 1) * 100, 2)
        nifty_1w  = round((nc.iloc[-1] / nc.iloc[-6] - 1) * 100, 2) if len(nc) >= 6 else 0
        above_e20 = price > float(ema20.iloc[-1])
        above_e50 = price > float(ema50.iloc[-1])
    except Exception as e:
        print(f"  [regime] Nifty fetch failed: {e}")
        return {"regime": "UNKNOWN", "nifty_close": None, "error": str(e)}

    vix_level, vix_change, vix_spike = 15.0, 0.0, False
    try:
        vix = yf.download(VIX_TICKER, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        vix.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                       for c in vix.columns]
        vc = vix["close"]
        vix_level  = float(vc.iloc[-1])
        vix_change = round((vc.iloc[-1] / vc.iloc[-2] - 1) * 100, 2) if len(vc) >= 2 else 0
        vix_spike  = vix_change > 8
    except:
        pass

    if above_e20 and above_e50 and vix_level < 20 and not vix_spike:
        regime = "BULL"
    elif above_e20 and vix_level < 25 and not vix_spike:
        regime = "NEUTRAL"
    elif not above_e20 or vix_spike or 20 <= vix_level <= 28:
        regime = "CAUTION"
    else:
        regime = "DANGER"

    return {
        "regime":       regime,
        "nifty_price":  round(price, 2),
        "nifty_1d":     nifty_1d,
        "nifty_1w":     nifty_1w,
        "above_ema20":  above_e20,
        "above_ema50":  above_e50,
        "vix_level":    round(vix_level, 2),
        "vix_change":   round(vix_change, 2),
        "vix_spike":    vix_spike,
        "nifty_close":  nc,
    }


# ── Relative Strength ─────────────────────────────────────────────────────────

def calc_rs(stock_close: pd.Series, nifty_close: pd.Series) -> dict:
    """RS ratio slope over 55 days + 10-day acceleration vs prior 10."""
    combined = pd.DataFrame({"s": stock_close, "n": nifty_close}).dropna()
    if len(combined) < 30:
        return {"rs_positive": False, "rs_accel": False, "rs_today": 0.0}

    rs = combined["s"] / combined["n"]

    window = min(55, len(rs))
    x55    = np.arange(window)
    slope  = float(np.polyfit(x55, rs.tail(window).values, 1)[0])

    rs_accel = False
    if len(rs) >= 20:
        x10        = np.arange(10)
        slope_last = float(np.polyfit(x10, rs.tail(10).values,       1)[0])
        slope_prev = float(np.polyfit(x10, rs.tail(20).head(10).values, 1)[0])
        rs_accel   = slope_last > slope_prev

    rs_today = 0.0
    if len(combined) >= 2:
        rs_today = round(
            (combined["s"].iloc[-1] / combined["s"].iloc[-2] - 1) * 100 -
            (combined["n"].iloc[-1] / combined["n"].iloc[-2] - 1) * 100, 2)

    return {
        "rs_positive": slope > 0,
        "rs_accel":    rs_accel,
        "rs_today":    rs_today,
    }


# ── Single Stock Scoring ──────────────────────────────────────────────────────

def score_stock(ticker: str, nifty_close: pd.Series,
                leading_sectors: set) -> dict | None:
    try:
        df = yf.download(ticker, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 60:
            return None

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        close  = df["close"]
        volume = df["volume"]
        high   = df["high"]
        low    = df["low"]

        # ── Indicators ──────────────────────────────────────────────────
        rsi        = ta.momentum.RSIIndicator(close, window=14).rsi()
        macd_obj   = ta.trend.MACD(close, 12, 26, 9)
        atr_series = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        sma20      = close.rolling(20).mean()
        sma50      = close.rolling(50).mean()
        sma200     = close.rolling(200).mean()
        vol_avg20  = volume.rolling(20).mean()

        price     = float(close.iloc[-1])
        rsi_val   = float(rsi.iloc[-1])
        macd_val  = float(macd_obj.macd().iloc[-1])
        macd_sig  = float(macd_obj.macd_signal().iloc[-1])
        s20       = float(sma20.iloc[-1])
        s50       = float(sma50.iloc[-1])
        s200      = float(sma200.iloc[-1])
        atr_val   = float(atr_series.iloc[-1])
        vol_ratio = float(volume.iloc[-1] / vol_avg20.iloc[-1]) if float(vol_avg20.iloc[-1]) > 0 else 0

        high_52w      = float(close.tail(252).max())
        low_52w       = float(close.tail(252).min())
        pct_from_high = (price / high_52w - 1) * 100
        prev_close    = float(close.iloc[-2]) if len(close) >= 2 else price
        daily_chg     = (price / prev_close - 1) * 100
        atr_pct       = round(atr_val / price * 100, 2)

        # ATR extension: distance from SMA20 in ATR units
        atr_extension = (price - s20) / atr_val if atr_val > 0 else 0

        # Relative Strength
        rs = calc_rs(close, nifty_close)

        sector = UNIVERSE.get(ticker, "Other")

        # ── 10-Point Scoring ────────────────────────────────────────────
        score = 0
        pts   = {}

        # 1. RSI zone (55–75 = ideal; >80 = overbought penalty)
        if 55 <= rsi_val <= 75:
            pts["RSI 55-75 (ideal zone)"] = True;  score += 1
        elif rsi_val > 75:
            pts["RSI > 75 (overbought)"]  = False  # no point, signal but extended
        else:
            pts["RSI < 55 (weak)"]        = False

        # 2. Full MA alignment
        pts["MA Stack (price>20>50>200)"] = price > s20 > s50 > s200
        if pts["MA Stack (price>20>50>200)"]: score += 1

        # 3. MACD bullish
        pts["MACD Bullish"] = macd_val > macd_sig
        if pts["MACD Bullish"]: score += 1

        # 4. Volume expansion
        pts["Volume > 1.5x avg"] = vol_ratio > 1.5
        if pts["Volume > 1.5x avg"]: score += 1

        # 5. Proximity to 52w high
        if pct_from_high >= -5:
            pts["Near 52w High (<5%)"]  = True;  score += 1
        elif pct_from_high >= -10:
            pts["Near 52w High (5-10%)"] = True; score += 1
        else:
            pts["Far from 52w High (>10%)"] = False

        # 6. RS vs Nifty — 55-day slope positive
        pts["RS vs Nifty (55d slope +ve)"] = rs["rs_positive"]
        if rs["rs_positive"]: score += 1

        # 7. RS today (stock outperforming Nifty today)
        pts[f"Outperforming Nifty today ({rs['rs_today']:+.1f}%)"] = rs["rs_today"] > 0
        if rs["rs_today"] > 0: score += 1

        # 8. NOT ATR extended (not chasing a vertical move)
        not_extended = atr_extension < 2.0
        pts[f"Not ATR-extended ({atr_extension:.1f}x ATR from SMA20)"] = not_extended
        if not_extended: score += 1

        # 9. Sector leadership
        in_leading = sector in leading_sectors
        pts[f"In leading sector ({sector})"] = in_leading
        if in_leading: score += 1

        # 10. RS acceleration (momentum building, not fading)
        pts["RS Accelerating (last 10d > prior 10d)"] = rs["rs_accel"]
        if rs["rs_accel"]: score += 1

        # Grade
        if score >= 8:
            grade = "A+"
        elif score >= 6:
            grade = "A"
        elif score >= 5:
            grade = "B"
        else:
            grade = "C"

        return {
            "ticker":        ticker.replace(".NS", ""),
            "sector":        sector,
            "price":         round(price, 2),
            "daily_chg":     round(daily_chg, 2),
            "rsi":           round(rsi_val, 1),
            "vol_ratio":     round(vol_ratio, 2),
            "pct_52w_high":  round(pct_from_high, 1),
            "atr_pct":       atr_pct,
            "atr_extension": round(atr_extension, 2),
            "rs_today":      rs["rs_today"],
            "score":         score,
            "grade":         grade,
            "pts":           pts,
            "52w_high":      round(high_52w, 2),
            "52w_low":       round(low_52w, 2),
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


# ── Sector Leadership ─────────────────────────────────────────────────────────

def compute_sector_leaders(raw_results: list) -> tuple[dict, set]:
    """
    Average 1-week return per sector, compare to Nifty 1w return.
    Returns sector_perf dict and set of outperforming sector names.
    """
    sector_returns: dict[str, list] = {}
    for r in raw_results:
        if r is None:
            continue
        sec = r["sector"]
        # approximate 1w from daily_chg series — use score as proxy signal
        # We use pct_52w_high as a proxy for recent trend strength
        sector_returns.setdefault(sec, []).append(r["daily_chg"])

    sector_avg = {
        sec: round(sum(vals) / len(vals), 2)
        for sec, vals in sector_returns.items() if vals
    }
    market_avg = round(sum(sector_avg.values()) / len(sector_avg), 2) if sector_avg else 0
    leading    = {sec for sec, ret in sector_avg.items() if ret > market_avg}
    return sector_avg, leading


# ── Report Builder ────────────────────────────────────────────────────────────

def build_report(regime: dict, results: list, sector_perf: dict) -> str:
    lines = []
    r_sym = {"BULL": "BULL  [GO]", "NEUTRAL": "NEUTRAL [SELECTIVE]",
             "CAUTION": "CAUTION [REDUCE SIZE]", "DANGER": "DANGER [DO NOT TRADE]",
             "UNKNOWN": "UNKNOWN"}.get(regime["regime"], regime["regime"])

    lines.append("=" * 65)
    lines.append(f"  MOMENTUM SCANNER v2 (NSE) — {datetime.now().strftime('%A, %B %d %Y %I:%M %p')}")
    lines.append("=" * 65)
    lines.append("")
    lines.append(f"MARKET REGIME: {r_sym}")
    lines.append(f"  Nifty 50:  Rs{regime.get('nifty_price','?')}  "
                 f"| Today: {regime.get('nifty_1d', 0):+.1f}%  "
                 f"| 1W: {regime.get('nifty_1w', 0):+.1f}%")
    lines.append(f"  EMA20: {'ABOVE' if regime.get('above_ema20') else 'BELOW'}  "
                 f"| EMA50: {'ABOVE' if regime.get('above_ema50') else 'BELOW'}")
    lines.append(f"  India VIX: {regime.get('vix_level','?')}  "
                 f"({regime.get('vix_change', 0):+.1f}%)"
                 + ("  *** SPIKE ***" if regime.get("vix_spike") else ""))
    lines.append("")

    if regime["regime"] == "DANGER":
        lines.append("  *** DO NOT OPEN NEW POSITIONS TODAY ***")
        lines.append("  Market is in distribution / high fear. Wait for regime to recover.")
        lines.append("")
    elif regime["regime"] == "CAUTION":
        lines.append("  Trade only A+ grade setups. Reduce position size by 50%.")
        lines.append("")

    # Sector performance
    if sector_perf:
        sorted_sec = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
        top3    = [f"{s} ({r:+.1f}%)" for s, r in sorted_sec[:3]]
        bottom3 = [f"{s} ({r:+.1f}%)" for s, r in sorted_sec[-3:]]
        lines.append(f"SECTOR PERFORMANCE (today avg):")
        lines.append(f"  Leading : {' | '.join(top3)}")
        lines.append(f"  Lagging : {' | '.join(bottom3)}")
        lines.append("")

    if not results:
        lines.append("No qualifying momentum setups found today.")
        return "\n".join(lines)

    # Grade filter based on regime
    min_score = {"BULL": 5, "NEUTRAL": 6, "CAUTION": 8, "DANGER": 99}.get(regime["regime"], 5)
    filtered  = [r for r in results if r["score"] >= min_score]

    lines.append(f"Found {len(results)} momentum stocks → {len(filtered)} pass regime filter.\n")
    lines.append(f"{'#':<4} {'Ticker':<12} {'Price':>9} {'Day%':>7} {'RSI':>6} "
                 f"{'Vol':>6} {'52wH%':>7} {'RS':>6} {'Ext':>5} {'Score':>6} {'Grade':>6}")
    lines.append("-" * 80)

    for i, s in enumerate(filtered[:25], 1):
        rs_str = f"{s['rs_today']:+.1f}%"
        lines.append(
            f"{i:<4} {s['ticker']:<12} Rs{s['price']:>8.1f} "
            f"{s['daily_chg']:>+6.1f}% "
            f"{s['rsi']:>6.1f} "
            f"{s['vol_ratio']:>5.1f}x "
            f"{s['pct_52w_high']:>+6.1f}% "
            f"{rs_str:>7} "
            f"{s['atr_extension']:>4.1f}x "
            f"{s['score']:>4}/10 "
            f"  {s['grade']}"
        )

    lines.append("")
    lines.append("COLUMNS: Day% = today change | RSI | Vol = volume ratio vs 20d avg |")
    lines.append("         52wH% = distance from 52w high | RS = relative to Nifty today |")
    lines.append("         Ext = ATR extension (>2x = overstretched) | Grade: A+/A/B/C")
    lines.append("")

    # ── Detail for top 10 ────────────────────────────────────────────────────
    lines.append("=" * 65)
    lines.append("  DETAIL — TOP 10")
    lines.append("=" * 65)
    for s in filtered[:10]:
        lines.append("")
        lines.append(f"  {s['ticker']} ({s['sector']}) — Rs{s['price']} | "
                     f"Grade {s['grade']} | {s['score']}/10")
        lines.append(f"  52w: Rs{s['52w_low']} — Rs{s['52w_high']} | "
                     f"ATR: {s['atr_pct']}%/day | Ext: {s['atr_extension']}x")
        for criterion, passed in s["pts"].items():
            mark = "+" if passed else "-"
            lines.append(f"    [{mark}] {criterion}")

    lines.append("")
    lines.append("=" * 65)
    lines.append("  SCORING: 8-10=A+  6-7=A  5=B  <5=C")
    lines.append("  10 criteria (1pt each): RSI zone | MA stack | MACD |")
    lines.append("  Volume | 52w high | RS slope | RS today | Not extended |")
    lines.append("  Sector leader | RS accelerating")
    lines.append("=" * 65)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_scan():
    print(f"\n{'='*65}")
    print(f"  MOMENTUM SCANNER v2 (NSE) — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    print("Fetching market regime (Nifty + VIX)...")
    regime = get_market_regime()
    print(f"  Regime: {regime['regime']} | Nifty: {regime.get('nifty_price', '?')} "
          f"({regime.get('nifty_1d', 0):+.1f}%) | VIX: {regime.get('vix_level', '?')}\n")

    nifty_close = regime.get("nifty_close")

    if regime["regime"] == "DANGER":
        print("*** DANGER REGIME — skipping stock scan. DO NOT TRADE TODAY. ***")
        report = build_report(regime, [], {})
        fname  = os.path.join(REPORTS_DIR, f"morning_scan_{date.today().isoformat()}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        try:
            print(report)
        except UnicodeEncodeError:
            print(report.encode("ascii", errors="replace").decode("ascii"))
        return []

    tickers = list(UNIVERSE.keys())
    print(f"Scanning {len(tickers)} stocks (pass 1 — raw data)...\n")

    raw = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1:>3}/{len(tickers)}] {ticker:<20}", end="\r")
        df = None
        try:
            df = yf.download(ticker, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
        except:
            pass
        if df is not None and len(df) >= 20:
            df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                          for c in df.columns]
            raw.append({"ticker": ticker, "df": df,
                        "sector": UNIVERSE.get(ticker, "Other")})

    print(f"\n  Downloaded {len(raw)}/{len(tickers)} stocks successfully.\n")

    # Pass 1: compute sector leadership from daily returns
    proto_results = []
    for item in raw:
        close = item["df"]["close"]
        prev  = float(close.iloc[-2]) if len(close) >= 2 else float(close.iloc[-1])
        d1    = (float(close.iloc[-1]) / prev - 1) * 100
        proto_results.append({"sector": item["sector"], "daily_chg": d1})

    sector_perf, leading_sectors = compute_sector_leaders(proto_results)
    print(f"  Leading sectors: {', '.join(sorted(leading_sectors))}\n")

    # Pass 2: full scoring
    print(f"Scoring {len(raw)} stocks (pass 2 — indicators + RS)...\n")
    results = []
    for i, item in enumerate(raw):
        print(f"  Scoring {item['ticker']:<20} ({i+1}/{len(raw)})", end="\r")
        r = score_stock(item["ticker"], nifty_close, leading_sectors)
        if r and r["score"] >= 4:
            results.append(r)

    results.sort(key=lambda x: (x["score"], x["rs_today"]), reverse=True)

    report = build_report(regime, results, sector_perf)

    fname = os.path.join(REPORTS_DIR, f"morning_scan_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    # Safe print for Windows terminals that don't support all unicode
    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nReport saved: {fname}")
    return results


if __name__ == "__main__":
    run_scan()
