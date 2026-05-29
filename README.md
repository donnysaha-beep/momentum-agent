# Momentum Agent

Automated daily stock momentum scanner and research agent for the S&P 500.

## What it does

**Morning Scan (8am EST, Mon-Fri)**
Screens all 500 S&P 500 stocks and scores each 0-5 based on:
- RSI > 60
- Price above SMA20 > SMA50 > SMA200 (full trend alignment)
- MACD bullish crossover
- Volume spike > 1.5x 20-day average
- Within 10% of 52-week high

**Evening Research (6pm EST, Mon-Fri + weekends)**
Deep-dives on the top picks from the morning scan:
- Performance vs S&P 500 (relative strength)
- Sector and industry context
- Trend health (days above SMA50)
- Daily volatility (ATR%)
- Recent news headlines

Reports are saved to the `reports/` folder automatically.

## Setup

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run manually
```bash
python scanner.py      # morning scan
python researcher.py   # evening research
```

### Automated scheduling (GitHub Actions)
Push this repo to GitHub — the workflows in `.github/workflows/` will run automatically on schedule.

### Local scheduling (Windows Task Scheduler)
See `task_scheduler_setup.md` for step-by-step instructions.
