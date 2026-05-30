"""
Auth Watchdog — 8:15am IST Mon-Fri
Validates Zerodha Kite token and alerts if broken.
Gives 60-min window to fix manually before 9:45am opening range agent.
"""

import os
import json
import requests
from datetime import datetime, date
import warnings
warnings.filterwarnings("ignore")

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".kite_token.json")
API_KEY    = os.environ.get("KITE_API_KEY", "vq3dyqpb9pyddio3")


def validate_token() -> dict:
    """Check if today's Kite token exists and is valid."""
    if not os.path.exists(TOKEN_FILE):
        return {"valid": False, "reason": "No token file found — run kite_auth.py"}

    with open(TOKEN_FILE) as f:
        data = json.load(f)

    if data.get("date") != date.today().isoformat():
        return {"valid": False, "reason": f"Token is from {data.get('date')} — need today's token"}

    access_token = data.get("access_token")
    if not access_token:
        return {"valid": False, "reason": "Token file exists but access_token is missing"}

    # Validate by hitting Kite profile endpoint
    try:
        resp = requests.get(
            "https://api.kite.trade/user/profile",
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {API_KEY}:{access_token}"
            },
            timeout=10
        )
        if resp.status_code == 200:
            profile = resp.json().get("data", {})
            return {
                "valid": True,
                "user": profile.get("user_name", "Unknown"),
                "user_id": profile.get("user_id", "Unknown"),
            }
        else:
            return {"valid": False, "reason": f"API returned {resp.status_code} — token may be expired"}
    except Exception as e:
        return {"valid": False, "reason": f"API call failed: {e}"}


def run_watchdog():
    print(f"\n{'='*55}")
    print(f"  AUTH WATCHDOG — {datetime.now().strftime('%A %d %b %Y %I:%M %p')}")
    print(f"{'='*55}\n")

    result = validate_token()

    if result["valid"]:
        print(f"  [OK] Kite token VALID")
        print(f"  Logged in as: {result['user']} ({result['user_id']})")
        print(f"  Opening range agent will have live data at 9:45am.\n")
    else:
        print(f"  [ALERT] Kite token INVALID")
        print(f"  Reason: {result['reason']}")
        print(f"\n  *** ACTION REQUIRED ***")
        print(f"  You have until 9:45am to fix this.")
        print(f"  Run this command now:")
        print(f"    py kite_auth.py")
        print(f"  Then log in to Zerodha and paste the request token.")
        print(f"\n  Without a valid token, opening range agent will")
        print(f"  fall back to delayed yfinance data (15-min delay).\n")

    print(f"{'='*55}\n")
    return result["valid"]


if __name__ == "__main__":
    run_watchdog()
