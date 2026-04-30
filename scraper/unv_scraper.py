"""
scraper/unv_scraper.py
Scrapes UNV (UN Volunteers) opportunities via their internal API.
Endpoint discovered via Network tab inspection:
  POST https://app.unv.org/api/doa/doa/SearchDoaAsyncByAzureCognitive

Filters applied at parse time:
  - NATIONAL volunteer type → skipped unless country == Ecuador (ECU)
  - Online/micro-task roles → skipped if hoursWeek <= 10h AND duration < 90 days
  - Micro-tasks without type → skipped if duration < 30 days
  - Date cutoff → MAX_AGE_DAYS

Fields parsed from response (value.result[]):
  name, publishDate, isOnsite, hostEntity.name, country,
  volunteerType, workArrangement, assignmentDuration,
  categoryName, expertiseAreas, hoursWeek, duration, id
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import requests

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_URL  = "https://app.unv.org/api/doa/doa/SearchDoaAsyncByAzureCognitive"
JOB_BASE = "https://app.unv.org/opportunities"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
        "Gecko/20100101 Firefox/149.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://app.unv.org",
    "Referer": "https://app.unv.org/opportunities",
}

MAX_AGE_DAYS = 20
PAGE_SIZE    = 50

# hoursWeek codes considered "low effort" (likely unpaid online)
LOW_EFFORT_CODES = {"1_5", "6_10"}

# Minimum duration (days) for low-effort roles to still be considered
MIN_DURATION_LOW_EFFORT = 90

# Minimum duration for roles with no volunteerType defined
MIN_DURATION_NO_TYPE = 30


def _extract_label(val) -> str:
    """Extract label from a UNV API object field, returning '' for empty/dash values."""
    if isinstance(val, dict):
        label = (val.get("label") or "").strip()
        return "" if label == "-" else label
    text = str(val or "").strip()
    return "" if text == "-" else text


def _extract_code(val) -> str:
    """Extract tableCode value from a UNV API object field."""
    if isinstance(val, dict):
        return (val.get("value") or {}).get("code") or ""
    return ""


class UNVScraper(BaseScraper):
    source_name = "unv"

    def fetch(self) -> List[Dict[str, Any]]:
        jobs     = []
        seen_ids: set = set()
        cutoff   = datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        skip     = 0

        while True:
            try:
                payload = {"take": PAGE_SIZE, "skip": skip}
                resp = requests.post(
                    API_URL, json=payload, headers=HEADERS, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"[UNV] Request failed at skip={skip}: {e}")
                break

            if not data.get("isSuccess"):
                logger.error(f"[UNV] API returned isSuccess=false at skip={skip}")
                break

            value  = data.get("value") or {}
            total  = value.get("total", 0)
            result = value.get("result") or []

            if not result:
                break

            page_jobs, oldest_date = self._parse_jobs(result, cutoff)

            new = [j for j in page_jobs if j["url"] not in seen_ids]
            seen_ids.update(j["url"] for j in new)
            jobs.extend(new)

            skip += PAGE_SIZE
            logger.info(
                f"[UNV] skip={skip}: {len(new)} kept "
                f"(total fetched: {skip}/{total})"
            )

            if skip >= total:
                break

            # Early stop — results are sorted by publishDate desc
            if oldest_date and oldest_date < cutoff:
                logger.info(f"[UNV] Reached cutoff ({cutoff.date()}), stopping")
                break

        logger.info(f"[UNV] Total opportunities after filters: {len(jobs)}")
        return jobs

    def _parse_jobs(
        self, result: list, cutoff: datetime
    ) -> tuple[List[Dict[str, Any]], Optional[datetime]]:
        jobs        = []
        oldest_date = None

        for item in result:
            # ── Date filter ───────────────────────────────────────────────
            date_raw  = item.get("publishDate") or ""
            post_date = self._parse_date(date_raw)

            if post_date:
                if oldest_date is None or post_date < oldest_date:
                    oldest_date = post_date
                if post_date < cutoff:
                    continue

            # ── Required fields ───────────────────────────────────────────
            title = (item.get("name") or "").strip()
            if not title:
                continue

            # ── Volunteer type filter ─────────────────────────────────────
            volunteer_type_code = _extract_code(item.get("volunteerType"))
            volunteer_type      = _extract_label(item.get("volunteerType"))

            # Country code for national-volunteer exception
            country_code = _extract_code(item.get("country"))

            if volunteer_type_code == "NATIONAL" and country_code != "ECU":
                logger.debug(f"[UNV] Skipping national role: {title} ({country_code})")
                continue

            # ── Duration & hours filter (unpaid online micro-tasks) ───────
            duration       = item.get("duration") or 0
            hours_week_code = _extract_code(item.get("hoursWeek"))

            if hours_week_code in LOW_EFFORT_CODES and duration < MIN_DURATION_LOW_EFFORT:
                logger.debug(f"[UNV] Skipping low-effort online task: {title}")
                continue

            if not volunteer_type_code and duration < MIN_DURATION_NO_TYPE:
                logger.debug(f"[UNV] Skipping short untyped task: {title}")
                continue

            # ── Location ──────────────────────────────────────────────────
            duty_stations = item.get("dutyStations") or []
            locations = [
                ds.get("label") or ds.get("shortDescription") or ""
                for ds in duty_stations
                if (ds.get("label") or ds.get("shortDescription") or "")
            ]

            # Fallback: country label
            country_label = _extract_label(item.get("country"))
            region        = _extract_label(
                (item.get("hostEntity") or {}).get("country") or {}
            )

            if locations:
                location = ", ".join(locations)
            elif country_label and country_label != "-":
                location = country_label
            elif region:
                location = region
            else:
                location = "N/A"

            is_onsite = item.get("isOnsite")
            is_remote = 0 if is_onsite else 1

            # ── Host entity & expertise ───────────────────────────────────
            host_entity = (item.get("hostEntity") or {}).get("name") or "UNV"

            expertise_areas = item.get("expertiseAreas") or []
            expertise = ", ".join(
                ea.get("label") or ea.get("shortDescription") or ""
                for ea in expertise_areas
                if (ea.get("label") or ea.get("shortDescription") or "") not in ("", "-")
            )

            # ── Other metadata (all may come as objects) ──────────────────
            work_arrangement    = _extract_label(item.get("workArrangement"))
            assignment_duration = _extract_label(item.get("assignmentDuration"))
            category_name       = _extract_label(item.get("categoryName"))

            # ── Description ───────────────────────────────────────────────
            description = " | ".join(filter(None, [
                f"Host: {host_entity}",
                f"Expertise: {expertise}"          if expertise           else "",
                f"Type: {volunteer_type}"          if volunteer_type      else "",
                f"Arrangement: {work_arrangement}" if work_arrangement    else "",
                f"Duration: {assignment_duration}" if assignment_duration else "",
                f"Category: {category_name}"       if category_name       else "",
                "Onsite" if is_onsite else "Remote/Online",
            ]))

            date_posted = date_raw.split("T")[0] if "T" in date_raw else date_raw

            job_id = item.get("id") or ""
            url    = f"{JOB_BASE}/{job_id}" if job_id else JOB_BASE

            jobs.append({
                "title":       title,
                "company":     host_entity,
                "location":    location,
                "is_remote":   is_remote,
                "url":         url,
                "description": description,
                "date_posted": date_posted,
            })

        return jobs, oldest_date

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            return None