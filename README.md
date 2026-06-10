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

- **Automated scraping** pulls from 14+ trusted security sources over a 3-day window
- **Embedding-based dedupe** clusters near-identical stories across feeds before LLM stage — saves tokens, avoids "the same breach summarized five times"
- **Two-model AI pipeline**: Groq Llama 3.3 70B for fast summarization, Gemini 2.5 Pro for judgment-heavy tournament ranking. Western/allied-origin models only.
- **Focus areas** for 5G / indoor cells, NMS / webapp management, and other enterprise-relevant topics get priority
- **Static site + email newsletter** means readers get it however they prefer
- **Brevo-owned subscriber list** with double opt-in, hosted signup form, and per-recipient unsubscribe — no PII ever touches this repo
- **Completely free to run** using GitHub Actions, GitHub Pages, Groq free tier, Gemini free tier, and Brevo free tier

No servers. No private repos. No databases. No costs. Just a cron job and good taste in sources.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WEEKLY PIPELINE                              │
│                                                                     │
│  Friday 4:30 PM PT          Saturday 12:00 PM PT                    │
│  ┌──────────────┐           ┌──────────────────┐                    │
│  │ Initial      │           │ Mid-cycle scrape │                    │
│  │ scrape       │──────────▶│ + embed dedupe + │                    │
│  │ (all sources)│           │ Groq summarize   │                    │
│  └──────────────┘           └────────┬─────────┘                    │
│                                      │                              │
│  Sunday 6:00 PM PT                   ▼          Monday 9:00 AM PT   │
│  ┌──────────────────┐       ┌──────────────────┐                    │
│  │ Final scrape +   │       │ Breaking news    │                    │
│  │ Gemini tournament│──────▶│ check, build     │                    │
│  │ rank (tiers)     │       │ site, send email │                    │
│  └──────────────────┘       └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              PUBLIC REPO                                │
│                          cybersecurity-weekly                           │
│                                                                         │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐  ┌───────────────────┐    │
│  │  Astro    │  │  Python   │  │  Content   │  │  GitHub Actions   │    │
│  │  Site     │  │  Scripts  │  │  (JSON)    │  │  Workflows        │    │
│  │           │  │           │  │            │  │                   │    │
│  │ src/      │  │ scrape.py │  │ content/   │  │ friday-scrape     │    │
│  │ layouts/  │  │ dedupe.py │  │   raw/     │  │ saturday-curate   │    │
│  │ pages/    │  │ curate.py │  │   2026/    │  │ sunday-finalize   │    │
│  │ comps/    │  │ finalize. │  │     w14.   │  │ monday-send       │    │
│  │           │  │   py      │  │      json  │  │                   │    │
│  │ Embeds    │  │ llm_      │  │ latest.    │  │                   │    │
│  │ Brevo     │  │  client.py│  │  json      │  │                   │    │
│  │ form      │  │ send_news │  │            │  │                   │    │
│  │ (iframe)  │  │  letter.py│  │            │  │                   │    │
│  └─────┬─────┘  └─────┬─────┘  └─────┬──────┘  └────────┬──────────┘    │
│        │              │              │                   │              │
│        ▼              ▼              ▼                   │              │
│  ┌──────────────────────────────────────────┐            │              │
│  │       GitHub Pages (static site)         │            │              │
│  └──────────────────────────────────────────┘            │              │
└─────────────────────────────────────────────────────────┼───────────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SERVICES                              │
│                                                                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │
│  │ Groq       │  │ Google     │  │ Brevo      │  │ RSS / Security   │   │
│  │ Llama 3.3  │  │ Gemini 2.5 │  │ - List     │  │ Blogs            │   │
│  │ (summarize)│  │ (rank)     │  │ - Form     │  │ (public)         │   │
│  │ free tier  │  │ free tier  │  │ - Send     │  │                  │   │
│  └────────────┘  └────────────┘  │ free tier  │  └──────────────────┘   │
│                                  └────────────┘                          │
│                                                                         │
│  All API keys stored as GitHub Secrets — never in code.                 │
│  Subscriber list lives entirely inside Brevo — never in this repo.      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why one repo (and no PII)?

