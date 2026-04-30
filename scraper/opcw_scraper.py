"""
scraper/opcw_scraper.py
Scrapes OPCW (Organisation for the Prohibition of Chemical Weapons) jobs
via their RSS feeds, one per contract type.

Base URL: https://jobs.opcw.org/handlers/offerRss.ashx?LCID=2057&Rss_Contract={id}

Contract types included:
  4965 — Fixed-term Professional (P-level)
  4968 — Short Term Appointment (STA)
  4969 — SSA Individual Contractor
  4970 — SSA Consultant
  6530 — JPO (Junior Professional Officer)

Excluded:
  5058 — Fixed-term General Service
  5389 — Fixed-term Director
  4966 — Intern
  6529 — Interpreter
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

BASE_RSS = "https://jobs.opcw.org/handlers/offerRss.ashx"

CONTRACT_TYPES = {
    4965: "Fixed-term Professional",
    4968: "Short Term Appointment",
    4969: "SSA Individual Contractor",
    4970: "SSA Consultant",
    6530: "JPO",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

MAX_AGE_DAYS = 60

# Atom namespace used in this feed
NS = {"a10": "http://www.w3.org/2005/Atom"}


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


class OPCWScraper(BaseScraper):
    source_name = "opcw"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        for contract_id, contract_name in CONTRACT_TYPES.items():
            logger.info(f"[OPCW] Fetching: {contract_name}")
            try:
                feed_jobs = self._fetch_feed(contract_id, contract_name, cutoff)
                new = [j for j in feed_jobs if j["url"] not in seen_ids]
                seen_ids.update(j["url"] for j in new)
                jobs.extend(new)
                logger.info(f"[OPCW] {contract_name} -> {len(new)} jobs")
            except Exception as e:
                logger.error(f"[OPCW] Error on {contract_name}: {e}")

        logger.info(f"[OPCW] Total jobs: {len(jobs)}")
        return jobs

    def _fetch_feed(
        self, contract_id: int, contract_name: str, cutoff: datetime
    ) -> List[Dict[str, Any]]:
        resp = requests.get(
            BASE_RSS,
            params={"LCID": 2057, "Rss_Contract": contract_id},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()

        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        jobs = []
        for item in channel.findall("item"):
            # ── Title ─────────────────────────────────────────────────────
            title_raw = (item.findtext("title") or "").strip()
            # Format: "2026-555 - Evaluation Officer (P3) (2 posts)"
            # Strip the year-id prefix
            title = re.sub(r"^\d{4}-\d+\s*-\s*", "", title_raw).strip()
            if not title:
                continue

            # ── URL ───────────────────────────────────────────────────────
            url = item.findtext("link") or ""
            if not url:
                continue

            # ── Categories ────────────────────────────────────────────────
            categories = [c.text or "" for c in item.findall("category")]
            # category[0] = department, category[1] = contract type, category[2] = address
            department = categories[0] if len(categories) > 0 else ""
            location   = categories[2] if len(categories) > 2 else "The Hague, Netherlands"

            # Simplify location — extract city if possible
            if "Hague" in location or "2517" in location:
                location = "The Hague, Netherlands"

            # ── Date ──────────────────────────────────────────────────────
            date_raw  = item.findtext("pubDate") or ""
            post_date = self._parse_rfc2822(date_raw)

            if post_date and post_date < cutoff:
                continue

            date_posted = (
                post_date.strftime("%Y-%m-%d") if post_date
                else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            )

            # ── Description ───────────────────────────────────────────────
            desc_html = item.findtext("description") or ""
            desc      = _strip_html(desc_html)
            if len(desc) > 3000:
                desc = desc[:3000]

            # Add contract type context
            if department:
                desc = f"Department: {department} | Contract: {contract_name} | {desc}"

            jobs.append({
                "title":       title,
                "company":     "OPCW",
                "location":    location,
                "is_remote":   0,
                "url":         url,
                "description": desc,
                "date_posted": date_posted,
            })

        return jobs

    @staticmethod
    def _parse_rfc2822(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            return None