"""
Paper Trade Tracker — NSE Momentum Agent
Logs paper trades during week 1 and tracks P&L vs actual signals.

Commands:
  python paper_tracker.py open   TICKER ENTRY STOP T1 T2 QTY [REGIME]
  python paper_tracker.py close  TICKER EXIT_PRICE
  python paper_tracker.py status            ← open trades with live price
  python paper_tracker.py history           ← all closed trades
  python paper_tracker.py summary           ← overall P&L and win rate

Examples:
  python paper_tracker.py open HDFCBANK 1802.50 1780 1850 1920 14 BULL
  python paper_tracker.py close HDFCBANK 1851
  python paper_tracker.py status
"""

import json
import sys
import os
from datetime import datetime, date

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

TRADES_FILE = os.path.join(os.path.dirname(__file__), "paper_trades.json")


# ── Storage helpers ───────────────────────────────────────────────────────────

def load_trades() -> list:
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE) as f:
        return json.load(f)


def save_trades(trades: list):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


# ── Live price ────────────────────────────────────────────────────────────────

def get_live_price(ticker: str) -> float | None:
    if not HAS_YF:
        return None
    try:
        ns = ticker + ".NS" if not ticker.endswith(".NS") else ticker
        df = yf.download(ns, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        return round(float(df["close"].iloc[-1]), 2)
    except:
        return None


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_open(args: list):
    if len(args) < 6:
        print("Usage: python paper_tracker.py open TICKER ENTRY STOP T1 T2 QTY [REGIME]")
        print("Example: python paper_tracker.py open HDFCBANK 1802.50 1780 1850 1920 14 BULL")
        return

    ticker = args[0].upper().replace(".NS", "")
    try:
        entry  = float(args[1])
        stop   = float(args[2])
        t1     = float(args[3])
        t2     = float(args[4])
        qty    = int(args[5])
        regime = args[6].upper() if len(args) > 6 else "UNKNOWN"
    except ValueError:
        print("Error: ENTRY, STOP, T1, T2 must be numbers. QTY must be a whole number.")
        return

    capital   = round(entry * qty, 2)
    max_loss  = round(abs(entry - stop) * qty, 2)
    reward_t1 = round(abs(t1 - entry) * qty, 2)
    rr1       = round(abs(t1 - entry) / abs(entry - stop), 2) if abs(entry - stop) > 0 else 0

    trade = {
        "id":          len(load_trades()) + 1,
        "status":      "OPEN",
        "ticker":      ticker,
        "regime":      regime,
        "open_date":   date.today().isoformat(),
        "open_time":   datetime.now().strftime("%I:%M %p"),
        "entry":       entry,
        "stop":        stop,
        "target1":     t1,
        "target2":     t2,
        "qty":         qty,
        "capital":     capital,
        "max_loss":    max_loss,
        "reward_t1":   reward_t1,
        "rr1":         rr1,
        "close_date":  None,
        "exit_price":  None,
        "pnl":         None,
        "pnl_pct":     None,
        "outcome":     None,
    }

    trades = load_trades()
    trades.append(trade)
    save_trades(trades)

    print(f"\nPAPER TRADE OPENED")
    print(f"{'='*50}")
    print(f"  Ticker   : {ticker} ({regime} regime)")
    print(f"  Entry    : Rs {entry}  x  {qty} shares")
    print(f"  Capital  : Rs {capital:,.0f}")
    print(f"  Stop     : Rs {stop}  (max loss Rs {max_loss:,.0f})")
    print(f"  Target 1 : Rs {t1}  (reward Rs {reward_t1:,.0f})")
    print(f"  Target 2 : Rs {t2}")
    print(f"  R:R      : 1:{rr1}")
    print(f"{'='*50}")
    print(f"Trade #{trade['id']} saved to {TRADES_FILE}")


def cmd_close(args: list):
    if len(args) < 2:
        print("Usage: python paper_tracker.py close TICKER EXIT_PRICE [BROKERAGE] [TAXES]")
        print("Example: python paper_tracker.py close ADANIGREEN 1426 23 9")
        return

    ticker     = args[0].upper().replace(".NS", "")
    try:
        exit_price = float(args[1])
        brokerage  = float(args[2]) if len(args) > 2 else 0
        taxes      = float(args[3]) if len(args) > 3 else 0
    except ValueError:
        print("Error: EXIT_PRICE, BROKERAGE and TAXES must be numbers.")
        return

    trades = load_trades()
    open_trades = [t for t in trades if t["status"] == "OPEN" and t["ticker"] == ticker]

    if not open_trades:
        print(f"No open paper trade found for {ticker}.")
        return

    trade = open_trades[-1]  # most recent open trade for that ticker
    pnl   = round((exit_price - trade["entry"]) * trade["qty"], 2)
    pnl_pct = round((exit_price / trade["entry"] - 1) * 100, 2)

    if pnl > 0:
        if exit_price >= trade["target1"]:
            outcome = "WIN — hit T1"
        else:
            outcome = "WIN — partial"
    elif pnl < 0:
        if exit_price <= trade["stop"]:
            outcome = "LOSS — stop hit"
        else:
            outcome = "LOSS — early exit"
    else:
        outcome = "BREAK EVEN"

    net_pnl     = round(pnl - brokerage - taxes, 2)
    net_pnl_pct = round((net_pnl / (trade["entry"] * trade["qty"])) * 100, 2)

    trade["status"]      = "CLOSED"
    trade["close_date"]  = date.today().isoformat()
    trade["exit_price"]  = exit_price
    trade["pnl"]         = pnl
    trade["brokerage"]   = brokerage
    trade["taxes"]       = taxes
    trade["net_pnl"]     = net_pnl
    trade["pnl_pct"]     = pnl_pct
    trade["net_pnl_pct"] = net_pnl_pct
    trade["outcome"]     = outcome

    save_trades(trades)

    pnl_sign = "+" if pnl >= 0 else ""
    net_sign = "+" if net_pnl >= 0 else ""
    print(f"\nPAPER TRADE CLOSED")
    print(f"{'='*50}")
    print(f"  Ticker     : {ticker}")
    print(f"  Entry      : Rs {trade['entry']}  ->  Exit: Rs {exit_price}")
    print(f"  Raw P&L    : Rs {pnl_sign}{pnl:,.2f}  ({pnl_sign}{pnl_pct:.2f}%)")
    if brokerage or taxes:
        print(f"  Brokerage  : Rs -{brokerage:.2f}")
        print(f"  Taxes      : Rs -{taxes:.2f}")
        print(f"  Net P&L    : Rs {net_sign}{net_pnl:,.2f}  ({net_sign}{net_pnl_pct:.2f}%)")
    print(f"  Outcome    : {outcome}")
    print(f"{'='*50}")


def cmd_status(args: list):
    trades = load_trades()
    open_trades = [t for t in trades if t["status"] == "OPEN"]

    if not open_trades:
        print("\nNo open paper trades.")
        return

    print(f"\nOPEN PAPER TRADES ({len(open_trades)} positions)")
    print("=" * 70)

    total_capital = 0
    total_unrealized = 0

    for t in open_trades:
        live = get_live_price(t["ticker"])
        unreal = round((live - t["entry"]) * t["qty"], 2) if live else None
        unreal_pct = round((live / t["entry"] - 1) * 100, 2) if live else None

        sign = "+" if (unreal or 0) >= 0 else ""
        live_str   = f"Rs {live}" if live else "N/A"
        unreal_str = f"Rs {sign}{unreal:,.0f} ({sign}{unreal_pct:.1f}%)" if unreal is not None else "N/A"

        print(f"\n  #{t['id']} {t['ticker']} [{t['regime']}]  opened {t['open_date']} @ {t['open_time']}")
        print(f"     Entry: Rs {t['entry']}  |  Qty: {t['qty']}  |  Capital: Rs {t['capital']:,.0f}")
        print(f"     Stop:  Rs {t['stop']}   |  T1: Rs {t['target1']}  |  T2: Rs {t['target2']}")
        print(f"     Live:  {live_str}  |  Unrealized P&L: {unreal_str}")

        if live:
            if live <= t["stop"]:
                print(f"     *** STOP HIT — exit now at Rs {t['stop']} ***")
            elif live >= t["target2"]:
                print(f"     *** TARGET 2 HIT — consider booking full profit ***")
            elif live >= t["target1"]:
                print(f"     *** TARGET 1 HIT — book 50%, move stop to entry ***")

        total_capital    += t["capital"]
        total_unrealized += unreal or 0

    sign = "+" if total_unrealized >= 0 else ""
    print(f"\n{'='*70}")
    print(f"  Total capital deployed: Rs {total_capital:,.0f}")
    print(f"  Total unrealized P&L  : Rs {sign}{total_unrealized:,.0f}")
    print(f"{'='*70}")


def cmd_history(args: list):
    trades = load_trades()
    closed = [t for t in trades if t["status"] == "CLOSED"]

    if not closed:
        print("\nNo closed paper trades yet.")
        return

    print(f"\nCLOSED PAPER TRADES ({len(closed)} trades)")
    print("=" * 70)
    print(f"{'#':<4} {'Ticker':<10} {'Date':<12} {'Entry':>8} {'Exit':>8} "
          f"{'Qty':>5} {'P&L':>10} {'%':>7}  Outcome")
    print("-" * 70)

    total_pnl = 0
    for t in closed:
        sign = "+" if (t["pnl"] or 0) >= 0 else ""
        pnl_str = f"Rs {sign}{t['pnl']:,.0f}" if t["pnl"] is not None else "N/A"
        pct_str = f"{sign}{t['pnl_pct']:.2f}%" if t["pnl_pct"] is not None else "N/A"
        print(f"{t['id']:<4} {t['ticker']:<10} {t['close_date']:<12} "
              f"Rs{t['entry']:>7.2f} Rs{t['exit_price']:>7.2f} "
              f"{t['qty']:>5}   {pnl_str:>10} {pct_str:>7}  {t['outcome']}")
        total_pnl += t["pnl"] or 0

    sign = "+" if total_pnl >= 0 else ""
    print("-" * 70)
    print(f"  Total closed P&L: Rs {sign}{total_pnl:,.0f}")


def cmd_summary(args: list):
    trades = load_trades()
    if not trades:
        print("\nNo paper trades recorded yet.")
        return

    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_t = [t for t in trades if t["status"] == "OPEN"]

    wins   = [t for t in closed if (t["pnl"] or 0) > 0]
    losses = [t for t in closed if (t["pnl"] or 0) < 0]
    be     = [t for t in closed if (t["pnl"] or 0) == 0]

    total_pnl    = sum(t["pnl"] or 0 for t in closed)
    total_wins   = sum(t["pnl"] or 0 for t in wins)
    total_losses = sum(t["pnl"] or 0 for t in losses)
    win_rate     = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win      = round(total_wins / len(wins), 0) if wins else 0
    avg_loss     = round(total_losses / len(losses), 0) if losses else 0
    expectancy   = round(total_pnl / len(closed), 0) if closed else 0

    print(f"\nPAPER TRADING SUMMARY")
    print(f"{'='*50}")
    print(f"  Total trades   : {len(closed)} closed  |  {len(open_t)} open")
    print(f"  Win rate       : {win_rate}%  ({len(wins)}W / {len(losses)}L / {len(be)}BE)")
    print(f"  Total P&L      : Rs {'+' if total_pnl >= 0 else ''}{total_pnl:,.0f}")
    print(f"  Avg win        : Rs +{avg_win:,.0f}")
    print(f"  Avg loss       : Rs {avg_loss:,.0f}")
    print(f"  Expectancy     : Rs {'+' if expectancy >= 0 else ''}{expectancy:,.0f} per trade")

    if closed:
        best  = max(closed, key=lambda t: t["pnl"] or 0)
        worst = min(closed, key=lambda t: t["pnl"] or 0)
        print(f"  Best trade     : {best['ticker']}  Rs +{best['pnl']:,.0f}")
        print(f"  Worst trade    : {worst['ticker']}  Rs {worst['pnl']:,.0f}")

    print(f"{'='*50}")
    print(f"  Note: Week 1 paper trading — no real money at risk.")
    print(f"  After 20+ trades, review system calibration in audit.py.")


# ── Main ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "open":    cmd_open,
    "close":   cmd_close,
    "status":  cmd_status,
    "history": cmd_history,
    "summary": cmd_summary,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Paper Trade Tracker — NSE Momentum Agent")
        print("")
        print("Commands:")
        print("  python paper_tracker.py open   TICKER ENTRY STOP T1 T2 QTY [REGIME]")
        print("  python paper_tracker.py close  TICKER EXIT_PRICE")
        print("  python paper_tracker.py status            ← open trades + live price")
        print("  python paper_tracker.py history           ← closed trades + P&L")
        print("  python paper_tracker.py summary           ← overall stats")
        print("")
        print("Example:")
        print("  python paper_tracker.py open HDFCBANK 1802.50 1780 1850 1920 14 BULL")
        sys.exit(0)

    COMMANDS[sys.argv[1]](sys.argv[2:])
