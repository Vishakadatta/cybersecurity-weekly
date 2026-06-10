# Setup Guide

Complete setup instructions for Cybersecurity Weekly.

## 1. Brevo: create the subscriber list + signup form

Brevo owns the entire subscriber lifecycle now — signup, double opt-in,
unsubscribe, bounce handling. No private repo or PAT required.

1. Sign up at https://app.brevo.com/ (free tier: 300 emails/day, unlimited contacts).
2. **Create a contact list**: Contacts → Lists → "Create a list" → name it
   anything (e.g. `cybersecurity-weekly`). Note the numeric **List ID** shown
   in the URL or list properties — you'll need it as `BREVO_LIST_ID`.
3. **Create a signup form**: Contacts → Forms → "Create a new form".
   - Add the email field.
   - Under "Confirmation & redirection", **enable double opt-in** (required
     for legal compliance and to keep deliverability healthy).
   - Under "Contact lists", point new subscribers to the list you created.
   - Save and publish.
4. **Copy the form URL**: on the form's "Share" tab, copy the hosted form URL
   (it looks like `https://sibforms.com/serve/MUIFA…`). This is your
   `PUBLIC_BREVO_FORM_URL`.
5. **Verify a sender address**: Senders, Domains & Dedicated IPs → Senders →
   add the email you want the newsletter to come from. Confirm via the
   verification email Brevo sends.
6. **Generate an API key**: SMTP & API → API Keys → "Generate a new API key".
   Save it as `BREVO_API_KEY`.
7. **(Optional) Create a hosted unsubscribe page**: Contacts → Forms →
   create a second form for unsubscribe, or use the unsubscribe page Brevo
   auto-generates per contact. Copy that URL as `PUBLIC_BREVO_UNSUBSCRIBE_URL`.

## 2. Get LLM API keys

### Groq (free) — used for article summarization

1. Go to https://console.groq.com/keys
2. Create an API key, copy it as `GROQ_API_KEY`.
3. Free tier: 30 RPM, 14.4k requests/day — far more than the weekly pipeline needs.

### Google Gemini (free) — used for tournament ranking + emergency check

1. Go to https://aistudio.google.com/apikey
2. Click "Create API Key", copy as `GEMINI_API_KEY`.
3. Free tier: 15 RPM, 1k RPD on Gemini 2.5 Pro.

## 3. Add secrets + variables to GitHub

Go to the repo's **Settings → Secrets and variables → Actions**.

### Repository secrets

| Secret | Value |
|---|---|
| `GROQ_API_KEY` | Groq API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `BREVO_API_KEY` | Brevo API key |
| `BREVO_LIST_ID` | Numeric ID of your Brevo subscriber list |
| `SENDER_EMAIL` | The verified Brevo sender email address |

### Repository variables

| Variable | Value |
|---|---|
| `SENDER_NAME` | Display name (default: "Cybersecurity Weekly") |
| `SITE_URL` | Public site URL (e.g. `https://you.github.io/cybersecurity-weekly/`) |
| `UNSUBSCRIBE_URL` | URL placed in the email's `List-Unsubscribe` header + footer link |
| `PUBLIC_BREVO_FORM_URL` | Brevo hosted signup form URL — embedded as an iframe on the site |
| `PUBLIC_BREVO_UNSUBSCRIBE_URL` | Optional. URL shown in the site footer as "Unsubscribe" |

Variables are used (instead of secrets) for non-sensitive values so the
Astro build can read them at build time.

## 4. Enable GitHub Pages

1. Repo Settings → Pages.
2. Under "Build and deployment", select **GitHub Actions** as the source.
3. The Monday workflow will deploy automatically.

## 5. Test the pipeline

You can manually trigger each workflow from the Actions tab:

```bash
gh workflow run "Friday: Scrape Sources"
gh workflow run "Saturday: Curate & Summarize"
gh workflow run "Sunday: Finalize & Rank"
gh workflow run "Monday: Send Newsletter & Deploy"
```

## 6. Done

The pipeline runs automatically every week:

- **Friday 4:30 PM PT** — Scrape sources
- **Saturday 12:00 PM PT** — Embedding dedupe + Groq summarization (Gemini fallback)
- **Sunday 6:00 PM PT** — Tournament ranking via Gemini + finalize
- **Monday 9:00 AM PT** — Emergency check + deploy site + send newsletter

## Local development

### Site (Astro)

```bash
npm install
# Optional: set the Brevo form URL so the subscribe section renders the iframe
export PUBLIC_BREVO_FORM_URL="https://sibforms.com/serve/YOUR_ID"
export PUBLIC_BREVO_UNSUBSCRIBE_URL="https://your-unsub-page"
npm run dev          # http://localhost:4321
npm run build        # Production build to dist/
```

### Scripts (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

export GROQ_API_KEY="..."
export GEMINI_API_KEY="..."
export BREVO_API_KEY="..."
export BREVO_LIST_ID="..."
export SENDER_EMAIL="newsletter@yourdomain.com"

python scripts/scrape.py
python scripts/curate.py     # Groq primary, Gemini fallback
python scripts/finalize.py   # Gemini primary, Groq fallback
python scripts/send_newsletter.py
```
