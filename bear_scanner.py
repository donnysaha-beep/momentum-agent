"""
Bear Market Scanner — NSE India
Runs at 10:00am IST Mon-Fri.

Activates in CAUTION / BEAR / DANGER regimes only.
Scans for SHORT setups:
  - Stock broke below Opening Range Low (ORB low)
  - Price below VWAP (institutional selling confirmed)
  - VWAP sloping downward
  - Volume expanding on breakdown
  - Not in oversold territory (RSI > 25 — still room to fall)

Gives SHORT trade plans with:
  - Entry trigger (break below ORB low)
  - Stop loss (above ORB high)
  - Target 1 (1.5x ATR below entry)
  - Target 2 (2.5x ATR below entry)
  - Position sizing in Rs
  - Probability score
"""

import os
import json
import glob
import warnings
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date, time
import ta

warnings.filterwarnings("ignore")

REPORTS_DIR  = os.path.join(os.path.dirname(__file__), "reports")
LAYER0_FILE  = os.path.join(os.path.dirname(__file__), "layer0.json")
NIFTY_TICKER = "^NSEI"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Capital per trade by regime (Rs) — same as opening range
CAPITAL_BY_REGIME = {
    "BULL":    0,       # No shorts in bull market
    "NEUTRAL": 25000,   # Selective shorts only
    "CAUTION": 62500,   # Active short regime
    "BEAR":    62500,   # Active short regime
    "DANGER":  25000,   # Reduced — market too volatile
    "UNKNOWN": 25000,
}

# Regimes where shorting is allowed
SHORT_REGIMES = {"CAUTION", "BEAR", "DANGER", "NEUTRAL"}


# ── Load regime from layer0.json ──────────────────────────────────────────────

def get_regime() -> str:
    if os.path.exists(LAYER0_FILE):
        try:
            with open(LAYER0_FILE) as f:
                l0 = json.load(f)
            if l0.get("date") == date.today().isoformat():
                return l0.get("regime", "UNKNOWN")
        except:
            pass
    return "UNKNOWN"


# ── Load tickers from morning scan ────────────────────────────────────────────

def get_scan_tickers() -> list:
    pattern = os.path.join(REPORTS_DIR, "morning_scan_*.txt")
    files   = sorted(glob.glob(pattern), reverse=True)
    if not files:
        # Fallback: liquid NSE stocks good for shorting
        return [
            "HDFCBANK.NS", "ICICIBANK.NS", "RELIANCE.NS", "INFY.NS",
            "TCS.NS", "AXISBANK.NS", "SBIN.NS", "LT.NS",
            "ADANIGREEN.NS", "JSWSTEEL.NS", "TATAMOTORS.NS", "BAJFINANCE.NS"
        ]

    with open(files[0], encoding="utf-8") as f:
        lines = f.readlines()

    tickers = []
    in_table = False
    for line in lines:
        if "Score" in line and "Grade" in line:
            in_table = True
            continue
        if in_table:
            parts = line.split()
            if len(parts) >= 8 and parts[0].isdigit():
                ticker = parts[1]
                if not ticker.endswith(".NS"):
                    ticker += ".NS"
                tickers.append(ticker)
            elif "COLUMNS" in line:
                break
        if len(tickers) >= 15:
            break

    return tickers if tickers else [
        "HDFCBANK.NS", "RELIANCE.NS", "INFY.NS", "TCS.NS", "SBIN.NS"
    ]


# ── VWAP ──────────────────────────────────────────────────────────────────────

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / df["volume"].cumsum()


# ── Nifty context ─────────────────────────────────────────────────────────────

