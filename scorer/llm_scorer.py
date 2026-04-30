"""
scorer/llm_scorer.py
Public API for LLM scoring — dispatches to the configured backend.

Backend is selected via settings.llm_backend:
  "ollama"     → scorer/backends/ollama_backend.py    (job-by-job, local)
  "anthropic"  → scorer/backends/anthropic_backend.py (batch, Anthropic API)

Both backends expose the same interface:
  score_job(job)           → (score: int, confidence: str, reasoning: str)
  score_jobs_batch(jobs)   → [(score, confidence, reasoning), ...]
"""
import logging
from typing import Dict, Any, Tuple, List

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_backend():
    backend = settings.llm_backend.lower().strip()
    if backend == "anthropic":
        from scorer.backends.anthropic_backend import score_job, score_jobs_batch
        logger.debug("[LLM] Using Anthropic API backend (batch)")
        return score_job, score_jobs_batch
    else:
        from scorer.backends.ollama_backend import score_job, score_jobs_batch
        logger.debug("[LLM] Using Ollama backend (job-by-job)")
        return score_job, score_jobs_batch


def score_job(job: Dict[str, Any]) -> Tuple[int, str, str]:
    """Score a single job. Returns (score, confidence, reasoning)."""
    _score_job, _ = _get_backend()
    return _score_job(job)


def score_jobs_batch(jobs: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """
    Score a list of jobs efficiently.
    Ollama: falls back to job-by-job internally.
    Anthropic: sends batches of settings.anthropic_batch_size per request.
    """
    if not jobs:
        return []
    _, _score_batch = _get_backend()
    return _score_batch(jobs)
