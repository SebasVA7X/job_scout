"""
scraper/sony_scraper.py
Scrapes Sony Global Careers jobs via the Workday public REST API.
Portal: https://sonyglobal.wd1.myworkdayjobs.com/SonyGlobalCareers

Uses wd1 subdomain — requires session GET first to establish cookies.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

PORTAL_URL   = "https://sonyglobal.wd1.myworkdayjobs.com/SonyGlobalCareers"
API_URL      = "https://sonyglobal.wd1.myworkdayjobs.com/wday/cxs/sonyglobal/SonyGlobalCareers/jobs"
JOB_BASE_URL = "https://sonyglobal.wd1.myworkdayjobs.com/en-US/SonyGlobalCareers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept":       "application/json",
    "Content-Type": "application/json",
    "Origin":       "https://sonyglobal.wd1.myworkdayjobs.com",
    "Referer":      PORTAL_URL,
}

SEARCH_KEYWORDS = [
    "data",
    "information management",
    "business intelligence",
    "information technology",
    "statistics",
    "economist",
    "analytics",
    "analisis de datos"
]

MAX_AGE_DAYS = 60


class SonyScraper(BaseScraper):
    source_name = "sony"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        session = requests.Session()
        try:
            session.get(
                PORTAL_URL,
                headers={"User-Agent": HEADERS["User-Agent"]},
                timeout=15
            )
        except Exception as e:
            logger.warning(f"[Sony] Session init failed (continuing anyway): {e}")

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[Sony] Searching: '{keyword}'")
            try:
                page_jobs = self._fetch_keyword(session, keyword, cutoff)
                new = [j for j in page_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[Sony] '{keyword}' -> {len(new)} new results")
            except Exception as e:
                logger.error(f"[Sony] Error on '{keyword}': {e}")

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
                "company":     "Sony",
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