def get_nifty_context() -> dict:
    try:
        df = yf.download(NIFTY_TICKER, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return {}
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today     = df[df.index.date == date.today()]
        yesterday = df[df.index.date < date.today()]
        if today.empty:
            return {}

        prev_close = float(yesterday["close"].iloc[-1]) if not yesterday.empty else None
        open_price = float(today["open"].iloc[0])
        current    = float(today["close"].iloc[-1])
        gap_pct    = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0

        orb      = today[today.index.time <= time(9, 30)]
        orb_high = float(orb["high"].max()) if not orb.empty else current
        orb_low  = float(orb["low"].min())  if not orb.empty else current
        vwap_now = float(calc_vwap(today).iloc[-1])

        # Bearish signals
        below_vwap   = current < vwap_now
        below_orb    = current < orb_low
        nifty_weak   = gap_pct < -0.5 or below_orb

        direction = "BEARISH" if below_vwap or below_orb else "NEUTRAL"

        return {
            "price":       round(current, 2),
            "open":        round(open_price, 2),
            "gap_pct":     gap_pct,
            "orb_high":    round(orb_high, 2),
            "orb_low":     round(orb_low, 2),
            "vwap":        round(vwap_now, 2),
            "direction":   direction,
            "below_vwap":  below_vwap,
            "below_orb":   below_orb,
            "nifty_weak":  nifty_weak,
        }
    except Exception as e:
        print(f"  Nifty error: {e}")
        return {}


# ── RSI from daily data ───────────────────────────────────────────────────────

def get_daily_rsi(ticker: str) -> float | None:
    try:
        df = yf.download(ticker, period="30d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 15:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        rsi = ta.momentum.RSIIndicator(df["close"], 14).rsi()
        return round(float(rsi.iloc[-1]), 1)
    except:
        return None


# ── ATR from daily data ───────────────────────────────────────────────────────

def get_daily_atr(ticker: str) -> float | None:
    try:
        df = yf.download(ticker, period="30d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 15:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        atr = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], 14
        ).average_true_range()
        return round(float(atr.iloc[-1]), 2)
    except:
        return None


# ── Analyse single stock for SHORT setup ─────────────────────────────────────

def analyse_short(ticker: str, regime: str, nifty: dict, capital: int) -> dict | None:
    try:
        # Get intraday data
        df = yf.download(ticker, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today = df[df.index.date == date.today()]
        if today.empty or len(today) < 3:
            return None

        # Previous close
        yesterday = df[df.index.date < date.today()]
        prev_close = float(yesterday["close"].iloc[-1]) if not yesterday.empty else None

        open_price = float(today["open"].iloc[0])
        current    = float(today["close"].iloc[-1])
        gap_pct    = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0

        # Opening Range (9:15 - 9:30am)
        orb = today[today.index.time <= time(9, 30)]
        if orb.empty:
            return None
        orb_high      = float(orb["high"].max())
        orb_low       = float(orb["low"].min())
        orb_range     = round(orb_high - orb_low, 2)
        orb_range_pct = round(orb_range / orb_high * 100, 2)

        # VWAP
        vwap        = calc_vwap(today)
        vwap_now    = round(float(vwap.iloc[-1]), 2)
        vwap_slope  = float(vwap.iloc[-1]) < float(vwap.iloc[max(0, len(vwap)-4)])  # sloping DOWN
        below_vwap  = current < vwap_now

        # Volume
        avg_vol       = float(today["volume"].mean())
        post_orb      = today[today.index.time > time(9, 30)]
        post_vol_avg  = float(post_orb["volume"].mean()) if not post_orb.empty else avg_vol
        vol_expanding = post_vol_avg > avg_vol

        # Breakdown status
        broke_down     = current < orb_low
        near_breakdown = not broke_down and current <= orb_low * 1.005

        # Lower lows post-ORB (bearish continuation)
        ll = False
        if not post_orb.empty and len(post_orb) >= 2:
            ll = all(post_orb["low"].iloc[i] <= post_orb["low"].iloc[i-1]
                     for i in range(1, min(len(post_orb), 4)))

        # ATR and RSI from daily data
        atr_daily = get_daily_atr(ticker)
        if not atr_daily:
            atr_daily = orb_range * 2

        rsi_val = get_daily_rsi(ticker)

        # Short trade plan
        entry_trigger = round(orb_low - 0.05, 2)          # break below ORB low
        target1       = round(entry_trigger - 1.5 * atr_daily, 2)  # 1.5x ATR below
        target2       = round(entry_trigger - 2.5 * atr_daily, 2)  # 2.5x ATR below
        stop_loss     = round(orb_high + 0.05, 2)          # stop above ORB high

        stop_pct    = round((stop_loss / entry_trigger - 1) * 100, 2)
        reward1_pct = round((entry_trigger - target1) / entry_trigger * 100, 2)
        reward2_pct = round((entry_trigger - target2) / entry_trigger * 100, 2)
        rr1 = round(reward1_pct / stop_pct, 2) if stop_pct > 0 else 0
        rr2 = round(reward2_pct / stop_pct, 2) if stop_pct > 0 else 0

        # Position sizing
        qty            = max(1, int(capital / entry_trigger)) if entry_trigger > 0 else 0
        actual_capital = round(qty * entry_trigger, 2)
        max_loss       = round(qty * abs(stop_loss - entry_trigger), 2)

        # Probability score (bearish factors)
        score_factors = [
            broke_down,                                    # broke ORB low
            below_vwap,                                    # below VWAP
            vwap_slope,                                    # VWAP sloping down
            vol_expanding,                                 # volume expanding
            ll,                                            # making lower lows
            gap_pct < 0,                                   # negative gap
            rr1 >= 1.5,                                    # good R:R
            rsi_val > 25 if rsi_val else True,             # not oversold
            nifty.get("below_vwap", False),                # Nifty also weak
            nifty.get("direction") == "BEARISH",           # market confirming
        ]
        prob_score = round(sum(score_factors) / len(score_factors) * 100)

        # Invalidations
        invalidations = []
        if rsi_val and rsi_val < 25:
            invalidations.append(f"RSI oversold ({rsi_val}) — short too risky, likely bounce")
        if not broke_down and not near_breakdown:
            invalidations.append("Stock holding above ORB low — no breakdown yet")
        if not below_vwap:
            invalidations.append("Above VWAP — no institutional selling confirmed")
        if nifty.get("direction") == "BULLISH":
            invalidations.append("Nifty is BULLISH — avoid shorts when market rising")
        if gap_pct < -3:
            invalidations.append(f"Gap down too large ({gap_pct:.1f}%) — bounce risk, avoid chasing")

        # Positives
        positive = []
        cautious = []

        # Verdict
        if invalidations and not broke_down:
            verdict = "SKIP"
        elif capital == 0:
            verdict = "SKIP"
            invalidations.append("BULL regime — no shorts today")
        elif broke_down and below_vwap and vol_expanding and prob_score >= 60:
            verdict = "SHORT NOW"
            positive.append("Broke ORB low with VWAP rejection")
            if vol_expanding: positive.append("Volume expanding — conviction confirmed")
            if ll:            positive.append("Making lower lows — bearish continuation")
            if vwap_slope:    positive.append("VWAP sloping downward")
        elif broke_down and below_vwap and prob_score >= 50:
            verdict = "SHORT NOW"
            positive.append("Broke ORB low with VWAP rejection")
            cautious.append("Volume weak — keep position size at minimum")
        elif near_breakdown and below_vwap and prob_score >= 45:
            verdict = "WATCH SHORT — near breakdown"
            cautious.append(f"Within 0.5% of ORB low (Rs {orb_low}) — set alert")
            positive.append("Below VWAP — distribution confirmed")
        elif broke_down and not below_vwap:
            verdict = "WAIT"
            cautious.append("Broke ORB low but reclaimed VWAP — wait for VWAP rejection")
        else:
            verdict = "WAIT"
            cautious.append("Inside opening range — direction not confirmed yet")

        return {
            "ticker":         ticker.replace(".NS", ""),
            "prev_close":     round(prev_close, 2) if prev_close else None,
            "open_price":     round(open_price, 2),
            "current":        round(current, 2),
            "gap_pct":        gap_pct,
            "orb_high":       round(orb_high, 2),
            "orb_low":        round(orb_low, 2),
            "orb_range":      orb_range,
            "orb_range_pct":  orb_range_pct,
            "vwap":           vwap_now,
            "below_vwap":     below_vwap,
            "vwap_slope":     vwap_slope,
            "broke_down":     broke_down,
            "vol_expanding":  vol_expanding,
            "rsi":            rsi_val,
            "atr_daily":      round(atr_daily, 2),
            "entry_trigger":  entry_trigger,
            "target1":        target1,
            "target2":        target2,
            "stop_loss":      stop_loss,
            "stop_pct":       stop_pct,
            "reward1_pct":    reward1_pct,
            "reward2_pct":    reward2_pct,
            "rr1":            rr1,
            "rr2":            rr2,
            "prob_score":     prob_score,
            "qty":            qty,
            "capital":        actual_capital,
            "max_loss":       max_loss,
            "verdict":        verdict,
            "positive":       positive,
            "cautious":       cautious,
            "invalidations":  invalidations,
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(nifty: dict, results: list, regime: str) -> str:
    now   = datetime.now()
    lines = []

    capital_today = CAPITAL_BY_REGIME.get(regime, 25000)
    size_label = {
        "BULL":    "NO SHORTS (Bull market)",
        "NEUTRAL": "REDUCED SHORT SIZE (Rs 25,000/trade)",
        "CAUTION": "ACTIVE SHORT SIZE (Rs 62,500/trade)",
        "BEAR":    "ACTIVE SHORT SIZE (Rs 62,500/trade)",
        "DANGER":  "SMALL SHORT SIZE (Rs 25,000/trade)",
        "UNKNOWN": "REDUCED SHORT SIZE (Rs 25,000/trade)",
    }.get(regime, "REDUCED SIZE")

    lines.append("=" * 65)
    lines.append(f"  BEAR SCANNER — {now.strftime('%A, %B %d %Y %I:%M %p')} IST")
    lines.append(f"  Short-side signals for NSE India")
    lines.append("=" * 65)
    lines.append("")

    if nifty:
        lines.append(f"NIFTY AT 10:00am: {nifty.get('direction', '?')}")
        lines.append(f"  Price: {nifty.get('price','?')}  |  Gap: {nifty.get('gap_pct',0):+.1f}%  "
                     f"|  VWAP: {nifty.get('vwap','?')}")
        lines.append(f"  ORB: {nifty.get('orb_low','?')} — {nifty.get('orb_high','?')}")
        if nifty.get("below_orb"):
            lines.append(f"  *** Nifty broke ORB low — bearish breadth confirmed ***")
        lines.append("")

    lines.append(f"REGIME: {regime}  |  SHORT SIZE: {size_label}")
    lines.append("")

    if capital_today == 0:
        lines.append("  *** BULL REGIME — NO SHORTS TODAY ***")
        lines.append("  Wait for regime to weaken before shorting.")
        lines.append("=" * 65)
        return "\n".join(lines)

    short_now   = [r for r in results if r["verdict"] == "SHORT NOW"]
    watch_short = [r for r in results if "WATCH SHORT" in r["verdict"]]
    wait        = [r for r in results if r["verdict"] == "WAIT"]
    skip        = [r for r in results if r["verdict"] == "SKIP"]

    lines.append(f"SUMMARY: {len(short_now)} SHORT NOW | {len(watch_short)} WATCH SHORT | "
                 f"{len(wait)} WAIT | {len(skip)} SKIP")
    lines.append("")

    def stock_block(r, show_plan=True):
        block = []
        block.append(f"  {r['verdict']}  [{r['prob_score']}% probability]")
        block.append(f"  {r['ticker']}")
        block.append(f"  {'─'*45}")
        block.append(f"  Current Price  : Rs {r['current']}")
        block.append(f"  Gap from prev  : {r['gap_pct']:+.1f}%  "
                     f"(prev Rs {r['prev_close']} | opened Rs {r['open_price']})")
        block.append(f"  Opening Range  : Rs {r['orb_low']} — Rs {r['orb_high']}  "
                     f"({r['orb_range_pct']}% wide)")
        block.append(f"  VWAP           : Rs {r['vwap']}  "
                     f"({'BELOW' if r['below_vwap'] else 'ABOVE'}, "
                     f"{'sloping DOWN' if r['vwap_slope'] else 'flat/up'})")
        block.append(f"  Volume         : {'EXPANDING' if r['vol_expanding'] else 'WEAK'}")
        block.append(f"  RSI (daily)    : {r['rsi'] if r['rsi'] else 'N/A'}")
        block.append(f"  ATR (daily)    : Rs {r['atr_daily']}")
        block.append("")

        if show_plan and r["verdict"] not in ("SKIP", "WAIT"):
            block.append(f"  SHORT TRADE PLAN:")
            block.append(f"    Entry trigger  : Rs {r['entry_trigger']}  (break BELOW ORB low)")
            block.append(f"    Target 1 (50%) : Rs {r['target1']}  (-{r['reward1_pct']:.1f}%)  "
                         f"[1.5x ATR] — cover half here")
            block.append(f"    Target 2 (50%) : Rs {r['target2']}  (-{r['reward2_pct']:.1f}%)  "
                         f"[2.5x ATR] — trail stop for rest")
            block.append(f"    Stop Loss      : Rs {r['stop_loss']}  (+{r['stop_pct']:.1f}%)  "
                         f"[above ORB high]")
            block.append(f"    Risk/Reward    : 1:{r['rr1']} (T1)  |  1:{r['rr2']} (T2)")
            block.append("")
            block.append(f"  POSITION SIZE ({regime} regime):")
            block.append(f"    Qty            : {r['qty']} shares")
            block.append(f"    Capital needed : Rs {r['capital']:,.0f}  (margin)")
            block.append(f"    Max loss       : Rs {r['max_loss']:,.0f}  (if stop hit)")
            block.append("")

        if r["positive"]:
            block.append(f"  WHY THIS SHORT:")
            for s in r["positive"]:
                block.append(f"    [+] {s}")
        if r["cautious"]:
            for s in r["cautious"]:
                block.append(f"    [~] {s}")
        if r["invalidations"]:
            block.append(f"  INVALIDATIONS:")
            for s in r["invalidations"]:
                block.append(f"    [-] {s}")
        block.append("")
        return block

    if short_now:
        lines.append("=" * 65)
        lines.append("  *** SHORT NOW ***")
        lines.append("=" * 65)
        for r in short_now:
            lines.extend(stock_block(r, show_plan=True))

    if watch_short:
        lines.append("=" * 65)
        lines.append("  WATCH SHORT — Set Price Alert at Entry Trigger")
        lines.append("=" * 65)
        for r in watch_short:
            lines.extend(stock_block(r, show_plan=True))

    if wait:
        lines.append("=" * 65)
        lines.append("  WAIT — No Short Signal Yet")
        lines.append("=" * 65)
        for r in wait:
            lines.append(f"  {r['ticker']}  [{r['prob_score']}%]  |  "
                         f"Rs {r['current']}  |  ORB: {r['orb_low']}—{r['orb_high']}  "
                         f"|  VWAP: {r['vwap']}")
            for s in r["cautious"]:
                lines.append(f"    [~] {s}")
        lines.append("")

    if skip:
        lines.append("=" * 65)
        lines.append("  SKIP — No Valid Short Setup")
        lines.append("=" * 65)
        for r in skip:
            lines.append(f"  {r['ticker']}  [{r['prob_score']}%]  |  Rs {r['current']}")
            for s in r["invalidations"]:
                lines.append(f"    [-] {s}")
        lines.append("")

    lines.append("=" * 65)
    lines.append("  SHORT TRADE MANAGEMENT RULES:")
    lines.append("  1. Short only on SHORT NOW — price must cross BELOW entry trigger")
    lines.append("  2. Confirm with volume expansion on breakdown candle")
    lines.append("  3. Cover 50% at Target 1 — move stop to entry (risk-free)")
    lines.append("  4. Trail stop above each new lower high for Target 2")
    lines.append("  5. Cover 100% if any 5-min candle CLOSES ABOVE VWAP")
    lines.append("  6. Cover 100% if Nifty breaks ABOVE its opening range HIGH")
    lines.append("  7. No new short entries after 1:30pm IST")
    lines.append("  8. Max 3 short trades per day")
    lines.append("  9. Never short a stock with RSI below 25 — bounce risk")
    lines.append(" 10. Need F&O/MIS margin — activate intraday short on Groww")
    lines.append("=" * 65)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_bear_scanner():
    print(f"\n{'='*65}")
    print(f"  BEAR SCANNER — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    regime  = get_regime()
    capital = CAPITAL_BY_REGIME.get(regime, 25000)

    print(f"Regime: {regime} | Short capital: Rs {capital:,}/trade")

    if regime == "BULL":
        print("BULL REGIME — shorts not recommended. Saving report.")
        nifty  = get_nifty_context()
        report = build_report(nifty, [], regime)
        fname  = os.path.join(REPORTS_DIR, f"bear_scanner_{date.today().isoformat()}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report saved: {fname}")
        return

    if regime not in SHORT_REGIMES:
        print(f"Regime {regime} — skipping bear scan.")
        return

    print("Fetching Nifty context...")
    nifty = get_nifty_context()
    if nifty:
        print(f"  Nifty: {nifty.get('price')} | Direction: {nifty.get('direction')} | "
              f"Gap: {nifty.get('gap_pct',0):+.1f}%\n")

    tickers = get_scan_tickers()
    print(f"Scanning {len(tickers)} stocks for short setups...\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        r = analyse_short(ticker, regime, nifty, capital)
        if r:
            results.append(r)

    # Sort: SHORT NOW first, then by prob score
    order   = {"SHORT NOW": 0, "WATCH SHORT — near breakdown": 1, "WAIT": 2, "SKIP": 3}
    results.sort(key=lambda x: (order.get(x["verdict"], 9), -x["prob_score"]))

    report = build_report(nifty, results, regime)
    fname  = os.path.join(REPORTS_DIR, f"bear_scanner_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nReport saved: {fname}")


if __name__ == "__main__":
    run_bear_scanner()
