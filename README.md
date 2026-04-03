# Cybersecurity Weekly

A fully automated, zero-cost cybersecurity newsletter and static website that curates, ranks, and delivers the week's most important security news every Monday morning — with zero manual intervention after initial setup.

**Live site:** _coming soon via GitHub Pages_

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [The 4-Day Pipeline](#the-4-day-pipeline)
- [News Sources](#news-sources)
- [Content Priority Tiers](#content-priority-tiers)
- [Subscription Flow](#subscription-flow)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Setup & Configuration](#setup--configuration)
- [Local Development](#local-development)
- [Contributing](#contributing)
- [License](#license)

---

## Why This Exists

Keeping up with cybersecurity news is a firehose. Most newsletters are either manually curated (unsustainable for a solo operator) or AI-generated garbage with no editorial judgment. This project takes a different approach:

- **Automated scraping** pulls from 15+ trusted security sources over a 3-day window
- **AI-powered tournament ranking** (Google Gemini) compares articles head-to-head and tiers the best ones
- **Focus areas** for 5G / indoor cells, NMS / webapp management, and other enterprise-relevant topics get priority
- **Static site + email newsletter** means readers get it however they prefer
- **Completely free to run** using GitHub Actions, GitHub Pages, Gemini free tier, and Brevo free tier

No servers. No databases. No costs. Just a cron job and good taste in sources.

---

## Documentation

**[Functional Specification](docs/FUNCTIONAL_SPEC.md)** — Complete technical specification covering architecture diagrams, code flow, data schemas, AI integration, subscription system, error handling, and more.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WEEKLY PIPELINE                              │
│                                                                     │
│  Friday 4:30 PM PT          Saturday 12:00 PM PT                    │
│  ┌──────────────┐           ┌──────────────────┐                    │
│  │ Initial      │           │ Mid-cycle scrape  │                    │
│  │ Scrape       │──────────▶│ + AI summarize    │                    │
│  │ (all sources)│           │ new articles      │                    │
│  └──────────────┘           └────────┬─────────┘                    │
│                                      │                              │
│  Sunday 6:00 PM PT                   ▼          Monday 9:00 AM PT   │
│  ┌──────────────────┐       ┌──────────────────┐                    │
│  │ Final scrape +   │       │ Breaking news     │                    │
│  │ Tournament rank  │──────▶│ check, build      │                    │
│  │ (AI tiers best)  │       │ site, send email  │                    │
│  └──────────────────┘       └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PUBLIC REPO                                     │
│                   cybersecurity-weekly                                   │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐  ┌───────────────────┐   │
│  │  Astro    │  │  Python   │  │  Content   │  │  GitHub Actions   │   │
│  │  Site     │  │  Scripts  │  │  (JSON)    │  │  Workflows        │   │
│  │           │  │           │  │            │  │                   │   │
│  │ src/      │  │ scripts/  │  │ content/   │  │ .github/          │   │
│  │ layouts/  │  │ scrape.py │  │ weekly/    │  │  workflows/       │   │
│  │ pages/    │  │ curate.py │  │  2026-W14/ │  │   scrape.yml      │   │
│  │ comps/    │  │ finalize. │  │   raw.json │  │   curate.yml      │   │
│  │           │  │   py      │  │   curated. │  │   finalize.yml    │   │
│  │           │  │ send_     │  │    json    │  │   publish.yml     │   │
│  │           │  │  news     │  │   final.   │  │   subscribe.yml   │   │
│  │           │  │  letter.py│  │    json    │  │                   │   │
│  └───────────┘  └─────┬─────┘  └─────┬──────┘  └────────┬──────────┘   │
│                       │              │                   │              │
│                       ▼              ▼                   │              │
│              ┌─────────────────────────────┐             │              │
│              │  GitHub Pages (static site) │             │              │
│              └─────────────────────────────┘             │              │
└─────────────────────────────────────────────────────────┬───────────────┘
                                                          │
                    ┌─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        PRIVATE REPO                                     │
│                cybersecurity-weekly-private                              │
│                                                                         │
│  Only stores subscriber email addresses.                                │
│  Accessed via GitHub PAT from the public repo's Actions.                │
│                                                                         │
│  subscribers/                                                           │
│    emails.json          ← encrypted list of subscriber emails           │
│                                                                         │
│  This repo has NO code, NO workflows, NO secrets beyond what the        │
│  public repo needs to read from it.                                     │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                       EXTERNAL SERVICES                                 │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐   │
│  │ Google       │  │ Brevo        │  │ RSS Feeds / Security Blogs   │   │
│  │ Gemini API   │  │ (email)      │  │ (public internet)            │   │
│  │ (free tier)  │  │ (free tier)  │  │                              │   │
│  └──────────────┘  └──────────────┘  └──────────────────────────────┘   │
│                                                                         │
│  All API keys stored as GitHub Secrets — never in code.                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why Two Repos?

| Concern | Where It Lives | Why |
|---|---|---|
| All source code, scripts, site | **Public repo** | Open source, transparent, forkable |
| Architecture, pipeline docs | **Public repo** | Not sensitive — the code *is* the architecture |
| Subscriber email addresses | **Private repo** | PII must never be in a public repo |
| API keys (Gemini, Brevo, PAT) | **GitHub Secrets** | Never committed to *any* repo |

The private repo is intentionally minimal — it's a dumb data store for emails, nothing else. If you fork this project, you just create your own private repo and point a PAT at it.

---

## The 4-Day Pipeline

Each week, four GitHub Actions workflows run on a fixed schedule:

| # | When (Pacific) | When (UTC) | Workflow | What Happens |
|---|---|---|---|---|
| 1 | **Friday 4:30 PM** | Fri 23:30 | `scrape.yml` | Scrape all RSS feeds and source sites. Store raw articles in `content/weekly/YYYY-WNN/raw.json`. |
| 2 | **Saturday 12:00 PM** | Sat 19:00 | `curate.yml` | Re-scrape for new articles. Send all articles to Gemini for summarization and relevance scoring. Output `curated.json`. |
| 3 | **Sunday 6:00 PM** | Mon 01:00 | `finalize.yml` | Final scrape. Gemini runs **tournament ranking**: articles are compared head-to-head, then assigned to priority tiers. Output `final.json`. |
| 4 | **Monday 9:00 AM** | Mon 16:00 | `publish.yml` | Emergency check for breaking news (last 12 hours). Build the Astro static site. Deploy to GitHub Pages. Send newsletter via Brevo. |

All content at every stage is committed to the repo as JSON, so you can audit exactly what the AI saw, ranked, and published.

### Tournament Ranking

The Sunday finalization step uses a tournament-style comparison rather than asking the AI to score articles in isolation. Gemini compares pairs of articles and picks the stronger one based on:

- Severity and real-world impact
- Relevance to focus areas (5G, indoor cells, NMS/webapp management)
- Novelty (is this actually new, or a rehash?)
- Source credibility

Winners advance. The final ranked list is split into tiers for the newsletter.

---

## News Sources

Feeds and sites scraped weekly:

| Source | Type | URL |
|---|---|---|
| **Security Now (GRC)** | Podcast show notes | grc.com |
| **Krebs on Security** | Blog / RSS | krebsonsecurity.com |
| **The Hacker News** | News / RSS | thehackernews.com |
| **BleepingComputer** | News / RSS | bleepingcomputer.com |
| **Dark Reading** | News / RSS | darkreading.com |
| **CISA Advisories** | Government / RSS | cisa.gov |
| **Ars Technica Security** | News / RSS | arstechnica.com/security |
| **CrowdStrike Blog** | Vendor | crowdstrike.com/blog |
| **Mandiant (Google Cloud)** | Vendor | cloud.google.com/blog/topics/threat-intelligence |
| **Unit 42 (Palo Alto)** | Vendor | unit42.paloaltonetworks.com |
| **Schneier on Security** | Blog / RSS | schneier.com |
| **The Record (Recorded Future)** | News / RSS | therecord.media |
| **Risky Business** | Podcast / RSS | risky.biz |
| **SANS Internet Storm Center** | Diary / RSS | isc.sans.edu |
| **Qualys Threat Research** | Vendor | blog.qualys.com |

Adding a source is as simple as adding an entry to `scripts/sources.json`.

---

## Content Priority Tiers

Every article that makes it past curation is assigned a tier:

| Tier | What Goes Here | Examples |
|---|---|---|
| **Tier 1 — Breaking** | Major incidents, zero-days, mass exploits | SolarWinds-level supply chain attack, critical CVE actively exploited |
| **Tier 2 — Focus Areas** | Stories relevant to 5G, indoor cells, NMS, webapp management platforms | New vulnerability in small cell firmware, RAN controller exploit, NMS auth bypass |
| **Tier 3 — Noteworthy** | Important but not breaking or focus-specific | New ransomware variant, nation-state campaign, significant policy changes |

The newsletter template gives Tier 1 stories full summaries with analysis, Tier 2 stories get focused summaries, and Tier 3 stories get brief one-liners with links.

---

## Subscription Flow

```
┌──────────────┐     ┌──────────────────────┐     ┌───────────────────┐
│ User opens a │     │ subscribe.yml        │     │ Private repo:     │
│ GitHub Issue │────▶│ workflow triggers     │────▶│ appends email to  │
│ with email   │     │                      │     │ emails.json       │
│ in body      │     │ 1. Extract email     │     └───────────────────┘
└──────────────┘     │ 2. Push to private   │
                     │    repo via PAT      │
                     │ 3. Redact issue body │
                     │ 4. Close issue with  │
                     │    confirmation      │
                     └──────────────────────┘
```

The user's email is **never visible** in the public repo — the workflow redacts the issue body immediately and replaces it with a "You're subscribed!" message. The actual email is written only to the private repo.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Static site** | [Astro](https://astro.build) + [Tailwind CSS](https://tailwindcss.com) | Fast, zero-JS by default, great for content sites |
| **Scraping & curation** | Python 3.12+ | `feedparser` for RSS, `httpx` for HTTP, `beautifulsoup4` for HTML parsing |
| **AI summarization & ranking** | [Google Gemini API](https://ai.google.dev) (free tier) | 15 RPM / 1M tokens/day free — more than enough for weekly curation |
| **Email delivery** | [Brevo](https://brevo.com) (free tier) | 300 emails/day free, REST API, no credit card required |
| **Hosting** | [GitHub Pages](https://pages.github.com) | Free, auto-deploys from Actions, custom domain support |
| **Automation** | [GitHub Actions](https://github.com/features/actions) | 2,000 free minutes/month, cron scheduling, secrets management |
| **Subscriber storage** | Private GitHub repo | Free, version-controlled, no database needed |

**Total running cost: $0/month** (within free tier limits for a newsletter under 300 subscribers).

---

## Repository Structure

```
cybersecurity-weekly/
├── .github/
│   └── workflows/
│       ├── scrape.yml              # Friday: initial scrape
│       ├── curate.yml              # Saturday: re-scrape + AI summarize
│       ├── finalize.yml            # Sunday: final scrape + tournament rank
│       ├── publish.yml             # Monday: build site + send newsletter
│       └── subscribe.yml           # On issue: handle new subscriber
├── src/                            # Astro site source
│   ├── layouts/
│   │   └── BaseLayout.astro        # HTML shell, meta tags, Tailwind
│   ├── pages/
│   │   ├── index.astro             # Latest issue (homepage)
│   │   └── archive/
│   │       └── [...slug].astro     # Past issues by week
│   └── components/
│       ├── Header.astro
│       ├── Footer.astro
│       ├── ArticleCard.astro       # Single article display
│       ├── TierSection.astro       # Group of articles by tier
│       └── SubscribeForm.astro     # Links to GitHub Issue for subscribe
├── public/
│   ├── favicon.svg
│   └── og-image.png
├── content/
│   └── weekly/                     # Auto-generated by pipeline
│       └── 2026-W14/              # ISO week number
│           ├── raw.json            # Stage 1: raw scraped articles
│           ├── curated.json        # Stage 2: summarized + scored
│           └── final.json          # Stage 3: tournament-ranked + tiered
├── scripts/
│   ├── sources.json                # Feed URLs and source metadata
│   ├── scrape.py                   # RSS/HTTP scraping logic
│   ├── curate.py                   # Gemini summarization + scoring
│   ├── finalize.py                 # Tournament ranking + tier assignment
│   └── send_newsletter.py          # Brevo API email delivery
├── templates/
│   └── newsletter.html             # Jinja2 email template
├── astro.config.mjs
├── tailwind.config.mjs
├── package.json
├── requirements.txt                # Python dependencies
├── .gitignore
└── README.md                       # You are here
```

---

## Setup & Configuration

### Prerequisites

- Node.js 20+
- Python 3.12+
- A [Google AI Studio](https://aistudio.google.com) account (for Gemini API key)
- A [Brevo](https://brevo.com) account (for email sending)
- A second **private** GitHub repository (for subscriber storage)

### GitHub Secrets Required

Set these in the public repo under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key from AI Studio |
| `BREVO_API_KEY` | Brevo REST API key |
| `PRIVATE_REPO_PAT` | GitHub Personal Access Token with `repo` scope, granting access to the private subscriber repo |
| `PRIVATE_REPO` | Full name of private repo, e.g. `youruser/cybersecurity-weekly-private` |
| `FROM_EMAIL` | Verified sender email in Brevo |
| `FROM_NAME` | Sender display name (e.g. "Cybersecurity Weekly") |

### Private Repo Setup

1. Create a new **private** repository named `cybersecurity-weekly-private`
2. Add a single file:

```json
// subscribers/emails.json
{
  "subscribers": []
}
```

3. Generate a **Fine-grained Personal Access Token** with:
   - Repository access: only the private repo
   - Permissions: Contents (Read and write)
4. Add the PAT as `PRIVATE_REPO_PAT` in the public repo's secrets

---

## Local Development

### Site (Astro)

```bash
npm install
npm run dev          # http://localhost:4321
npm run build        # Production build to dist/
```

### Scripts (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run individual pipeline stages
python scripts/scrape.py
python scripts/curate.py
python scripts/finalize.py
python scripts/send_newsletter.py --dry-run
```

Set environment variables locally for testing:

```bash
export GEMINI_API_KEY="your-key-here"
export BREVO_API_KEY="your-key-here"
```

---

## Contributing

This project is designed to be forkable. If you want to run your own cybersecurity newsletter:

1. Fork this repo
2. Create your own private subscriber repo
3. Set up the required GitHub Secrets
4. Customize `scripts/sources.json` with your preferred feeds
5. Edit the Astro templates to match your branding
6. The pipeline runs itself every week

### Ways to contribute to *this* instance:

- **Add news sources**: Submit a PR adding entries to `scripts/sources.json`
- **Improve ranking prompts**: The Gemini prompts in `scripts/curate.py` and `scripts/finalize.py` can always be tuned
- **Site design**: UI/UX improvements to the Astro site
- **Bug fixes**: If a feed parser breaks or an edge case appears in the pipeline
- **Documentation**: Clarifications, typo fixes, better diagrams

---

## License

**Source Available — free for non-commercial use, commercial use requires a paid license.**

You can read, use, modify, and share this code for personal, academic, or nonprofit purposes at no cost. If you or your organization make money from it (selling it, running it as a service, using it in a commercial product), you need a commercial license agreement with revenue sharing. See [LICENSE](LICENSE) for the full legal text.

Copyright (c) 2026 Vishaka Datta Jamba Ehebbar
