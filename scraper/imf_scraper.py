"""
scraper/imf_scraper.py
Scrapes IMF (International Monetary Fund) jobs via the Workday public REST API.
Portal: https://imf.wd5.myworkdayjobs.com/IMF

Same Workday pattern as UNHCR — tenant has its own subdomain so no session needed.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

WORKDAY_API_URL = "https://imf.wd5.myworkdayjobs.com/wday/cxs/imf/IMF/jobs"
JOB_BASE_URL    = "https://imf.wd5.myworkdayjobs.com/en-US/IMF"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":       "application/json",
    "Content-Type": "application/json",
}

SEARCH_KEYWORDS = [
    "data",
    "information management",
    "business intelligence",
    "information technology",
    "statistics",
    "economist",
    "analytics",
]

MAX_AGE_DAYS = 20


class IMFScraper(BaseScraper):
    source_name = "imf"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[IMF] Searching: '{keyword}'")
            try:
                page_jobs = self._fetch_keyword(keyword, cutoff)
                new = [j for j in page_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[IMF] '{keyword}' -> {len(new)} new results")
            except Exception as e:
                logger.error(f"[IMF] Error on '{keyword}': {e}")

        return jobs

    def _fetch_keyword(self, keyword: str, cutoff: datetime) -> List[Dict[str, Any]]:
        payload = {
            "appliedFacets": {},
            "limit":         20,
            "offset":        0,
            "searchText":    keyword,
        }
        resp = requests.post(
            WORKDAY_API_URL, json=payload, headers=HEADERS, timeout=20
        )
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
            post_date = self._parse_workday_date(date_raw)
            if post_date and post_date < cutoff:
                continue

            if isinstance(location, list):
                location = ", ".join(location)

            url = f"{JOB_BASE_URL}{external_id}"

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            jobs.append({
                "title":       title,
                "company":     "IMF",
                "location":    str(location),
                "is_remote":   0,
                "url":         url,
                "description": "",
                "date_posted": date_posted,
            })

        return jobs

    @staticmethod
    def _parse_workday_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        s   = date_str.lower().strip()
        now = datetime.now(tz=timezone.utc)

        if "today" in s:
            return now
        if "yesterday" in s:
            return now - timedelta(days=1)
        if "30+" in s:
            return now - timedelta(days=31)

        match = re.search(r"(\d+)\s+day", s)
        if match:
            return now - timedelta(days=int(match.group(1)))

        return None
