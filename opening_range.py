"""
Opening Range Agent v2 — NSE India
Runs at 9:45am IST Mon-Fri.

Upgrades in v2:
  - Position sizing in rupees (based on regime + VIX)
  - Probability score (0-100% setup quality)
  - ATR-based dynamic targets
  - Gap trap rejection (red first candle after gap-up = SKIP)
  - Trade invalidation rules
  - No-trade day detection
  - Zerodha Kite API for live data (falls back to yfinance if not authenticated)
"""

import os
import json
import glob
import warnings
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date, time

warnings.filterwarnings("ignore")

REPORTS_DIR  = os.path.join(os.path.dirname(__file__), "reports")
TOKEN_FILE   = os.path.join(os.path.dirname(__file__), ".kite_token.json")
NIFTY_TICKER = "^NSEI"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Capital per trade by regime (Rs)
CAPITAL_BY_REGIME = {
    "BULL":    40000,
    "NEUTRAL": 25000,
    "CAUTION": 12500,
    "DANGER":  0,
    "BEAR":    12500,
    "UNKNOWN": 12500,
}


# ── Kite live data (optional) ─────────────────────────────────────────────────

def get_kite_intraday(ticker_ns: str) -> pd.DataFrame | None:
    """Fetch 1-min candles from Zerodha Kite if token is available."""
    try:
        if not os.path.exists(TOKEN_FILE):
            return None
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("date") != date.today().isoformat():
            return None

        from kiteconnect import KiteConnect
        api_key = os.environ.get("KITE_API_KEY", "vq3dyqpb9pyddio3")
        kite    = KiteConnect(api_key=api_key)
        kite.set_access_token(data["access_token"])

        symbol  = ticker_ns.replace(".NS", "")
        instruments = kite.instruments("NSE")
        inst_map = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}
        token   = inst_map.get(symbol)
        if not token:
            return None

        from datetime import datetime as dt
        candles = kite.historical_data(
            token,
            dt.combine(date.today(), time(9, 15)),
            dt.combine(date.today(), time(9, 50)),
            "minute"
        )
        if not candles:
            return None

        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"date": "datetime"})
        df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index)
        return df

    except Exception:
        return None


# ── yfinance fallback ─────────────────────────────────────────────────────────

