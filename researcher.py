"""
Evening Research Agent v2 — NSE India
Loads today's morning scan top picks and produces a deep report:
  - Market regime summary
  - Relative performance vs Nifty (1D/1W/1M/3M)
  - Trend health (days above SMA50, ATR%, extension)
  - RS vs Nifty (55-day slope + today's outperformance)
  - Entry context (tight base vs extended, ATR-based stop suggestion)
  - Recent news headlines
  - Trade verdict: WATCH / WAIT / AVOID
"""

import yfinance as yf
import pandas as pd
import numpy as np
import ta
import json
from datetime import datetime, date
import os
import glob
import warnings
warnings.filterwarnings("ignore")

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

NIFTY_TICKER = "^NSEI"
VIX_TICKER   = "^INDIAVIX"


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(val, suffix="%") -> str:
    if val is None: return "N/A"
    sign = "+" if float(val) >= 0 else ""
    return f"{sign}{float(val):.1f}{suffix}"

def fmt_rs(val) -> str:
    if val is None: return "N/A"
    sign = "+" if float(val) >= 0 else ""
    tag  = " (OUTPERFORMING)" if float(val) > 0.5 else (" (UNDERPERFORMING)" if float(val) < -0.5 else "")
    return f"{sign}{float(val):.1f}%{tag}"

def fmt_mcap(val) -> str:
    if not val: return "N/A"
    if val >= 1e12: return f"Rs{val/1e12:.1f}T"
    if val >= 1e9:  return f"Rs{val/1e9:.1f}B"
    return f"Rs{val/1e6:.0f}M"


# ── Load tickers from morning scan ────────────────────────────────────────────

def get_scan_tickers() -> list:
    pattern = os.path.join(REPORTS_DIR, "morning_scan_*.txt")
    files   = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("No morning scan found. Using default NSE watchlist.")
        return ["HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS","RELIANCE.NS",
                "LT.NS","SBIN.NS","AXISBANK.NS","BAJFINANCE.NS","TATAMOTORS.NS"]

    with open(files[0], encoding="utf-8") as f:
        lines = f.readlines()

    tickers = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit() and parts[1].isupper() and len(parts[1]) <= 12:
            raw = parts[1]
            # Add .NS suffix if not already present and looks like NSE ticker
            if not raw.endswith(".NS") and not raw.startswith("^"):
                raw = raw + ".NS"
            tickers.append(raw)
        if len(tickers) >= 15:
            break

    return tickers if tickers else ["HDFCBANK.NS","INFY.NS","TCS.NS","RELIANCE.NS","LT.NS"]


# ── Market context ────────────────────────────────────────────────────────────

def get_market_context() -> dict:
    # Fix 1: Load regime from layer0.json (single source of truth)
    LAYER0_FILE = os.path.join(os.path.dirname(__file__), "layer0.json")
    layer0_regime = None
    if os.path.exists(LAYER0_FILE):
        try:
            with open(LAYER0_FILE) as f:
                l0 = json.load(f)
            if l0.get("date") == date.today().isoformat():
                layer0_regime = l0.get("regime")
        except:
            pass

    try:
        nifty = yf.download(NIFTY_TICKER, period="6mo", interval="1d",
                            progress=False, auto_adjust=True)
        nifty.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                         for c in nifty.columns]
        nc = nifty["close"]
        ema20 = nc.ewm(span=20, adjust=False).mean()
        ema50 = nc.ewm(span=50, adjust=False).mean()
        # Fix 2: Use layer0 regime if available, else calculate locally
        if layer0_regime:
            regime = layer0_regime
        else:
            regime = ("BULL" if float(nc.iloc[-1]) > float(ema20.iloc[-1]) > float(ema50.iloc[-1])
                      else "CAUTION" if float(nc.iloc[-1]) > float(ema20.iloc[-1])
                      else "BEAR")

        ctx = {
            "nifty_close": nc,
            "nifty_price": round(float(nc.iloc[-1]), 2),
            "nifty_1d":    round((nc.iloc[-1]/nc.iloc[-2]-1)*100, 2) if len(nc)>=2 else 0,
            "nifty_1w":    round((nc.iloc[-1]/nc.iloc[-6]-1)*100, 2) if len(nc)>=6 else 0,
            "nifty_1m":    round((nc.iloc[-1]/nc.iloc[-22]-1)*100, 2) if len(nc)>=22 else 0,
            "nifty_3m":    round((nc.iloc[-1]/nc.iloc[-66]-1)*100, 2) if len(nc)>=66 else 0,
            "regime":      regime,
        }
    except Exception as e:
        return {"nifty_close": None, "nifty_price": 0, "nifty_1d": 0,
                "nifty_1w": 0, "nifty_1m": 0, "nifty_3m": 0, "regime": "UNKNOWN"}

    # Fix 3: VIX fetch was unreachable (was after return). Now fixed.
    try:
        vix = yf.download(VIX_TICKER, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        vix.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                       for c in vix.columns]
        vc = vix["close"]
        ctx["vix"]        = round(float(vc.iloc[-1]), 2)
        ctx["vix_change"] = round((vc.iloc[-1]/vc.iloc[-2]-1)*100, 2) if len(vc)>=2 else 0
    except:
        ctx["vix"] = None
        ctx["vix_change"] = None

    return ctx


