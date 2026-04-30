"""
scraper/impactpool_scraper.py
Scrapes Impactpool job listings via HTML parsing + Turbo Stream pagination.
Portal: https://www.impactpool.org/search

Uses keyword search to limit volume — each keyword fetches up to MAX_PAGES pages.
Page 1: standard HTML GET
Page 2+: Turbo Stream GET with special Accept header
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

import requests
from bs4 import BeautifulSoup

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL   = "https://www.impactpool.org"
SEARCH_URL = f"{BASE_URL}/search"

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept":  "text/html,application/xhtml+xml",
    "Referer": SEARCH_URL,
}

HEADERS_TURBO = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept":      "text/vnd.turbo-stream.html, text/html, application/xhtml+xml",
    "Referer":     SEARCH_URL,
    "Turbo-Frame": "search_results",
}

SEARCH_KEYWORDS = [
    "data",
    "information management",
    "operational data management",
    "business intelligence",
    "monitoring evaluation",
    "data engineer",
]

# Level/title strings that indicate non-relevant postings — filtered at parse time
SKIP_LEVELS_RE = re.compile(
    r"\b(internship|intern|volunteer|voluntari)\b", re.IGNORECASE
)

PAGE_SIZE = 40
MAX_PAGES = 3  # per keyword — keeps volume manageable (~120 jobs per keyword)


class ImpactpoolScraper(BaseScraper):
    source_name = "impactpool"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        session  = requests.Session()

        for keyword in SEARCH_KEYWORDS:
            logger.info(f"[Impactpool] Searching: '{keyword}'")
            kw_jobs = self._fetch_keyword(session, keyword)
            new = [j for j in kw_jobs if j["url"] not in seen_ids]
            seen_ids.update(j["url"] for j in new)
            jobs.extend(new)
            logger.info(f"[Impactpool] '{keyword}' -> {len(new)} new jobs")

        logger.info(f"[Impactpool] Total jobs: {len(jobs)}")
        return jobs

    def _fetch_keyword(self, session: requests.Session, keyword: str) -> List[Dict[str, Any]]:
        jobs = []

        # Page 1 — standard HTML
        try:
            resp = session.get(
                SEARCH_URL,
                params={"q": keyword, "page": 1, "per_page": PAGE_SIZE},
                headers=HEADERS_HTML,
                timeout=20,
            )
            resp.raise_for_status()
            page_jobs = self._parse_html(resp.text)
            jobs.extend(page_jobs)
            if len(page_jobs) < PAGE_SIZE:
                return jobs
        except Exception as e:
            logger.error(f"[Impactpool] Error on '{keyword}' page 1: {e}")
            return jobs

        # Pages 2+ — Turbo Stream
        for page in range(2, MAX_PAGES + 1):
            try:
                resp = session.get(
                    SEARCH_URL,
                    params={"q": keyword, "page": page, "per_page": PAGE_SIZE},
                    headers=HEADERS_TURBO,
                    timeout=20,
                )
                resp.raise_for_status()

                html = self._extract_turbo_html(resp.text)
                if not html:
                    break

                page_jobs = self._parse_html(html)
                if not page_jobs:
                    break

                jobs.extend(page_jobs)

                if len(page_jobs) < PAGE_SIZE:
                    break

            except Exception as e:
                logger.error(f"[Impactpool] Error on '{keyword}' page {page}: {e}")
                break

        return jobs

    def _extract_turbo_html(self, turbo_text: str) -> str:
        """Extract inner HTML from <turbo-stream action="append"> template tags."""
        soup  = BeautifulSoup(turbo_text, "html.parser")
        parts = []
        for stream in soup.find_all("turbo-stream", action="append"):
            template = stream.find("template")
            if template:
                parts.append(str(template.decode_contents()))
        return " ".join(parts)

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Parse job listings from HTML — each job is an <a href='/jobs/ID'>.

        DOM structure per card:
          <a href="/jobs/ID">
            <div type="cardTitle">         → title
            <div type="bodyEmphasis">      → [0] company  [1] city  [2] level
          </a>
        """
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        now  = datetime.now(tz=timezone.utc)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.match(r"^/jobs/\d+", href):
                continue

            # ── Title ─────────────────────────────────────────────────
            title_div = a.find("div", attrs={"type": "cardTitle"})
            title = title_div.get_text(strip=True) if title_div else ""
            if not title:
                continue

            # Skip internships by title
            if re.search(r"\bintern(ship)?\b", title, re.IGNORECASE):
                continue

            # ── bodyEmphasis divs: [0] company, [1] location, [2] level
            emphasis = a.find_all("div", attrs={"type": "bodyEmphasis"})
            company  = emphasis[0].get_text(strip=True) if len(emphasis) > 0 else "Unknown"
            location = emphasis[1].get_text(strip=True) if len(emphasis) > 1 else "N/A"
            level    = emphasis[2].get_text(strip=True) if len(emphasis) > 2 else ""

            # Skip internships/volunteers by level
            if SKIP_LEVELS_RE.search(level):
                continue

            # ── Remote detection ──────────────────────────────────────
            is_remote = 1 if re.search(r"\bremote\b|\bhome.based\b", location, re.IGNORECASE) else 0

            # ── Description: level carries the most useful signal ─────
            description = level if level and level != "Level not specified" else ""

            url = f"{BASE_URL}{href}"

            jobs.append({
                "title":       title,
                "company":     company,
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": description,
                "date_posted": now.strftime("%Y-%m-%d"),
            })

        return jobs