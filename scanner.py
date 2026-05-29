"""
Morning Momentum Scanner
Runs at 8am EST Mon-Fri. Screens S&P 500 for high-momentum stocks.
Scoring: RSI > 60, price above MAs, MACD bullish, volume spike, near 52w high.
"""

import yfinance as yf
import pandas as pd
import ta
from datetime import datetime, date
import os

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def get_sp500_tickers():
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        tickers = tables[0]["Symbol"].tolist()
        return [t.replace(".", "-") for t in tickers]
    except Exception as e:
        print(f"Failed to fetch S&P 500 list: {e}")
        return [
            "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO","JPM","LLY",
            "V","UNH","XOM","MA","JNJ","PG","HD","COST","MRK","ABBV",
            "CVX","CRM","BAC","AMD","NFLX","TMO","ORCL","ACN","LIN","MCD",
            "PEP","ADBE","CSCO","WMT","TXN","DIS","INTC","AMGN","INTU","IBM",
            "GS","BLK","SPGI","NOW","ISRG","AMAT","PANW","ADI","REGN","VRTX"
        ]


def score_stock(ticker: str) -> dict | None:
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 60:
            return None

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        close = df["close"]
        volume = df["volume"]

        rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
        macd_obj = ta.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        vol_avg20 = volume.rolling(20).mean()

        latest_idx = -1
        price = float(close.iloc[latest_idx])
        rsi = float(rsi_series.iloc[latest_idx])
        macd_val = float(macd_obj.macd().iloc[latest_idx])
        macd_sig = float(macd_obj.macd_signal().iloc[latest_idx])
        s20 = float(sma20.iloc[latest_idx])
        s50 = float(sma50.iloc[latest_idx])
        s200 = float(sma200.iloc[latest_idx])
        vol_ratio = float(volume.iloc[latest_idx] / vol_avg20.iloc[latest_idx]) if vol_avg20.iloc[latest_idx] > 0 else 0

        high_52w = float(close.tail(252).max())
        low_52w = float(close.tail(252).min())
        pct_from_high = (price / high_52w - 1) * 100
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else price
        daily_change_pct = (price / prev_close - 1) * 100

        score = 0
        criteria = {}

        criteria["RSI > 60"] = rsi > 60
        if criteria["RSI > 60"]: score += 1

        criteria["Above SMA20/50/200"] = price > s20 > s50 > s200
        if criteria["Above SMA20/50/200"]: score += 1

        criteria["MACD Bullish"] = macd_val > macd_sig
        if criteria["MACD Bullish"]: score += 1

        criteria["Volume Spike >1.5x"] = vol_ratio > 1.5
        if criteria["Volume Spike >1.5x"]: score += 1

        criteria["Near 52w High (<10% away)"] = pct_from_high >= -10
        if criteria["Near 52w High (<10% away)"]: score += 1

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "daily_change_pct": round(daily_change_pct, 2),
            "rsi": round(rsi, 1),
            "vol_ratio": round(vol_ratio, 2),
            "pct_from_52w_high": round(pct_from_high, 1),
            "score": score,
            "criteria": criteria,
            "52w_high": round(high_52w, 2),
            "52w_low": round(low_52w, 2),
        }
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


def run_scan():
    print(f"\n{'='*60}")
    print(f"  MOMENTUM SCANNER — {datetime.now().strftime('%A, %B %d %Y %I:%M %p')}")
    print(f"{'='*60}\n")

    tickers = get_sp500_tickers()
    print(f"Scanning {len(tickers)} stocks...\n")

    results = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}          ", end="\r")
        result = score_stock(ticker)
        if result and result["score"] >= 3:
            results.append(result)

    results.sort(key=lambda x: (x["score"], x["rsi"]), reverse=True)
    top = results[:25]

    lines = []
    lines.append("=" * 60)
    lines.append(f"  HIGH MOMENTUM STOCKS — {date.today().strftime('%B %d, %Y')}")
    lines.append(f"  Morning Scan | S&P 500 Universe")
    lines.append("=" * 60)
    lines.append(f"\nFound {len(results)} momentum stocks. Top 25:\n")
    lines.append(f"{'#':<4} {'Ticker':<8} {'Price':>8} {'Day%':>7} {'RSI':>6} {'Vol':>6} {'52wH%':>7} {'Score':>6}")
    lines.append("-" * 60)

    for i, s in enumerate(top, 1):
        lines.append(
            f"{i:<4} {s['ticker']:<8} ${s['price']:>7.2f} "
            f"{s['daily_change_pct']:>+6.1f}% "
            f"{s['rsi']:>6.1f} "
            f"{s['vol_ratio']:>5.1f}x "
            f"{s['pct_from_52w_high']:>+6.1f}% "
            f"{s['score']}/5"
        )

    lines.append("\n" + "-" * 60)
    lines.append("SCORING CRITERIA:")
    lines.append("  [1] RSI > 60       [2] Price > SMA20 > SMA50 > SMA200")
    lines.append("  [3] MACD Bullish   [4] Volume > 1.5x avg   [5] Within 10% of 52w high")
    lines.append("-" * 60)

    if top:
        lines.append("\nDETAIL — TOP 10:\n")
        for s in top[:10]:
            lines.append(f"  {s['ticker']} — ${s['price']} | Score {s['score']}/5")
            for criterion, passed in s["criteria"].items():
                mark = "+" if passed else "-"
                lines.append(f"    [{mark}] {criterion}")
            lines.append(f"    52w range: ${s['52w_low']} — ${s['52w_high']}")
            lines.append("")

    report = "\n".join(lines)
    print("\n" + report)

    filename = os.path.join(REPORTS_DIR, f"morning_scan_{date.today().isoformat()}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved: {filename}")
    return top


if __name__ == "__main__":
    run_scan()