| Concern | Where It Lives | Why |
|---|---|---|
| All source code, scripts, site | **This repo** | Open source, transparent, forkable |
| Architecture, pipeline docs | **This repo** | Not sensitive — the code *is* the architecture |
| Subscriber emails | **Brevo** | Brevo owns the full subscriber lifecycle: signup form, double opt-in, list storage, unsubscribe, bounce handling |
| API keys (Groq, Gemini, Brevo) | **GitHub Secrets** | Never committed to any repo |
| Brevo list ID, form URL, sender | **GitHub Secrets / Variables** | Build-time config, not exposed in source |

No PII ever lands in this repo. The Monday sender reads the active subscriber list from Brevo via the Contacts API and ships transactional emails with `List-Unsubscribe` headers so email clients can render a native unsubscribe button.

---

## The 4-Day Pipeline

Each week, four GitHub Actions workflows run on a fixed schedule:

| # | When (Pacific) | When (UTC) | Workflow | What Happens |
|---|---|---|---|---|
| 1 | **Friday 4:30 PM** | Fri 23:30 | `friday-scrape.yml` | Scrape all RSS feeds. Store raw articles in `content/raw/`. |
| 2 | **Saturday 12:00 PM** | Sat 19:00 | `saturday-curate.yml` | Re-scrape for new articles. **Embedding-dedupe** near-identical titles, send canonical articles to **Groq Llama 3.3 70B** for summarization + relevance scoring. Output `*-curated.json`. |
| 3 | **Sunday 6:00 PM** | Mon 01:00 | `sunday-finalize.yml` | Final scrape. **Gemini 2.5 Pro** runs **tournament ranking**: articles are compared head-to-head, then assigned to priority tiers. Output the year's `wNN.json` edition file. |
| 4 | **Monday 9:00 AM** | Mon 16:00 | `monday-send.yml` | Emergency check for breaking news. Build the Astro static site. Deploy to GitHub Pages. Pull subscribers from Brevo list and send the newsletter. |

All content at every stage is committed to the repo as JSON, so you can audit exactly what the AI saw, ranked, and published.

### Two-model split

The pipeline uses two different LLMs deliberately:

- **Groq Llama 3.3 70B Versatile** for **summarization** — fast (~500 tok/s), free, US-origin (Meta). The summarize-and-tag stage is mostly extraction and doesn't need deep judgment.
- **Gemini 2.5 Pro** for **tournament ranking + Monday emergency check** — judgment-heavy "which of these stories matters more" comparisons benefit from a stronger reasoner.

Both backends share a common `llm_client.py` with a fallback chain — if the primary backend is rate-limited or down, the other takes over automatically. **Only Western/allied-origin models are used** (Meta Llama, Google Gemini). No Chinese-origin LLMs anywhere in the pipeline, even when offered free via aggregators.

### Embedding dedupe

Before any LLM call, the curator embeds article titles with `sentence-transformers/all-MiniLM-L6-v2` (runs locally, no API) and clusters anything with cosine similarity ≥ 0.78. Each cluster collapses to a single canonical article (highest-weight source wins). This typically cuts the article volume sent to the LLM by 30–50%, since the same breach often shows up across Krebs, BleepingComputer, THN, and Dark Reading in the same week.

### Tournament Ranking

The Sunday finalization step uses a tournament-style comparison rather than asking the AI to score articles in isolation. Gemini compares pairs of articles and picks the stronger one based on:

- Severity and real-world impact
- Relevance to focus areas (5G, indoor cells, NMS/webapp management)
- Novelty (is this actually new, or a rehash?)
- Source credibility (weighted in `sources.json`)

Winners advance. The final ranked list is split into tiers for the newsletter.

---

## News Sources

Feeds and sites scraped weekly (each with a `weight` in `scripts/sources.json` used as a tournament tiebreaker):

| Source | Type | URL |
|---|---|---|
| **Krebs on Security** | Blog / RSS | krebsonsecurity.com |
| **The Hacker News** | News / RSS | thehackernews.com |
| **BleepingComputer** | News / RSS | bleepingcomputer.com |
| **Dark Reading** | News / RSS | darkreading.com |
| **CISA Advisories** | Government / RSS | cisa.gov |
| **Ars Technica Security** | News / RSS | arstechnica.com/security |
| **Security Now (GRC)** | Podcast show notes | grc.com |
| **CrowdStrike Blog** | Vendor | crowdstrike.com/blog |
| **Google Threat Intelligence** | Vendor | cloud.google.com/blog/topics/threat-intelligence |
| **Palo Alto Unit 42** | Vendor | unit42.paloaltonetworks.com |
| **Sophos News** | Vendor | news.sophos.com |
| **Recorded Future** | News / RSS | recordedfuture.com |
| **Schneier on Security** | Blog / RSS | schneier.com |
| **SANS Internet Storm Center** | Diary / RSS | isc.sans.edu |

