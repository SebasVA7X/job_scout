"""
main.py
Entry point. Sets up logging, runs the pipeline once on startup,
then schedules it via APScheduler.

Usage:
    python main.py                  # full mode: run once + scheduler
    python main.py --no-scheduler   # run pipeline once and exit
"""
import logging
import sys
import time
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import colorlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from notifier.telegram_bot import send_system_message
from scheduler.runner import run_pipeline


def setup_logging() -> None:
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)

    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    file_handler = logging.FileHandler(
        f"{settings.log_dir}/job-scout.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root_logger.addHandler(handler)
    root_logger.addHandler(file_handler)


def _safe_run() -> None:
    """Wrapper so a pipeline crash does not kill the scheduler."""
    logger = logging.getLogger(__name__)
    try:
        run_pipeline()
    except Exception as e:
        logger.error(f"Pipeline run failed: {e}", exc_info=True)
        send_system_message(f"Pipeline error: {e}")


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Job Scout starting up...")
    send_system_message("Job Scout started")

    # Run immediately on startup
    try:
        run_pipeline()
    except Exception as e:
        logger.error(f"Initial run failed: {e}", exc_info=True)

    # Schedule recurring runs
    scheduler = BlockingScheduler(timezone="UTC")

    for hour in settings.schedule_hours:
        scheduler.add_job(
            _safe_run,
            trigger=CronTrigger(hour=hour, minute=0),
            name=f"job-scout-{hour}h",
            misfire_grace_time=300,
        )
        logger.info(f"Scheduled pipeline at {hour:02d}:00 UTC daily")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Job Scout shutting down.")
        send_system_message("Job Scout stopped")


if __name__ == "__main__":
    if "--no-scheduler" in sys.argv:
        setup_logging()
        logger = logging.getLogger(__name__)
        logger.info("Running in no-scheduler mode — single run then exit.")
        run_pipeline()
        logger.info("Done.")
    else:
        main()