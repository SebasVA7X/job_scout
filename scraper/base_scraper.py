"""
scraper/base_scraper.py
Abstract base that all scrapers implement.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseScraper(ABC):
    source_name: str = "unknown"

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """
        Fetch raw job listings from the source.
        Must return a list of dicts with at minimum:
            title, company, location, is_remote, url, description, date_posted
        Optional: salary_min, salary_max, salary_currency, deadline
        deadline: application closing date as 'YYYY-MM-DD' string, or None if unknown.
        """
        ...

    def normalize(self, raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply source-name tag and defaults."""
        for job in raw:
            job.setdefault("source", self.source_name)
            job.setdefault("company", "")
            job.setdefault("location", "")
            job.setdefault("is_remote", 0)
            job.setdefault("description", "")
            job.setdefault("salary_min", None)
            job.setdefault("salary_max", None)
            job.setdefault("salary_currency", None)
            job.setdefault("date_posted", None)
            job.setdefault("deadline", None)
            job.setdefault("keyword_score", 0)
        return raw

    def run(self) -> List[Dict[str, Any]]:
        raw = self.fetch()
        return self.normalize(raw)
