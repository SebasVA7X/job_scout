"""
scraper/wb_scraper.py
Scrapes World Bank Group jobs via Cornerstone OnDemand (CSOD) API.
Portal: https://worldbankgroup.csod.com/ux/ats/careersite/1/home?c=worldbankgroup

CSOD generates a short-lived JWT Bearer token server-side when loading the page.
We use Playwright to intercept the token, then paginate with requests.

API: POST https://us.api.csod.com/rec-job-search/external/jobs
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

PORTAL_URL = "https://worldbankgroup.csod.com/ux/ats/careersite/1/home?c=worldbankgroup"
API_URL    = "https://us.api.csod.com/rec-job-search/external/jobs"
JOB_BASE   = "https://worldbankgroup.csod.com/ux/ats/careersite/1/home/requisition"

MAX_AGE_DAYS = 60
PAGE_SIZE    = 25


class WBScraper(BaseScraper):
    source_name = "wb"

    def fetch(self) -> List[Dict[str, Any]]:
        token = self._get_bearer_token()
        if not token:
            logger.error("[WB] Could not obtain Bearer token")
            return []

        return self._fetch_all_jobs(token)

    def _get_bearer_token(self) -> str | None:
        """Load the career site with Playwright and intercept the Bearer token."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("[WB] Playwright not installed. Run: pip install playwright && playwright install chromium")
            return None

        token = None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page    = context.new_page()

            def on_request(req):
                nonlocal token
                if "us.api.csod.com" in req.url:
                    auth = req.headers.get("authorization", "")
                    if auth.startswith("Bearer ") and not token:
                        token = auth.replace("Bearer ", "").strip()
                        logger.info("[WB] Bearer token captured")

            page.on("request", on_request)

            try:
                logger.info("[WB] Loading career site to capture token...")
                page.goto(PORTAL_URL, wait_until="networkidle", timeout=60000)
                # Wait a bit to ensure the first API call fires
                page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning(f"[WB] Page load warning: {e}")
            finally:
                browser.close()

        return token

    def _fetch_all_jobs(self, token: str) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Origin":        "https://worldbankgroup.csod.com",
            "Referer":       "https://worldbankgroup.csod.com/",
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
        }

        page = 1
        while True:
            payload = {
                "careerSiteId":            1,
                "careerSitePageId":        1,
                "pageNumber":              page,
                "pageSize":                PAGE_SIZE,
                "cultureId":               1,
                "searchText":              "",
                "cultureName":             "en-US",
                "states":                  [],
                "countryCodes":            [],
                "cities":                  [],
                "placeID":                 "",
                "radius":                  None,
                "postingsWithinDays":       None,
                "customFieldCheckboxKeys": [],
                "customFieldDropdowns":    [],
            }

            resp = requests.post(API_URL, json=payload, headers=headers, timeout=20)

            if resp.status_code == 401:
                logger.error("[WB] Token expired mid-pagination")
                break
            resp.raise_for_status()

            data  = resp.json()
            reqs  = (data.get("data") or {}).get("requisitions") or []
            total = (data.get("data") or {}).get("totalCount") or 0

            if not reqs:
                break

            page_jobs, oldest_date = self._parse_jobs(reqs, cutoff)

            new = [j for j in page_jobs if j["url"] not in seen_ids]
            seen_ids.update(j["url"] for j in new)
            jobs.extend(new)

            fetched = page * PAGE_SIZE
            logger.info(f"[WB] page={page}: {len(new)} kept (total: {fetched}/{total})")

            if fetched >= total:
                break

            if oldest_date and oldest_date < cutoff:
                logger.info(f"[WB] Reached cutoff ({cutoff.date()}), stopping")
                break

            page += 1

        logger.info(f"[WB] Total jobs after filters: {len(jobs)}")
        return jobs

    def _parse_jobs(
        self, reqs: list, cutoff: datetime
    ) -> tuple[List[Dict[str, Any]], datetime | None]:
        jobs        = []
        oldest_date = None

        for item in reqs:
            title  = (item.get("displayJobTitle") or "").strip()
            req_id = item.get("requisitionId") or ""

            if not title or not req_id:
                continue

            # ── Date filter ───────────────────────────────────────────────
            date_raw  = item.get("postingEffectiveDate") or ""
            post_date = self._parse_date(date_raw)

            if post_date:
                if oldest_date is None or post_date < oldest_date:
                    oldest_date = post_date
                if post_date < cutoff:
                    continue

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            # ── Location ──────────────────────────────────────────────────
            locations = item.get("locations") or []
            location  = ", ".join(
                f"{loc.get('city', '')}, {loc.get('country', '')}".strip(", ")
                for loc in locations
                if loc.get("city") or loc.get("country")
            ) or "N/A"

            url = f"{JOB_BASE}/{req_id}"

            jobs.append({
                "title":       title,
                "company":     "World Bank Group",
                "location":    location,
                "is_remote":   0,
                "url":         url,
                "description": "",
                "date_posted": date_posted,
            })

        return jobs, oldest_date

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse M/D/YYYY format used by CSOD e.g. '4/22/2026'."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
