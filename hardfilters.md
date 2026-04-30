# Hard Filters & Gates — Where to Customize Job Searches

This document describes every place in the codebase where jobs are filtered, blocked, or scored before they reach your Telegram. If you want to search for different roles, industries, or geographies, these are the only files you need to touch.

---

## Overview

Jobs pass through four sequential gates. A job blocked at any gate never reaches the next one.

```
[Scraped jobs]
      │
      ▼
① Age / Deadline gate          scheduler/runner.py
      │
      ▼
② US-only / geo discard        scraper/jobspy_collector.py
      │
      ▼
③ Keyword gate (pre-LLM)       scorer/keyword_filter.py
      │
      ▼
④ LLM scoring & profile        scorer/backends/prompts.py
      │
      ▼
[Saved to DB → Telegram]
```

---

## Gate ① — Age / Deadline Filter

**File:** `scheduler/runner.py` (lines 47, 69–88)

Jobs are discarded before any keyword or LLM scoring if:
- Their `deadline` date is in the past, **or**
- They have no deadline and were posted more than **20 days ago**

```python
MAX_AGE_DAYS_NO_DEADLINE = 20   # line 47
```

**To change:** Edit `MAX_AGE_DAYS_NO_DEADLINE`. Set it higher if you want to catch older postings (e.g., `30`), or lower to keep the feed very fresh (e.g., `7`).

This filter runs in `_is_expired()` and cannot be overridden per-source.

---

## Gate ② — Geography / Visa Discard (JobSpy only)

**File:** `scraper/jobspy_collector.py`

Two things control which jobs come in from LinkedIn and Indeed.

### Search terms and target regions

```python
SEARCHES = [
    ("data analyst",                  "Remote"),
    ("business intelligence analyst", "Remote"),
    ("power bi analyst",              "Remote"),
    # ... Latin America, New Zealand, Australia, Spain, Ecuador, Europe
]
```

Each entry is a `(search_term, location)` pair. LinkedIn and Indeed use the location to bias results geographically.

**To change for a different profession:** Replace the search terms. For example, for a software engineer:

```python
SEARCHES = [
    ("software engineer",    "Remote"),
    ("backend developer",    "Remote"),
    ("python developer",     "Remote"),
    ("full stack engineer",  "Latin America"),
    # ...
]
```

**To change target regions:** Replace or add location strings. Any city, country, or region name that LinkedIn/Indeed recognize works (e.g., `"Germany"`, `"Singapore"`, `"New York"`).

### Hard discard phrases (description-level)

```python
DISCARD_PHRASES = [
    "visa sponsorship is not available",
    "must be authorized to work in the us",
    "must reside in the united states",
    "remote within the united states",
    "us only",
    "u.s. only",
    "eu only",
    "green card required",
    "u.s. citizen",
    "us citizen",
    # ...
]
```

If any of these phrases appear in the job description, the job is dropped immediately — before keyword scoring, before the DB, before any API call.

**To change:** Add or remove entries freely. These are simple lowercase substring matches against the full description text. If you are based in the US or EU and want to see local roles, remove the US/EU phrases. If you want to block additional country restrictions, add them here.

---

## Gate ③ — Keyword Gate (Pre-LLM)

**File:** `scorer/keyword_filter.py`

This is the most important filter for adapting the system to a different profession. It runs before the LLM and determines what gets saved to the database at all.

### Hard disqualifiers — Internships

```python
INTERNSHIP_TERMS = [
    "intern", "internship", "trainee", "apprentice",
    "graduate program", "fresher",
    "entry level", "entry-level",
    "pasante", "practicante", "práctica profesional",
    # ...
]
```

If any of these appear in the job **title**, the job scores 0 and is discarded immediately, regardless of anything else.

**To change:** Remove terms you want to allow (e.g., remove `"entry level"` if you want junior roles). Add terms specific to your field.

### Hard disqualifiers — Operational blacklist

```python
OPERATIONAL_BLACKLIST = [
    "WASH", "protection officer", "field security", "security officer",
    "supply chain officer", "logistics officer", "procurement",
    "legal officer", "paralegal", "lawyer",
    "nurse", "doctor", "physician", "clinical", "driver",
    "billing analyst", "payroll analyst", "claims analyst",
    "data entry", "digitador", "data encoder", "data clerk",
    # ...
]
```

