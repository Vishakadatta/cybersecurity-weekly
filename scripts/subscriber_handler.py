"""
GitHub Issue subscriber handler.
Parses subscribe/unsubscribe issues, updates the private repo's emails.json,
redacts the issue body, and closes it with a confirmation comment.
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
PRIVATE_REPO_TOKEN = os.environ["PRIVATE_REPO_TOKEN"]
REPO_OWNER = os.environ["REPO_OWNER"]
PUBLIC_REPO = os.environ["PUBLIC_REPO"]
PRIVATE_REPO = os.environ["PRIVATE_REPO"]

GITHUB_API = "https://api.github.com"


def gh_api(method: str, path: str, token: str = "", **kwargs):
    """Make an authenticated GitHub API request."""
    t = token or GITHUB_TOKEN
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {t}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API}{path}"
    resp = httpx.request(method, url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else None


def extract_email_from_issue(body: str) -> str | None:
    """Extract email address from issue body (YAML form or plain text)."""
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", body or "")
    return email_match.group(0) if email_match else None


def get_subscribers_file() -> tuple[list[str], str | None]:
    """Fetch the current subscriber list from the private repo."""
    try:
        data = gh_api(
            "GET",
            f"/repos/{REPO_OWNER}/{PRIVATE_REPO}/contents/subscribers/emails.json",
            token=PRIVATE_REPO_TOKEN,
        )
        content = json.loads(
            __import__("base64").b64decode(data["content"]).decode()
        )
        return content.get("emails", []), data.get("sha")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return [], None
        raise


def update_subscribers_file(emails: list[str], sha: str | None):
    """Push updated subscriber list to the private repo."""
    import base64
    content = json.dumps({"emails": sorted(set(emails))}, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    body = {
        "message": f"Update subscriber list ({len(emails)} subscribers)",
        "content": encoded,
    }
    if sha:
        body["sha"] = sha

    gh_api(
        "PUT",
        f"/repos/{REPO_OWNER}/{PRIVATE_REPO}/contents/subscribers/emails.json",
        token=PRIVATE_REPO_TOKEN,
        json=body,
    )


def redact_and_close_issue(issue_number: int, action: str, success: bool):
    """Redact email from the issue body and close it."""
    comment = (
        f"Thanks! You've been **{action}d** successfully."
        if success
        else f"Sorry, couldn't process your {action} request. Please try again or open a new issue."
    )

    gh_api(
        "PATCH",
        f"/repos/{REPO_OWNER}/{PUBLIC_REPO}/issues/{issue_number}",
        json={
            "body": f"*[Email redacted for privacy]*\n\nStatus: {'Processed' if success else 'Failed'}",
            "state": "closed",
        },
    )

    gh_api(
        "POST",
        f"/repos/{REPO_OWNER}/{PUBLIC_REPO}/issues/{issue_number}/comments",
        json={"body": comment},
    )


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("ERROR: GITHUB_EVENT_PATH not set (must run in GitHub Actions)", file=sys.stderr)
        sys.exit(1)

    with open(event_path) as f:
        event = json.load(f)

    issue = event.get("issue", {})
    issue_number = issue.get("number")
    title = (issue.get("title") or "").lower().strip()
    body = issue.get("body", "")

    if "subscribe" not in title and "unsubscribe" not in title:
        print(f"Issue #{issue_number} is not a subscribe/unsubscribe request, skipping")
        return

    is_unsubscribe = "unsubscribe" in title
    action = "unsubscribe" if is_unsubscribe else "subscribe"
    print(f"Processing {action} request from issue #{issue_number}")

    email = extract_email_from_issue(body)
    if not email:
        print(f"No email found in issue #{issue_number}")
        redact_and_close_issue(issue_number, action, success=False)
        return

    print(f"Found email: {email[:3]}***@{email.split('@')[1]}")

    emails, sha = get_subscribers_file()

    if is_unsubscribe:
        if email in emails:
            emails.remove(email)
            print(f"Removed {email[:3]}*** from subscriber list")
        else:
            print(f"Email not found in subscriber list")
    else:
        if email not in emails:
            emails.append(email)
            print(f"Added {email[:3]}*** to subscriber list")
        else:
            print(f"Email already subscribed")

    update_subscribers_file(emails, sha)
    redact_and_close_issue(issue_number, action, success=True)
    print(f"Done processing {action} for issue #{issue_number}")


if __name__ == "__main__":
    main()
