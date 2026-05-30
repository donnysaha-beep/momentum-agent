"""
Intraday Pulse Check — runs every 60 min from 10am to 3pm IST
Monitors Nifty trend and VIX intraday.
Writes market_pulse.json which opening_range.py reads for live invalidation.
If conditions flip bearish mid-day: flags TIGHTEN_STOPS or STOP_NEW_ENTRIES.
"""

import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, date, time
import warnings
warnings.filterwarnings("ignore")

PULSE_FILE  = os.path.join(os.path.dirname(__file__), "market_pulse.json")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

NIFTY_TICKER = "^NSEI"
VIX_TICKER   = "^INDIAVIX"


def get_pulse() -> dict:
    pulse = {
        "timestamp":   datetime.now().isoformat(),
        "date":        date.today().isoformat(),
        "status":      "NORMAL",
        "action":      "CONTINUE",
        "nifty_price": None,
        "nifty_vs_vwap": None,
        "nifty_vs_orb_low": None,
        "vix_level":   None,
        "vix_spike":   False,
        "alerts":      [],
    }

    try:
        # Nifty intraday
        nifty = yf.download(NIFTY_TICKER, period="1d", interval="5m",
                            progress=False, auto_adjust=True)
        if nifty is not None and not nifty.empty:
            nifty.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                             for c in nifty.columns]
            today = nifty[nifty.index.date == date.today()]
            if not today.empty:
                price      = float(today["close"].iloc[-1])
                orb        = today[today.index.time <= time(9, 30)]
                orb_low    = float(orb["low"].min()) if not orb.empty else price
                orb_high   = float(orb["high"].max()) if not orb.empty else price

                # VWAP
                typical    = (today["high"] + today["low"] + today["close"]) / 3
                vwap       = float((typical * today["volume"]).cumsum().iloc[-1] /
                                   today["volume"].cumsum().iloc[-1])

                above_vwap    = price > vwap
                above_orb_low = price > orb_low

                pulse["nifty_price"]       = round(price, 2)
                pulse["nifty_vwap"]        = round(vwap, 2)
                pulse["nifty_orb_low"]     = round(orb_low, 2)
                pulse["nifty_vs_vwap"]     = "ABOVE" if above_vwap else "BELOW"
                pulse["nifty_vs_orb_low"]  = "ABOVE" if above_orb_low else "BELOW"

                if not above_vwap and not above_orb_low:
                    pulse["alerts"].append("Nifty below VWAP AND ORB low — bearish structure")
                elif not above_vwap:
                    pulse["alerts"].append("Nifty below VWAP — weakening")
                elif not above_orb_low:
                    pulse["alerts"].append("Nifty broke ORB low — stop new entries")

    except Exception as e:
        pulse["alerts"].append(f"Nifty data error: {e}")

    try:
        # VIX
        vix = yf.download(VIX_TICKER, period="2d", interval="5m",
                          progress=False, auto_adjust=True)
        if vix is not None and not vix.empty:
            vix.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                           for c in vix.columns]
            today_vix = vix[vix.index.date == date.today()]
            yest_vix  = vix[vix.index.date < date.today()]
            if not today_vix.empty:
                vix_now  = float(today_vix["close"].iloc[-1])
                vix_open = float(today_vix["open"].iloc[0])
                vix_chg  = round((vix_now / vix_open - 1) * 100, 2)
                spike    = vix_chg > 8

                pulse["vix_level"] = round(vix_now, 2)
                pulse["vix_chg"]   = vix_chg
                pulse["vix_spike"] = spike

                if spike:
                    pulse["alerts"].append(f"VIX SPIKE +{vix_chg:.1f}% intraday — fear entering market")
                elif vix_now > 20:
                    pulse["alerts"].append(f"VIX elevated at {vix_now} — reduce position size")

    except Exception as e:
        pulse["alerts"].append(f"VIX data error: {e}")

    # Determine overall action
    critical = any(
        "ORB low" in a or "SPIKE" in a or "bearish structure" in a
        for a in pulse["alerts"]
    )
    warning = any("below VWAP" in a or "elevated" in a for a in pulse["alerts"])

    if critical:
        pulse["status"] = "DANGER"
        pulse["action"] = "STOP_NEW_ENTRIES — tighten stops on open positions"
    elif warning:
        pulse["status"] = "CAUTION"
        pulse["action"] = "TIGHTEN_STOPS — no new entries unless A+ setup"
    else:
        pulse["status"] = "NORMAL"
        pulse["action"] = "CONTINUE — market structure intact"

    return pulse


def run_pulse():
    now = datetime.now()
    print(f"\n  INTRADAY PULSE — {now.strftime('%I:%M %p IST')}")
    print(f"  {'─'*45}")

    pulse = get_pulse()

    print(f"  Nifty : {pulse.get('nifty_price','?')} | "
          f"VWAP: {pulse.get('nifty_vs_vwap','?')} | "
          f"ORB: {pulse.get('nifty_vs_orb_low','?')}")
    print(f"  VIX   : {pulse.get('vix_level','?')} "
          f"({'SPIKE' if pulse.get('vix_spike') else 'OK'})")
    print(f"  Status: {pulse['status']}")
    print(f"  Action: {pulse['action']}")

    if pulse["alerts"]:
        print(f"\n  ALERTS:")
        for a in pulse["alerts"]:
            print(f"    ! {a}")

    # Save pulse file
    with open(PULSE_FILE, "w") as f:
        json.dump(pulse, f, indent=2)

    # Append to daily pulse log
    log_file = os.path.join(REPORTS_DIR, f"pulse_log_{date.today().isoformat()}.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{now.strftime('%H:%M')}] {pulse['status']} | {pulse['action']}\n")
        for a in pulse["alerts"]:
            f.write(f"  ! {a}\n")

    print(f"\n  Pulse saved. Next check in 60 min.\n")
    return pulse


if __name__ == "__main__":
    run_pulse()
