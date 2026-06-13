# Cybersecurity Weekly

Fully automated, zero-cost cybersecurity newsletter and static site. Curates, ranks, and delivers the week's most important security news every Monday morning — zero manual intervention after initial setup.

**Focus areas:** Linux distro security (kernel, glibc, OpenSSL, sudo/systemd CVEs) and open-source supply-chain security (npm/PyPI/crates malware, backdoored releases, CI compromise).

**Live site:** _coming soon via GitHub Pages_

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WEEKLY PIPELINE                              │
│                                                                     │
│  Fri 4:30 PM PT               Sat 8 AM – Sun 8 AM PT               │
│  ┌──────────────┐             ┌──────────────────────┐              │
│  │ Initial      │             │ 3× scrape passes +   │              │
│  │ scrape       │────────────▶│ curate (4 sweepers):  │              │
│  │ (19 sources) │             │ dedupe + discover +   │              │
│  └──────────────┘             │ summarize (resumable) │              │
│                               └──────────┬───────────┘              │
│  Sun 12 PM – Mon 5 AM PT                ▼          Mon 8:30 AM PT   │
│  ┌──────────────────┐         ┌──────────────────┐                  │
│  │ Finalize         │         │ Emergency check, │                  │
│  │ (3 sweepers):    │────────▶│ build site,      │                  │
│  │ synthesis +      │         │ send newsletter  │                  │
│  │ grounding gate   │         └──────────────────┘                  │
│  └──────────────────┘                                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                            PUBLIC REPO                                │
│                                                                       │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐  ┌─────────────────┐   │
│  │  Astro 6  │  │  Python   │  │  Content   │  │  GitHub Actions │   │
│  │  Site     │  │  Scripts  │  │  (JSON)    │  │  (pipeline.yml) │   │
│  │           │  │           │  │            │  │                 │   │
│  │ src/      │  │ scrape    │  │ content/   │  │ 9 cron triggers │   │
│  │ layouts/  │  │ dedupe    │  │   raw/     │  │ + sweepers for  │   │
│  │ pages/    │  │ discover  │  │   2026/    │  │ resumability    │   │
│  │ comps/    │  │ curate    │  │ latest.json│  │                 │   │
│  │           │  │ finalize  │  │            │  │                 │   │
│  │ Embeds    │  │ state     │  │ *-state.json│ │                 │   │
│  │ Brevo     │  │ llm_client│  │            │  │                 │   │
│  │ form      │  │ send_news │  │            │  │                 │   │
│  └───────────┘  └───────────┘  └────────────┘  └─────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SERVICES                              │
│                                                                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │ Groq       │  │ Google     │  │ Brevo      │  │ RSS / Security │  │
│  │ Llama 4/3.x│  │ Gemini 3   │  │ - List     │  │ Feeds (19)     │  │
│  │ (primary)  │  │ (fallback) │  │ - Form     │  │                │  │
│  │ free tier  │  │ free tier  │  │ - Send     │  └────────────────┘  │
│  └────────────┘  └────────────┘  │ free tier  │                      │
│                                  └────────────┘                      │
└───────────────────────────────────────────────────────────────────────┘
```

## Pipeline Schedule

All times Pacific (UTC conversions in `pipeline.yml` comment table).

| When | What |
|---|---|
| **Fri 4:30 PM** | Scrape #1 (opens edition) |
| **Sat 8:00 AM** | Scrape #2 + curate attempt 1 |
| **Sat 2:00 PM** | Curate sweeper |
| **Sat 8:00 PM** | Curate sweeper |
| **Sun 8:00 AM** | Scrape #3 (final) + curate deadline sweeper |
| **Sun 12:00 PM** | Finalize attempt 1 (gate: curate complete) |
| **Sun 6:00 PM** | Finalize sweeper |
| **Mon 5:00 AM** | Finalize deadline sweeper |
| **Mon 8:30 AM** | Emergency check → send newsletter + deploy site |
| **Wed 9:00 AM** | Health check (staleness monitor) |

## Resumability

Each LLM-calling stage (curate, finalize) writes a checkpoint file (`{edition}-state.json`) tracking which units are done and the running token tally per model.

- **Quota exhaustion** mid-stage: commit progress, set `partial`, exit 0 (no failure issue).
- **Sweeper re-run**: reads checkpoint, resumes only undone units.
- **Already complete**: no-op exit 0 (seconds, not minutes).
- **Deadline miss**: final sweeper checks state file — opens failure issue only if status ≠ complete.

**Tunables:** `FULLTEXT_MAX_WORDS` (default 1000), `TIER1_MAX_WORDS` (60), `TIER2_MAX_WORDS` (40), `TIER3_MAX_WORDS` (30), `LLM_DELAY_SECONDS`, `LLM_MAX_RETRIES`.

## News Sources

19 sources across journalism and advisory feeds (`scripts/sources.json`):

| Source | Kind | Weight |
|---|---|---|
| Krebs on Security | journalism | 1.5 |
| The Hacker News | journalism | 1.0 |
| BleepingComputer | journalism | 1.2 |
| Dark Reading | journalism | 1.0 |
| CISA Advisories | advisory | 1.5 |
| Ars Technica Security | journalism | 1.0 |
| Security Now (GRC) | journalism | 0.8 |
| CrowdStrike Blog | journalism | 0.8 |
| Google Threat Intelligence | journalism | 1.0 |
| Palo Alto Unit 42 | journalism | 1.0 |
| Sophos News | journalism | 0.8 |
| Recorded Future | journalism | 0.8 |
| Schneier on Security | journalism | 1.2 |
| SANS Internet Storm Center | journalism | 1.1 |
| Ubuntu Security Notices | advisory | 1.3 |
| Debian Security Advisories | advisory | 1.3 |
| Red Hat Security Advisories | advisory | 1.3 |
| LWN.net | journalism | 1.2 |
| GitHub Security Blog | journalism | 1.2 |

Journalism sources headline the newsletter; advisory sources render as teal monospace chips (USN →, DSA →, RHSA →, CISA →).

## LLM Stack

Task-routed model selection (Groq primary, Gemini last-resort):

| Task | Primary | Fallback |
|---|---|---|
| Discovery scoring | Llama 3.1 8B | Scout |
| Summarize | Llama 4 Scout | Llama 3.3 70B |
| Editorial synthesis | **Llama 3.3 70B** | Scout → Gemini 3 Flash |
| Dedup verify | Scout | 70B |
| Emergency check | Scout | Gemini 3 Flash |

8B is prohibited in editorial/verify chains (hard assertion). Only Western/allied-origin models used.

## Deduplication

Three layers:

| Layer | Stage | Mechanism | Catches |
|---|---|---|---|
| L1 URL | scrape | SHA-256(URL) set | Same URL re-scraped |
| L2a CVE | dedupe | Exact CVE-ID join (union-find) | Advisory + journalism covering same vuln |
| L2b Embedding | dedupe | MiniLM cosine (title+summary) | Same story, different sources |
| L3 Verify | finalize | LLM merge-pair check | Same event described differently |

## Content Tiers

| Tier | Criteria | Teaser Cap |
|---|---|---|
| T1 — Breaking | Active exploitation, mass impact, critical CVEs | ≤ 60 words + impact + action |
| T2 — Focus | Linux distro, OSS supply-chain, significant but contained | ≤ 40 words + impact |
| T3 — Notable | Important but not urgent | ≤ 30 words (one sentence) |

## Tech Stack

| Layer | Technology |
|---|---|
| Static site | Astro 6 + Tailwind CSS 3 |
| Scraping | Python 3.12, feedparser, httpx |
| Full-text | trafilatura |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 (local) |
| AI pipeline | Groq (Llama 4 Scout, 3.3 70B, 3.1 8B) + Gemini 3 Flash |
| Email | Brevo (free tier) |
| Hosting | GitHub Pages |
| Automation | GitHub Actions (9 cron triggers) |

**Total running cost: $0/month.**

## Repository Structure

```
cybersecurity-weekly/
├── .github/workflows/
│   ├── pipeline.yml          # 9 cron triggers, sweeper-based resumability
│   ├── ci.yml                # PR validation (syntax + build)
│   ├── codeql.yml            # Security scanning
│   └── health-check.yml      # Wednesday staleness monitor
├── src/
│   ├── layouts/BaseLayout.astro
│   ├── pages/
│   │   ├── index.astro
│   │   └── archive/
│   │       ├── index.astro
│   │       └── [edition].astro
│   └── components/
│       ├── Header.astro
│       ├── Footer.astro
│       ├── ArticleCard.astro     # Tier cards + advisory chips
│       ├── Newsletter.astro      # Brevo form embed
│       └── ArchiveSidebar.astro
├── content/
│   ├── raw/                      # Intermediate data + state checkpoints
│   ├── 2026/                     # Finalized editions
│   └── latest.json
├── scripts/
│   ├── sources.json              # 19 feeds with kind + weight
│   ├── scrape.py                 # RSS ingestion + CVE extraction
│   ├── dedupe.py                 # CVE-ID join + embedding clustering
│   ├── discover.py               # LLM relevance scoring
│   ├── curate.py                 # Discovery + summarization (resumable)
│   ├── finalize.py               # Synthesis + caps + grounding gate (resumable)
│   ├── state.py                  # Checkpoint read/write
│   ├── llm_client.py             # Task-routed LLM client
│   ├── edition.py                # Edition identity
│   ├── monday_check.py           # Emergency breaking news check
│   ├── send_newsletter.py        # Brevo API sender
│   ├── requirements.txt
│   └── requirements-light.txt
├── templates/email.html
├── astro.config.mjs
├── tailwind.config.mjs
└── package.json
```

## Setup

### Prerequisites

- Node.js 22+ / Python 3.12+
- [Groq](https://console.groq.com) account
- [Google AI Studio](https://aistudio.google.com) account
- [Brevo](https://brevo.com) account

### GitHub Secrets + Variables

**Secrets:** `GROQ_API_KEY`, `GEMINI_API_KEY`, `BREVO_API_KEY`, `BREVO_LIST_ID`, `SENDER_EMAIL`

**Variables:** `SITE_URL`, `UNSUBSCRIBE_URL`, `PUBLIC_BREVO_FORM_URL`, `PUBLIC_BREVO_UNSUBSCRIBE_URL`

See [SETUP.md](SETUP.md) for full Brevo configuration.

### Local Development

```bash
# Site
npm install
export PUBLIC_BREVO_FORM_URL="https://sibforms.com/serve/YOUR_ID"
npm run dev          # http://localhost:4321
npm run build        # Production build

# Scripts
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
export GROQ_API_KEY="your-key"
export GEMINI_API_KEY="your-key"
python scripts/scrape.py
python scripts/curate.py
python scripts/finalize.py
```

## License

**Source Available — free for non-commercial use, commercial use requires a paid license.**

Copyright (c) 2026 Vishakadatta Jambae Hebbar
