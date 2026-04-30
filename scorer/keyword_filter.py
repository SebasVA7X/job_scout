"""
scorer/keyword_filter.py
Keyword scoring with:
  - Exact word-boundary match (primary signal)
  - Substring/phrase match (secondary signal)
  - Remote detection from raw text
  - Operational role blacklist (title-level disqualifiers)
  - Internship/trainee hard disqualifier
  - Normalized 0-100 score, decoupled from the gate threshold
"""
from __future__ import annotations
import re
from typing import Dict, Any, List, Set, Tuple

from config.settings import settings

# ── Sources that never have real descriptions ─────────────────────────────────
NO_DESCRIPTION_SOURCES = {"idb", "unhcr", "un_careers", "iom"}

# ── Hard disqualifiers — internship/trainee only ──────────────────────────────
INTERNSHIP_TERMS = [
    "intern", "internship", "trainee", "apprentice",
    "graduate program", "fresher",
    "entry level", "entry-level",
    # Spanish
    "pasante", "practicante", "práctica profesional",
    "programa de talento joven", "trainee",
]

# ── Operational blacklist — department/role context that signals non-data ─────
OPERATIONAL_BLACKLIST = [
    # UN/INGO departments
    "EECD", "WASH",
    # Role types
    "protection officer", "field security", "security officer",
    "supply chain officer", "supply chain manager",
    "logistics officer", "procurement",
    "legal officer", "paralegal", "lawyer",
    "nurse", "doctor", "physician", "clinical",
    "driver", "conductor",
    # Finance/admin analyst variants that are NOT data roles
    "billing analyst", "payroll analyst", "claims analyst",
    "collections analyst", "transportation analyst",
    "accounts payable", "accounts receivable",
    "third party billing",
    # Spanish operational roles
    "oficial de protección", "oficial de seguridad",
    "analista de soporte operativo",
# Fake/Low-tier data roles
    "data entry", "digitador", "data encoder", "data clerk",
    "grabador de datos", "auxiliar de datos", "transcriptionist",
]

# ── Remote signals ────────────────────────────────────────────────────────────
REMOTE_SIGNALS = [
    "remote", "remoto", "work from home", "fully remote",
    "home-based", "home based", "telework", "telecommute",
    "anywhere", "distributed team",
    # Spanish/Portuguese
    "trabajo remoto", "100% remoto", "totalmente remoto",
    "trabalho remoto", "100% remote",
]

# ── Exact match keywords (word boundary) — primary signal ────────────────────
EXACT_KEYWORDS: List[Tuple[str, float]] = [
    ("data analyst",              3.0),
    ("data engineer",             3.0),
    ("data engineering",          2.5),
    ("business intelligence",     3.0),
    ("BI developer",              3.0),
    ("BI analyst",                3.0),
    ("data warehouse",            2.5),
    ("data pipeline",             2.5),
    ("ETL",                       2.5),
    ("ELT",                       2.0),
    ("SQL",                       1.5),
    ("Power BI",                  2.5),
    ("Tableau",                   2.0),
    ("DAX",                       2.0),
    ("Power Query",               2.0),
    ("analytics",                 1.5),
    ("reporting",                 1.0),
    ("dashboard",                 1.5),
    ("monitoring",                1.5),
    ("evaluation",                1.5),
    ("M&E",                       2.5),
    ("MEAL",                      2.5),
    ("results framework",         2.0),
    ("indicators",                1.0),
    ("logframe",                  2.0),
    ("performance measurement",   2.0),
    ("Python",                    1.5),
    ("dbt",                       2.0),
    ("Spark",                     2.0),
    ("Airflow",                   2.0),
    ("AWS",                       1.0),
    ("Azure",                     1.0),
    ("GCP",                       1.0),
    ("BigQuery",                  2.0),
    ("machine learning",          2.0),
    ("LLM",                       2.0),
    ("NLP",                       1.5),
    ("RAG",                       2.0),
    ("generative AI",             2.0),
    ("information management",    3.0),
    ("information systems",       2.0),
    ("data management",           2.5),
    ("operational data",          2.0),
    ("program management",        1.5),
    ("project management",        1.5),
    ("consultant",                1.0),
]

# ── Substring/phrase keywords — secondary signal ──────────────────────────────
SUBSTRING_KEYWORDS: List[Tuple[str, float]] = [
    ("business intelligence",     2.0),
    ("data analytics",            2.0),
    ("data analysis",             2.0),
    ("data science",              1.5),
    ("information management",    2.0),
    ("monitoring and evaluation", 2.0),
    ("data visualization",        1.5),
    ("business analyst",          1.5),
    ("systems analyst",           1.0),
    ("reporting analyst",         1.5),
    ("analytics engineer",        2.5),
    ("analytics manager",         2.0),
    ("data insights",             1.5),
    ("data quality",              1.5),
    ("data governance",           1.5),
    ("data architect",            2.0),
    ("data modeler",              2.0),
    ("data steward",              1.5),
    ("data coordinator",          1.5),
    # ── Spanish variants ──────────────────────────────────────────────────────
    ("ingeniero de datos",        3.0),
    ("analista de datos",         3.0),
    ("analista de inteligencia",  2.5),
    ("inteligencia de negocios",  2.5),
    ("inteligencia comercial",    2.0),
    ("ingeniería de datos",       2.5),
    ("analista de información",   2.0),
    ("gestión de datos",          2.0),
    ("ciencia de datos",          2.0),
    ("visualización de datos",    1.5),
    ("trabajo remoto",            1.0),
    ("100% remoto",               1.0),
    ("analista de negocio",       1.5),
    ("desarrollador de datos",    2.0),
    ("arquitecto de datos",       2.0),
    ("monitoreo y evaluación",    2.5),
    # ── Portuguese variants ───────────────────────────────────────────────────
    ("engenheiro de dados",       3.0),
    ("analista de dados",         3.0),
    ("engenharia de dados",       2.5),
    ("ciência de dados",          2.0),
    ("trabalho remoto",           1.0),
]