Adding a source is as simple as adding an entry to `scripts/sources.json` (include a `weight` between 0.5 and 2.0).

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
│ User submits │     │ Brevo hosted form    │     │ Brevo contact     │
│ email on the │────▶│ (sibforms.com)       │────▶│ list (active)     │
│ site         │     │                      │     │                   │
│ (iframe)     │     │ 1. Double opt-in     │     │ Read-only access  │
└──────────────┘     │    email sent        │     │ from Monday job   │
                     │ 2. User confirms     │     │ via Brevo API     │
                     │ 3. Added to list     │     └───────────────────┘
                     └──────────────────────┘
```

The signup form is a Brevo-hosted page embedded as an iframe (`PUBLIC_BREVO_FORM_URL`). The user's email **never touches this repo** — it goes straight from the form into Brevo's contact list. Double opt-in is enabled, so spurious or malicious submissions never confirm. Unsubscribe is handled by Brevo's per-recipient unsubscribe URL plus the `List-Unsubscribe` header in each email (renders as a native button in Gmail, Apple Mail, etc.).

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Static site** | [Astro](https://astro.build) + [Tailwind CSS](https://tailwindcss.com) | Fast, zero-JS by default, great for content sites |
| **Scraping & curation** | Python 3.12+ | `feedparser` for RSS, `httpx` for HTTP, `beautifulsoup4` for HTML parsing |
| **Embedding dedupe** | `sentence-transformers/all-MiniLM-L6-v2` | Runs locally during Actions run — no API, no key |
| **AI summarization** | [Groq](https://console.groq.com) Llama 3.3 70B (free tier) | 30 RPM / 14.4k RPD — vastly more than the pipeline needs |
| **AI ranking** | [Google Gemini](https://ai.google.dev) 2.5 Pro (free tier) | 15 RPM / 1k RPD — fine for ~20 ranking calls/week |
| **Email + subscriber list** | [Brevo](https://brevo.com) (free tier) | 300 emails/day, unlimited contacts, hosted signup form with double opt-in |
| **Hosting** | [GitHub Pages](https://pages.github.com) | Free, auto-deploys from Actions, custom domain support |
| **Automation** | [GitHub Actions](https://github.com/features/actions) | 2,000 free minutes/month, cron scheduling, secrets management |

**Total running cost: $0/month** (within free tier limits for a newsletter under 300 subscribers).

---

## Repository Structure

```
cybersecurity-weekly/
├── .github/
│   └── workflows/
│       ├── friday-scrape.yml       # Cron: Fri 4:30 PM PT — initial scrape
│       ├── saturday-curate.yml     # Cron: Sat 12:00 PM PT — dedupe + Groq summarize
│       ├── sunday-finalize.yml     # Cron: Sun 6:00 PM PT — Gemini tournament rank
│       └── monday-send.yml         # Cron: Mon 9:00 AM PT — deploy + send
├── src/
│   ├── layouts/
│   │   └── BaseLayout.astro        # HTML shell, meta tags, Tailwind
│   ├── pages/
│   │   ├── index.astro             # Latest issue (homepage)
│   │   └── archive/
│   │       ├── index.astro         # Archive listing
│   │       └── [week].astro        # Dynamic archive pages
│   └── components/
│       ├── Header.astro            # Site header / navigation
│       ├── Footer.astro            # Site footer (Brevo unsubscribe link)
│       ├── ArticleCard.astro       # Single article display
│       ├── Newsletter.astro        # Subscribe CTA section (Brevo iframe embed)
│       └── ArchiveSidebar.astro    # Weekly edition navigation
├── public/
│   └── favicon.svg
├── content/
│   ├── raw/                        # Intermediate scrape data (per-stage)
│   ├── 2026/
│   │   └── w14.json                # Finalized weekly content
│   └── latest.json                 # Pointer to current week
├── scripts/
│   ├── sources.json                # Feed URLs, source weights, metadata
│   ├── requirements.txt            # Pinned Python dependencies
│   ├── scrape.py                   # RSS/HTTP scraping logic
│   ├── dedupe.py                   # Embedding-based dedupe (sentence-transformers)
│   ├── llm_client.py               # Provider-agnostic LLM client (Groq + Gemini)
│   ├── curate.py                   # Dedupe + Groq summarization + scoring
│   ├── finalize.py                 # Tournament ranking (Gemini) + tier assignment
│   ├── monday_check.py             # Monday emergency scrape check
│   └── send_newsletter.py          # Brevo API: read list + send transactional
├── templates/
│   └── email.html                  # Jinja2 email template
├── astro.config.mjs
├── tailwind.config.mjs
├── tsconfig.json
├── package.json
├── SETUP.md                        # Step-by-step setup guide
├── LICENSE
├── .gitignore
└── README.md                       # You are here
```

---

## Setup & Configuration

### Prerequisites

- Node.js 20+
- Python 3.12+
- A [Groq](https://console.groq.com) account (for summarization)
- A [Google AI Studio](https://aistudio.google.com) account (for ranking)
- A [Brevo](https://brevo.com) account (for email + subscriber list)

### GitHub Secrets + Variables Required

Set these under **Settings → Secrets and variables → Actions**.

**Repository secrets:**

| Secret | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key (Llama 3.3 70B summarization) |
| `GEMINI_API_KEY` | Google Gemini API key (tournament ranking) |
| `BREVO_API_KEY` | Brevo REST API key |
| `BREVO_LIST_ID` | Numeric ID of your Brevo subscriber list |
| `SENDER_EMAIL` | Verified Brevo sender email address |

**Repository variables (non-sensitive):**

| Variable | Description |
|---|---|
| `SENDER_NAME` | From-name on the email (default "Cybersecurity Weekly") |
| `SITE_URL` | Public site URL for in-email links |
| `UNSUBSCRIBE_URL` | Goes into the `List-Unsubscribe` header on every send |
| `PUBLIC_BREVO_FORM_URL` | Brevo hosted form URL — embedded as iframe on site |
| `PUBLIC_BREVO_UNSUBSCRIBE_URL` | Optional — shown as "Unsubscribe" footer link |

See [SETUP.md](SETUP.md) for the full step-by-step (5-minute) Brevo configuration.

---

## Local Development

### Site (Astro)

```bash
npm install
# Set the Brevo form URL so the subscribe section renders the iframe
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

