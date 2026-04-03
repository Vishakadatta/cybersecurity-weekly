# Setup Guide

Complete setup instructions for Cybersecurity Weekly.

## 1. Create the Private Repo

Run the automated setup script (requires `gh` CLI):

```bash
bash scripts/setup_private_repo.sh
```

Or manually:
1. Go to https://github.com/new
2. Create a **private** repo named `cybersecurity-weekly-private`
3. Add a file `subscribers/emails.json` with content: `{"emails": []}`

## 2. Get API Keys

### Google Gemini API (free)
1. Go to https://aistudio.google.com/apikey
2. Click "Create API Key"
3. Copy the key

### Brevo Email API (free)
1. Sign up at https://app.brevo.com/
2. Go to SMTP & API → API Keys
3. Create a new API key
4. Copy the key

### GitHub Personal Access Token
1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select the `repo` scope (full control of private repos)
4. Copy the token

## 3. Add Secrets to GitHub

Go to your **public** repo's settings:
`https://github.com/YOUR_USERNAME/cybersecurity-weekly/settings/secrets/actions`

Add these three repository secrets:

| Secret Name | Value |
|-------------|-------|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `BREVO_API_KEY` | Your Brevo transactional email API key |
| `PRIVATE_REPO_TOKEN` | Your GitHub PAT with `repo` scope |

## 4. Enable GitHub Pages

1. Go to repo Settings → Pages
2. Under "Build and deployment", select **GitHub Actions** as the source
3. The Monday workflow will handle deployment automatically

## 5. Verify Brevo Sender

1. In Brevo dashboard, go to Senders & IP
2. Add and verify the sender email address
3. Update `SENDER_EMAIL` in `scripts/send_newsletter.py` if needed

## 6. Test the Pipeline

You can manually trigger each workflow from the GitHub Actions tab:

```bash
# Or via CLI
gh workflow run "Friday: Scrape Sources"
gh workflow run "Saturday: Curate & Summarize"
gh workflow run "Sunday: Finalize & Rank"
gh workflow run "Monday: Send Newsletter & Deploy"
```

## 7. Done!

The pipeline will run automatically every week:
- **Friday 4:30 PM PT** — Scrape sources
- **Saturday 12:00 PM PT** — AI summarize + fresh scrape
- **Sunday 6:00 PM PT** — Tournament ranking + finalize
- **Monday 9:00 AM PT** — Emergency check + deploy + send
