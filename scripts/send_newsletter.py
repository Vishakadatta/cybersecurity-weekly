"""
Monday sender.
Optionally does a last-minute emergency scrape check,
then sends the finalized newsletter via Brevo to all subscribers.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
CONTENT_DIR = ROOT_DIR / "content"
RAW_DIR = CONTENT_DIR / "raw"

PT = timezone(timedelta(hours=-7))

SENDER_NAME = "Cybersecurity Weekly"
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "vishakadj@gmail.com")


def get_current_week() -> tuple[str, str]:
    now = datetime.now(PT)
    year = str(now.year)
    week = f"w{now.isocalendar()[1]:02d}"
    return year, week


def load_subscribers(private_data_path: str | None = None) -> list[str]:
    """Load subscriber emails from the private repo checkout."""
    search_paths = [
        Path(private_data_path) / "subscribers" / "emails.json" if private_data_path else None,
        ROOT_DIR / "private-data" / "subscribers" / "emails.json",
    ]

    for p in search_paths:
        if p and p.exists():
            with open(p) as f:
                data = json.load(f)
            return data.get("emails", [])

    print("[WARN] No subscriber file found, no emails will be sent", file=sys.stderr)
    return []


def send_email(api_instance, to_email: str, subject: str, html_content: str) -> bool:
    """Send a single email via Brevo."""
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email}],
        sender={"name": SENDER_NAME, "email": SENDER_EMAIL},
        subject=subject,
        html_content=html_content,
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        return True
    except ApiException as e:
        masked = to_email[:3] + "***@" + to_email.split("@")[1] if "@" in to_email else "***"
        print(f"  [ERROR] Failed to send to {masked}: {e}", file=sys.stderr)
        return False


def main():
    brevo_key = os.environ.get("BREVO_API_KEY")
    if not brevo_key:
        print("ERROR: BREVO_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_key
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    year, week = get_current_week()
    content_file = CONTENT_DIR / year / f"{week}.json"
    email_file = RAW_DIR / f"{year}-{week}-email.html"

    if not content_file.exists():
        print(f"ERROR: No finalized content at {content_file}", file=sys.stderr)
        sys.exit(1)

    with open(content_file) as f:
        content = json.load(f)

    if not email_file.exists():
        print(f"ERROR: No email HTML at {email_file}", file=sys.stderr)
        sys.exit(1)

    with open(email_file) as f:
        html_content = f.read()

    subject = content["subjectLine"]
    private_data_path = os.environ.get("PRIVATE_DATA_PATH")
    subscribers = load_subscribers(private_data_path)

    if not subscribers:
        print("No subscribers found. Skipping email send.")
        return

    print(f"Sending newsletter to {len(subscribers)} subscribers")
    print(f"Subject: {subject}")

    sent = 0
    failed = 0
    for email in subscribers:
        if send_email(api_instance, email, subject, html_content):
            sent += 1
            masked = email[:3] + "***@" + email.split("@")[1] if "@" in email else "***"
            print(f"  [OK] {masked}")
        else:
            failed += 1

    print(f"\nDone: {sent} sent, {failed} failed out of {len(subscribers)} total")


if __name__ == "__main__":
    main()
