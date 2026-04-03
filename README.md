# Cybersecurity Weekly

A fully automated, zero-cost cybersecurity newsletter and web application. Every week it scrapes reputable security sources, uses AI to curate and rank the most important stories, publishes a beautiful website, and sends a concise newsletter — all without any human intervention.

## How It Works

```
Friday 4:30 PM PT     Scrape all sources, collect raw articles
Saturday 12:00 PM PT  Summarize + scrape again for new stories
Sunday 6:00 PM PT     Final scrape + AI tournament ranking
Monday 9:00 AM PT     Emergency check, build site, send newsletter
```

The pipeline runs entirely on GitHub Actions. No server, no laptop, no admin needed.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  PUBLIC REPO: cybersecurity-weekly                        │
│                                                          │
│  src/pages/index.astro         Main page                 │
│  src/pages/archive/[week].astro Archive pages            │
│  src/components/                Reusable UI pieces        │
│  src/layouts/                   Page layouts              │
│  content/2026/w16.json          Curated articles (weekly) │
│  scripts/*.py                   Automation pipeline       │
│  templates/email.html           Newsletter template       │
│  .github/workflows/*.yml        Scheduled Actions         │
└───────────────────────┬──────────────────────────────────┘
                        │
          GitHub Actions connects both repos
                        │
┌───────────────────────┴──────────────────────────────────┐
│  PRIVATE REPO: cybersecurity-weekly-private               │
│                                                          │
│  subscribers/emails.json        Subscriber email list     │
└──────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology | Cost |
|-------|-----------|------|
| Static Site Generator | [Astro](https://astro.build) + Tailwind CSS | $0 |
| Scraping & Curation | Python (feedparser, httpx, BeautifulSoup) | $0 |
| AI Summarization | Google Gemini API (free tier — 1M tokens/day) | $0 |
| Email Delivery | Brevo (free tier — 300 emails/day) | $0 |
| Website Hosting | GitHub Pages | $0 |
| Automation & Compute | GitHub Actions (scheduled cron workflows) | $0 |
| Storage | Git repo (JSON files for content + archives) | $0 |
| Subscriber Management | GitHub Issues → private repo | $0 |
| **Total** | | **$0/month** |

## News Sources

### Primary (RSS/Atom feeds preferred)
- **Security Now (GRC)** — Steve Gibson's weekly podcast and show notes
- **Krebs on Security** — Brian Krebs' investigative security journalism
- **The Hacker News** — thehackernews.com daily security news
- **BleepingComputer** — Breaking malware, vulnerability, and tech news
- **Dark Reading** — Enterprise security news and analysis
- **CISA Advisories** — US government cybersecurity alerts and advisories
- **Ars Technica Security** — In-depth security reporting

### Vendor & Research Blogs
- **CrowdStrike Blog** — Threat intelligence and incident reports
- **Google Threat Intelligence (Mandiant)** — APT research and analysis
- **Palo Alto Unit 42** — Threat research and malware analysis
- **Sophos News** — Threat research and security trends
- **Recorded Future** — Threat intelligence insights

## Content Priority Tiers

Stories are ranked by AI using a tournament system where all articles from the week compete against each other.

| Tier | Description | Examples |
|------|-------------|---------|
| **Tier 1** | Major breaking stories with widespread impact | Log4j-class vulnerabilities, nation-state attacks, critical zero-days |
| **Tier 2** | Focus area stories (project niche) | 5G security, indoor small cells, NMS/webapp management vulnerabilities |
| **Tier 3** | Other noteworthy security news | New malware families, data breaches, policy changes, tool releases |

## 4-Day Pipeline Detail

### Friday 4:30 PM PT — Initial Harvest
- Scrape all RSS feeds and source websites
- Store raw articles with metadata (title, source, URL, publish date, raw content)
- Light Gemini pass: categorize articles, detect duplicates across sources
- Output: `content/raw/{year}-w{week}-friday.json`

### Saturday 12:00 PM PT — Summarize + Fresh Scrape
- Generate AI summaries of Friday's articles (2-3 sentences each)
- Scrape all sources again for newly published articles
- Merge new finds into the article pool, deduplicate
- Output: `content/raw/{year}-w{week}-saturday.json`

### Sunday 6:00 PM PT — Final Scrape + Tournament Ranking
- One last scrape for weekend-breaking news
- **Tournament ranking**: Feed ALL collected articles to Gemini
  - Compare articles against each other for importance and impact
  - Select the top stories, assign priority tiers
  - Generate polished summaries for each selected article
  - Generate a catchy newsletter subject line
  - Generate the HTML email body from template
- Output: `content/{year}/w{week}.json` (finalized)

### Monday 9:00 AM PT — Emergency Check + Ship
- Quick scrape: check if anything massive broke overnight/early morning
- If a major story is found, inject as the top story and re-rank
- Build the Astro site with the finalized content
- Deploy to GitHub Pages
- Send newsletter to all subscribers via Brevo
- Output: Live website + emails delivered

## GitHub Actions Cron Schedule (UTC)

| Workflow | Pacific Time | UTC Cron Expression |
|----------|-------------|-------------------|
| `friday-scrape.yml` | Fri 4:30 PM PT | `30 23 * * 5` |
| `saturday-curate.yml` | Sat 12:00 PM PT | `0 19 * * 6` |
| `sunday-finalize.yml` | Sun 6:00 PM PT | `0 1 * * 1` |
| `monday-send.yml` | Mon 9:00 AM PT | `0 16 * * 1` |
| `subscriber-handler.yml` | On issue open | `on: issues` |

## Subscription Flow

1. User clicks "Subscribe" on the website
2. Link opens a GitHub Issue using a pre-filled template (email field)
3. GitHub Action triggers on issue creation:
   - Reads the email from the issue body
   - Pushes it to `cybersecurity-weekly-private` repo's `subscribers/emails.json`
   - Edits the issue body to redact the email for privacy
   - Closes the issue with a confirmation comment
4. Unsubscribe follows the same pattern with a different issue template

## Project Structure

```
cybersecurity-weekly/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── subscribe.yml          Subscribe form template
│   │   └── unsubscribe.yml        Unsubscribe form template
│   └── workflows/
│       ├── friday-scrape.yml      Weekly scrape trigger
│       ├── saturday-curate.yml    AI summarization pass
│       ├── sunday-finalize.yml    Tournament ranking + finalize
│       ├── monday-send.yml        Build site + send newsletter
│       └── subscriber-handler.yml Process subscribe/unsubscribe issues
├── src/
│   ├── components/
│   │   ├── ArticleCard.astro      Single article display card
│   │   ├── Header.astro           Site header with branding
│   │   ├── Footer.astro           Site footer
│   │   ├── Newsletter.astro       Subscribe CTA section
│   │   └── ArchiveSidebar.astro   Weekly archive navigation
│   ├── layouts/
│   │   └── BaseLayout.astro       Shared page layout (head, nav, footer)
│   └── pages/
│       ├── index.astro            Homepage — current week's curated news
│       └── archive/
│           └── [week].astro       Dynamic archive pages per week
├── content/
│   ├── raw/                       Raw scraped data (intermediate, per-day)
│   ├── 2026/
│   │   └── w{nn}.json             Finalized weekly content files
│   └── latest.json                Pointer to the current week's file
├── scripts/
│   ├── requirements.txt           Python dependencies
│   ├── scrape.py                  Source scraping (RSS + HTML fallback)
│   ├── curate.py                  AI summarization and deduplication
│   ├── finalize.py                Tournament ranking, email generation
│   ├── send_newsletter.py         Brevo email dispatch
│   ├── subscriber_handler.py      Process subscribe/unsubscribe issues
│   └── sources.json               List of all news sources and their feed URLs
├── templates/
│   └── email.html                 HTML email template (inline CSS)
├── public/
│   └── favicon.svg                Site favicon
├── astro.config.mjs               Astro configuration
├── tailwind.config.mjs            Tailwind CSS configuration
├── package.json                   Node.js dependencies (Astro, Tailwind)
└── README.md                      This file
```

## Setup Instructions

### Prerequisites
- Node.js 18+ (for Astro)
- Python 3.11+ (for scraping/curation scripts)
- A GitHub account with two repositories:
  - `cybersecurity-weekly` (public) — this repo
  - `cybersecurity-weekly-private` (private) — subscriber data

### API Keys & Secrets

Add these as GitHub Actions secrets in the **public** repo:

| Secret Name | Description | Where to Get It |
|-------------|-------------|----------------|
| `GEMINI_API_KEY` | Google Gemini API key | [Google AI Studio](https://aistudio.google.com/apikey) |
| `BREVO_API_KEY` | Brevo transactional email API key | [Brevo Dashboard](https://app.brevo.com/) |
| `PRIVATE_REPO_TOKEN` | GitHub PAT with repo scope for private repo access | [GitHub Settings > Tokens](https://github.com/settings/tokens) |

### Local Development

```bash
# Install Astro dependencies
npm install

# Install Python dependencies
pip install -r scripts/requirements.txt

# Run the Astro dev server
npm run dev

# Run a scrape manually (for testing)
python scripts/scrape.py
```

## Gemini API Token Budget

The free tier provides 1M tokens/day. Our weekly usage:

| Day | Estimated Tokens | Task |
|-----|-----------------|------|
| Friday | ~200K | Categorization and deduplication |
| Saturday | ~400K | Deep summarization of all articles |
| Sunday | ~300K | Tournament ranking + email generation |
| Monday | ~100K | Final QA check |
| **Total** | **~1M of 4M available** | **75% headroom** |

## License

MIT