If any of these appear in the job **title**, the job scores 0 and is discarded. These are role types that are definitively not a fit.

**To change:** This list must match your profession. If you are targeting legal roles, remove `"legal officer"` and `"lawyer"`. If you are targeting supply chain, remove those entries. Add role names that are clearly out of scope for your search instead.

### Positive keywords — Exact match (primary signal)

```python
EXACT_KEYWORDS = [
    ("data analyst",           3.0),
    ("data engineer",          3.0),
    ("business intelligence",  3.0),
    ("Power BI",               2.5),
    ("ETL",                    2.5),
    ("M&E",                    2.5),
    ("MEAL",                   2.5),
    ("SQL",                    1.5),
    ("Python",                 1.5),
    ("machine learning",       2.0),
    ("information management", 3.0),
    # ... ~40 terms total
]
```

These are matched at **word boundaries** (regex `\b`) against the title (weight ×2.5) and description (weight ×1.0). Higher weights mean the term contributes more to the score.

**To change for a different profession:** Replace these entirely. For example, for a cybersecurity role:

```python
EXACT_KEYWORDS = [
    ("security engineer",      3.0),
    ("penetration testing",    3.0),
    ("SOC analyst",            3.0),
    ("incident response",      2.5),
    ("vulnerability",          2.0),
    ("SIEM",                   2.5),
    ("firewall",               1.5),
    ("CISSP",                  2.0),
    # ...
]
```

### Positive keywords — Substring/phrase match (secondary signal)

```python
SUBSTRING_KEYWORDS = [
    ("data analytics",         2.0),
    ("data analysis",          2.0),
    ("monitoring and evaluation", 2.0),
    ("business analyst",       1.5),
    ("analytics engineer",     2.5),
    ("data quality",           1.5),
    # Spanish / Portuguese variants
    ("ingeniero de datos",     3.0),
    ("analista de datos",      3.0),
    ("monitoreo y evaluación", 2.5),
    # ...
]
```

These are matched as plain substrings (no word boundary requirement), against the same title + description fields. Useful for multi-word phrases and non-English variants.

**To change:** Add your profession's Spanish/Portuguese equivalents here, or any phrases that don't need strict word-boundary matching.

### Score gate threshold

Jobs with a keyword score below `SCORE_SAVE_THRESHOLD` (default: `10`) are discarded before being saved to the database. This value is set in `.env`:

```env
SCORE_SAVE_THRESHOLD=10
```

Lowering this (e.g., to `5`) lets more borderline jobs through to the LLM. Raising it (e.g., to `20`) keeps the DB smaller but risks missing relevant roles with sparse keyword matches.

### Remote bonus

```python
REMOTE_SIGNALS = [
    "remote", "remoto", "work from home", "fully remote",
    "home-based", "home based", "telework",
    "trabajo remoto", "trabalho remoto",
    # ...
]
```

Jobs containing any of these phrases receive a **+10 point bonus** on the keyword score. Remove this section or set the bonus to `0` if remote preference is not relevant to your search.

**This is a complex file, ask help from your favorite LLM if you need to tailor it for you.**

---

## Gate ④ — LLM Scoring & Candidate Profile

**File:** `scorer/backends/prompts.py`

After the keyword gate, the LLM scores each job 0–100 using a detailed system prompt. This is where the candidate's specific background, preferred roles, and hard disqualifiers are defined.

### Candidate profile

```python
CANDIDATE_PROFILE = """\
- Professional background: [e.g., data analyst, engineer, designer]
- Years of experience: [X+ years]
- Core skills: [e.g., Python, SQL, BI tools, etc.]
- Domain experience: [e.g., finance, healthcare, NGOs, tech]
- Tools & technologies: [list relevant tools]
- Preferences: [remote/on-site, industries, role types]
- Constraints: [optional — roles to avoid, location limits, etc.]
"""
```

**To change:** Rewrite this section entirely to match the target candidate. Include years of experience, specific tools, sectors, seniority level, and anything the candidate will not consider.

### Location rules