def _build_exact_regex(terms: List[str]) -> re.Pattern:
    escaped = [re.escape(t) for t in terms]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def _build_blacklist_regex(terms: List[str]) -> re.Pattern:
    escaped = [re.escape(t) for t in terms]
    pattern = "(?:" + "|".join(escaped) + ")"
    return re.compile(pattern, re.IGNORECASE)


_EXACT_KW_TERMS   = [kw for kw, _ in EXACT_KEYWORDS]
_EXACT_KW_WEIGHTS = {kw.lower(): w for kw, w in EXACT_KEYWORDS}
_EXACT_REGEX      = _build_exact_regex(_EXACT_KW_TERMS)
_INTERNSHIP_REGEX = _build_exact_regex(INTERNSHIP_TERMS)
_BLACKLIST_REGEX  = _build_blacklist_regex(OPERATIONAL_BLACKLIST)
_REMOTE_REGEX     = _build_exact_regex(REMOTE_SIGNALS)


def _source_name(job: Dict[str, Any]) -> str:
    return str(job.get("source", "")).split(":")[0].lower()


def _detect_remote(title: str, location: str, description: str) -> bool:
    combined = f"{title} {location} {description}"
    return bool(_REMOTE_REGEX.search(combined))


def _exact_signal(text: str, weight: float = 1.0) -> Tuple[float, List[str]]:
    if not text:
        return 0.0, []
    matches = []
    signal  = 0.0
    for m in _EXACT_REGEX.finditer(text):
        kw = m.group(0).lower()
        matches.append(kw)
        signal += _EXACT_KW_WEIGHTS.get(kw, 1.0) * weight
    return signal, matches


def _substring_signal(text: str, weight: float = 1.0) -> Tuple[float, List[str]]:
    if not text:
        return 0.0, []
    text_lower = text.lower()
    matches: List[str] = []
    signal  = 0.0
    seen: Set[str] = set()
    for kw, w in SUBSTRING_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower not in seen and kw_lower in text_lower:
            matches.append(kw_lower)
            signal += w * weight
            seen.add(kw_lower)
    return signal, matches


def keyword_score(job: Dict[str, Any]) -> int:
    source   = _source_name(job)
    title    = str(job.get("title",       "") or "")
    desc     = str(job.get("description", "") or "")
    location = str(job.get("location",    "") or "")
    has_desc = bool(desc.strip()) and source not in NO_DESCRIPTION_SOURCES

    # ── 1. Hard disqualifier: internship / trainee ────────────────────────────
    if _INTERNSHIP_REGEX.search(title):
        job["keyword_debug"] = {"discard": "internship", "title": title}
        job["keyword_score"] = 0
        return 0

    # ── 2. Operational blacklist ──────────────────────────────────────────────
    bl_match = _BLACKLIST_REGEX.search(title)
    if bl_match:
        job["keyword_debug"] = {"discard": "operational_blacklist", "match": bl_match.group(0)}
        job["keyword_score"] = 0
        return 0

    # ── 3. Keyword signals ────────────────────────────────────────────────────
    title_exact_sig, title_exact_matches = _exact_signal(title,   weight=2.5)
    title_sub_sig,   title_sub_matches   = _substring_signal(title, weight=2.0)

    if has_desc:
        desc_exact_sig, desc_exact_matches = _exact_signal(desc,   weight=1.0)
        desc_sub_sig,   desc_sub_matches   = _substring_signal(desc, weight=0.8)
    else:
        desc_exact_sig = desc_sub_sig = 0.0
        desc_exact_matches = desc_sub_matches = []

    total_signal = title_exact_sig + title_sub_sig + desc_exact_sig + desc_sub_sig

    # ── 4. Remote bonus ───────────────────────────────────────────────────────
    is_remote = _detect_remote(title, location, desc)
    remote_bonus = 10.0 if is_remote else 0.0
    if is_remote and not job.get("is_remote"):
        job["is_remote"] = 1

    # ── 5. Normalize to 0-100 ─────────────────────────────────────────────────
    # signal=0 → 0, signal≥CEILING → 90 (+ up to 10 from remote = 100)
    SIGNAL_CEILING = 35.0
    if total_signal == 0:
        raw_score = 0.0
    else:
        raw_score = min((total_signal / SIGNAL_CEILING) * 90, 90) + remote_bonus

    final_score = max(0, min(int(round(raw_score)), 100))

    job["keyword_debug"] = {
        "total_signal":  round(total_signal, 2),
        "remote_bonus":  remote_bonus,
        "is_remote":     is_remote,
        "title_exact":   title_exact_matches,
        "title_substr":  title_sub_matches,
        "desc_exact":    desc_exact_matches,
        "desc_substr":   desc_sub_matches,
    }
    job["keyword_score"] = final_score
    return final_score


def passes_keyword_gate(job: Dict[str, Any]) -> bool:
    score = keyword_score(job)
    job["keyword_score"] = score
    return score >= settings.score_save_threshold