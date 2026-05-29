"""
Evening Research Agent
Runs at 6pm EST daily + weekends. Loads today's morning scan and
produces a deeper report: trend strength, sector context,
relative performance vs S&P 500, and recent news headlines.
"""

import yfinance as yf
import pandas as pd
import ta
from datetime import datetime, date
import os
import glob

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

SP500_ETF = "SPY"


def get_latest_morning_tickers() -> list:
    pattern = os.path.join(REPORTS_DIR, "morning_scan_*.txt")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("No morning scan found. Using default watchlist.")
        return ["NVDA", "AAPL", "MSFT", "META", "AMZN", "GOOGL", "AVGO", "AMD", "TSLA", "LLY"]

    with open(files[0], encoding="utf-8") as f:
        lines = f.readlines()

    tickers = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit() and parts[1].isupper() and len(parts[1]) <= 5:
            tickers.append(parts[1])
        if len(tickers) >= 15:
            break

    return tickers if tickers else ["NVDA", "AAPL", "MSFT", "META", "AMZN"]


def get_spy_performance() -> dict:
    try:
        spy = yf.download(SP500_ETF, period="6mo", interval="1d", progress=False, auto_adjust=True)
        spy.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in spy.columns]
        close = spy["close"]
        return {
            "1d": round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2),
            "1w": round((close.iloc[-1] / close.iloc[-6] - 1) * 100, 2) if len(close) >= 6 else None,
            "1m": round((close.iloc[-1] / close.iloc[-22] - 1) * 100, 2) if len(close) >= 22 else None,
            "3m": round((close.iloc[-1] / close.iloc[-66] - 1) * 100, 2) if len(close) >= 66 else None,
        }
    except:
        return {}


def research_stock(ticker: str, spy_perf: dict) -> dict | None:
    try:
        info = yf.Ticker(ticker).info
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return None

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        close = df["close"]
        high = df["high"]
        low = df["low"]

        perf_1d = round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2) if len(close) >= 2 else 0
        perf_1w = round((close.iloc[-1] / close.iloc[-6] - 1) * 100, 2) if len(close) >= 6 else None
        perf_1m = round((close.iloc[-1] / close.iloc[-22] - 1) * 100, 2) if len(close) >= 22 else None
        perf_3m = round((close.iloc[-1] / close.iloc[-66] - 1) * 100, 2) if len(close) >= 66 else None

        rs_1m = round(perf_1m - spy_perf.get("1m", 0), 2) if perf_1m and spy_perf.get("1m") else None
        rs_3m = round(perf_3m - spy_perf.get("3m", 0), 2) if perf_3m and spy_perf.get("3m") else None

        atr_series = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
        atr_pct = round(float(atr_series.iloc[-1]) / float(close.iloc[-1]) * 100, 2)

        sma50 = close.rolling(50).mean()
        days_above_sma50 = int((close.tail(20) > sma50.tail(20)).sum())

        news_items = []
        try:
            news = yf.Ticker(ticker).news
            for item in (news or [])[:5]:
                title = item.get("content", {}).get("title", "") or item.get("title", "")
                if title:
                    news_items.append(title)
        except:
            pass

        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap"),
            "price": round(float(close.iloc[-1]), 2),
            "pe_ratio": info.get("trailingPE"),
            "perf_1d": perf_1d,
            "perf_1w": perf_1w,
            "perf_1m": perf_1m,
            "perf_3m": perf_3m,
            "rs_vs_spy_1m": rs_1m,
            "rs_vs_spy_3m": rs_3m,
            "atr_pct": atr_pct,
            "days_above_sma50_last20": days_above_sma50,
            "news": news_items,
        }
    except Exception as e:
        print(f"  Error researching {ticker}: {e}")
        return None


def fmt(val, suffix="%") -> str:
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}{suffix}"


def fmt_mcap(val) -> str:
    if not val:
        return "N/A"
    if val >= 1e12:
        return f"${val/1e12:.1f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    return f"${val/1e6:.0f}M"


def run_research():
    print(f"\n{'='*60}")
    print(f"  EVENING RESEARCH — {datetime.now().strftime('%A, %B %d %Y %I:%M %p')}")
    print(f"{'='*60}\n")

    tickers = get_latest_morning_tickers()
    print(f"Researching {len(tickers)} stocks from today's scan...\n")

    spy_perf = get_spy_performance()
    print(f"S&P 500 today: {fmt(spy_perf.get('1d'))} | 1W: {fmt(spy_perf.get('1w'))} | "
          f"1M: {fmt(spy_perf.get('1m'))} | 3M: {fmt(spy_perf.get('3m'))}\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  Researching {ticker} ({i+1}/{len(tickers)})...")
        r = research_stock(ticker, spy_perf)
        if r:
            results.append(r)

    lines = []
    lines.append("=" * 60)
    lines.append(f"  EVENING RESEARCH REPORT — {date.today().strftime('%B %d, %Y')}")
    lines.append("=" * 60)
    lines.append(f"\nS&P 500 BENCHMARK (SPY):")
    lines.append(f"  1D: {fmt(spy_perf.get('1d'))}  1W: {fmt(spy_perf.get('1w'))}  "
                 f"1M: {fmt(spy_perf.get('1m'))}  3M: {fmt(spy_perf.get('3m'))}")
    lines.append("")

    for r in results:
        lines.append("-" * 60)
        lines.append(f"  {r['ticker']} — {r['name']}")
        lines.append(f"  {r['sector']} | {r['industry']} | {fmt_mcap(r['market_cap'])}")
        lines.append(f"  Price: ${r['price']}  |  P/E: {r['pe_ratio'] or 'N/A'}")
        lines.append("")
        lines.append(f"  PERFORMANCE vs SPY:")
        lines.append(f"    1D:  {fmt(r['perf_1d'])}  (SPY: {fmt(spy_perf.get('1d'))})")
        lines.append(f"    1W:  {fmt(r['perf_1w'])}  (SPY: {fmt(spy_perf.get('1w'))})")
        lines.append(f"    1M:  {fmt(r['perf_1m'])}  → Rel Strength: {fmt(r['rs_vs_spy_1m'])}")
        lines.append(f"    3M:  {fmt(r['perf_3m'])}  → Rel Strength: {fmt(r['rs_vs_spy_3m'])}")
        lines.append("")
        lines.append(f"  TREND HEALTH:")
        lines.append(f"    Days above SMA50 (last 20 days): {r['days_above_sma50_last20']}/20")
        lines.append(f"    Daily volatility (ATR%): {r['atr_pct']}%")
        lines.append("")
        if r["news"]:
            lines.append(f"  RECENT NEWS:")
            for headline in r["news"]:
                lines.append(f"    * {headline}")
            lines.append("")

    lines.append("=" * 60)
    lines.append("  END OF REPORT")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print("\n" + report)

    filename = os.path.join(REPORTS_DIR, f"evening_research_{date.today().isoformat()}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved: {filename}")


if __name__ == "__main__":
    run_research()
