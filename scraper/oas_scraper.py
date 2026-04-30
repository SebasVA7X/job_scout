"""
scraper/oas_scraper.py
Scrapes OAS (Organization of American States) jobs via their Taleo RSS feed.
Feed URL: https://phf.tbe.taleo.net/phf01/ats/servlet/Rss?org=OAS2&cws=39&WebPage=SRCHR_V2&WebVersion=0&_rss_version=2

RSS 2.0 format. No per-item publish dates — uses channel pubDate as fallback.
Description contains full job text (truncated in scraper for LLM).
"""
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

RSS_URL = (
    "https://phf.tbe.taleo.net/phf01/ats/servlet/Rss"
    "?org=OAS2&cws=39&WebPage=SRCHR_V2&WebVersion=0&_rss_version=2"
)

MAX_AGE_DAYS = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class OASScraper(BaseScraper):
    source_name = "oas"

    def fetch(self) -> List[Dict[str, Any]]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        resp = requests.get(RSS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            logger.error("[OAS] No <channel> found in RSS feed")
            return []

        # Channel-level pubDate as fallback for items without their own date
        channel_date_raw = channel.findtext("pubDate") or ""
        channel_date     = self._parse_rfc2822(channel_date_raw)

        jobs = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            url   = item.findtext("link") or item.findtext("guid") or ""
            desc  = (item.findtext("description") or "").strip()

            if not title or not url:
                continue

            # Per-item date (Taleo sometimes includes pubDate per item)
            item_date_raw = item.findtext("pubDate") or ""
            post_date     = self._parse_rfc2822(item_date_raw) or channel_date

            # Date filter — if no date available, keep the item
            if post_date and post_date < cutoff:
                continue

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            # Truncate description for LLM
            if len(desc) > 3000:
                desc = desc[:3000]

            # OAS is Washington DC based
            location  = "Washington, D.C., United States"
            is_remote = 0

            # Extract grade from title e.g. "Officer – P03"
            # Keep full title as-is for keyword scoring

            jobs.append({
                "title":       title,
                "company":     "OAS",
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": desc,
                "date_posted": date_posted,
            })

        logger.info(f"[OAS] {len(jobs)} vacancies found")
        return jobs

    @staticmethod
    def _parse_rfc2822(date_str: str) -> datetime | None:
        """Parse RFC 2822 date format used in RSS (e.g. 'Tue, 21 Apr 2026 20:45:23 GMT')."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
