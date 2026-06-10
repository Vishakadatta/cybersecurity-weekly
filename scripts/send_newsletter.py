"""
Monday sender.
Reads the latest finalized edition from content/latest.json, pulls subscribers
from a Brevo contact list, and sends the newsletter via Brevo's transactional
API.

Subscribers are managed entirely inside Brevo (signup form, double opt-in,
unsubscribe). This script only reads the list — it never writes to it.
"""

import json
import os
import sys
from pathlib import Path

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

from edition import CONTENT_DIR, RAW_DIR, get_edition

SENDER_NAME = os.environ.get("SENDER_NAME", "Cybersecurity Weekly")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
BREVO_LIST_ID = os.environ.get("BREVO_LIST_ID", "")
UNSUBSCRIBE_URL_TEMPLATE = os.environ.get("UNSUBSCRIBE_URL", "")

PAGE_LIMIT = 500


def load_subscribers_from_brevo(api_client) -> list[dict]:
    """Page through every contact in the configured Brevo list."""
    if not BREVO_LIST_ID:
        print("ERROR: BREVO_LIST_ID environment variable not set", file=sys.stderr)
        sys.exit(1)

    list_id = int(BREVO_LIST_ID)
    contacts_api = sib_api_v3_sdk.ContactsApi(api_client)

    all_contacts: list[dict] = []
    offset = 0
    while True:
        try:
            page = contacts_api.get_contacts_from_list(
                list_id=list_id, limit=PAGE_LIMIT, offset=offset
            )
        except ApiException as e:
            print(f"ERROR: Brevo get_contacts_from_list failed: status={e.status} body={e.body}", file=sys.stderr)
            sys.exit(1)

        contacts = getattr(page, "contacts", []) or []
        if not contacts:
            break
        all_contacts.extend(contacts)
        if len(contacts) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return all_contacts


def send_email(api_instance, to_email: str, subject: str, html_content: str) -> bool:
    headers = {}
    if UNSUBSCRIBE_URL_TEMPLATE:
        headers["List-Unsubscribe"] = f"<{UNSUBSCRIBE_URL_TEMPLATE}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email}],
        sender={"name": SENDER_NAME, "email": SENDER_EMAIL},
        subject=subject,
        html_content=html_content,
        headers=headers or None,
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        return True
    except ApiException as e:
        masked = to_email[:3] + "***@" + to_email.split("@")[1] if "@" in to_email else "***"
        print(f"  [ERROR] Failed to send to {masked}: status={e.status} body={e.body}", file=sys.stderr)
        return False


def _validate_env() -> dict[str, str]:
    """Validate every required env var at once and emit a single, actionable
    error if anything is missing. Failing one-at-a-time across CI runs is
    tedious; this preflight catches all of them in a single failed job."""
    required_secrets = {
        "BREVO_API_KEY":   "GitHub repo Secret. Brevo dashboard → SMTP & API → API Keys.",
        "BREVO_LIST_ID":   "GitHub repo Secret. Numeric ID of your Brevo contact list (Contacts → Lists).",
        "SENDER_EMAIL":    "GitHub repo Secret. The verified Brevo sender email address.",
    }
    required_vars = {
        "SENDER_NAME":     'GitHub repo Variable. The from-name on the email (e.g. "Cybersecurity Weekly").',
        "UNSUBSCRIBE_URL": "GitHub repo Variable. Goes into the List-Unsubscribe header on every send.",
    }

    missing: list[str] = []
    values: dict[str, str] = {}
    for k, hint in {**required_secrets, **required_vars}.items():
        v = os.environ.get(k, "").strip()
        if not v:
            kind = "Secret" if k in required_secrets else "Variable"
            missing.append(f"  - {k:18}  [{kind}]  {hint}")
        else:
            values[k] = v

    if missing:
        print(
            "ERROR: required environment is incomplete. Set the following in\n"
            "  GitHub repo → Settings → Secrets and variables → Actions:\n\n"
            + "\n".join(missing)
            + "\n\nAfter setting them, re-run the workflow via 'Run workflow' on the Actions tab.",
            file=sys.stderr,
        )
        sys.exit(1)

    return values


def main():
    _validate_env()
    brevo_key = os.environ["BREVO_API_KEY"]

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_key
    api_client = sib_api_v3_sdk.ApiClient(configuration)
    transac_api = sib_api_v3_sdk.TransactionalEmailsApi(api_client)

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

    print(f"Fetching subscribers from Brevo list {BREVO_LIST_ID}...")
    contacts = load_subscribers_from_brevo(api_client)
    subscribers = [c.get("email") for c in contacts if c.get("email") and not c.get("emailBlacklisted")]
    subscribers = [e for e in subscribers if e]

    if not subscribers:
        print("No active subscribers found in Brevo list. Skipping email send.")
        return

    print(f"Sender:  {SENDER_EMAIL}")
    print(f"Sending newsletter to {len(subscribers)} subscribers")
    print(f"Subject: {subject}")

    sent = 0
    failed = 0
    for email in subscribers:
        if send_email(transac_api, email, subject, html_content):
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
