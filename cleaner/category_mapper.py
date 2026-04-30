"""
cleaner/category_mapper.py
Maps a cleaned job title to a deterministic category label.
Rules are evaluated in order — first match wins.
If no rule matches, category = "Other".

Categories are purely informational (for dashboard/Tableau).
The LLM never sees or uses them.
"""
import re
from typing import List, Tuple, Optional

# ── Rule table ────────────────────────────────────────────────────────────────
# Each entry: (category_label, [keyword_patterns])
# Patterns are matched case-insensitively against the cleaned title.
# All patterns in the list are OR-ed — any match triggers the category.

CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    ("Data Engineer", [
        r"\bdata\s+engineer",
        r"\bingeni[eé]r[oa]\s+de\s+datos",
        r"\bdata\s+engineering",
        r"\bingeni[eé]r[íi]a\s+de\s+datos",
        r"\bETL\b",
        r"\bELT\b",
        r"\banalytics\s+engineer",
        r"\boperational\s+data\s+management",
        r"\bgestión\s+operativa\s+de\s+datos",
    ]),
    ("Data Analyst", [
        r"\bdata\s+anal[iy]s[ti]",
        r"\banalista\s+de\s+datos",
        r"\banalista\s+de\s+información",
        r"\bBI\s+anal[iy]s[ti]",
        r"\bbusiness\s+intelligence\s+anal[iy]s[ti]",
        r"\banalista\s+de\s+inteligencia",
        r"\bdata\s+analytics",
        r"\bdata\s+analysis",
        r"\banalytics\s+specialist",
        r"\breporting\s+anal[iy]s[ti]",
        r"\bdata\s+insights",
        r"\banalista\s+de\s+negocio",
        r"\bbusiness\s+anal[iy]s[ti]",
    ]),
    ("BI Developer", [
        r"\bBI\s+developer",
        r"\bbusiness\s+intelligence\s+developer",
        r"\bpower\s+bi\b",
        r"\btableau\b",
        r"\bdata\s+visualization\s+specialist",
        r"\bvisualizaci[oó]n\s+de\s+datos",
        r"\bdesarrollador\s+de\s+datos",
    ]),
    ("Data Scientist", [
        r"\bdata\s+scien[ct]",
        r"\bciencia\s+de\s+datos",
        r"\bciência\s+de\s+dados",
        r"\bmachine\s+learning\s+engineer",
        r"\bml\s+engineer",
        r"\bAI\s+engineer",
        r"\bNLP\s+engineer",
    ]),
    ("Information Management", [
        r"\binformation\s+management",
        r"\bIM\s+officer",
        r"\bIM\s+specialist",
        r"\bIM\s+analyst",
        r"\bIM\s+consultant",
        r"\bgestión\s+de\s+información",
        r"\bdata\s+management\s+officer",
        r"\bdata\s+management\s+specialist",
        r"\boperational\s+data",
        r"\bregistration\s+officer",
    ]),
    ("M&E / MEAL", [
        r"\bM&E\b",
        r"\bMEAL\b",
        r"\bmonitoring\s+(and|&)\s+evaluation",
        r"\bmonitoreo\s+y\s+evaluaci[oó]n",
        r"\bresults\s+measurement",
        r"\bperformance\s+measurement",
        r"\blogframe",
        r"\bresults\s+framework",
    ]),
    ("Program / Project Management", [
        r"\bprogram\s+manager",
        r"\bproject\s+manager",
        r"\bportfolio\s+manager",
        r"\bprogram\s+officer",
        r"\bproject\s+officer",
        r"\bprogramme\s+manager",
        r"\bprogramme\s+officer",
        r"\bconsultant\b",
        r"\bcoordinator\b",
    ]),
]

# Precompile all patterns
_COMPILED_RULES: List[Tuple[str, List[re.Pattern]]] = [
    (label, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, patterns in CATEGORY_RULES
]


def map_category(title_clean: str) -> str:
    """
    Return the first matching category label, or 'Other' if none match.
    Matching is done against the cleaned title only (deterministic, no LLM).
    """
    if not title_clean:
        return "Other"

    for label, patterns in _COMPILED_RULES:
        for pattern in patterns:
            if pattern.search(title_clean):
                return label

    return "Other"
