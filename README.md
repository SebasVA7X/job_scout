# Job Scout (version 1.0)

An automated job scraping and AI-powered recommendation system. Monitors 15+ sources — UN agencies, international organizations, NGOs, LinkedIn, and Indeed — scores every listing against a candidate profile using Claude or Ollama, and delivers ranked alerts via Telegram.

Deveoped along with ClaudeCode, designed to run continuously on a Raspberry Pi 5 or similar, containerized with Docker.

---

## Features

- **15+ scrapers** covering UN agencies, World Bank, IMF, IDB, ImpactPool, LinkedIn, and more
- **Two-stage filtering**: fast keyword gate before the more expensive LLM call
- **AI scoring** via Claude Haiku (Anthropic) or Ollama (qwen2.5:7b) — every job gets a 0–100 score with reasoning, based on a detailed candidate profile
- **Telegram alerts** for top matches (≥80), Excel digest for good-but-not-top matches (40–79)
- **Deduplication**: SHA-256-based job IDs; reposts are tracked and re-scored, not re-notified
- **Scheduled runs** via APScheduler (configurable hours, e.g. `8,18` for 8 AM and 6 PM UTC)
- **Docker-first**: single `docker compose up -d` deployment

**NOTE:** You don't need Docker to run the pipeline, you can instead download the repository and run it using a .venv instance with your local Python environment (3.11 to 3.13 were tested.)

---

## Architecture

```
scheduler/main.py          Entry point: logging setup, pipeline run, cron scheduling
scheduler/runner.py        Orchestrates the full pipeline
scraper/                   16 scraper classes (one per source)
cleaner/                   Title normalization + category mapping (rule-based)
scorer/
  keyword_filter.py        Pre-LLM keyword scoring and blacklist gate
  llm_scorer.py            Public scoring API
  backends/
    anthropic_backend.py   Batch Claude API calls
    ollama_backend.py      Local Ollama fallback
    prompts.py             Candidate profile and scoring instructions
db/
  models.py                SQLite schema + migrations
  repository.py            All SQL operations (upsert, queries)
notifier/telegram_bot.py   Alert messages and Excel digest delivery
config/settings.py         Centralized config loaded from .env
```

### Pipeline

```
SCRAPE → FILTER (keyword gate) → UPSERT to jobs_raw
       → CLEAN titles + map categories → UPSERT to jobs_cleaned
       → LLM SCORE (Claude or Ollama)
       → NOTIFY via Telegram (alerts + digest)
```

---

## Sources

| Category | Sources |
|---|---|
| General job boards | LinkedIn,(via JobSpy, 50+ searches) |
| UN system | UN Careers, UNHCR, UNDP, UNV, WFP, IOM |
| Financial / multilateral | IMF, World Bank\*, IDB, BIS, OAS |
| Other international | OPCW, ACLED |
| NGO / impact | ImpactPool |
| Private sector example | Sony |

\* World Bank scraper exists but is disabled by default in `runner.py` due to having to use Playwright.

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/) (or a local Ollama instance)
- A Telegram bot token and chat ID
- Docker & Docker Compose (for production deployment)

---

## Filters

**You can consult the structure and how to change filters in [hardfilters.md](hardfilters.md)**

## Quick Start (Local / Development)

```bash
git clone <repo-url>
cd JobScraper

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in your API keys (see Configuration section)

# Run the full pipeline once and exit
python -m scheduler.main --no-scheduler

# Or run once then keep scheduling
python -m scheduler.main
```

---

## Docker Deployment (Raspberry Pi / Server)

```bash
# Copy project to host
scp -r . device<DEVICE_IP>:/home/device/jobscraper
ssh device@<DEVICE_IP>
cd /home/device/jobscraper

# Configure secrets
cp .env.example .env
nano .env                       # fill in all values

# Create persistent directories
mkdir -p data logs

# Build and start
docker compose up -d

# Monitor
docker logs -f job-scout
```

The container restarts automatically (`unless-stopped`). The SQLite database and logs survive restarts via bind mounts:

```
./data/jobs.db   ←→   /app/data/jobs.db   (inside container)
./logs/          ←→   /app/logs/          (inside container)
```

---

## Configuration

Copy `.env.example` to `.env` and set the following:

```env
# ── Database ──────────────────────────────────────────────
DB_PATH=./data/jobs.db

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>

# ── LLM Backend ───────────────────────────────────────────
LLM_BACKEND=anthropic                  # or "ollama"

# Anthropic (preferred)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_BATCH_SIZE=15                # jobs per API request

# Ollama (local fallback)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<model-name>

# ── Scoring thresholds ────────────────────────────────────
SCORE_ALERT_THRESHOLD=80               # send individual Telegram message
SCORE_DIGEST_THRESHOLD=40              # include in Excel digest
SCORE_SAVE_THRESHOLD=10                # minimum score to persist to DB
MAX_ALERTS_PER_RUN=2                   # cap on immediate alerts per run

# ── Scheduling ────────────────────────────────────────────
SCHEDULE_HOURS=8                       # UTC hour(s) — "8" or "8,18"

# ── JobSpy (LinkedIn / Indeed) ────────────────────────────
JOBSPY_RESULTS=20                      # results per search term
JOBSPY_HOURS_OLD=48                    # only jobs posted in last N hours

# ── Logging ───────────────────────────────────────────────
LOG_DIR=./logs
LOG_LEVEL=INFO                         # DEBUG | INFO | WARNING | ERROR
```

