"""
Zerodha Kite Authentication Helper
Handles the daily login flow and stores the access token for the session.
Run this manually each morning before 9:15am to generate a fresh access token.
"""

import os
import json
import webbrowser
from datetime import date
from kiteconnect import KiteConnect

API_KEY    = os.environ.get("KITE_API_KEY",    "vq3dyqpb9pyddio3")
API_SECRET = os.environ.get("KITE_API_SECRET", "6on05nsdwf5bec4ux4p9rc44jmeo9qm0")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".kite_token.json")


def get_kite() -> KiteConnect:
    """Return an authenticated KiteConnect instance."""
    kite = KiteConnect(api_key=API_KEY)

    # Check if we have a valid token from today
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("date") == date.today().isoformat():
            kite.set_access_token(data["access_token"])
            return kite

    # Need fresh login
    login_url = kite.login_url()
    print(f"\nOpening Zerodha login in browser...")
    print(f"URL: {login_url}\n")
    webbrowser.open(login_url)

    print("After logging in, you will be redirected to a page like:")
    print("  https://127.0.0.1?request_token=XXXXXXXX&action=login&status=success")
    print("\nCopy the 'request_token' value from the URL and paste it here:")
    request_token = input("Request token: ").strip()

    data      = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)

    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": date.today().isoformat(), "access_token": access_token}, f)

    print(f"\nLogged in successfully. Token saved for today.")
    return kite


if __name__ == "__main__":
    kite = get_kite()
    profile = kite.profile()
    print(f"Logged in as: {profile['user_name']} ({profile['user_id']})")
