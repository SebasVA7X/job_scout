"""
db/repository.py
All DB read/write operations for both jobs_raw and jobs_cleaned.

Repost logic (jobs_raw):
  - hash(title+company) is the dedup key
  - On collision: increment repost_count, update date_posted/deadline,
    reset llm_attempted=0 so the job gets re-scored
"""
import hashlib
import json
import sqlite3
from typing import Optional, List, Dict, Any

from db.models import get_connection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_job_id(title: str, company: str) -> str:
    raw = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _serialize_debug(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return json.dumps(value)
    return value


# ── jobs_raw ──────────────────────────────────────────────────────────────────

def upsert_job(job: Dict[str, Any]) -> bool:
    """
    Insert a new job or handle a repost:
      - NEW job       → INSERT, return True
      - REPOST        → increment repost_count, update date/deadline,
                        reset llm_attempted=0, return False
    """
    job_id        = _make_job_id(job.get("title", ""), job.get("company", ""))
    keyword_debug = _serialize_debug(job.get("keyword_debug"))

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, date_posted FROM jobs_raw WHERE job_id = ?", (job_id,)
        ).fetchone()

        if existing is None:
            # New job
            conn.execute("""
                INSERT INTO jobs_raw (
                    job_id, title, company, location, is_remote, url, source,
                    description, salary_min, salary_max, salary_currency,
                    date_posted, deadline, keyword_score, keyword_debug
                ) VALUES (
                    :job_id, :title, :company, :location, :is_remote, :url, :source,
                    :description, :salary_min, :salary_max, :salary_currency,
                    :date_posted, :deadline, :keyword_score, :keyword_debug
                )
            """, {**job, "job_id": job_id, "keyword_debug": keyword_debug})
            return True

        # Repost — update date and reset scoring if the posting date changed
        new_date = job.get("date_posted") or ""
        old_date = existing["date_posted"] or ""

        if new_date and new_date != old_date:
            conn.execute("""
                UPDATE jobs_raw
                SET repost_count  = repost_count + 1,
                    date_posted   = ?,
                    deadline      = COALESCE(?, deadline),
                    llm_attempted = 0,
                    updated_at    = datetime('now')
                WHERE job_id = ?
            """, (new_date, job.get("deadline"), job_id))

        return False


def get_unscored_raw_jobs(limit: int = 100) -> List[sqlite3.Row]:
    """Jobs in jobs_raw that haven't been through the LLM yet."""
    with get_connection() as conn:
        return conn.execute("""
            SELECT * FROM jobs_raw
            WHERE llm_attempted = 0
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()


def mark_llm_attempted(job_id: str) -> None:
    with get_connection() as conn:
        conn.execute("""
            UPDATE jobs_raw
            SET llm_attempted = 1, updated_at = datetime('now')
            WHERE job_id = ?
        """, (job_id,))


# ── jobs_cleaned ──────────────────────────────────────────────────────────────

def upsert_cleaned_job(job: Dict[str, Any]) -> None:
    """
    Insert or update a row in jobs_cleaned.
    Called by the cleaner pipeline after title cleaning + category mapping.
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs_cleaned (
                job_id, title_clean, company, location, is_remote, url, source,
                description, date_posted, deadline, keyword_score,
                category, repost_count
            ) VALUES (
                :job_id, :title_clean, :company, :location, :is_remote, :url, :source,
                :description, :date_posted, :deadline, :keyword_score,
                :category, :repost_count
            )
            ON CONFLICT(job_id) DO UPDATE SET
                title_clean  = excluded.title_clean,
                category     = excluded.category,
                repost_count = excluded.repost_count,
                date_posted  = excluded.date_posted,
                deadline     = excluded.deadline,
                updated_at   = datetime('now')
        """, job)


def get_unscored_cleaned_jobs(limit: Optional[int] = 100) -> List[sqlite3.Row]:
    """Jobs in jobs_cleaned that haven't been LLM-scored yet."""
    with get_connection() as conn:
        if limit is None:
            return conn.execute("""
                SELECT * FROM jobs_cleaned
                WHERE llm_score IS NULL
                ORDER BY created_at DESC
            """).fetchall()
        return conn.execute("""
            SELECT * FROM jobs_cleaned
            WHERE llm_score IS NULL
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()


def update_llm_score(job_id: str, score: int, confidence: str, reasoning: str) -> None:
    """Write LLM results to jobs_cleaned and mark attempted in jobs_raw."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE jobs_cleaned
            SET llm_score      = ?,
                llm_confidence = ?,
                llm_reasoning  = ?,
                updated_at     = datetime('now')
            WHERE job_id = ?
        """, (score, confidence, reasoning, job_id))

    mark_llm_attempted(job_id)


def get_unnotified_jobs_above_threshold(threshold: int) -> List[sqlite3.Row]:
    """Unnotified jobs at or above threshold, ordered by score."""
    with get_connection() as conn:
        return conn.execute("""
            SELECT * FROM jobs_cleaned
            WHERE llm_score >= ? AND notified = 0
            ORDER BY llm_score DESC
        """, (threshold,)).fetchall()


def mark_notified(job_ids: List[str]) -> None:
    with get_connection() as conn:
        conn.executemany(
            "UPDATE jobs_cleaned SET notified = 1, updated_at = datetime('now') WHERE job_id = ?",
            [(jid,) for jid in job_ids],
        )


# ── Scrape run log ────────────────────────────────────────────────────────────

def log_run_start(source: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO scrape_runs (source) VALUES (?)", (source,)
        )
        return cur.lastrowid


def log_run_end(run_id: int, jobs_found: int, jobs_new: int, status: str = "ok") -> None:
    with get_connection() as conn:
        conn.execute("""
            UPDATE scrape_runs
            SET finished_at = datetime('now'), jobs_found = ?, jobs_new = ?, status = ?
            WHERE id = ?
        """, (jobs_found, jobs_new, status, run_id))


# ── Utilities ─────────────────────────────────────────────────────────────────

def reset_all_scores() -> int:
    """Dev utility — reset all LLM scores for a fresh scoring run."""
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE jobs_cleaned
            SET llm_score = NULL, llm_reasoning = NULL, notified = 0,
                updated_at = datetime('now')
        """)
        conn.execute("UPDATE jobs_raw SET llm_attempted = 0")
        return cur.rowcount
