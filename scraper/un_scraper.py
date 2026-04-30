"""
scraper/un_scraper.py
Scrapes UN Careers job openings via their public RSS feed.
Feed URL: https://careers.un.org/jobfeed?language=en

RSS 2.0 format. Single GET request returns all active jobs (~400).
Description field contains: Level, Job ID, Job Network, Job Family,
Department, Location, Date posted.

Local filters applied:
  - Category exclusions (INT internships, GS general service)
  - Date cutoff (MAX_AGE_DAYS)
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

RSS_URL = "https://careers.un.org/jobfeed?language=en"
JOB_BASE = "https://careers.un.org/jobSearchDescription"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Levels to exclude
EXCLUDED_LEVELS = {"NO", "GS", "I"}  # National Officers, General Service, Internships

MAX_AGE_DAYS = 60


class UNScraper(BaseScraper):
    source_name = "un_careers"

    def fetch(self) -> List[Dict[str, Any]]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        resp = requests.get(RSS_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        root  = ET.fromstring(resp.content)
        items = root.findall(".//item")
        jobs  = []

        logger.info(f"[UN] Feed contains {len(items)} items")

        for item in items:
            title    = (item.findtext("title") or "").strip()
            url      = item.findtext("link") or item.findtext("guid") or ""
            desc_raw = item.findtext("description") or ""
            date_raw = item.findtext("pubDate") or ""

            if not title or not url:
                continue

            # ── Parse description fields ───────────────────────────────────
            meta = self._parse_description(desc_raw)

            # ── Category filter ───────────────────────────────────────────
            level = meta.get("level", "")
            level_prefix = level.split("-")[0].strip() if "-" in level else level
            if any(level_prefix.startswith(ex) for ex in EXCLUDED_LEVELS):
                continue

            # ── Date filter ───────────────────────────────────────────────
            post_date = self._parse_rfc2822(date_raw) or self._parse_date(meta.get("date_posted", ""))
            if post_date and post_date < cutoff:
                continue

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            location  = meta.get("location", "N/A")
            is_remote = 1 if "home" in location.lower() else 0

            # Build description string for keyword gate + LLM
            description = " | ".join(filter(None, [
                f"Level: {level}"                          if level                        else "",
                f"Network: {meta.get('job_network', '')}" if meta.get("job_network")      else "",
                f"Family: {meta.get('job_family', '')}"   if meta.get("job_family")       else "",
                f"Dept: {meta.get('department', '')}"     if meta.get("department")       else "",
            ]))

            jobs.append({
                "title":       title,
                "company":     "United Nations",
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": description,
                "date_posted": date_posted,
            })

        logger.info(f"[UN] {len(jobs)} jobs after filters")
        return jobs

    @staticmethod
    def _parse_description(desc: str) -> dict:
        """Extract key-value pairs from the HTML description field."""
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", desc)
        text = re.sub(r"\s+", " ", text).strip()

        result = {}
        patterns = {
            "level":        r"Level\s*:\s*([^\|<\n]+)",
            "job_network":  r"Job Network\s*:\s*([^\|<\n]+)",
            "job_family":   r"Job Family\s*:\s*([^\|<\n]+)",
            "department":   r"Department(?:/Office)?\s*:\s*([^\|<\n]+)",
            "location":     r"(?:Duty Station|Location)\s*:\s*([^\|<\n]+)",
            "date_posted":  r"(?:Date Posted|Posting Date)\s*:\s*([^\|<\n]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result[key] = match.group(1).strip()

        return result

    @staticmethod
    def _parse_rfc2822(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            return None

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None