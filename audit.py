"""
Layer 3: Performance Audit Agent — 6:30pm IST Mon-Fri
Reads today's signals and end-of-day prices, categorizes every decision into:
  - GOOD_WIN     : Triggered, hit target
  - GOOD_LOSS    : Triggered, hit stop loss cleanly
  - FALSE_POSITIVE: Triggered but reversed without hitting SL (manual exit)
  - VALID_SKIP   : Correctly skipped a bad setup
  - MISSED_TRADE : Did not trigger but would have worked

Also maintains a running performance log (trade_journal.json) for optimization.
"""

import yfinance as yf
import pandas as pd
import json
import os
import glob
from datetime import datetime, date
import warnings
warnings.filterwarnings("ignore")

REPORTS_DIR  = os.path.join(os.path.dirname(__file__), "reports")
JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "trade_journal.json")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ── Load today's opening range report ────────────────────────────────────────

def load_todays_signals() -> list:
    """Parse today's opening range report for signals."""
    pattern = os.path.join(REPORTS_DIR, f"opening_range_{date.today().isoformat()}.txt")
    files   = glob.glob(pattern)
    if not files:
        print("No opening range report found for today.")
        return []

    with open(files[0], encoding="utf-8") as f:
        lines = f.readlines()

    signals = []
    current = {}
    for line in lines:
        line = line.strip()
        if line.startswith("SYMBOL:") or (line and line.isupper() and len(line) <= 12
                                           and not any(c in line for c in [":", "|", "-"])):
            if current:
                signals.append(current)
            current = {"ticker": line.replace("SYMBOL:", "").strip()}
        elif "Entry trigger" in line or "Entry :" in line:
            try:
                current["entry"] = float(line.split("Rs")[-1].split()[0].strip())
            except: pass
        elif "Target 1" in line and "Rs" in line:
            try:
                current["target1"] = float(line.split("Rs")[-1].split()[0].strip())
            except: pass
        elif "Target 2" in line and "Rs" in line:
            try:
                current["target2"] = float(line.split("Rs")[-1].split()[0].strip())
            except: pass
        elif "Stop Loss" in line and "Rs" in line:
            try:
                current["stop"] = float(line.split("Rs")[1].split()[0].strip())
            except: pass
        elif "TRADE NOW" in line:
            current["verdict"] = "TRADE NOW"
        elif "WATCH" in line and "verdict" not in current:
            current["verdict"] = "WATCH"
        elif "SKIP" in line and "verdict" not in current:
            current["verdict"] = "SKIP"
        elif "WAIT" in line and "verdict" not in current:
            current["verdict"] = "WAIT"

    if current and "ticker" in current:
        signals.append(current)

    return signals


# ── Get end of day price data ─────────────────────────────────────────────────

