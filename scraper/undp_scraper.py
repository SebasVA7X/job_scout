"""
scraper/undp_scraper.py
Scrapes UNDP (United Nations Development Program) jobs via Oracle HCM REST API.
Endpoint discovered via Network tab inspection.

Portal: https://estm.fa.em2.oraclecloud.com
API:    GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL  = "https://estm.fa.em2.oraclecloud.com"
API_URL   = f"{BASE_URL}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
JOB_URL   = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/preview/{{job_id}}"
PORTAL    = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1/jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept":  "application/json",
    "Referer": PORTAL,
}

MAX_AGE_DAYS = 60
PAGE_SIZE    = 50


class UNDPScraper(BaseScraper):
    source_name = "undp"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        offset   = 0

        while True:
            params = {
                "onlyData": "true",
                "expand":   "requisitionList.workLocation,requisitionList.secondaryLocations",
                "finder": f"findReqs;siteNumber=CX_1,limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC",
            }

            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            search = data.get("items", [{}])[0]
            total  = search.get("TotalJobsCount", 0)
            reqs   = search.get("requisitionList", [])

            if not reqs:
                break

            page_jobs, oldest_date = self._parse_jobs(reqs, cutoff)

            new = [j for j in page_jobs if j["url"] not in seen_ids]
            seen_ids.update(j["url"] for j in new)
            jobs.extend(new)

            offset += PAGE_SIZE
            logger.info(f"[UNDP] offset={offset}: {len(new)} kept (total: {offset}/{total})")

            if offset >= total:
                break

            # Early stop — sorted by posting date desc
            if oldest_date and oldest_date < cutoff:
                logger.info(f"[UNDP] Reached cutoff ({cutoff.date()}), stopping")
                break

        logger.info(f"[UNDP] Total jobs after filters: {len(jobs)}")
        return jobs

    def _parse_jobs(
        self, reqs: list, cutoff: datetime
    ) -> tuple[List[Dict[str, Any]], datetime | None]:
        jobs        = []
        oldest_date = None

        for item in reqs:
            # ── Date filter ───────────────────────────────────────────────
            date_raw  = item.get("PostedDate") or ""
            post_date = self._parse_date(date_raw)

            if post_date:
                if oldest_date is None or post_date < oldest_date:
                    oldest_date = post_date
                if post_date < cutoff:
                    continue

            # ── Required fields ───────────────────────────────────────────
            job_id = str(item.get("Id") or "")
            title  = (item.get("Title") or "").strip()
            if not title or not job_id:
                continue

            # ── Location ──────────────────────────────────────────────────
            location = item.get("PrimaryLocation") or ""

            # Secondary locations
            secondary = item.get("secondaryLocations") or []
            if secondary:
                extra = [
                    s.get("Name") or s.get("LocationName") or ""
                    for s in secondary if s.get("Name") or s.get("LocationName")
                ]
                if extra:
                    location = f"{location}, {', '.join(extra)}" if location else ", ".join(extra)

            workplace = (item.get("WorkplaceType") or "").lower()
            is_remote = 1 if "remote" in workplace else 0

            # ── Description ───────────────────────────────────────────────
            desc_parts = []
            if item.get("JobFamily"):
                desc_parts.append(f"Family: {item['JobFamily']}")
            if item.get("ContractType"):
                desc_parts.append(f"Contract: {item['ContractType']}")
            if item.get("WorkerType"):
                desc_parts.append(f"Type: {item['WorkerType']}")
            short_desc = (item.get("ShortDescriptionStr") or "").strip()
            if short_desc:
                desc_parts.append(short_desc)

            description = " | ".join(desc_parts) if desc_parts else ""

            url = JOB_URL.format(job_id=job_id)

            jobs.append({
                "title":       title,
                "company":     "UNDP",
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": description,
                "date_posted": date_raw,
            })

        return jobs, oldest_date

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None