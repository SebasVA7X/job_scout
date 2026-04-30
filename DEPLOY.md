# Job Scout — Intended for Raspberry Pi 5 use - Could be used with any device with docker

## Project Structure

```
/home/device/jobscraper/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env                  ← create manually, NEVER commit to GitHub
├── .env.example
├── requirements.txt
├── config/
├── db/
├── cleaner/
├── scorer/
├── scraper/
├── scheduler/
├── notifier/
├── data/                 ← created by Docker, persistent (SQLite DB lives here)
└── logs/                 ← created by Docker, persistent
```

---

## Step 1 — Transfer the project to your device

From Windows (PowerShell), using SCP (need to have SSH configured):
```powershell
scp -r C:\path\to\JobScraper device@IP:/home/device/jobscraper
```

Or use WinSCP if you prefer a GUI.

**Tip:** Exclude `.venv` and `__pycache__` before transferring — they're not needed
and will bloat the transfer. Use rsync from Git Bash or WSL if available:
```bash
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='data/' --exclude='logs/' \
  ./JobScraper/ pi@IP:/home/device/jobscraper/
```

---

## Step 2 — Create the .env file on the Pi

```bash
ssh device@IP
cd /home/device/jobscraper
cp .env.example .env
nano .env
```

Fill in your real values:
```env
# LLM Backend
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_BATCH_SIZE=15

# Telegram
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...

# Database
DB_PATH=./data/jobs.db

# Scheduler (hour in local time — timezone set in docker-compose.yml)
SCHEDULE_HOURS=8

# Scoring
SCORE_ALERT_THRESHOLD=80
SCORE_DIGEST_THRESHOLD=40
SCORE_SAVE_THRESHOLD=10
MAX_ALERTS_PER_RUN=2

# Logging
LOG_DIR=./logs
LOG_LEVEL=INFO

# JobSpy
JOBSPY_RESULTS=20
JOBSPY_HOURS_OLD=48
```

Save: Ctrl+O, Enter, Ctrl+X

---

## Step 3 — Create persistent directories

```bash
mkdir -p /home/device/jobscraper/data
mkdir -p /home/device/jobscraper/logs
```

---

## Step 4 — Dockerfile notes

The Dockerfile creates directories and a non-root user **before** mounting volumes,
so no manual `chown` is needed on the host:

```dockerfile
RUN mkdir -p /app/data /app/logs \
    && useradd -m -u 1000 scraper \
    && chown -R scraper:scraper /app
USER scraper
```

Combined with `user: "1000:1000"` in `docker-compose.yml`, the container runs
as a non-root user and can write to mounted volumes without permission issues.

---

## Step 5 — Build the image

```bash
cd /home/device/jobscraper
docker build -t job-scout .
```

First build takes 2-5 minutes on a Raspberry Pi 5 with NVMe. Subsequent builds are faster
thanks to Docker layer caching — if `requirements.txt` hasn't changed, pip
dependencies are not reinstalled.

---

## Step 6 — Start the container

```bash
docker compose up -d
```

You may see this warning — it's harmless, just means the device kernel doesn't have
memory cgroup enabled:
```
Your kernel does not support memory limit capabilities. Limitation discarded.
```

---

## Step 7 — Verify it's running

```bash
# Check container status
docker ps

# Follow logs in real time
docker logs -f job-scout

# Or read the log file directly from the host
tail -f /home/device/jobscraper/logs/job-scout.log
```

You should see:
```
[INFO] Job Scout starting up...
[INFO] LLM backend: anthropic
[INFO] Scheduler running. Next run at 08:00 America/Guayaquil
```

---

## Timezone

The container timezone is set via `docker-compose.yml`:
```yaml
environment:
  TZ: America/Guayaquil
```

`SCHEDULE_HOURS=8` means 8:00 AM Ecuador time. No UTC conversion needed.

---

## World Bank Scraper

The WB scraper (`wb_scraper.py`) requires Playwright + Chromium and is **disabled**
in Docker to keep the image lightweight and avoid ARM compatibility issues.
The WB publishes very few data roles — check manually once a week if needed.

To run it manually outside Docker:
```bash
pip install playwright
playwright install chromium
python -c "from scraper.wb_scraper import WBScraper; print(WBScraper().run())"
```

---

## Switching LLM Backend

Change one line in `.env` and restart — no rebuild needed:
```env
LLM_BACKEND=anthropic   # Anthropic API — batch scoring, recommended for production
LLM_BACKEND=ollama      # Local Ollama — useful for large backlog runs to save cost
```

```bash
nano /home/device/jobscraper/.env
docker compose restart
```

---

## Day-to-Day Commands

```bash
# Stop
docker compose down

# Restart (picks up .env changes)
docker compose restart

# Rebuild after code changes
docker compose down
docker build -t job-scout .
docker compose up -d

# Resource usage
docker stats job-scout

# Enter the container (debug)
docker exec -it job-scout bash

# Check the DB from outside the container
ls -lh /home/device/jobscraper/data/
sqlite3 /home/device/jobscraper/data/jobs.db ".tables"
```

---

## Updating the Code

```bash
# 1. Transfer updated files from Windows
scp path/to/file.py pi@192.168.50.224:/home/device/jobscraper/path/to/file.py

# 2. Rebuild and restart
cd /home/device/jobscraper
docker compose down
docker build -t job-scout .
docker compose up -d
```

---

## Re-scoring Jobs After a Fix

If jobs were scored with `parse_error` due to a bug, reset them so they get
re-scored on the next run:

```bash
sqlite3 /home/device/jobscraper/data/jobs.db "
UPDATE jobs_cleaned
SET llm_score = NULL, llm_reasoning = NULL
WHERE llm_reasoning = 'parse_error';

UPDATE jobs_raw
SET llm_attempted = 0
WHERE job_id IN (
    SELECT job_id FROM jobs_cleaned
    WHERE llm_reasoning = 'parse_error'
);
"
```

---

## Running Multiple Profiles

To run separate pipelines for different candidate profiles (e.g. data analyst +
human rights lawyer), create independent project folders:

```
/home/device/jobscraper-me/
/home/device/jobscraper-otherperson/
```

Each with its own `.env` (different `SCHEDULE_HOURS`, `DB_PATH`) and
`docker-compose.yml` (different `container_name`). Stagger run times by at least
2 hours to avoid overlap:

```env
# jobscraper-you
SCHEDULE_HOURS=8
container_name: job-scout-you

# jobscraper-otherperson
SCHEDULE_HOURS=10
container_name: job-scout-otherperson
```

---

## Auto-start on deviceReboot

Ensure Docker starts automatically with the system:
```bash
sudo systemctl enable docker
```

The container itself restarts automatically thanks to `restart: unless-stopped`
in `docker-compose.yml`.

---

## Notes

- The SQLite DB lives at `/home/device/jobscraper/data/jobs.db` — persists across restarts
- Logs rotate automatically (max 3 × 10MB files) via Docker logging config
- The health check queries the DB every 30 minutes — `docker ps` shows `healthy`/`unhealthy`
- Anthropic API cost estimate: ~$0.20-0.40/month at normal volume
- Set a spending limit at console.anthropic.com → Billing → Usage limits