```python
LOCATION_RULES = """
Hard disqualifiers (score 0-15):
- Restricted to specific nationalities (e.g. "US citizens only")
- Requires active security clearance (Secret, Top Secret)
- Explicitly limited to local/national candidates only
- Remote role restricted to specific countries (e.g. "US-based only")
  Exception: worldwide, global, or (Country)-specific remote is fine.

Candidate is based in Ecuador — can work remotely from there or relocate internationally.
"""
```

**To change:** Update the candidate's base country and adjust the exceptions. If the candidate is EU-based and EU-only roles are fine, remove the `"EU only"` hard disqualifier from both here and `DISCARD_PHRASES` in `jobspy_collector.py`.

### Scoring bands

```python
SCORING_BANDS = """
- 85-100: Strong domain fit + good skills match. Candidate should apply.
- 65-84:  Good domain fit, minor gaps.
- 40-64:  Partial fit — data-adjacent but limited scope.
- 0-39:   Poor fit — wrong domain, internship, or hard disqualifier.
"""
```

**To change:** Adjust the band descriptions to reflect what counts as a strong fit for your profession. The LLM interprets these bands when generating scores, so wording matters.

### System prompts (what the LLM is told)

There are two system prompts:
- `SYSTEM_PROMPT_WITH_DESCRIPTION` — used when a full description is available
- `SYSTEM_PROMPT_NO_DESCRIPTION` — used when only the title/company/location are known

Both contain inline lists of strong-fit and not-fit role examples. For example:

```python
# In SYSTEM_PROMPT_WITH_DESCRIPTION:
"Strong fit: data analytics, business intelligence, data engineering, ETL, reporting,
M&E/MEAL, information management, AI/ML, program/project management with data focus."

"Not a fit: purely operational, clinical, legal, administrative, or field-based roles."
```

**To change:** Edit the "Strong fit" and "Not a fit" examples to describe your target profession. This directly guides Claude's domain evaluation for jobs where the description exists and for title-only scoring.

---

## Summary Table

| Gate | File | What to Edit | When to Edit |
|---|---|---|---|
| Age filter | `scheduler/runner.py` | `MAX_AGE_DAYS_NO_DEADLINE` | Want older or fresher jobs |
| Search terms & regions | `scraper/jobspy_collector.py` | `SEARCHES` list | Different roles or geographies on LinkedIn/Indeed |
| Visa/geo discard | `scraper/jobspy_collector.py` | `DISCARD_PHRASES` | Based in US/EU, or want to block more restrictions |
| Internship disqualifier | `scorer/keyword_filter.py` | `INTERNSHIP_TERMS` | Want to include junior/graduate roles |
| Role blacklist | `scorer/keyword_filter.py` | `OPERATIONAL_BLACKLIST` | Different profession (remove non-applicable entries) |
| Positive keywords | `scorer/keyword_filter.py` | `EXACT_KEYWORDS`, `SUBSTRING_KEYWORDS` | Different profession, tools, or languages |
| Score gate threshold | `.env` | `SCORE_SAVE_THRESHOLD` | More or fewer jobs reaching the LLM |
| Remote preference | `scorer/keyword_filter.py` | `REMOTE_SIGNALS` bonus | Remote not a priority |
| Candidate profile | `scorer/backends/prompts.py` | `CANDIDATE_PROFILE` | Different person or role type |
| Location rules | `scorer/backends/prompts.py` | `LOCATION_RULES` | Different base country or visa situation |
| LLM scoring guidance | `scorer/backends/prompts.py` | System prompts | Different domain definition |

---

## Quickstart: Adapting for a New Profession

Minimum changes needed to repurpose the system:

1. **`scraper/jobspy_collector.py`** — Replace `SEARCHES` with your job titles and target regions.
2. **`scorer/keyword_filter.py`** — Replace `EXACT_KEYWORDS` and `SUBSTRING_KEYWORDS` with terms relevant to your field. Clean up `OPERATIONAL_BLACKLIST` to remove entries that don't apply.
3. **`scorer/backends/prompts.py`** — Rewrite `CANDIDATE_PROFILE` and update the "Strong fit / Not a fit" examples in both system prompts.

Everything else (database, scheduling, Telegram delivery, deduplication) requires no changes.
