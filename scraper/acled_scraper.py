"""
scraper/acled_scraper.py
Scrapes ACLED (Armed Conflict Location & Event Data Project) jobs
via the BambooHR public careers API.

API: GET https://acleddata.bamboohr.com/careers/list
Returns JSON with all open positions — no auth required.

ACLED is fully remote, small team (~2-10 open roles at any time).
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_URL  = "https://acleddata.bamboohr.com/careers/list"
JOB_BASE = "https://acleddata.bamboohr.com/careers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/json",
}


class ACLEDScraper(BaseScraper):
    source_name = "acled"

    def fetch(self) -> List[Dict[str, Any]]:
        resp = requests.get(API_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        jobs = []
        now  = datetime.now(tz=timezone.utc)

        for item in data.get("result", []):
            job_id = item.get("id") or ""
            title  = (item.get("jobOpeningName") or "").strip()

            if not title or not job_id:
                continue

            department = item.get("departmentLabel") or ""
            employment = item.get("employmentStatusLabel") or ""

            # Location — ACLED is remote-first, locationType=1 means remote
            loc_type   = item.get("locationType")
            ats_loc    = item.get("atsLocation") or {}
            country    = ats_loc.get("country") or ""
            city       = ats_loc.get("city") or ""
            is_remote  = 1 if loc_type == "1" or "remote" in title.lower() else 0

            if city and country:
                location = f"{city}, {country}"
            elif country:
                location = country
            else:
                location = "Remote" if is_remote else "N/A"

            url = f"{JOB_BASE}/{job_id}"

            description = " | ".join(filter(None, [
                f"Department: {department}" if department else "",
                f"Employment: {employment}" if employment else "",
            ]))

            jobs.append({
                "title":       title,
                "company":     "ACLED",
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": description,
                "date_posted": now.strftime("%Y-%m-%d"),
            })

        logger.info(f"[ACLED] {len(jobs)} open positions found")
        return jobs