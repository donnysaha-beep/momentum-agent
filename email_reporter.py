"""
Email Reporter — NSE Momentum Agent
Sends any report file to donny.saha@gmail.com via Gmail SMTP.

Usage (called by GitHub Actions after each agent):
  python email_reporter.py layer0
  python email_reporter.py scanner
  python email_reporter.py opening_range
  python email_reporter.py researcher
  python email_reporter.py audit

Requires GitHub Secrets:
  GMAIL_USER         = donny.saha@gmail.com
  GMAIL_APP_PASSWORD = your 16-char Gmail App Password
"""

import os
import sys
import glob
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
TO_EMAIL    = "donny.saha@gmail.com"

REPORT_CONFIG = {
    "layer0": {
        "pattern": "layer0_intelligence_*.txt",
        "subject": "[Momentum Agent] Layer 0 Market Intelligence — {date}",
        "emoji":   "🌍",
    },
    "scanner": {
        "pattern": "morning_scan_*.txt",
        "subject": "[Momentum Agent] Morning Scan — {date}",
        "emoji":   "📊",
    },
    "opening_range": {
        "pattern": "opening_range_*.txt",
        "subject": "[Momentum Agent] Opening Range Signals — {date}",
        "emoji":   "🔔",
    },
    "researcher": {
        "pattern": "evening_research_*.txt",
        "subject": "[Momentum Agent] Evening Research — {date}",
        "emoji":   "🔬",
    },
    "audit": {
        "pattern": "audit_*.txt",
        "subject": "[Momentum Agent] Performance Audit — {date}",
        "emoji":   "📈",
    },
    "bear_scanner": {
        "pattern": "bear_scanner_*.txt",
        "subject": "[Momentum Agent] Bear Scanner — Short Signals {date}",
        "emoji":   "🐻",
    },
}


def find_latest_report(pattern: str) -> str | None:
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, pattern)), reverse=True)
    return files[0] if files else None


def send_email(subject: str, body: str, gmail_user: str, app_password: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = gmail_user
        msg["To"]      = TO_EMAIL

        # Plain text part
        text_part = MIMEText(body, "plain", "utf-8")

        # HTML part — monospace so the text-art tables render correctly
        html_body = (
            "<html><body>"
            "<pre style='font-family:Courier New,monospace;font-size:13px;"
            "line-height:1.4;white-space:pre;'>"
            + body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</pre></body></html>"
        )
        html_part = MIMEText(html_body, "html", "utf-8")

        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, app_password)
            server.sendmail(gmail_user, TO_EMAIL, msg.as_string())

        print(f"  Email sent to {TO_EMAIL}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("  ERROR: Gmail authentication failed.")
        print("  Check GMAIL_USER and GMAIL_APP_PASSWORD secrets.")
        return False
    except Exception as e:
        print(f"  ERROR sending email: {e}")
        return False


def run(report_type: str):
    config = REPORT_CONFIG.get(report_type)
    if not config:
        print(f"Unknown report type: {report_type}")
        print(f"Valid types: {', '.join(REPORT_CONFIG.keys())}")
        sys.exit(1)

    gmail_user    = os.environ.get("GMAIL_USER", "").strip()
    app_password  = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not gmail_user or not app_password:
        print("  GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping email.")
        print("  (Add these as GitHub Secrets to enable email reports.)")
        return

    report_file = find_latest_report(config["pattern"])
    if not report_file:
        print(f"  No {report_type} report found in {REPORTS_DIR} — nothing to email.")
        return

    with open(report_file, encoding="utf-8") as f:
        body = f.read()

    today_str = date.today().strftime("%A, %B %d %Y")
    subject   = config["subject"].format(date=today_str)
    emoji     = config["emoji"]

    footer = (
        f"\n\n{'='*65}\n"
        f"Sent by: Momentum Agent (GitHub Actions)\n"
        f"Time: {datetime.now().strftime('%I:%M %p IST')} | "
        f"Report: {os.path.basename(report_file)}\n"
        f"Paper trading week — signals only, no real trades yet.\n"
        f"{'='*65}"
    )

    print(f"\n{emoji} Sending {report_type} report email...")
    send_email(subject, body + footer, gmail_user, app_password)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python email_reporter.py <report_type>")
        print(f"Types: {', '.join(REPORT_CONFIG.keys())}")
        sys.exit(1)
    run(sys.argv[1])
