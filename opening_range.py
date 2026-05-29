"""
Opening Range Agent — NSE India
Runs at 9:45am IST Mon-Fri.

Workflow:
  1. Loads today's A+ picks from morning scan (8am)
  2. Downloads 5-min intraday data (9:15am - 9:45am)
  3. Calculates Opening Range (first 15 min: 9:15-9:30am)
  4. Calculates VWAP, gap, volume profile
  5. Generates TRADE NOW / WAIT / SKIP verdict with:
     - Current market price
     - Entry trigger price
     - Target 1 (conservative) + Target 2 (full move)
     - Stop loss + stop %
     - Risk/reward ratio
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date, time
import os
import glob
import warnings
warnings.filterwarnings("ignore")

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

NIFTY_TICKER = "^NSEI"

# NSE market open time
MARKET_OPEN  = time(9, 15)
ORB_END      = time(9, 30)   # Opening Range = first 15 min
SCAN_TIME    = time(9, 45)   # when this script runs


# ── Load tickers from morning scan ───────────────────────────────────────────

def get_morning_picks() -> list:
    pattern = os.path.join(REPORTS_DIR, "morning_scan_*.txt")
    files   = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("No morning scan found. Using default watchlist.")
        return ["HDFCBANK.NS", "INFY.NS", "TCS.NS", "LT.NS", "RELIANCE.NS"]

    with open(files[0], encoding="utf-8") as f:
        lines = f.readlines()

    # Only take A+ grade stocks
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
                grade  = parts[-1]
                if grade in ("A+", "A"):
                    if not ticker.endswith(".NS"):
                        ticker = ticker + ".NS"
                    tickers.append(ticker)
            elif line.strip().startswith("COLUMNS"):
                break
        if len(tickers) >= 15:
            break

    return tickers if tickers else ["HDFCBANK.NS", "LT.NS", "RELIANCE.NS"]


# ── VWAP ─────────────────────────────────────────────────────────────────────

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol  = df["volume"].cumsum()
    cum_tpv  = (typical * df["volume"]).cumsum()
    return cum_tpv / cum_vol


# ── Nifty opening range ───────────────────────────────────────────────────────

def get_nifty_context() -> dict:
    try:
        df = yf.download(NIFTY_TICKER, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return {}
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today = df[df.index.date == date.today()]
        if today.empty:
            return {}

        current_price = float(today["close"].iloc[-1])
        open_price    = float(today["open"].iloc[0])
        gap_pct       = round((open_price / float(
            df[df.index.date < date.today()]["close"].iloc[-1]) - 1) * 100, 2)

        orb = today[today.index.time <= ORB_END]
        orb_high = float(orb["high"].max()) if not orb.empty else current_price
        orb_low  = float(orb["low"].min())  if not orb.empty else current_price

        vwap = calc_vwap(today)
        vwap_now = float(vwap.iloc[-1])

        direction = "BULLISH" if current_price > vwap_now else "BEARISH"

        return {
            "price":    round(current_price, 2),
            "open":     round(open_price, 2),
            "gap_pct":  gap_pct,
            "orb_high": round(orb_high, 2),
            "orb_low":  round(orb_low, 2),
            "vwap":     round(vwap_now, 2),
            "direction": direction,
        }
    except Exception as e:
        print(f"  Nifty context error: {e}")
        return {}


# ── Analyse single stock ──────────────────────────────────────────────────────

def analyse_stock(ticker: str) -> dict | None:
    try:
        # Intraday 5-min data
        df = yf.download(ticker, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)

        today     = df[df.index.date == date.today()]
        yesterday = df[df.index.date < date.today()]
        if today.empty:
            return None

        prev_close   = float(yesterday["close"].iloc[-1]) if not yesterday.empty else None
        open_price   = float(today["open"].iloc[0])
        current      = float(today["close"].iloc[-1])
        current_high = float(today["high"].max())
        current_low  = float(today["low"].min())

        gap_pct = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0

        # Opening Range (9:15 - 9:30am)
        orb_candles = today[today.index.time <= ORB_END]
        if orb_candles.empty:
            return None

        orb_high   = float(orb_candles["high"].max())
        orb_low    = float(orb_candles["low"].min())
        orb_range  = round(orb_high - orb_low, 2)
        orb_range_pct = round(orb_range / orb_low * 100, 2)

        # VWAP
        vwap       = calc_vwap(today)
        vwap_now   = round(float(vwap.iloc[-1]), 2)
        vwap_slope = float(vwap.iloc[-1]) > float(vwap.iloc[max(0, len(vwap)-3)])

        # Volume analysis
        avg_5m_vol = float(today["volume"].mean())
        orb_vol    = float(orb_candles["volume"].sum())
        post_orb   = today[today.index.time > ORB_END]
        post_orb_vol_avg = float(post_orb["volume"].mean()) if not post_orb.empty else avg_5m_vol
        vol_expanding = post_orb_vol_avg > avg_5m_vol

        # Breakout status
        broke_out_high = current > orb_high
        broke_down_low = current < orb_low
        above_vwap     = current > vwap_now

        # Higher highs in post-ORB period (trend continuation)
        if not post_orb.empty and len(post_orb) >= 2:
            hh = all(post_orb["high"].iloc[i] >= post_orb["high"].iloc[i-1]
                     for i in range(1, len(post_orb)))
        else:
            hh = False

        # ── Trade Plan ───────────────────────────────────────────────────────
        # Entry: above ORB high (for longs)
        entry_trigger = round(orb_high + 0.10, 2)   # 10 paise above ORB high

        # Targets: 1x and 2x the ORB range projected from ORB high
        target1 = round(orb_high + orb_range * 1.0, 2)
        target2 = round(orb_high + orb_range * 2.0, 2)

        # Stop loss: below ORB low (or midpoint if tight range)
        stop_loss   = round(orb_low - 0.10, 2)
        stop_pct    = round((stop_loss / current - 1) * 100, 2)
        reward1_pct = round((target1 / current - 1) * 100, 2)
        reward2_pct = round((target2 / current - 1) * 100, 2)
        rr1 = round(abs(reward1_pct / stop_pct), 2) if stop_pct != 0 else 0
        rr2 = round(abs(reward2_pct / stop_pct), 2) if stop_pct != 0 else 0

        # ── Verdict ──────────────────────────────────────────────────────────
        reasons = []
        skip_reasons = []

        if broke_out_high and above_vwap and vol_expanding:
            verdict = "TRADE NOW"
            reasons.append("Broke ORB high with expanding volume")
            if above_vwap:     reasons.append("Price above VWAP (institutional support)")
            if vwap_slope:     reasons.append("VWAP sloping upward")
            if hh:             reasons.append("Making higher highs post-ORB")
            if gap_pct > 0.5:  reasons.append(f"Gapped up {gap_pct:+.1f}% from yesterday")

        elif broke_out_high and above_vwap:
            verdict = "TRADE NOW"
            reasons.append("Broke ORB high and above VWAP")
            if not vol_expanding: reasons.append("Note: volume not yet expanding — watch closely")

        elif above_vwap and not broke_out_high and current > (orb_high * 0.995):
            verdict = "WATCH — near breakout"
            reasons.append(f"Within 0.5% of ORB high (Rs{orb_high}) — breakout imminent")
            if above_vwap: reasons.append("Above VWAP — setup intact")

        elif broke_down_low or (not above_vwap and not broke_out_high):
            verdict = "SKIP"
            skip_reasons.append("Below ORB low or below VWAP — no valid long setup")
            if broke_down_low: skip_reasons.append("ORB breakdown — bearish")

        else:
            verdict = "WAIT"
            reasons.append("Inside ORB range — no direction confirmed yet")

        # Skip if risk/reward is poor
        if rr1 < 1.0 and verdict == "TRADE NOW":
            verdict = "WAIT"
            reasons = []
            skip_reasons.append(f"Risk/reward too tight (R:R = 1:{rr1}) — wait for better entry")

        # Skip if gap up is too large (chasing)
        if gap_pct > 3.0:
            verdict = "SKIP"
            skip_reasons.append(f"Gapped up {gap_pct:.1f}% at open — too late to chase")

        return {
            "ticker":        ticker.replace(".NS", ""),
            "prev_close":    round(prev_close, 2) if prev_close else None,
            "open_price":    round(open_price, 2),
            "current":       round(current, 2),
            "gap_pct":       gap_pct,
            "orb_high":      round(orb_high, 2),
            "orb_low":       round(orb_low, 2),
            "orb_range":     orb_range,
            "orb_range_pct": orb_range_pct,
            "vwap":          vwap_now,
            "above_vwap":    above_vwap,
            "vwap_slope":    vwap_slope,
            "broke_out":     broke_out_high,
            "vol_expanding": vol_expanding,
            "entry_trigger": entry_trigger,
            "target1":       target1,
            "target2":       target2,
            "stop_loss":     stop_loss,
            "stop_pct":      stop_pct,
            "reward1_pct":   reward1_pct,
            "reward2_pct":   reward2_pct,
            "rr1":           rr1,
            "rr2":           rr2,
            "verdict":       verdict,
            "reasons":       reasons,
            "skip_reasons":  skip_reasons,
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(nifty: dict, results: list) -> str:
    now   = datetime.now()
    lines = []

    lines.append("=" * 65)
    lines.append(f"  OPENING RANGE REPORT — {now.strftime('%A, %B %d %Y %I:%M %p')} IST")
    lines.append(f"  Analysis window: 9:15am — 9:45am NSE")
    lines.append("=" * 65)
    lines.append("")

    if nifty:
        direction_tag = "MARKET BULLISH" if nifty.get("direction") == "BULLISH" else "MARKET BEARISH"
        lines.append(f"NIFTY 50 AT 9:45am: {direction_tag}")
        lines.append(f"  Price: {nifty.get('price','?')}  |  Open: {nifty.get('open','?')}  "
                     f"|  Gap: {nifty.get('gap_pct', 0):+.1f}%")
        lines.append(f"  VWAP: {nifty.get('vwap','?')}  |  "
                     f"ORB: {nifty.get('orb_low','?')} — {nifty.get('orb_high','?')}")
        lines.append("")

    # Sort: TRADE NOW first
    order   = {"TRADE NOW": 0, "WATCH — near breakout": 1, "WAIT": 2, "SKIP": 3}
    results = sorted(results, key=lambda x: order.get(x["verdict"], 9))

    trade_now = [r for r in results if r["verdict"] == "TRADE NOW"]
    watch     = [r for r in results if "WATCH" in r["verdict"]]
    wait      = [r for r in results if r["verdict"] == "WAIT"]
    skip      = [r for r in results if r["verdict"] == "SKIP"]

    lines.append(f"SUMMARY: {len(trade_now)} TRADE NOW | {len(watch)} WATCH | "
                 f"{len(wait)} WAIT | {len(skip)} SKIP")
    lines.append("")

    # ── TRADE NOW ─────────────────────────────────────────────────────────────
    if trade_now:
        lines.append("=" * 65)
        lines.append("  *** TRADE NOW ***")
        lines.append("=" * 65)
        for r in trade_now:
            lines.append("")
            lines.append(f"  {r['ticker']}")
            lines.append(f"  {'─' * 40}")
            lines.append(f"  Current Price : Rs {r['current']}")
            lines.append(f"  Gap from prev : {r['gap_pct']:+.1f}%  "
                         f"(prev close Rs {r['prev_close']} | opened Rs {r['open_price']})")
            lines.append(f"  Opening Range : Rs {r['orb_low']} — Rs {r['orb_high']}  "
                         f"(range: {r['orb_range_pct']}%)")
            lines.append(f"  VWAP          : Rs {r['vwap']}  "
                         f"({'ABOVE' if r['above_vwap'] else 'BELOW'}, "
                         f"slope {'UP' if r['vwap_slope'] else 'FLAT/DOWN'})")
            lines.append(f"  Volume        : {'EXPANDING' if r['vol_expanding'] else 'WEAK'}")
            lines.append("")
            lines.append(f"  TRADE PLAN:")
            lines.append(f"    Entry        : Rs {r['entry_trigger']}  (above ORB high)")
            lines.append(f"    Target 1     : Rs {r['target1']}  ({r['reward1_pct']:+.1f}%)  "
                         f"[1x ORB range] — book 50% here")
            lines.append(f"    Target 2     : Rs {r['target2']}  ({r['reward2_pct']:+.1f}%)  "
                         f"[2x ORB range] — trail rest")
            lines.append(f"    Stop Loss    : Rs {r['stop_loss']}  ({r['stop_pct']:+.1f}%)  "
                         f"[below ORB low]")
            lines.append(f"    Risk/Reward  : 1:{r['rr1']} (T1)  |  1:{r['rr2']} (T2)")
            lines.append("")
            lines.append(f"  WHY:")
            for reason in r["reasons"]:
                lines.append(f"    [+] {reason}")
            lines.append("")

    # ── WATCH ─────────────────────────────────────────────────────────────────
    if watch:
        lines.append("=" * 65)
        lines.append("  WATCH — Near Breakout")
        lines.append("=" * 65)
        for r in watch:
            lines.append("")
            lines.append(f"  {r['ticker']}  |  Rs {r['current']}  |  "
                         f"ORB: {r['orb_low']} — {r['orb_high']}  |  VWAP: {r['vwap']}")
            lines.append(f"  Entry if price crosses Rs {r['entry_trigger']}  "
                         f"| T1: Rs {r['target1']}  | Stop: Rs {r['stop_loss']}")
            for reason in r["reasons"]:
                lines.append(f"    [~] {reason}")
            lines.append("")

    # ── WAIT ──────────────────────────────────────────────────────────────────
    if wait:
        lines.append("=" * 65)
        lines.append("  WAIT — Inside Range / No Signal Yet")
        lines.append("=" * 65)
        for r in wait:
            lines.append(f"  {r['ticker']}  |  Rs {r['current']}  |  "
                         f"ORB: {r['orb_low']} — {r['orb_high']}  |  VWAP: {r['vwap']}")
            for reason in r["reasons"]:
                lines.append(f"    [~] {reason}")
        lines.append("")

    # ── SKIP ──────────────────────────────────────────────────────────────────
    if skip:
        lines.append("=" * 65)
        lines.append("  SKIP — No Valid Setup")
        lines.append("=" * 65)
        for r in skip:
            lines.append(f"  {r['ticker']}  |  Rs {r['current']}")
            for reason in r["skip_reasons"]:
                lines.append(f"    [-] {reason}")
        lines.append("")

    lines.append("=" * 65)
    lines.append("  TRADE RULES:")
    lines.append("  1. Only enter on TRADE NOW signals")
    lines.append("  2. Entry = price crosses above entry trigger with volume")
    lines.append("  3. Book 50% at Target 1, trail stop to entry for rest")
    lines.append("  4. Exit 100% if price closes 5-min candle below VWAP")
    lines.append("  5. No new entries after 1:30pm — too late in the day")
    lines.append("=" * 65)

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_opening_range():
    print(f"\n{'='*65}")
    print(f"  OPENING RANGE AGENT — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    tickers = get_morning_picks()
    print(f"Analysing {len(tickers)} stocks from morning scan...\n")

    print("Fetching Nifty context...")
    nifty = get_nifty_context()
    if nifty:
        print(f"  Nifty: {nifty.get('price')} | VWAP: {nifty.get('vwap')} | "
              f"Direction: {nifty.get('direction')}\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        r = analyse_stock(ticker)
        if r:
            results.append(r)

    if not results:
        print("No data available yet — market may not have opened.")
        return

    report = build_report(nifty, results)

    fname = os.path.join(REPORTS_DIR,
                         f"opening_range_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nReport saved: {fname}")


if __name__ == "__main__":
    run_opening_range()
