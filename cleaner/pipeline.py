"""
cleaner/pipeline.py
Cleaning pipeline: reads new rows from jobs_raw, applies title cleaning
and category mapping, writes results to jobs_cleaned.

Called from runner.py between the keyword gate / raw save step and
the LLM scoring step.
"""
import logging
import sqlite3
from typing import List

from db.models import get_connection
from db.repository import upsert_cleaned_job
from cleaner.title_cleaner import clean_title
from cleaner.category_mapper import map_category

logger = logging.getLogger(__name__)


def _get_uncleaned_raw_jobs(limit: int = 500) -> List[sqlite3.Row]:
    """
    Return jobs_raw rows that don't yet have a corresponding jobs_cleaned row.
    Also re-processes rows where repost_count changed (date was updated).
    """
    with get_connection() as conn:
        return conn.execute("""
            SELECT r.*
            FROM jobs_raw r
            LEFT JOIN jobs_cleaned c ON r.job_id = c.job_id
            WHERE c.job_id IS NULL
               OR r.repost_count > c.repost_count
            ORDER BY r.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()


def run_cleaning_pipeline() -> int:
    """
    Process all uncleaned jobs_raw rows into jobs_cleaned.
    Returns the number of rows processed.
    """
    rows = _get_uncleaned_raw_jobs()
    if not rows:
        logger.info("[Cleaner] No new rows to clean.")
        return 0

    logger.info(f"[Cleaner] Processing {len(rows)} rows...")
    processed = 0

    for row in rows:
        raw = dict(row)
        try:
            title_clean = clean_title(raw.get("title") or "")
            category    = map_category(title_clean)

            cleaned = {
                "job_id":        raw["job_id"],
                "title_clean":   title_clean,
                "company":       raw.get("company"),
                "location":      raw.get("location"),
                "is_remote":     raw.get("is_remote", 0),
                "url":           raw.get("url"),
                "source":        raw.get("source"),
                "description":   raw.get("description"),
                "date_posted":   raw.get("date_posted"),
                "deadline":      raw.get("deadline"),
                "keyword_score": raw.get("keyword_score", 0),
                "category":      category,
                "repost_count":  raw.get("repost_count", 0),
            }

            upsert_cleaned_job(cleaned)
            processed += 1

        except Exception as e:
            logger.error(
                f"[Cleaner] Failed to clean job_id={raw.get('job_id')}: {e}",
                exc_info=True,
            )

    logger.info(f"[Cleaner] Done — {processed} rows written to jobs_cleaned.")
    return processed
