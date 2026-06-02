"""
Central Configuration — NSE Momentum Agent
All settings in one place. Change here, applies everywhere.
"""

# ── Identity ──────────────────────────────────────────────────────────────────
AGENT_NAME    = "NSE Momentum Agent"
REPO_OWNER    = "donnysaha-beep"
REPO_NAME     = "momentum-agent"
REPORTS_DIR   = "reports"

# ── Market timing (IST) ───────────────────────────────────────────────────────
MARKET_OPEN   = "09:15"
MARKET_CLOSE  = "15:30"
NO_ENTRY_AFTER = "13:30"  # no new trades after 1:30pm

# ── Capital & position sizing (Rs) ────────────────────────────────────────────
CAPITAL_BY_REGIME = {
    "BULL":    40000,
    "NEUTRAL": 25000,
    "CAUTION": 12500,
    "DANGER":  0,
    "UNKNOWN": 12500,
}
TOTAL_CAPITAL     = 200000   # Rs 2 lakh total
MAX_TRADES_PER_DAY = 3
MAX_SECTOR_PCT     = 0.20    # max 20% capital in one sector

# ── Scoring thresholds ────────────────────────────────────────────────────────
MIN_SCORE_BULL    = 5
MIN_SCORE_NEUTRAL = 6
MIN_SCORE_CAUTION = 8
MIN_SCORE_DANGER  = 99       # effectively no trades

# ── Risk parameters ───────────────────────────────────────────────────────────
ATR_STOP_MULTIPLIER   = 1.5  # stop loss = 1.5x ATR below entry
ATR_TARGET1_MULT      = 1.5  # target 1 = 1.5x ATR above entry
ATR_TARGET2_MULT      = 2.5  # target 2 = 2.5x ATR above entry
MIN_RR_RATIO          = 1.5  # minimum risk:reward to take trade
MAX_ATR_EXTENSION     = 2.0  # skip if price > 2x ATR from SMA20
GAP_TRAP_THRESHOLD    = 2.0  # gap > 2% + red first candle = trap

# ── Market regime thresholds ──────────────────────────────────────────────────
VIX_CALM        = 15.0
VIX_NORMAL      = 20.0
VIX_ELEVATED    = 25.0
VIX_SPIKE_PCT   = 8.0        # VIX day change % = spike
NIFTY_EMA_SHORT = 20
NIFTY_EMA_LONG  = 50

# ── Indicators ────────────────────────────────────────────────────────────────
RSI_IDEAL_LOW  = 55
RSI_IDEAL_HIGH = 75
RSI_OVERBOUGHT = 80
MACD_FAST      = 12
MACD_SLOW      = 26
MACD_SIGNAL    = 9
ATR_PERIOD     = 14
RS_SLOPE_DAYS  = 55
RS_ACCEL_DAYS  = 10
VOL_AVG_DAYS   = 20
MIN_VOL_RATIO  = 1.5         # volume must be 1.5x 20-day avg

