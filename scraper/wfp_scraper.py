"""
scraper/wfp_scraper.py
Scrapes WFP jobs via the Workday public REST API.
Portal: https://wd3.myworkdaysite.com/en-GB/recruiting/wfp/job_openings

Workday exposes a standard JSON API at:
  POST /wday/cxs/{tenant}/{jobBoard}/jobs

Requires a session GET first to establish cookies — WFP uses
wd3.myworkdaysite.com (shared Workday host) which enforces Origin checks.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

PORTAL_URL   = "https://wd3.myworkdaysite.com/en-GB/recruiting/wfp/job_openings"
API_URL      = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings/jobs"
JOB_BASE_URL = "https://wd3.myworkdaysite.com/en-GB/recruiting/wfp/job_openings"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":       "application/json",
    "Content-Type": "application/json",
    "Origin":       "https://wd3.myworkdaysite.com",
    "Referer":      PORTAL_URL,
}

SEARCH_KEYWORDS = [
    "data",
    "datos"
    "information management",
    "business intelligence",
    "information technology",
    "operational data management"
    "statistics",
    "economist",
    "analytics",
    "analista de datos"
]

MAX_AGE_DAYS = 60


class WFPScraper(BaseScraper):
    source_name = "wfp"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        # Establish session cookies before hitting the API
        session = requests.Session()
        try:
            session.get(PORTAL_URL, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        except Exception as e:
            logger.warning(f"[WFP] Session init failed (continuing anyway): {e}")

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[WFP] Searching: '{keyword}'")
            try:
                page_jobs = self._fetch_keyword(session, keyword, cutoff)
                new = [j for j in page_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[WFP] '{keyword}' -> {len(new)} new results")
            except Exception as e:
                logger.error(f"[WFP] Error on '{keyword}': {e}")

        return jobs

    def _fetch_keyword(
        self, session: requests.Session, keyword: str, cutoff: datetime
    ) -> List[Dict[str, Any]]:
        payload = {
            "appliedFacets": {},
            "limit":         20,
            "offset":        0,
            "searchText":    keyword,
        }
        resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return self._parse_jobs(resp.json(), cutoff)

    def _parse_jobs(self, data: dict, cutoff: datetime) -> List[Dict[str, Any]]:
        jobs     = []
        listings = data.get("jobPostings") or []

        for item in listings:
            title       = (item.get("title") or "").strip()
            external_id = item.get("externalPath") or ""
            location    = item.get("locationsText") or ""
            date_raw    = item.get("postedOn") or ""

            if not title or not external_id:
                continue

            # ── Date filter ───────────────────────────────────────────────
            # Workday uses relative strings like "Posted Today", "Posted 30+ Days Ago"
            post_date = self._parse_workday_date(date_raw)
            if post_date and post_date < cutoff:
                continue

            if isinstance(location, list):
                location = ", ".join(location)

            url = f"{JOB_BASE_URL}{external_id}"

            # Normalize relative date to ISO string
            post_date_normalized = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            jobs.append({
                "title":       title,
                "company":     "WFP",
                "location":    str(location),
                "is_remote":   0,
                "url":         url,
                "description": "",
                "date_posted": post_date_normalized,
            })

        return jobs

    @staticmethod
    def _parse_workday_date(date_str: str) -> datetime | None:
        """
        Workday returns relative strings instead of ISO dates:
          'Posted Today', 'Posted Yesterday', 'Posted 5 Days Ago',
          'Posted 30+ Days Ago'
        Convert to approximate absolute datetime for cutoff comparison.
        """
        if not date_str:
            return None

        s = date_str.lower().strip()
        now = datetime.now(tz=timezone.utc)

        if "today" in s:
            return now
        if "yesterday" in s:
            return now - timedelta(days=1)
        if "30+" in s:
            return now - timedelta(days=31)

        # "Posted N Days Ago"
        import re
        match = re.search(r"(\d+)\s+day", s)
        if match:
            return now - timedelta(days=int(match.group(1)))

        return None