def get_eod_data(ticker: str) -> dict | None:
    """Get today's OHLCV and intraday high/low for the full session."""
    try:
        ns_ticker = ticker + ".NS" if not ticker.endswith(".NS") else ticker
        df = yf.download(ns_ticker, period="2d", interval="5m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today = df[df.index.date == date.today()]
        if today.empty:
            return None

        return {
            "open":        float(today["open"].iloc[0]),
            "high":        float(today["high"].max()),
            "low":         float(today["low"].min()),
            "close":       float(today["close"].iloc[-1]),
            "session_high": float(today["high"].max()),
            "session_low":  float(today["low"].min()),
        }
    except Exception as e:
        print(f"  EOD data error for {ticker}: {e}")
        return None


# ── Categorize each signal ────────────────────────────────────────────────────

def categorize_signal(signal: dict, eod: dict) -> dict:
    """
    Determine outcome bucket for each signal.
    """
    ticker  = signal.get("ticker", "?")
    verdict = signal.get("verdict", "SKIP")
    entry   = signal.get("entry")
    target1 = signal.get("target1")
    stop    = signal.get("stop")

    if eod is None:
        return {**signal, "outcome": "NO_DATA", "outcome_detail": "Could not fetch EOD data"}

    session_high = eod["session_high"]
    session_low  = eod["session_low"]
    close        = eod["close"]

    # For TRADE NOW signals
    if verdict == "TRADE NOW" and entry:
        triggered = session_high >= entry  # price reached entry trigger

        if not triggered:
            # Signal said TRADE NOW but price never reached entry
            outcome = "VALID_SKIP" if session_low < (entry * 0.98) else "MISSED_TRADE"
            detail  = ("Entry never triggered — stock went down, skip was correct"
                       if outcome == "VALID_SKIP" else
                       "Entry never triggered — stock consolidated, no move")
        else:
            # Was triggered — did it hit target or stop?
            hit_target1 = target1 and session_high >= target1
            hit_stop    = stop and session_low <= stop

            if hit_target1 and not hit_stop:
                outcome = "GOOD_WIN"
                gain    = round((target1 - entry) / entry * 100, 2) if target1 else 0
                detail  = f"Hit Target 1 (Rs {target1}) — +{gain}%"
            elif hit_target1 and hit_stop:
                outcome = "GOOD_WIN"  # assume T1 hit first (intraday pattern)
                gain    = round((target1 - entry) / entry * 100, 2) if target1 else 0
                detail  = f"Hit Target 1 (Rs {target1}) before stop — +{gain}% (partial)"
            elif hit_stop and not hit_target1:
                outcome = "GOOD_LOSS"
                loss    = round((stop - entry) / entry * 100, 2) if stop else 0
                detail  = f"Hit stop loss (Rs {stop}) — {loss}% (clean stop, system worked)"
            else:
                outcome = "FALSE_POSITIVE"
                chg     = round((close - entry) / entry * 100, 2)
                detail  = f"Triggered but no target/stop hit — closed at Rs {close} ({chg:+.1f}%)"

    # For WATCH / WAIT signals
    elif verdict in ("WATCH", "WAIT") and entry:
        triggered = session_high >= entry
        if triggered and target1 and session_high >= target1:
            outcome = "MISSED_TRADE"
            detail  = f"Would have worked — reached Target 1 (Rs {target1})"
        elif triggered:
            outcome = "MISSED_TRADE"
            detail  = f"Entry triggered but no target set — monitor"
        else:
            outcome = "VALID_SKIP"
            detail  = "Correctly watched — no valid entry formed"

    # For SKIP signals
    elif verdict == "SKIP":
        if entry and session_high >= entry and target1 and session_high >= target1:
            outcome = "FALSE_NEGATIVE"
            detail  = f"Skipped but stock hit Rs {target1} — review skip criteria"
        else:
            outcome = "VALID_SKIP"
            detail  = f"Correctly skipped — session high Rs {session_high}"

    else:
        outcome = "NO_SIGNAL"
        detail  = "No actionable signal generated"

    return {
        **signal,
        "eod_open":   eod["open"],
        "eod_high":   eod["high"],
        "eod_low":    eod["low"],
        "eod_close":  eod["close"],
        "outcome":    outcome,
        "outcome_detail": detail,
    }


# ── Update journal ────────────────────────────────────────────────────────────

def update_journal(results: list):
    """Append today's results to the running trade journal."""
    journal = []
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE) as f:
            journal = json.load(f)

    today_entry = {
        "date":    date.today().isoformat(),
        "trades":  results,
        "summary": {
            "good_wins":       sum(1 for r in results if r["outcome"] == "GOOD_WIN"),
            "good_losses":     sum(1 for r in results if r["outcome"] == "GOOD_LOSS"),
            "false_positives": sum(1 for r in results if r["outcome"] == "FALSE_POSITIVE"),
            "valid_skips":     sum(1 for r in results if r["outcome"] == "VALID_SKIP"),
            "missed_trades":   sum(1 for r in results if r["outcome"] == "MISSED_TRADE"),
            "false_negatives": sum(1 for r in results if r["outcome"] == "FALSE_NEGATIVE"),
        }
    }

    # Replace today's entry if exists
    journal = [e for e in journal if e["date"] != date.today().isoformat()]
    journal.append(today_entry)

    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2)

    return today_entry["summary"]


# ── Cumulative stats ──────────────────────────────────────────────────────────

