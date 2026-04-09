"""
Monday sender.
Reads the latest finalized edition from content/latest.json
and sends the newsletter via Brevo to all subscribers.
"""

import json
import os
import sys
from pathlib import Path

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

from edition import CONTENT_DIR, RAW_DIR, get_edition

SENDER_NAME = "Cybersecurity Weekly"
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")


def load_subscribers(private_data_path: str | None = None) -> list[str]:
    root = Path(__file__).parent.parent
    search_paths = [
        Path(private_data_path) / "subscribers" / "emails.json" if private_data_path else None,
        root / "private-data" / "subscribers" / "emails.json",
    ]

    for p in search_paths:
        if p and p.exists():
            with open(p) as f:
                data = json.load(f)
            return data.get("emails", [])

    print("[WARN] No subscriber file found, no emails will be sent", file=sys.stderr)
    return []


def send_email(api_instance, to_email: str, subject: str, html_content: str) -> bool:
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
        print(f"  [ERROR] Failed to send to {masked}: status={e.status} body={e.body}", file=sys.stderr)
        return False


def main():
    brevo_key = os.environ.get("BREVO_API_KEY")
    if not brevo_key:
        print("ERROR: BREVO_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    if not SENDER_EMAIL:
        print("ERROR: SENDER_EMAIL environment variable not set", file=sys.stderr)
        sys.exit(1)

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_key
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    year, edition = get_edition()
    content_file = CONTENT_DIR / year / f"{edition}.json"
    email_file = RAW_DIR / f"{edition}-email.html"

    print(f"Edition: {edition}")

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

    print(f"Sender: {SENDER_EMAIL}")
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

    if sent == 0 and failed > 0:
        print("ERROR: All emails failed to send.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
