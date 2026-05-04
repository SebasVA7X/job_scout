"""
scraper/unhcr_scraper.py
Scrapes UNHCR jobs via the Workday public REST API.
Portal: https://unhcr.wd3.myworkdayjobs.com/External

Workday exposes a standard JSON API at:
  POST /wday/cxs/{tenant}/{jobBoard}/jobs
with a JSON body for search params.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

WORKDAY_API_URL = "https://unhcr.wd3.myworkdayjobs.com/wday/cxs/unhcr/External/jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}

SEARCH_KEYWORDS = [
    "data",
    "information management",
    "business intelligence",
    "information technology",
    "operational data management",
    "statistics",
    "economist",
    "analytics",
    "analisis de datos"
]

JOB_BASE_URL = "https://unhcr.wd3.myworkdayjobs.com/en-US/External"


class UNHCRScraper(BaseScraper):
    source_name = "unhcr"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs = []
        seen_ids = set()

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[UNHCR] Searching: '{keyword}'")
            try:
                page_jobs = self._fetch_keyword(keyword)
                new = [j for j in page_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[UNHCR] '{keyword}' -> {len(new)} new results")
            except Exception as e:
                logger.error(f"[UNHCR] Error on '{keyword}': {e}")

        return jobs

    def _fetch_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        # Workday uses POST with JSON body
        payload = {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": keyword,
        }
        resp = requests.post(
            WORKDAY_API_URL,
            json=payload,
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return self._parse_jobs(data)

    def _parse_jobs(self, data: dict) -> List[Dict[str, Any]]:
        jobs = []
        # Workday standard response shape
        listings = data.get("jobPostings") or []

        for item in listings:
            title       = item.get("title") or ""
            external_id = item.get("externalPath") or item.get("bulletFields", [None])[0] or ""
            location    = ""
            date_raw    = item.get("postedOn") or ""
            desc        = item.get("jobDescription") or ""

            # Location often lives in locationsText or a nested list
            loc_raw = item.get("locationsText") or ""
            if isinstance(loc_raw, list):
                location = ", ".join(loc_raw)
            else:
                location = str(loc_raw)

            # Build URL from externalPath
            url = f"{JOB_BASE_URL}{external_id}" if external_id else ""

            if not title:
                continue

            jobs.append({
                "title":       title,
                "company":     "UNHCR",
                "location":    location,
                "is_remote":   0,
                "url":         url,
                "description": str(desc)[:4000],
                "date_posted": (self._parse_workday_date(date_raw) or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d"),
                "deadline":    None,  # Workday API does not expose closing dates
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
