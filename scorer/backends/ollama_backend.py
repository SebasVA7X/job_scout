"""
scorer/backends/ollama_backend.py
Local Ollama scoring — one job per request, network-isolated.
"""
import json
import logging
import re
from typing import Dict, Any, Tuple, List

import requests

from config.settings import settings
from scorer.backends.prompts import (
    CANDIDATE_PROFILE,
    SYSTEM_PROMPT_WITH_DESCRIPTION,
    SYSTEM_PROMPT_NO_DESCRIPTION,
    USER_TEMPLATE_WITH_DESCRIPTION,
    USER_TEMPLATE_NO_DESCRIPTION,
    is_jobspy,
)

logger = logging.getLogger(__name__)

OLLAMA_URL = f"{settings.ollama_base_url}/api/generate"


def _calc_confidence(job: Dict[str, Any]) -> str:
    desc_len = len(str(job.get("description", "") or "").strip())
    source   = job.get("source", "")
    if is_jobspy(source) and desc_len > 500:
        return "high"
    elif is_jobspy(source) and desc_len > 100:
        return "medium"
    return "low"


def score_job(job: Dict[str, Any]) -> Tuple[int, str, str]:
    """Score a single job. Returns (score, confidence, reasoning)."""
    confidence = _calc_confidence(job)
    use_desc   = is_jobspy(job.get("source", ""))

    desc = str(job.get("description", "") or "")
    if use_desc and len(desc) > 3000:
        desc = desc[:1500] + "\n[...]\n" + desc[-1000:]

    title = job.get("title_clean") or job.get("title", "")

    if use_desc:
        system = SYSTEM_PROMPT_WITH_DESCRIPTION
        prompt = USER_TEMPLATE_WITH_DESCRIPTION.format(
            profile=CANDIDATE_PROFILE,
            title=title,
            company=job.get("company", ""),
            location=job.get("location", ""),
            is_remote="Yes" if job.get("is_remote") else "No",
            keyword_score=int(job.get("keyword_score", 0) or 0),
            description=desc,
        )
    else:
        system = SYSTEM_PROMPT_NO_DESCRIPTION
        prompt = USER_TEMPLATE_NO_DESCRIPTION.format(
            profile=CANDIDATE_PROFILE,
            title=title,
            company=job.get("company", ""),
            location=job.get("location", ""),
            is_remote="Yes" if job.get("is_remote") else "No",
            keyword_score=int(job.get("keyword_score", 0) or 0),
        )

    payload = {
        "model":  settings.ollama_model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 200},
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        score, reasoning = _parse_response(raw)
        return score, confidence, reasoning
    except requests.RequestException as e:
        logger.error(f"[Ollama] Request failed: {e}")
        return 0, "low", "ollama_unavailable"
    except Exception as e:
        logger.error(f"[Ollama] Unexpected error: {e}")
        return 0, "low", "scoring_error"


def score_jobs_batch(jobs: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """Ollama doesn't do batch — falls back to job-by-job."""
    return [score_job(j) for j in jobs]


def _parse_response(text: str) -> Tuple[int, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        logger.warning(f"[Ollama] No JSON found: '{text[:200]}'")
        return 0, "parse_error"
    try:
        data      = json.loads(match.group())
        score     = max(0, min(100, int(data.get("score", 0))))
        reasoning = str(data.get("reasoning", ""))[:500]
        return score, reasoning
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"[Ollama] Parse failed: {e}")
        return 0, "parse_error"