# ── Stock universe ────────────────────────────────────────────────────────────
# Imported by scanner.py — single source of truth
UNIVERSE = {
    # Energy & Power
    "RELIANCE.NS":   "Energy",   "ONGC.NS":      "Energy",
    "BPCL.NS":       "Energy",   "IOC.NS":        "Energy",
    "TATAPOWER.NS":  "Energy",   "ADANIGREEN.NS": "Energy",
    "NTPC.NS":       "Energy",   "POWERGRID.NS":  "Energy",
    "COALINDIA.NS":  "Energy",   "NHPC.NS":       "Energy",
    "SJVN.NS":       "Energy",   "CESC.NS":       "Energy",
    "TORNTPOWER.NS": "Energy",
    # IT
    "TCS.NS":        "IT",       "HCLTECH.NS":    "IT",
    "WIPRO.NS":      "IT",       "TECHM.NS":      "IT",
    "NAUKRI.NS":     "IT",       "INDIAMART.NS":  "IT",
    "INFY.NS":       "IT",
    # Banking & Finance
    "HDFCBANK.NS":   "Banking",  "ICICIBANK.NS":  "Banking",
    "SBIN.NS":       "Banking",  "KOTAKBANK.NS":  "Banking",
    "AXISBANK.NS":   "Banking",  "BAJFINANCE.NS": "Banking",
    "BAJAJFINSV.NS": "Banking",  "AUBANK.NS":     "Banking",
    "IDFCFIRSTB.NS": "Banking",  "FEDERALBNK.NS": "Banking",
    "BANDHANBNK.NS": "Banking",  "RBLBANK.NS":    "Banking",
    "MUTHOOTFIN.NS": "Finance",  "CHOLAFIN.NS":   "Finance",
    "SHRIRAMFIN.NS": "Finance",  "MANAPPURAM.NS": "Finance",
    "IIFL.NS":       "Finance",
    # Industrials / Infra
    "LT.NS":         "Infra",    "SIEMENS.NS":    "Infra",
    "ABB.NS":        "Infra",    "BHEL.NS":       "Infra",
    "RVNL.NS":       "Infra",    "IRB.NS":        "Infra",
    "ADANIPORTS.NS": "Infra",    "ADANIENT.NS":   "Infra",
    "GMRAIRPORT.NS": "Infra",
    # Defence
    "HAL.NS":        "Defence",  "BEL.NS":        "Defence",
    # Auto
    "MARUTI.NS":     "Auto",     "BAJAJ-AUTO.NS": "Auto",
    "EICHERMOT.NS":  "Auto",     "HEROMOTOCO.NS": "Auto",
    "M&M.NS":        "Auto",     "TATAMOTORS.NS": "Auto",
    # FMCG
    "HINDUNILVR.NS": "FMCG",    "ITC.NS":        "FMCG",
    "NESTLEIND.NS":  "FMCG",    "DABUR.NS":      "FMCG",
    "MARICO.NS":     "FMCG",    "COLPAL.NS":     "FMCG",
    "BRITANNIA.NS":  "FMCG",    "GODREJCP.NS":   "FMCG",
    "TATACONSUM.NS": "FMCG",
    # Pharma
    "SUNPHARMA.NS":  "Pharma",   "DRREDDY.NS":    "Pharma",
    "CIPLA.NS":      "Pharma",   "DIVISLAB.NS":   "Pharma",
    "APOLLOHOSP.NS": "Pharma",
    # Metals
    "TATASTEEL.NS":  "Metals",   "JSWSTEEL.NS":   "Metals",
    "HINDALCO.NS":   "Metals",   "VEDL.NS":       "Metals",
    "SAIL.NS":       "Metals",   "NMDC.NS":       "Metals",
    "MOIL.NS":       "Metals",   "NATIONALUM.NS": "Metals",
    "JINDALSTEL.NS": "Metals",   "APLAPOLLO.NS":  "Metals",
    # Consumer
    "ASIANPAINT.NS": "Consumer", "TITAN.NS":      "Consumer",
    "PIDILITIND.NS": "Consumer", "PAGEIND.NS":    "Consumer",
    "DMART.NS":      "Consumer", "TRENT.NS":      "Consumer",
    "JUBLFOOD.NS":   "Consumer",
    # Cement
    "ULTRACEMCO.NS": "Cement",   "GRASIM.NS":     "Cement",
    # Electricals
    "HAVELLS.NS":    "Electricals","VOLTAS.NS":    "Electricals",
    "CROMPTON.NS":   "Electricals","POLYCAB.NS":   "Electricals",
    # New Economy
    "NYKAA.NS":      "NewEconomy","ZOMATO.NS":     "NewEconomy",
    "POLICYBZR.NS":  "NewEconomy","PAYTM.NS":      "NewEconomy",
    # PSU
    "IRCTC.NS":      "PSU",      "IRFC.NS":       "PSU",
}

# ── Email (set as GitHub Secrets, not here) ───────────────────────────────────
ALERT_EMAIL = "donny.saha@gmail.com"

# ── Execution log file ────────────────────────────────────────────────────────
EXECUTION_LOG = "execution_log.json"
