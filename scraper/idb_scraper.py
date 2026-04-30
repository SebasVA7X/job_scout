"""
scraper/idb_scraper.py
Scrapes IDB Careers via their internal SuccessFactors API.
Endpoint discovered via Network tab inspection:
  POST https://jobs.iadb.org/services/recruiting/v1/jobs

Fields in response:
  response.id, response.unifiedStandardTitle, response.urlTitle,
  response.jobLocationShort[], response.cust_workModality[],
  response.unifiedStandardStart, response.unifiedStandardEnd
"""
import logging
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_URL  = "https://jobs.iadb.org/services/recruiting/v1/jobs"
JOB_BASE = "https://jobs.iadb.org/job"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": "https://jobs.iadb.org",
    "Referer": "https://jobs.iadb.org/search/",
}

SEARCH_KEYWORDS = [
    "data",
    "datos",
    "information management",
    "business intelligence",
    "information technology",
    "statistics",
    "economist",
    "analytics",
    "analista de datos"
]


class IDBScraper(BaseScraper):
    source_name = "idb"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs = []
        seen_ids = set()

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[IDB] Searching: '{keyword}'")
            try:
                page_jobs = self._fetch_keyword(keyword)
                new = [j for j in page_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[IDB] '{keyword}' -> {len(new)} new results")
            except Exception as e:
                logger.error(f"[IDB] Error on '{keyword}': {e}")

        return jobs

    def _fetch_keyword(self, keyword: str, page: int = 0) -> List[Dict[str, Any]]:
        payload = {
            "alertId":      "",
            "brand":        "",
            "categoryId":   0,
            "facetFilters": {},
            "keywords":     keyword,
            "locale":       "en_US",
            "location":     "",
            "pageNumber":   page,
            "rcmCandidateId": "",
            "skills":       [],
            "sortBy":       "",
        }
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_jobs(data)

    def _parse_jobs(self, data: dict) -> List[Dict[str, Any]]:
        jobs = []
        listings = data.get("jobSearchResult") or []

        for item in listings:
            r = item.get("response", {})

            job_id    = str(r.get("id") or "")
            title     = r.get("unifiedStandardTitle") or r.get("title") or ""
            url_title = r.get("urlTitle") or r.get("unifiedUrlTitle") or ""
            locations = r.get("jobLocationShort") or []
            location  = ", ".join(l.strip() for l in locations[:2]) if locations else "N/A"
            modality  = (r.get("cust_workModality") or [""])[0]
            date_raw  = r.get("unifiedStandardStart") or ""
            end_raw   = r.get("unifiedStandardEnd") or ""
            is_remote = 1 if "remote" in modality.lower() else 0

            url      = f"{JOB_BASE}/{url_title}/{job_id}-en_US" if job_id else ""
            deadline = end_raw.split("T")[0] if "T" in end_raw else (end_raw or None)

            if not title:
                continue

            jobs.append({
                "title":       title,
                "company":     "IDB / IADB",
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": modality,
                "date_posted": date_raw,
                "deadline":    deadline,
            })

        return jobs