# ── Deep research per stock ───────────────────────────────────────────────────

def research_stock(ticker: str, mkt: dict) -> dict | None:
    try:
        info = yf.Ticker(ticker).info
        df   = yf.download(ticker, period="1y", interval="1d",
                           progress=False, auto_adjust=True)
        if df is None or len(df) < 30:
            return None

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]

        # ── Performance ──────────────────────────────────────────────────
        def perf(n):
            return round((close.iloc[-1]/close.iloc[-n]-1)*100, 2) if len(close)>=n else None

        p1d, p1w, p1m, p3m, p6m = perf(2), perf(6), perf(22), perf(66), perf(132)

        # ── Relative Strength vs Nifty ───────────────────────────────────
        nc = mkt.get("nifty_close")
        rs_1d = rs_1m = rs_3m = rs_slope = rs_accel = None
        if nc is not None:
            combined = pd.DataFrame({"s": close, "n": nc}).dropna()
            if len(combined) >= 20:
                rs_1d = round(p1d - mkt["nifty_1d"], 2) if p1d else None
                rs_1m = round(p1m - mkt["nifty_1m"], 2) if p1m else None
                rs_3m = round(p3m - mkt["nifty_3m"], 2) if p3m else None

                rs_series = combined["s"] / combined["n"]
                win = min(55, len(rs_series))
                x   = np.arange(win)
                rs_slope = float(np.polyfit(x, rs_series.tail(win).values, 1)[0]) > 0
                if len(rs_series) >= 20:
                    x10       = np.arange(10)
                    sl_last   = float(np.polyfit(x10, rs_series.tail(10).values, 1)[0])
                    sl_prior  = float(np.polyfit(x10, rs_series.tail(20).head(10).values, 1)[0])
                    rs_accel  = sl_last > sl_prior

        # ── Technical ────────────────────────────────────────────────────
        rsi_series = ta.momentum.RSIIndicator(close, 14).rsi()
        atr_series = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        sma20      = close.rolling(20).mean()
        sma50      = close.rolling(50).mean()
        sma200     = close.rolling(200).mean()
        vol_avg20  = volume.rolling(20).mean()

        price         = float(close.iloc[-1])
        rsi_val       = round(float(rsi_series.iloc[-1]), 1)
        atr_val       = float(atr_series.iloc[-1])
        atr_pct       = round(atr_val / price * 100, 2)
        atr_extension = round((price - float(sma20.iloc[-1])) / atr_val, 2) if atr_val > 0 else 0
        vol_ratio     = round(float(volume.iloc[-1]) / float(vol_avg20.iloc[-1]), 2) if float(vol_avg20.iloc[-1]) > 0 else 0
        days_above_50 = int((close.tail(20) > sma50.tail(20)).sum())
        high_52w      = float(close.tail(252).max())
        low_52w       = float(close.tail(252).min())
        pct_52w_high  = round((price / high_52w - 1) * 100, 1)

        # ── ATR-based stop suggestion ─────────────────────────────────────
        stop_loss     = round(price - 1.5 * atr_val, 2)
        stop_pct      = round((stop_loss / price - 1) * 100, 1)

        # ── Base tightness (low ATR% = tight consolidation = good entry) ──
        atr_10d = float(atr_series.tail(10).mean())
        atr_30d = float(atr_series.tail(30).mean())
        tightening = atr_10d < atr_30d  # volatility contracting = base forming

        # ── Verdict ──────────────────────────────────────────────────────
        watch_signals = []
        wait_signals  = []
        avoid_signals = []

        if rsi_val > 80:
            avoid_signals.append("RSI overbought (>80)")
        if atr_extension > 2.5:
            avoid_signals.append(f"Severely extended ({atr_extension}x ATR from SMA20)")
        if days_above_50 < 5:
            wait_signals.append("Weak trend (only {days_above_50}/20 days above SMA50)")
        if rs_slope:
            watch_signals.append("RS slope positive (institutional accumulation)")
        if rs_accel:
            watch_signals.append("RS accelerating (momentum building)")
        if tightening:
            watch_signals.append("Volatility contracting (base forming, potential breakout)")
        if pct_52w_high >= -3:
            watch_signals.append(f"Within {abs(pct_52w_high):.1f}% of 52w high (breakout zone)")
        if vol_ratio > 2:
            watch_signals.append(f"Heavy volume today ({vol_ratio}x avg) = conviction")
        if atr_extension > 1.5:
            wait_signals.append(f"Extended {atr_extension}x from SMA20 — wait for pullback")
        if rs_1d and rs_1d < -1:
            wait_signals.append("Underperforming Nifty today — wait for RS to recover")

        if avoid_signals:
            verdict = "AVOID"
        elif len(watch_signals) >= 3 and not wait_signals:
            verdict = "WATCH NOW"
        elif watch_signals:
            verdict = "WATCH"
        else:
            verdict = "WAIT"

        # ── News ─────────────────────────────────────────────────────────
        news_items = []
        try:
            for item in (yf.Ticker(ticker).news or [])[:5]:
                title = item.get("content", {}).get("title", "") or item.get("title", "")
                if title:
                    news_items.append(title)
        except:
            pass

        return {
            "ticker":        ticker.replace(".NS", ""),
            "name":          info.get("longName", ticker.replace(".NS","")),
            "sector":        info.get("sector", "Unknown"),
            "market_cap":    info.get("marketCap"),
            "price":         round(price, 2),
            "pe":            info.get("trailingPE"),
            "p1d": p1d, "p1w": p1w, "p1m": p1m, "p3m": p3m, "p6m": p6m,
            "rs_1d": rs_1d, "rs_1m": rs_1m, "rs_3m": rs_3m,
            "rs_slope": rs_slope, "rs_accel": rs_accel,
            "rsi":           rsi_val,
            "atr_pct":       atr_pct,
            "atr_extension": atr_extension,
            "vol_ratio":     vol_ratio,
            "days_above_50": days_above_50,
            "pct_52w_high":  pct_52w_high,
            "52w_high":      round(high_52w, 2),
            "52w_low":       round(low_52w, 2),
            "stop_loss":     stop_loss,
            "stop_pct":      stop_pct,
            "tightening":    tightening,
            "verdict":       verdict,
            "watch_signals": watch_signals,
            "wait_signals":  wait_signals,
            "avoid_signals": avoid_signals,
            "news":          news_items,
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(mkt: dict, results: list) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"  EVENING RESEARCH REPORT v2 (NSE) — {date.today().strftime('%B %d, %Y')}")
    lines.append("=" * 65)
    lines.append("")
    lines.append(f"MARKET REGIME: {mkt['regime']}")
    lines.append(f"  Nifty 50: Rs{mkt['nifty_price']}  "
                 f"1D: {fmt(mkt['nifty_1d'])}  1W: {fmt(mkt['nifty_1w'])}  "
                 f"1M: {fmt(mkt['nifty_1m'])}  3M: {fmt(mkt['nifty_3m'])}")
    lines.append("")

    # Summary table
    lines.append(f"{'Ticker':<14} {'Price':>9} {'1D':>7} {'1M':>7} {'RS-1M':>8} "
                 f"{'RSI':>6} {'Ext':>5} {'Verdict':<14}")
    lines.append("-" * 75)
    for r in results:
        lines.append(
            f"{r['ticker']:<14} Rs{r['price']:>8.1f} "
            f"{fmt(r['p1d']):>7} {fmt(r['p1m']):>7} {fmt(r['rs_1m']):>8} "
            f"{r['rsi']:>6.1f} {r['atr_extension']:>4.1f}x "
            f"  {r['verdict']}"
        )
    lines.append("")

    # Detail per stock
    lines.append("=" * 65)
    lines.append("  FULL DETAIL")
    lines.append("=" * 65)

    for r in results:
        lines.append("")
        lines.append(f"  {r['ticker']} — {r['name']}")
        lines.append(f"  {r['sector']} | {fmt_mcap(r['market_cap'])} | P/E: {r['pe'] or 'N/A'}")
        lines.append(f"  Price: Rs{r['price']}  |  52w range: Rs{r['52w_low']} — Rs{r['52w_high']}")
        lines.append("")

        lines.append(f"  PERFORMANCE vs NIFTY:")
        lines.append(f"    1D:  {fmt(r['p1d'])}  vs Nifty {fmt(mkt['nifty_1d'])}  "
                     f"-> RS: {fmt_rs(r['rs_1d'])}")
        lines.append(f"    1W:  {fmt(r['p1w'])}  vs Nifty {fmt(mkt['nifty_1w'])}")
        lines.append(f"    1M:  {fmt(r['p1m'])}  vs Nifty {fmt(mkt['nifty_1m'])}  "
                     f"-> RS: {fmt_rs(r['rs_1m'])}")
        lines.append(f"    3M:  {fmt(r['p3m'])}  vs Nifty {fmt(mkt['nifty_3m'])}  "
                     f"-> RS: {fmt_rs(r['rs_3m'])}")
        lines.append(f"    6M:  {fmt(r['p6m'])}")
        lines.append("")

        lines.append(f"  TREND HEALTH:")
        lines.append(f"    RSI: {r['rsi']}  |  Days above SMA50 (last 20): {r['days_above_50']}/20")
        lines.append(f"    Daily volatility (ATR%): {r['atr_pct']}%")
        lines.append(f"    ATR extension from SMA20: {r['atr_extension']}x  "
                     + ("(STRETCHED)" if r['atr_extension'] > 2 else
                        "(EXTENDED)" if r['atr_extension'] > 1.5 else "(HEALTHY)"))
        lines.append(f"    Volatility trend: {'CONTRACTING (base forming)' if r['tightening'] else 'EXPANDING'}")
        lines.append(f"    Volume today: {r['vol_ratio']}x 20-day avg")
        lines.append(f"    RS 55-day slope: {'POSITIVE' if r['rs_slope'] else 'NEGATIVE'}"
                     + (" | RS ACCELERATING" if r['rs_accel'] else ""))
        lines.append("")

        lines.append(f"  SUGGESTED STOP LOSS (1.5x ATR): Rs{r['stop_loss']} ({r['stop_pct']}%)")
        lines.append("")

        verdict_line = f"  VERDICT: {r['verdict']}"
        lines.append(verdict_line)
        for s in r["watch_signals"]:
            lines.append(f"    [+] {s}")
        for s in r["wait_signals"]:
            lines.append(f"    [~] {s}")
        for s in r["avoid_signals"]:
            lines.append(f"    [-] {s}")
        lines.append("")

        if r["news"]:
            lines.append(f"  RECENT NEWS:")
            for headline in r["news"]:
                lines.append(f"    * {headline}")
        lines.append("")
        lines.append("-" * 65)

    lines.append("")
    lines.append("=" * 65)
    lines.append("  VERDICT KEY:")
    lines.append("  WATCH NOW = strong setup, entry conditions met")
    lines.append("  WATCH     = good stock, monitor for entry trigger")
    lines.append("  WAIT      = momentum present but entry not ideal yet")
    lines.append("  AVOID     = overbought or breaking down")
    lines.append("=" * 65)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_research():
    print(f"\n{'='*65}")
    print(f"  EVENING RESEARCH v2 (NSE) — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    tickers = get_scan_tickers()
    print(f"Researching {len(tickers)} stocks from today's morning scan...\n")

    mkt = get_market_context()
    print(f"Nifty: {mkt['nifty_price']} ({mkt['nifty_1d']:+.1f}%) | Regime: {mkt['regime']}\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...")
        r = research_stock(ticker, mkt)
        if r:
            results.append(r)

    # Sort: WATCH NOW first, then by RS 1M descending
    order = {"WATCH NOW": 0, "WATCH": 1, "WAIT": 2, "AVOID": 3}
    results.sort(key=lambda x: (order.get(x["verdict"], 9), -(x["rs_1m"] or 0)))

    report = build_report(mkt, results)

    fname = os.path.join(REPORTS_DIR, f"evening_research_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nReport saved: {fname}")


if __name__ == "__main__":
    run_research()