def get_yf_intraday(ticker_ns: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker_ns, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today = df[df.index.date == date.today()]
        return today if not today.empty else None
    except:
        return None


def get_intraday(ticker_ns: str) -> pd.DataFrame | None:
    df = get_kite_intraday(ticker_ns)
    if df is not None and not df.empty:
        print(f"    [Kite live data]")
        return df
    return get_yf_intraday(ticker_ns)


# ── Load morning picks ────────────────────────────────────────────────────────

def get_morning_picks() -> tuple[list, str]:
    """Returns (tickers, regime)"""
    pattern = os.path.join(REPORTS_DIR, "morning_scan_*.txt")
    files   = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return ["HDFCBANK.NS","LT.NS","RELIANCE.NS","INFY.NS","TCS.NS"], "UNKNOWN"

    with open(files[0], encoding="utf-8") as f:
        content = f.read()
        lines   = content.splitlines()

    # Extract regime
    regime = "UNKNOWN"
    for line in lines:
        if "MARKET REGIME:" in line:
            if "BULL" in line:    regime = "BULL"
            elif "NEUTRAL" in line: regime = "NEUTRAL"
            elif "CAUTION" in line: regime = "CAUTION"
            elif "DANGER" in line:  regime = "DANGER"
            elif "BEAR" in line:    regime = "BEAR"
            break

    # Extract A+ and A grade tickers
    tickers    = []
    in_table   = False
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
                        ticker += ".NS"
                    tickers.append(ticker)
            elif "COLUMNS" in line:
                break
        if len(tickers) >= 15:
            break

    return (tickers if tickers else ["HDFCBANK.NS","LT.NS","RELIANCE.NS"]), regime


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

        prev_close  = float(yesterday["close"].iloc[-1]) if not yesterday.empty else None
        open_price  = float(today["open"].iloc[0])
        current     = float(today["close"].iloc[-1])
        gap_pct     = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0

        orb         = today[today.index.time <= time(9, 30)]
        orb_high    = float(orb["high"].max()) if not orb.empty else current
        orb_low     = float(orb["low"].min())  if not orb.empty else current
        vwap_now    = float(calc_vwap(today).iloc[-1])

        # Nifty opening candle (9:15-9:20)
        first_candle = today.iloc[0] if not today.empty else None
        nifty_first_red = (float(first_candle["close"]) < float(first_candle["open"])
                           ) if first_candle is not None else False

        # Breadth proxy: Nifty below its own ORB low = bearish breadth
        nifty_below_orb = current < orb_low

        direction = "BULLISH" if current > vwap_now and not nifty_below_orb else "BEARISH"

        # No-trade day signals
        no_trade_signals = []
        if gap_pct < -1.5:
            no_trade_signals.append(f"Nifty gapped down {gap_pct:.1f}% — gap-fill risk")
        if nifty_first_red and gap_pct > 1.0:
            no_trade_signals.append("Nifty gap-up with red first candle — trap reversal risk")
        if nifty_below_orb:
            no_trade_signals.append("Nifty broke below opening range low — avoid longs")

        return {
            "price":           round(current, 2),
            "open":            round(open_price, 2),
            "gap_pct":         gap_pct,
            "orb_high":        round(orb_high, 2),
            "orb_low":         round(orb_low, 2),
            "vwap":            round(vwap_now, 2),
            "direction":       direction,
            "first_candle_red": nifty_first_red,
            "below_orb":       nifty_below_orb,
            "no_trade_signals": no_trade_signals,
        }
    except Exception as e:
        print(f"  Nifty error: {e}")
        return {}


# ── Analyse single stock ──────────────────────────────────────────────────────

def analyse_stock(ticker: str, regime: str, nifty: dict) -> dict | None:
    try:
        df = get_intraday(ticker)
        if df is None or df.empty:
            return None

        # Previous close for gap calculation
        df_daily = yf.download(ticker, period="5d", interval="1d",
                               progress=False, auto_adjust=True)
        df_daily.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                            for c in df_daily.columns]
        prev_close = float(df_daily["close"].iloc[-2]) if len(df_daily) >= 2 else None

        open_price  = float(df["open"].iloc[0])
        current     = float(df["close"].iloc[-1])
        gap_pct     = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0

        # Opening Range (9:15 - 9:30am)
        orb = df[df.index.time <= time(9, 30)]
        if orb.empty:
            return None
        orb_high     = float(orb["high"].max())
        orb_low      = float(orb["low"].min())
        orb_range    = round(orb_high - orb_low, 2)
        orb_range_pct = round(orb_range / orb_low * 100, 2)

        # First candle (9:15-9:20 or first 5-min)
        first_candle     = orb.iloc[0]
        first_candle_red = float(first_candle["close"]) < float(first_candle["open"])

        # VWAP
        vwap         = calc_vwap(df)
        vwap_now     = round(float(vwap.iloc[-1]), 2)
        vwap_slope   = float(vwap.iloc[-1]) > float(vwap.iloc[max(0, len(vwap)-4)])
        above_vwap   = current > vwap_now

        # Volume
        avg_vol      = float(df["volume"].mean())
        orb_vol_rate = float(orb["volume"].sum()) / max(len(orb), 1)
        post_orb     = df[df.index.time > time(9, 30)]
        post_vol_avg = float(post_orb["volume"].mean()) if not post_orb.empty else avg_vol
        vol_expanding = post_vol_avg > avg_vol

        # Breakout status
        broke_out    = current > orb_high
        broke_down   = current < orb_low
        near_breakout = not broke_out and current >= orb_high * 0.995

        # Higher highs post-ORB
        hh = False
        if not post_orb.empty and len(post_orb) >= 2:
            hh = all(post_orb["high"].iloc[i] >= post_orb["high"].iloc[i-1]
                     for i in range(1, min(len(post_orb), 4)))

        # ATR from daily data for dynamic targets
        atr_daily = None
        try:
            import ta
            df_atr = yf.download(ticker, period="30d", interval="1d",
                                 progress=False, auto_adjust=True)
            df_atr.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                              for c in df_atr.columns]
            atr_series = ta.volatility.AverageTrueRange(
                df_atr["high"], df_atr["low"], df_atr["close"], 14
            ).average_true_range()
            atr_daily = float(atr_series.iloc[-1])
        except:
            atr_daily = orb_range * 2  # fallback

        # ── Dynamic Targets (ATR-based) ──────────────────────────────────
        entry_trigger = round(orb_high + 0.05, 2)
        target1       = round(entry_trigger + 1.5 * atr_daily, 2)
        target2       = round(entry_trigger + 2.5 * atr_daily, 2)
        stop_loss     = round(orb_low - 0.05, 2)
        stop_pct      = round((stop_loss / entry_trigger - 1) * 100, 2)
        reward1_pct   = round((target1 / entry_trigger - 1) * 100, 2)
        reward2_pct   = round((target2 / entry_trigger - 1) * 100, 2)
        rr1 = round(abs(reward1_pct / stop_pct), 2) if stop_pct != 0 else 0
        rr2 = round(abs(reward2_pct / stop_pct), 2) if stop_pct != 0 else 0

        # ── Position Sizing ──────────────────────────────────────────────
        capital       = CAPITAL_BY_REGIME.get(regime, 12500)
        qty           = max(1, int(capital / entry_trigger)) if entry_trigger > 0 else 0
        actual_capital = round(qty * entry_trigger, 2)
        max_loss      = round(qty * abs(entry_trigger - stop_loss), 2)

        # ── Probability Score ────────────────────────────────────────────
        score_factors = [
            broke_out,           # broke ORB high
            above_vwap,          # above VWAP
            vwap_slope,          # VWAP sloping up
            vol_expanding,       # volume expanding
            hh,                  # higher highs
            gap_pct > 0,         # positive gap
            gap_pct < 2.0,       # not over-gapped
            rr1 >= 1.5,          # good risk/reward
            not first_candle_red or gap_pct < 0.5,  # no gap trap
            nifty.get("direction") == "BULLISH",     # market bullish
        ]
        prob_score = round(sum(score_factors) / len(score_factors) * 100)

        # ── Invalidation Rules ───────────────────────────────────────────
        invalidations = []
        if nifty.get("below_orb"):
            invalidations.append("Nifty broke its own ORB low — avoid all longs")
        if nifty.get("first_candle_red") and nifty.get("gap_pct", 0) > 1.0:
            invalidations.append("Nifty gap-up trap — high reversal risk today")
        if broke_down:
            invalidations.append("Stock broke below ORB low — setup invalidated")
        if not above_vwap and not near_breakout:
            invalidations.append("Below VWAP with no breakout — no valid long")

        # ── Gap Trap Rejection ───────────────────────────────────────────
        gap_trap = gap_pct > 2.0 and first_candle_red
        if gap_trap:
            invalidations.append(
                f"GAP TRAP: Gapped up {gap_pct:.1f}% but first candle closed red — "
                f"institutions selling into gap, do not buy"
            )

        # ── Verdict ──────────────────────────────────────────────────────
        positive = []
        cautious = []

        if gap_trap or broke_down or (invalidations and not broke_out):
            verdict = "SKIP"
        elif capital == 0:
            verdict = "SKIP"
            invalidations.append("DANGER regime — no capital deployed today")
        elif broke_out and above_vwap and prob_score >= 60:
            verdict = "TRADE NOW"
            positive.append("Broke ORB high with VWAP support")
            if vol_expanding:  positive.append("Volume expanding — conviction confirmed")
            if hh:             positive.append("Making higher highs post-ORB")
            if vwap_slope:     positive.append("VWAP sloping upward")
        elif near_breakout and above_vwap and prob_score >= 50:
            verdict = "WATCH — near breakout"
            cautious.append(f"Within 0.5% of ORB high (Rs{orb_high}) — set alert")
            positive.append("Above VWAP — institutional support intact")
        elif broke_out and not above_vwap:
            verdict = "WAIT"
            cautious.append("Broke ORB but below VWAP — weak breakout, wait for VWAP reclaim")
        else:
            verdict = "WAIT"
            cautious.append("Inside opening range — direction not confirmed yet")

        return {
            "ticker":          ticker.replace(".NS", ""),
            "prev_close":      round(prev_close, 2) if prev_close else None,
            "open_price":      round(open_price, 2),
            "current":         round(current, 2),
            "gap_pct":         gap_pct,
            "orb_high":        round(orb_high, 2),
            "orb_low":         round(orb_low, 2),
            "orb_range":       orb_range,
            "orb_range_pct":   orb_range_pct,
            "vwap":            vwap_now,
            "above_vwap":      above_vwap,
            "vwap_slope":      vwap_slope,
            "broke_out":       broke_out,
            "vol_expanding":   vol_expanding,
            "first_candle_red": first_candle_red,
            "gap_trap":        gap_trap,
            "atr_daily":       round(atr_daily, 2) if atr_daily else None,
            "entry_trigger":   entry_trigger,
            "target1":         target1,
            "target2":         target2,
            "stop_loss":       stop_loss,
            "stop_pct":        stop_pct,
            "reward1_pct":     reward1_pct,
            "reward2_pct":     reward2_pct,
            "rr1":             rr1,
            "rr2":             rr2,
            "prob_score":      prob_score,
            "qty":             qty,
            "capital":         actual_capital,
            "max_loss":        max_loss,
            "verdict":         verdict,
            "positive":        positive,
            "cautious":        cautious,
            "invalidations":   invalidations,
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(nifty: dict, results: list, regime: str) -> str:
    now   = datetime.now()
    lines = []

    capital_today = CAPITAL_BY_REGIME.get(regime, 12500)
    size_label    = {
        "BULL": "FULL SIZE (Rs 40,000/trade)",
        "NEUTRAL": "HALF SIZE (Rs 25,000/trade)",
        "CAUTION": "QUARTER SIZE (Rs 12,500/trade)",
        "BEAR":    "QUARTER SIZE (Rs 12,500/trade)",
        "DANGER":  "NO TRADES TODAY",
        "UNKNOWN": "REDUCED SIZE (Rs 12,500/trade)",
    }.get(regime, "REDUCED SIZE")

    lines.append("=" * 65)
    lines.append(f"  OPENING RANGE REPORT v2 — {now.strftime('%A, %B %d %Y %I:%M %p')} IST")
    lines.append("=" * 65)
    lines.append("")

    # Market context
    if nifty:
        lines.append(f"NIFTY AT 9:45am: {nifty.get('direction','?')}")
        lines.append(f"  Price: {nifty.get('price','?')}  |  Gap: {nifty.get('gap_pct',0):+.1f}%  "
                     f"|  VWAP: {nifty.get('vwap','?')}")
        lines.append(f"  ORB: {nifty.get('orb_low','?')} — {nifty.get('orb_high','?')}")
        if nifty.get("no_trade_signals"):
            lines.append(f"  *** WARNING ***")
            for w in nifty["no_trade_signals"]:
                lines.append(f"    [-] {w}")
        lines.append("")

    lines.append(f"REGIME: {regime}  |  POSITION SIZE: {size_label}")
    lines.append("")

    if capital_today == 0:
        lines.append("  *** DO NOT TRADE TODAY — DANGER REGIME ***")
        lines.append("=" * 65)
        return "\n".join(lines)

    order   = {"TRADE NOW": 0, "WATCH — near breakout": 1, "WAIT": 2, "SKIP": 3}
    results = sorted(results, key=lambda x: (-x["prob_score"],
                                              order.get(x["verdict"], 9)))

    trade_now = [r for r in results if r["verdict"] == "TRADE NOW"]
    watch     = [r for r in results if "WATCH" in r["verdict"]]
    wait      = [r for r in results if r["verdict"] == "WAIT"]
    skip      = [r for r in results if r["verdict"] == "SKIP"]

    lines.append(f"SUMMARY: {len(trade_now)} TRADE NOW | {len(watch)} WATCH | "
                 f"{len(wait)} WAIT | {len(skip)} SKIP")
    lines.append("")

    def stock_block(r, show_trade_plan=True):
        block = []
        verdict_tag = f"  {r['verdict']}  [{r['prob_score']}% probability]"
        block.append(verdict_tag)
        block.append(f"  {r['ticker']}")
        block.append(f"  {'─'*45}")
        block.append(f"  Current Price  : Rs {r['current']}")
        block.append(f"  Gap from prev  : {r['gap_pct']:+.1f}%  "
                     f"(prev Rs {r['prev_close']} | opened Rs {r['open_price']})")
        block.append(f"  Opening Range  : Rs {r['orb_low']} — Rs {r['orb_high']}  "
                     f"({r['orb_range_pct']}% wide)")
        block.append(f"  VWAP           : Rs {r['vwap']}  "
                     f"({'ABOVE' if r['above_vwap'] else 'BELOW'}, "
                     f"{'sloping UP' if r['vwap_slope'] else 'flat/down'})")
        block.append(f"  Volume         : {'EXPANDING' if r['vol_expanding'] else 'WEAK'}")
        block.append(f"  ATR (daily)    : Rs {r['atr_daily']}")
        if r.get("gap_trap"):
            block.append(f"  *** GAP TRAP DETECTED — DO NOT BUY ***")
        block.append("")

        if show_trade_plan and r["verdict"] not in ("SKIP",):
            block.append(f"  TRADE PLAN:")
            block.append(f"    Entry trigger  : Rs {r['entry_trigger']}  (break above ORB high)")
            block.append(f"    Target 1 (50%) : Rs {r['target1']}  ({r['reward1_pct']:+.1f}%)  "
                         f"[1.5x ATR] — sell half here")
            block.append(f"    Target 2 (50%) : Rs {r['target2']}  ({r['reward2_pct']:+.1f}%)  "
                         f"[2.5x ATR] — trail stop for rest")
            block.append(f"    Stop Loss      : Rs {r['stop_loss']}  ({r['stop_pct']:+.1f}%)  "
                         f"[below ORB low]")
            block.append(f"    Risk/Reward    : 1:{r['rr1']} (T1)  |  1:{r['rr2']} (T2)")
            block.append("")
            block.append(f"  POSITION SIZE ({regime} regime):")
            block.append(f"    Qty            : {r['qty']} shares")
            block.append(f"    Capital needed : Rs {r['capital']:,.0f}")
            block.append(f"    Max loss       : Rs {r['max_loss']:,.0f}  "
                         f"(if stop hit)")
            block.append("")

        if r["positive"]:
            block.append(f"  WHY THIS SETUP:")
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

    if trade_now:
        lines.append("=" * 65)
        lines.append("  *** TRADE NOW ***")
        lines.append("=" * 65)
        for r in trade_now:
            lines.extend(stock_block(r, show_trade_plan=True))

    if watch:
        lines.append("=" * 65)
        lines.append("  WATCH — Set Price Alert at Entry Trigger")
        lines.append("=" * 65)
        for r in watch:
            lines.extend(stock_block(r, show_trade_plan=True))

    if wait:
        lines.append("=" * 65)
        lines.append("  WAIT — No Signal Yet")
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
        lines.append("  SKIP — No Valid Setup")
        lines.append("=" * 65)
        for r in skip:
            lines.append(f"  {r['ticker']}  [{r['prob_score']}%]  |  Rs {r['current']}")
            for s in r["invalidations"]:
                lines.append(f"    [-] {s}")
        lines.append("")

    lines.append("=" * 65)
    lines.append("  TRADE MANAGEMENT RULES:")
    lines.append("  1. Enter only on TRADE NOW — price must cross entry trigger")
    lines.append("  2. Confirm with volume spike at breakout candle")
    lines.append("  3. Sell 50% at Target 1 — move stop to entry (risk-free)")
    lines.append("  4. Trail stop below each new higher low for Target 2")
    lines.append("  5. Exit 100% if any 5-min candle closes below VWAP")
    lines.append("  6. Exit 100% if Nifty breaks its opening range low")
    lines.append("  7. No new entries after 1:30pm IST")
    lines.append("  8. Max 3 trades per day")
    lines.append("=" * 65)

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_opening_range():
    print(f"\n{'='*65}")
    print(f"  OPENING RANGE AGENT v2 — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    tickers, regime = get_morning_picks()
    capital = CAPITAL_BY_REGIME.get(regime, 12500)
    print(f"Regime: {regime} | Position size: Rs {capital:,}/trade")
    print(f"Analysing {len(tickers)} stocks from morning scan...\n")

    if capital == 0:
        print("DANGER REGIME — no trades today. Report saved.")
        nifty  = get_nifty_context()
        report = build_report(nifty, [], regime)
        fname  = os.path.join(REPORTS_DIR, f"opening_range_{date.today().isoformat()}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        return

    print("Fetching Nifty context...")
    nifty = get_nifty_context()
    if nifty:
        print(f"  Nifty: {nifty.get('price')} | Gap: {nifty.get('gap_pct',0):+.1f}% | "
              f"Direction: {nifty.get('direction')}\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        r = analyse_stock(ticker, regime, nifty)
        if r:
            results.append(r)

    if not results:
        print("No intraday data available yet.")
        return

    report = build_report(nifty, results, regime)
    fname  = os.path.join(REPORTS_DIR, f"opening_range_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nReport saved: {fname}")


if __name__ == "__main__":
    run_opening_range()
