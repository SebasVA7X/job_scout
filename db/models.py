"""
db/models.py
SQLite schema — two-table design:
  jobs_raw     : ingestion layer — one row per unique title+company, tracks reposts
  jobs_cleaned : derived layer — cleaned title, category, LLM scores for dashboard
"""
import sqlite3
from pathlib import Path
from config.settings import settings


def get_connection() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist, then apply migrations."""
    with get_connection() as conn:
        conn.executescript("""
            -- ── Raw ingestion layer ───────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS jobs_raw (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT UNIQUE NOT NULL,   -- hash(title+company)
                title           TEXT NOT NULL,
                company         TEXT,
                location        TEXT,
                is_remote       INTEGER DEFAULT 0,
                url             TEXT,
                source          TEXT,
                description     TEXT,
                salary_min      REAL,
                salary_max      REAL,
                salary_currency TEXT,
                date_posted     TEXT,
                deadline        TEXT,
                keyword_score   INTEGER DEFAULT 0,
                keyword_debug   TEXT,
                repost_count    INTEGER DEFAULT 0,      -- incremented on each repost
                llm_attempted   INTEGER DEFAULT 0,      -- 1 = LLM has run at least once
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_raw_score     ON jobs_raw(keyword_score);
            CREATE INDEX IF NOT EXISTS idx_raw_source    ON jobs_raw(source);
            CREATE INDEX IF NOT EXISTS idx_raw_created   ON jobs_raw(created_at);
            CREATE INDEX IF NOT EXISTS idx_raw_attempted ON jobs_raw(llm_attempted);
            CREATE INDEX IF NOT EXISTS idx_raw_deadline  ON jobs_raw(deadline);

            -- ── Cleaned + scored layer ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS jobs_cleaned (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT UNIQUE NOT NULL,   -- FK to jobs_raw.job_id
                title_clean     TEXT NOT NULL,          -- stripped title
                company         TEXT,
                location        TEXT,
                is_remote       INTEGER DEFAULT 0,
                url             TEXT,
                source          TEXT,
                description     TEXT,
                date_posted     TEXT,
                deadline        TEXT,
                keyword_score   INTEGER DEFAULT 0,
                category        TEXT DEFAULT 'Other',   -- mapped category label
                repost_count    INTEGER DEFAULT 0,
                llm_score       INTEGER,                -- NULL = not yet scored
                llm_confidence  TEXT DEFAULT 'low',
                llm_reasoning   TEXT,
                notified        INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_clean_score     ON jobs_cleaned(llm_score);
            CREATE INDEX IF NOT EXISTS idx_clean_notified  ON jobs_cleaned(notified);
            CREATE INDEX IF NOT EXISTS idx_clean_source    ON jobs_cleaned(source);
            CREATE INDEX IF NOT EXISTS idx_clean_category  ON jobs_cleaned(category);
            CREATE INDEX IF NOT EXISTS idx_clean_created   ON jobs_cleaned(created_at);

            -- ── Scrape run log ────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS scrape_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                started_at  TEXT DEFAULT (datetime('now')),
                finished_at TEXT,
                jobs_found  INTEGER DEFAULT 0,
                jobs_new    INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'running'
            );
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Safe incremental migrations for databases that may already have
    the old single-table 'jobs' schema.
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # If the old 'jobs' table exists but the new ones don't, migrate data
    if "jobs" in tables and "jobs_raw" not in tables:
        conn.executescript("""
            ALTER TABLE jobs RENAME TO jobs_raw_legacy;

            CREATE TABLE IF NOT EXISTS jobs_raw (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT UNIQUE NOT NULL,
                title           TEXT NOT NULL,
                company         TEXT,
                location        TEXT,
                is_remote       INTEGER DEFAULT 0,
                url             TEXT,
                source          TEXT,
                description     TEXT,
                salary_min      REAL,
                salary_max      REAL,
                salary_currency TEXT,
                date_posted     TEXT,
                deadline        TEXT,
                keyword_score   INTEGER DEFAULT 0,
                keyword_debug   TEXT,
                repost_count    INTEGER DEFAULT 0,
                llm_attempted   INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            INSERT INTO jobs_raw (
                job_id, title, company, location, is_remote, url, source,
                description, salary_min, salary_max, salary_currency,
                date_posted, deadline, keyword_score, keyword_debug,
                repost_count, llm_attempted, created_at, updated_at
            )
            SELECT
                job_id, title, company, location, is_remote, url, source,
                description, salary_min, salary_max, salary_currency,
                date_posted, deadline, keyword_score, keyword_debug,
                0, CASE WHEN llm_reasoning IS NOT NULL THEN 1 ELSE 0 END,
                created_at, updated_at
            FROM jobs_raw_legacy;
        """)

    # Add repost_count if missing (upgrade from earlier new schema)
    if "jobs_raw" in tables:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(jobs_raw)").fetchall()
        }
        if "repost_count" not in existing:
            conn.execute("ALTER TABLE jobs_raw ADD COLUMN repost_count INTEGER DEFAULT 0")
        if "llm_attempted" not in existing:
            conn.execute("ALTER TABLE jobs_raw ADD COLUMN llm_attempted INTEGER DEFAULT 0")