---

## Database Schema

**`jobs_raw`** — Raw ingestion layer

| Column | Description |
|---|---|
| `job_id` | SHA-256(title + company)[:16] — primary key |
| `title`, `company`, `location` | Raw job metadata |
| `is_remote`, `url`, `source` | Source and access info |
| `description` | Full job description (may be empty) |
| `salary_min`, `salary_max`, `salary_currency` | Compensation data when available |
| `date_posted`, `deadline` | Timing fields |
| `keyword_score` | Pre-LLM keyword filter score (0–100) |
| `keyword_debug` | JSON debugging info from the keyword filter |
| `repost_count` | Times this title+company pair has been seen |
| `llm_attempted` | 1 = LLM has scored this job at least once |

**`jobs_cleaned`** — Processed and scored layer

| Column | Description                                                       |
|---|-------------------------------------------------------------------|
| `job_id` | FK to `jobs_raw.job_id`                                           |
| `title_clean` | Normalized title (prefixes, emojis stripped)                      |
| `category` | Rule-based category (Data Engineer, BI Developer, M&E/MEAL, etc.) |
| `llm_score` | LLM's fit score, 0–100 (NULL if not yet scored)                   |
| `llm_confidence` | `low` / `medium` / `high` (based on description length)           |
| `llm_reasoning` | LLM's explanation for the score                                   |
| `notified` | 1 = Telegram notification already sent                            |

**`scrape_runs`** — Audit log per source per run (started_at, finished_at, jobs_found, jobs_new, status).

---

## Notifications

**Individual alert** (LLM score ≥ 80, up to `MAX_ALERTS_PER_RUN` per run):
```
Score: 91 | High confidence
Senior Data Engineer — UNHCR
📍 Remote | 💰 $90k–120k
[Source] [Apply →]

Reasoning: Strong domain fit...
```

**Excel digest** (score 40–79, or overflow from alert cap):
- Color-coded rows: green (80+), orange (60–79), grey (40–59)
- Columns: Score, Confidence, Title, Company, Location, Remote, Source, Posted, URL, LLM Reasoning
- Sent as a `.xlsx` file attachment

**System messages**: startup confirmation, error alerts, and "no new jobs this run" notices keep you informed that the scheduler is alive.

---

## Scoring

### Keyword Filter (pre-LLM gate)

Weighted keyword scoring runs before any API call. Jobs below `SCORE_SAVE_THRESHOLD` (default 10) are discarded without hitting the LLM.

- Positive signals: job title and description keywords ("data analyst", "SQL", "Power BI", etc.)
- Hard disqualifiers: internships, purely operational roles, certain geographic restrictions
- Remote bonus: +10 if "remote", "remoto", or "work from home" found

### LLM Scoring

Each job is scored 0–100 by the LLM using a detailed system prompt that encodes:

- Candidate background 
- Preferred roles and organizations (NGOs, international orgs, private sector, consulting)
- Hard exclusions (internships, purely operational roles)
- Confidence bands based on description length

**Score bands:**

| Range | Meaning |
|---|---|
| 85–100 | Strong domain fit + strong skills match |
| 65–84 | Good fit, minor gaps |
| 40–64 | Partial fit (data-adjacent or limited scope) |
| 0–39 | Poor fit or disqualifier |


---

## Candidate Profile

The scoring prompt is baked into [`scorer/backends/prompts.py`](scorer/backends/prompts.py). To adapt this system for a different profile, edit the candidate profile and keyword lists in:

- [`scorer/backends/prompts.py`](scorer/backends/prompts.py) — LLM system prompt and scoring rules
- [`scorer/keyword_filter.py`](scorer/keyword_filter.py) — keyword weights and blacklist
- [`scraper/jobspy_collector.py`](scraper/jobspy_collector.py) — search terms and target regions

---

## Project Constraints

- **No web UI**: outputs are Telegram messages + SQLite. Query the DB directly or connect a BI tool.
- **No email**: Telegram is the only notification channel.
- **Single-user**: the candidate profile is hardcoded in the LLM prompt.
- **Memory limit**: Docker Compose caps the container at 512 MB (tuned for Raspberry Pi 5).
- **No test suite** currently.
- **Cost**: If used with Claude, it should consume ~$0.40 for processed 500 records, final costs depends on how many runs are scheduled daily, and how many jobs are pulled in each run. 

## Potential Issues

- This tool is a decision-support assistant, not an exhaustive job search engine. Relevant vacancies may be missed if postings use unexpected wording or if source coverage changes.
- LLM-based scoring can be imperfect and may occasionally misclassify or overrate/underrate listings. Periodic manual review of the database is recommended.
- Individual scrapers may fail if source websites change their URLs, HTML structure, JSON endpoints, or access policies.
- Results should be treated as ranked leads, not final recommendations.

---

## License

MIT
