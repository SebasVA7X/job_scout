"""
scorer/backends/prompts.py
Shared prompt templates used by both Ollama and Anthropic backends.
"""

CANDIDATE_PROFILE = """\
- Professional background: background
- Years of experience: years_exp+ years
- Core skills: skills
- Domain experience: domains
- Tools & technologies: tools
- Preferences: preferences
- Constraints: constraints
"""

LOCATION_RULES = """\
LOCATION RULES — CRITICAL:
Candidate is based in: candidate_location
Relocation: relocation_preference (e.g., willing to relocate worldwide / local only)

Hard disqualifiers (score 0-15):
- Restricted to specific nationalities/citizenships not held by the candidate.
- Requires active security clearance (Secret, Top Secret, etc.).
- Explicitly limited to local/national candidates only (unless matching candidate's location).
- Remote role restricted to specific countries/timezones that exclude the candidate.
  Exception: "Worldwide", "Global", or roles explicitly mentioning {candidate_location} are fine.
"""

SCORING_BANDS = """\
SCORING BANDS:
- 85-100: Strong domain fit + good skills match. Candidate should apply.
- 65-84:  Good domain fit, minor gaps (unfamiliar sector, slight skill mismatch, or on-site only).
- 40-64:  Partial fit — data-adjacent but limited scope.
- 0-39:   Poor fit — wrong domain, internship, or hard disqualifier triggered.\
"""

SYSTEM_PROMPT_WITH_DESCRIPTION = f"""\
You are a job-fit evaluator. Score how well the job listing matches the candidate profile.
Use the full job description to evaluate domain fit, required skills, seniority, and location constraints.

DOMAIN FIT — most important signal:
High priority domains: priority_domains
Avoid/Low fit: Roles with no data/technical component or explicitly listed in constraints.

SECTOR RULE: Private sector (tech, fintech, consulting, startups) is equally valid as international orgs.
Do NOT penalize for private sector. Penalize only if the role requires a license the candidate lacks.

{LOCATION_RULES}

SENIORITY: seniority_preference
LANGUAGE: Add the languages you are interested in.

{SCORING_BANDS}

You respond ONLY with valid JSON — no preamble, no markdown, no explanation outside the JSON.\
"""

SYSTEM_PROMPT_NO_DESCRIPTION = f"""\
You are a job-fit evaluator. Score how well the job listing matches the candidate profile.
IMPORTANT: No job description is available — evaluate based on title, organization, and location only.
Do NOT penalize for missing description — it is a structural limitation of this portal, not a signal.

DOMAIN FIT — evaluate from title alone:
Add your own domains to tell the LLM to score them for you.

Not a fit: Add the roles you would like to be penalized or excluded. 

ORGANIZATION SIGNAL: For UN agencies and international NGOs, give moderate benefit of the doubt
to ambiguous titles — these orgs frequently embed data/reporting duties.

{LOCATION_RULES}

SENIORITY: Your preferred seniority category. 
LANGUAGE: Which languages you prefer. 
Examples: You can add examples from one language and its translation. 

{SCORING_BANDS}

You respond ONLY with valid JSON — no preamble, no markdown, no explanation outside the JSON.\
"""

# ── Single-job user templates ─────────────────────────────────────────────────

USER_TEMPLATE_WITH_DESCRIPTION = """\
CANDIDATE PROFILE:
{profile}

JOB LISTING:
Title: {title}
Company: {company}
Location: {location}
Remote: {is_remote}
Keyword signal: {keyword_score}/100
Description:
{description}

Respond only with JSON: {{"score": <int 0-100>, "reasoning": "<max 2 sentences>"}}\
"""

USER_TEMPLATE_NO_DESCRIPTION = """\
CANDIDATE PROFILE:
{profile}

JOB LISTING:
Title: {title}
Company: {company}
Location: {location}
Remote: {is_remote}
Keyword signal: {keyword_score}/100
(No description available.)

Respond only with JSON: {{"score": <int 0-100>, "reasoning": "<max 2 sentences>"}}\
"""

# ── Batch user template (Anthropic only) ─────────────────────────────────────

USER_TEMPLATE_BATCH = """\
CANDIDATE PROFILE:
{profile}

Score each job listing below for fit with the candidate profile.
Return a JSON array with one object per job, in the same order.
Each object must have exactly: "index" (int), "score" (int 0-100), "reasoning" (max 2 sentences).

JOBS:
{jobs_block}

Respond ONLY with a JSON array. Example format:
[{{"index": 0, "score": 75, "reasoning": "Good fit. Minor location concern."}}, ...]\
"""


def format_job_for_batch(index: int, job: dict) -> str:
    """Format a single job entry for inclusion in a batch prompt."""
    has_desc = bool(str(job.get("description", "") or "").strip())
    title    = job.get("title_clean") or job.get("title", "")
    desc     = str(job.get("description", "") or "")
    if has_desc and len(desc) > 800:
        desc = desc[:500] + "\n[...]\n" + desc[-200:]

    lines = [
        f"[{index}] Title: {title}",
        f"    Company: {job.get('company', '')}",
        f"    Location: {job.get('location', '')}",
        f"    Remote: {'Yes' if job.get('is_remote') else 'No'}",
        f"    Keyword signal: {int(job.get('keyword_score', 0) or 0)}/100",
    ]
    if has_desc:
        lines.append(f"    Description: {desc}")
    else:
        lines.append("    (No description available)")

    return "\n".join(lines)


def is_jobspy(source: str) -> bool:
    return str(source or "").lower().startswith("jobspy")