# Run individual pipeline stages
python scripts/scrape.py
python scripts/curate.py
python scripts/finalize.py
```

Set environment variables locally for testing:

```bash
export GROQ_API_KEY="your-key-here"
export GEMINI_API_KEY="your-key-here"
export BREVO_API_KEY="your-key-here"
export BREVO_LIST_ID="123"
export SENDER_EMAIL="newsletter@yourdomain.com"
```

---

## Contributing

This project is designed to be forkable. If you want to run your own cybersecurity newsletter:

1. Fork this repo
2. Create a Brevo list + signup form (see [SETUP.md](SETUP.md))
3. Set up the required GitHub Secrets + Variables
4. Customize `scripts/sources.json` with your preferred feeds (and per-source `weight`)
5. Edit the Astro templates to match your branding
6. The pipeline runs itself every week

### Ways to contribute to *this* instance:

- **Add news sources**: Submit a PR adding entries to `scripts/sources.json` (include a `weight` between 0.5 and 2.0)
- **Improve prompts**: The summarization prompt in `scripts/curate.py` and the ranking prompt in `scripts/finalize.py` can always be tuned
- **Site design**: UI/UX improvements to the Astro site
- **Bug fixes**: If a feed parser breaks or an edge case appears in the pipeline
- **Documentation**: Clarifications, typo fixes, better diagrams

---

## License

**Source Available — free for non-commercial use, commercial use requires a paid license.**

You can read, use, modify, and share this code for personal, academic, or nonprofit purposes at no cost. If you or your organization make money from it (selling it, running it as a service, using it in a commercial product), you need a commercial license agreement with revenue sharing. See [LICENSE](LICENSE) for the full legal text.

Copyright (c) 2026 Vishakadatta Jambae Hebbar