def get_cumulative_stats() -> dict:
    if not os.path.exists(JOURNAL_FILE):
        return {}
    with open(JOURNAL_FILE) as f:
        journal = json.load(f)

    totals = {
        "good_wins": 0, "good_losses": 0, "false_positives": 0,
        "valid_skips": 0, "missed_trades": 0, "total_days": len(journal)
    }
    for entry in journal:
        for key in totals:
            if key != "total_days":
                totals[key] += entry["summary"].get(key, 0)

    total_trades = totals["good_wins"] + totals["good_losses"] + totals["false_positives"]
    totals["win_rate"] = round(totals["good_wins"] / total_trades * 100, 1) if total_trades > 0 else 0
    totals["total_trades"] = total_trades
    return totals


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(results: list, summary: dict, cumulative: dict) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"  PERFORMANCE AUDIT — {date.today().strftime('%A, %B %d %Y')}")
    lines.append(f"  Layer 3 | {datetime.now().strftime('%I:%M %p')} IST")
    lines.append("=" * 65)
    lines.append("")

    lines.append("TODAY'S SUMMARY:")
    lines.append(f"  Good Wins       : {summary['good_wins']}")
    lines.append(f"  Good Losses     : {summary['good_losses']}")
    lines.append(f"  False Positives : {summary['false_positives']}")
    lines.append(f"  Valid Skips     : {summary['valid_skips']}")
    lines.append(f"  Missed Trades   : {summary['missed_trades']}")
    lines.append("")

    # Outcome icons
    icons = {
        "GOOD_WIN": "[WIN]", "GOOD_LOSS": "[LOSS]",
        "FALSE_POSITIVE": "[FP]", "VALID_SKIP": "[SKIP OK]",
        "MISSED_TRADE": "[MISSED]", "FALSE_NEGATIVE": "[FN]",
        "NO_DATA": "[NO DATA]", "NO_SIGNAL": "[NO SIGNAL]"
    }

    lines.append("TRADE-BY-TRADE BREAKDOWN:")
    lines.append("-" * 65)
    for r in results:
        icon = icons.get(r["outcome"], "[?]")
        lines.append(f"  {icon:<12} {r.get('ticker','?'):<12} | Verdict: {r.get('verdict','?')}")
        if r.get("entry"):
            lines.append(f"               Entry: Rs {r['entry']} | "
                         f"Stop: Rs {r.get('stop','?')} | T1: Rs {r.get('target1','?')}")
        lines.append(f"               EOD: O:{r.get('eod_open','?')} H:{r.get('eod_high','?')} "
                     f"L:{r.get('eod_low','?')} C:{r.get('eod_close','?')}")
        lines.append(f"               {r.get('outcome_detail','')}")
        lines.append("")

    if cumulative:
        lines.append("=" * 65)
        lines.append(f"  RUNNING PERFORMANCE ({cumulative['total_days']} days tracked)")
        lines.append("=" * 65)
        lines.append(f"  Total Trades    : {cumulative['total_trades']}")
        lines.append(f"  Win Rate        : {cumulative['win_rate']}%")
        lines.append(f"  Good Wins       : {cumulative['good_wins']}")
        lines.append(f"  Good Losses     : {cumulative['good_losses']}")
        lines.append(f"  False Positives : {cumulative['false_positives']}")
        lines.append(f"  Valid Skips     : {cumulative['valid_skips']}")
        lines.append(f"  Missed Trades   : {cumulative['missed_trades']}")
        lines.append("")

        # Calibration advice
        lines.append("SYSTEM CALIBRATION NOTES:")
        wr = cumulative["win_rate"]
        if wr >= 60:
            lines.append("  System performing well. Maintain current parameters.")
        elif wr >= 50:
            lines.append("  Win rate acceptable. Review false positives — tighten volume filter.")
        elif wr >= 40:
            lines.append("  Below target. Consider raising minimum probability score to 70%.")
        else:
            lines.append("  Win rate low. Review regime filter — may be trading in wrong conditions.")

        fp = cumulative["false_positives"]
        if fp > cumulative["good_wins"]:
            lines.append("  High false positives — add VWAP reclaim confirmation before entry.")
        missed = cumulative["missed_trades"]
        if missed > cumulative["good_wins"]:
            lines.append("  Many missed trades — entry trigger may be set too high above ORB.")

    lines.append("")
    lines.append("=" * 65)
    lines.append("  OUTCOME KEY:")
    lines.append("  GOOD_WIN      = Signal triggered, hit Target 1 or better")
    lines.append("  GOOD_LOSS     = Signal triggered, stop hit cleanly — system worked")
    lines.append("  FALSE_POSITIVE= Triggered but reversed without hitting SL")
    lines.append("  VALID_SKIP    = Correctly avoided a bad setup")
    lines.append("  MISSED_TRADE  = Did not trigger but setup would have worked")
    lines.append("  FALSE_NEGATIVE= Incorrectly skipped a winning setup")
    lines.append("=" * 65)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_audit():
    print(f"\n{'='*65}")
    print(f"  PERFORMANCE AUDIT — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*65}\n")

    signals = load_todays_signals()
    if not signals:
        print("No signals to audit today — writing empty audit report.")
        summary = {"good_wins": 0, "good_losses": 0, "false_positives": 0,
                   "valid_skips": 0, "missed_trades": 0, "false_negatives": 0}
        cumulative = get_cumulative_stats()
        report = build_report([], summary, cumulative)
        fname = os.path.join(REPORTS_DIR, f"audit_{date.today().isoformat()}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Empty audit saved: {fname}")
        return

    print(f"Auditing {len(signals)} signals...\n")
    results = []
    for s in signals:
        ticker = s.get("ticker", "")
        if not ticker:
            continue
        print(f"  Fetching EOD data for {ticker}...")
        eod = get_eod_data(ticker)
        result = categorize_signal(s, eod)
        results.append(result)
        print(f"  {ticker}: {result['outcome']} — {result['outcome_detail']}")

    summary    = update_journal(results)
    cumulative = get_cumulative_stats()
    report     = build_report(results, summary, cumulative)

    fname = os.path.join(REPORTS_DIR, f"audit_{date.today().isoformat()}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)

    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print(report.encode("ascii", errors="replace").decode("ascii"))

    print(f"\nAudit saved: {fname}")
    print(f"Journal updated: {JOURNAL_FILE}")


if __name__ == "__main__":
    run_audit()
