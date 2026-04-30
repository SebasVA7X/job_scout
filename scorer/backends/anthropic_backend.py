"""
scorer/backends/anthropic_backend.py
Anthropic API scoring — batch of N jobs per request to minimize cost.

Batch strategy:
  - Jobs with descriptions (JobSpy) and without (org scrapers) are scored
    in separate batches so the right system prompt is applied to each group.
  - Batch size is controlled by settings.anthropic_batch_size (default 15).
  - If the LLM returns malformed JSON for a batch, each job in that batch
    falls back to score=0/reasoning="parse_error" rather than crashing.
"""
import json
import logging
import re
from typing import Dict, Any, Tuple, List

import anthropic

from config.settings import settings
from scorer.backends.prompts import (
    CANDIDATE_PROFILE,
    SYSTEM_PROMPT_WITH_DESCRIPTION,
    SYSTEM_PROMPT_NO_DESCRIPTION,
    USER_TEMPLATE_BATCH,
    format_job_for_batch,
    is_jobspy,
)

logger = logging.getLogger(__name__)


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _calc_confidence(job: Dict[str, Any]) -> str:
    desc_len = len(str(job.get("description", "") or "").strip())
    source   = job.get("source", "")
    if is_jobspy(source) and desc_len > 500:
        return "high"
    elif is_jobspy(source) and desc_len > 100:
        return "medium"
    return "low"


def score_job(job: Dict[str, Any]) -> Tuple[int, str, str]:
    """Score a single job — wraps score_jobs_batch for convenience."""
    results = score_jobs_batch([job])
    return results[0]


def score_jobs_batch(jobs: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """
    Score a list of jobs using batched Anthropic API calls.
    Returns a list of (score, confidence, reasoning) in the same order as input.
    """
    if not jobs:
        return []

    # Split into desc / no-desc groups preserving original indices
    with_desc    = [(i, j) for i, j in enumerate(jobs) if is_jobspy(j.get("source", ""))]
    without_desc = [(i, j) for i, j in enumerate(jobs) if not is_jobspy(j.get("source", ""))]

    results: Dict[int, Tuple[int, str, str]] = {}

    for group, system_prompt in [
        (with_desc,    SYSTEM_PROMPT_WITH_DESCRIPTION),
        (without_desc, SYSTEM_PROMPT_NO_DESCRIPTION),
    ]:
        if not group:
            continue

        batch_size = settings.anthropic_batch_size
        for start in range(0, len(group), batch_size):
            chunk = group[start : start + batch_size]
            chunk_results = _score_chunk(chunk, system_prompt)
            results.update(chunk_results)

    # Fallback for any missing indices
    for i, job in enumerate(jobs):
        if i not in results:
            logger.warning(f"[Anthropic] No result for index {i}, using fallback")
            results[i] = (0, "low", "missing_result")

    return [results[i] for i in range(len(jobs))]


def _score_chunk(
    chunk: List[Tuple[int, Dict[str, Any]]],
    system_prompt: str,
) -> Dict[int, Tuple[int, str, str]]:
    """
    Score a single batch chunk. Returns a dict of {original_index: (score, conf, reasoning)}.
    """
    # Build the jobs block with local indices 0..N-1
    jobs_block = "\n\n".join(
        format_job_for_batch(local_i, job)
        for local_i, (_, job) in enumerate(chunk)
    )

    prompt = USER_TEMPLATE_BATCH.format(
        profile=CANDIDATE_PROFILE,
        jobs_block=jobs_block,
    )

    try:
        client   = _get_client()
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw_text = response.content[0].text
        parsed   = _parse_batch_response(raw_text, len(chunk))

    except anthropic.APIError as e:
        logger.error(f"[Anthropic] API error: {e}")
        parsed = [(0, "low", "api_error")] * len(chunk)
    except Exception as e:
        logger.error(f"[Anthropic] Unexpected error: {e}")
        parsed = [(0, "low", "scoring_error")] * len(chunk)

    # Map local indices back to original indices
    results = {}
    for local_i, (orig_i, job) in enumerate(chunk):
        score, _, reasoning = parsed[local_i] if local_i < len(parsed) else (0, "low", "missing")
        confidence = _calc_confidence(job)
        results[orig_i] = (score, confidence, reasoning)

    return results


def _parse_batch_response(
    text: str, expected: int
) -> List[Tuple[int, str, str]]:
    """
    Parse a JSON array from the LLM response.
    Returns a list of (score, confidence, reasoning) of length `expected`.
    Falls back to (0, "low", "parse_error") for any missing/malformed entries.
    """
    fallback = [(0, "low", "parse_error")] * expected

    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()

    # Find JSON array in response
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        logger.warning(f"[Anthropic] No JSON array found in response: '{text[:300]}'")
        return fallback

    try:
        items = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"[Anthropic] JSON decode failed: {e} | raw: '{text[:300]}'")
        return fallback

    results = list(fallback)  # start with fallbacks

    for item in items:
        try:
            idx       = int(item.get("index", -1))
            score     = max(0, min(100, int(item.get("score", 0))))
            reasoning = str(item.get("reasoning", ""))[:500]
            if 0 <= idx < expected:
                results[idx] = (score, "low", reasoning)  # confidence set by caller
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"[Anthropic] Malformed item {item}: {e}")
            continue

    return results
