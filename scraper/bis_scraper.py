"""
scraper/bis_scraper.py
Scrapes BIS (Bank for International Settlements) vacancies via RSS feed.
Feed URL: https://www.bis.org/doclist/vacancies.rss

RSS fields available:
  title, link, description (deadline + location), dc:date
Note: no job description available — keyword scoring based on title only.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

RSS_URL  = "https://www.bis.org/doclist/vacancies.rss"
MAX_AGE_DAYS = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# XML namespaces used in the BIS RSS feed
NS = {
    "rdf":     "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "cb":      "http://www.cbwiki.net/wiki/index.php/Specification_1.1",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "rss":     "http://purl.org/rss/1.0/",
}


class BISScraper(BaseScraper):
    source_name = "bis"

    def fetch(self) -> List[Dict[str, Any]]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        resp = requests.get(RSS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        jobs = []

        for item in root.findall("rss:item", NS):
            title    = (item.findtext("rss:title", default="", namespaces=NS) or
                        item.findtext("dc:title", default="", namespaces=NS) or "").strip()
            url      = item.findtext("rss:link", default="", namespaces=NS) or ""
            desc_raw = item.findtext("rss:description", default="", namespaces=NS) or ""
            date_raw = item.findtext("dc:date", default="", namespaces=NS) or ""

            if not title or not url:
                continue

            # ── Date filter ───────────────────────────────────────────────
            post_date = self._parse_date(date_raw)
            if post_date and post_date < cutoff:
                continue

            # ── Parse description field: "Application deadline: YYYY-MM-DD | Location: X" ──
            location = ""
            for part in desc_raw.split("|"):
                part = part.strip()
                if part.lower().startswith("location:"):
                    location = part.split(":", 1)[-1].strip()

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            jobs.append({
                "title":       title,
                "company":     "BIS",
                "location":    location or "Basel, Switzerland",
                "is_remote":   0,
                "url":         url,
                "description": desc_raw,
                "date_posted": date_posted,
            })

        logger.info(f"[BIS] {len(jobs)} vacancies found")
        return jobs

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None