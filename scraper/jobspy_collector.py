"""
scraper/jobspy_collector.py
Collects jobs from LinkedIn, Indeed, Glassdoor via the JobSpy library.

Searches are defined per (term, location) pair to target:
  - Remote/global roles
  - European tech hubs
  - LATAM markets

Adjust SEARCHES to tune coverage vs volume.
"""
import logging
from typing import List, Dict, Any

from jobspy import scrape_jobs

from scraper.base_scraper import BaseScraper


logger = logging.getLogger(__name__)

SITES = ["indeed", "linkedin"]

# Each entry: (search_term, location)
# Location drives geographic bias in LinkedIn/Indeed results
SEARCHES = [
    # ── Remote / global ───────────────────────────────────────────────
    ("data analyst",                    "Remote"),
    ("business intelligence analyst",   "Remote"),
    ("power bi analyst",                "Remote"),
    ("sql data analyst",                "Remote"),
    ("reporting analyst",               "Remote"),
    ("insights analyst",                "Remote"),
    ("power bi developer",              "Remote"),
    ("analytics engineer",              "Remote"),

    # LATAM / Americas / timezone-compatible
    ("data analyst",                    "Latin America"),
    ("business intelligence analyst",   "Latin America"),
    ("power bi analyst",                "Latin America"),
    ("sql data analyst",                "Latin America"),
    ("reporting analyst",               "Latin America"),
    ("insights analyst",                "Latin America"),
    ("power bi developer",              "Latin America"),
    ("analytics engineer",              "Latin America"),

    #New Zealand

    ("data analyst", "New Zealand"),
    ("business intelligence analyst", "New Zealand"),
    ("power bi analyst", "New Zealand"),
    ("sql data analyst", "New Zealand"),
    ("reporting analyst", "New Zealand"),
    ("insights analyst", "New Zealand"),
    ("power bi developer", "New Zealand"),
    ("analytics engineer", "New Zealand"),

    #Australia

    ("data analyst", "Australia"),
    ("business intelligence analyst", "Australia"),
    ("power bi analyst", "Australia"),
    ("sql data analyst", "Australia"),
    ("reporting analyst", "Australia"),
    ("insights analyst", "Australia"),
    ("power bi developer", "Australia"),
    ("analytics engineer", "Australia"),

    #Spain

    ("data analyst", "Spain"),
    ("business intelligence analyst", "Spain"),
    ("power bi analyst", "Spain"),
    ("sql data analyst", "Spain"),
    ("reporting analyst", "Spain"),
    ("insights analyst", "Spain"),
    ("power bi developer", "Spain"),
    ("analytics engineer", "Spain"),


    # Ecuador-specific
    ("analista de datos",                    "Ecuador"),
    ("analista de business intelligence",   "Ecuador"),
    ("analista de power bi",                "Ecuador"),
    ("analista sql",                "Ecuador"),
    ("analista de informacion",               "Ecuador"),
    ("analista de reporteria",                "Ecuador"),
    ("desarrollador de power bi",              "Ecuador"),
    ("ingeniera de analitics",              "Ecuador"),

    # Spanish LATAM
    ("analista de datos", "Colombia"),
    ("analista de datos", "México"),
    ("analista de datos", "Perú"),
    ("analista de datos", "Chile"),
    ("analista de datos", "Argentina"),
    ("analista de datos", "Uruguay"),

    # Relocation / sponsorship, keep as special searches
    ("data analyst", "Europe"),
    ("business intelligence", "Europe"),
    ("power bi analyst relocation", "Europe"),
    ("sql data analyst relocation", "Europe"),
]

RESULTS_PER_SEARCH = 20  # keep volume manageable
HOURS_OLD          = 72  # last 3 days

# Jobs containing any of these phrases are discarded immediately
# Catches US or EU only roles that don't sponsor visas
DISCARD_PHRASES = [
    "visa sponsorship is not available",
    "must be authorized to work in the us",
    "must be authorized to work in the united states",
    "sponsorship is not available for this position",
    "we are unable to sponsor",
    "we cannot sponsor",
    "unable to provide sponsorship",
    "must reside in the united states",
    "must be based in the united states",
    "remote within the united states",
    "remote within the us",
    "remote in the us only",
    "us only",
    "u.s. only",
    "eu only"
    "green card required",
    "u.s. citizen",
    "us citizen",
]


class JobSpyCollector(BaseScraper):
    source_name = "jobspy"

    def fetch(self) -> List[Dict[str, Any]]:
        all_jobs:  List[Dict[str, Any]] = []
        seen_urls: set = set()

        for term, location in SEARCHES:
            logger.info(f"[JobSpy] '{term}' @ {location}")
            try:
                df = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    location=location,
                    results_wanted=RESULTS_PER_SEARCH,
                    hours_old=HOURS_OLD,
                    is_remote=True,
                    linkedin_fetch_description=True,
                    country_indeed="worldwide",  # avoid US-only Indeed results
                )

                if df is None or df.empty:
                    logger.warning(f"[JobSpy] No results for '{term}' @ {location}")
                    continue

                new = 0
                for _, row in df.iterrows():
                    url = str(row.get("job_url", "") or "")
                    if url in seen_urls:
                        continue

                    # Discard US-only roles by description phrases
                    desc = str(row.get("description", "") or "").lower()
                    if any(phrase in desc for phrase in DISCARD_PHRASES):
                        continue

                    seen_urls.add(url)
                    all_jobs.append(self._row_to_dict(row))
                    new += 1

                logger.info(f"[JobSpy] '{term}' @ {location} → {new} new results")

            except Exception as e:
                logger.error(f"[JobSpy] Error on '{term}' @ {location}: {e}")

        logger.info(f"[JobSpy] Total jobs: {len(all_jobs)}")
        return all_jobs

    def _row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "title":           str(row.get("title", "") or ""),
            "company":         str(row.get("company", "") or ""),
            "location":        str(row.get("location", "") or ""),
            "is_remote":       1 if row.get("is_remote") else 0,
            "url":             str(row.get("job_url", "") or ""),
            "description":     str(row.get("description", "") or "")[:4000],
            "salary_min":      self._safe_float(row.get("min_amount")),
            "salary_max":      self._safe_float(row.get("max_amount")),
            "salary_currency": str(row.get("currency", "") or ""),
            "date_posted":     str(row.get("date_posted", "") or ""),
            "source":          f"jobspy:{row.get('site', '')}",
        }

    @staticmethod
    def _safe_float(val) -> float | None:
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None