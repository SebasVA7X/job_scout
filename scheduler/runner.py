"""
scheduler/runner.py
Orchestrates the full pipeline:
  1. Scrape all sources
  2. Expired / age filter
  3. Keyword gate
  4. Upsert to jobs_raw  (repost logic)
  5. Cleaning pipeline   → jobs_cleaned (title clean + category)
  6. LLM scoring         → batch via configured backend
  7. Notifications
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from db import repository
from db.models import init_db
from cleaner.pipeline import run_cleaning_pipeline
from notifier.telegram_bot import (
    send_immediate_alerts,
    send_digest,
    send_no_new_jobs,
    send_system_message,
)
from scorer.keyword_filter import passes_keyword_gate
from scorer.llm_scorer import score_jobs_batch
from scraper.idb_scraper import IDBScraper
from scraper.jobspy_collector import JobSpyCollector
from scraper.un_scraper import UNScraper
from scraper.unhcr_scraper import UNHCRScraper
from scraper.unv_scraper import UNVScraper
from scraper.wfp_scraper import WFPScraper
from scraper.iom_scraper import IOMScraper
from scraper.imf_scraper import IMFScraper
from scraper.impactpool_scraper import ImpactpoolScraper
from scraper.wb_scraper import WBScraper
from scraper.sony_scraper import SonyScraper
from scraper.oas_scraper import OASScraper
from scraper.opcw_scraper import OPCWScraper
from scraper.undp_scraper import UNDPScraper
from scraper.acled_scraper import ACLEDScraper
from scraper.bis_scraper import BISScraper
from config.settings import settings

logger = logging.getLogger(__name__)

MAX_AGE_DAYS_NO_DEADLINE = 20

SCRAPERS = [
    # JobSpyCollector(),
    # IDBScraper(),
    # UNScraper(),
    # UNHCRScraper(),
    # UNVScraper(),
    # WFPScraper(),
    # IOMScraper(),
    # IMFScraper(),
    # ImpactpoolScraper(),
    # # WBScraper(),
    # SonyScraper(),
    # OASScraper(),
    # OPCWScraper(),
    # UNDPScraper(),
    ACLEDScraper(),
    # BISScraper(),
]


def _is_expired(job: Dict[str, Any]) -> bool:
    today = datetime.now(tz=timezone.utc).date()

    deadline_str = job.get("deadline")
    if deadline_str:
        try:
            deadline = datetime.strptime(str(deadline_str)[:10], "%Y-%m-%d").date()
            return deadline < today
        except ValueError:
            pass

    date_posted_str = job.get("date_posted")
    if date_posted_str:
        try:
            posted = datetime.strptime(str(date_posted_str)[:10], "%Y-%m-%d").date()
            return (today - posted).days > MAX_AGE_DAYS_NO_DEADLINE
        except ValueError:
            pass

    return False


def run_pipeline() -> None:
    run_timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    logger.info("=" * 60)
    logger.info(f"Job Scout pipeline starting — {run_timestamp}")
    logger.info(f"[Config] LLM backend: {settings.llm_backend}")
    logger.info("=" * 60)

    init_db()
    total_new = 0

    # ── 1. Scrape + keyword gate + save to jobs_raw ───────────────────────────
    for scraper in SCRAPERS:
        run_id = repository.log_run_start(scraper.source_name)
        try:
            raw_jobs = scraper.run()
            logger.info(f"[{scraper.source_name}] Fetched {len(raw_jobs)} raw jobs")

            active = [j for j in raw_jobs if not _is_expired(j)]
            expired_count = len(raw_jobs) - len(active)
            if expired_count:
                logger.info(
                    f"[{scraper.source_name}] Discarded {expired_count} expired/old jobs"
                )

            passed = [j for j in active if passes_keyword_gate(j)]
            logger.info(
                f"[{scraper.source_name}] Keyword filter: {len(passed)}/{len(active)} passed"
            )

            new_count = 0
            for job in passed:
                if repository.upsert_job(job):
                    new_count += 1

            logger.info(f"[{scraper.source_name}] {new_count} new jobs saved to jobs_raw")
            total_new += new_count
            repository.log_run_end(run_id, len(raw_jobs), new_count, "ok")

        except Exception as e:
            logger.error(
                f"[{scraper.source_name}] Pipeline error: {e}", exc_info=True
            )
            repository.log_run_end(run_id, 0, 0, "error")

    # ── 2. Cleaning pipeline → jobs_cleaned ───────────────────────────────────
    logger.info("[Cleaner] Running cleaning pipeline...")
    cleaned_count = run_cleaning_pipeline()
    logger.info(f"[Cleaner] {cleaned_count} rows written to jobs_cleaned")

    # ── 3. LLM Scoring (batch) ────────────────────────────────────────────────
    unscored_rows = repository.get_unscored_cleaned_jobs(limit=500)
    unscored      = [dict(r) for r in unscored_rows]
    logger.info(f"[LLM] Scoring {len(unscored)} jobs via {settings.llm_backend} backend...")

    if unscored:
        results = score_jobs_batch(unscored)
        for job, (score, confidence, reasoning) in zip(unscored, results):
            repository.update_llm_score(job["job_id"], score, confidence, reasoning)
            logger.info(
                f"[LLM] {job.get('title_clean', job.get('title', '?'))[:50]} "
                f"@ {job.get('company', '?')} → {score}/100 [{confidence}]"
            )

    # ── 4. Notifications ──────────────────────────────────────────────────────
    all_unnotified = repository.get_unnotified_jobs_above_threshold(
        threshold=settings.score_digest_threshold
    )
    all_unnotified = [dict(j) for j in all_unnotified]

    # Sort by score descending — best jobs first
    all_unnotified.sort(key=lambda j: j.get("llm_score", 0), reverse=True)

    # Top MAX_ALERTS_PER_RUN above alert threshold → individual Telegram alerts
    alert_candidates = [
        j for j in all_unnotified
        if j.get("llm_score", 0) >= settings.score_alert_threshold
    ]
    immediate = alert_candidates[: settings.max_alerts_per_run]
    overflow  = alert_candidates[settings.max_alerts_per_run :]

    # Everything below alert threshold + overflow from cap → Excel digest
    digest = [
        j for j in all_unnotified
        if settings.score_digest_threshold <= j.get("llm_score", 0) < settings.score_alert_threshold
    ] + overflow

    notified_ids = []

    if immediate:
        logger.info(f"[Telegram] Sending {len(immediate)} immediate alerts...")
        notified_ids += send_immediate_alerts(immediate)

    if digest:
        logger.info(f"[Telegram] Sending digest with {len(digest)} jobs...")
        notified_ids += send_digest(digest, run_timestamp)

    if not immediate and not digest:
        logger.info("[Telegram] No new jobs to notify — sending notice.")
        send_no_new_jobs()

    if notified_ids:
        repository.mark_notified(notified_ids)

    logger.info(f"Pipeline complete. New jobs this run: {total_new}")
    logger.info("=" * 60)
