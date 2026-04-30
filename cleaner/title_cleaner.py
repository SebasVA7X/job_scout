"""
cleaner/title_cleaner.py
Strips noise from raw job titles:
  - Leading numeric/reference prefixes  (e.g. "2026-555 -", "REF-001:")
  - Leading/trailing emojis and symbols
  - Excessive whitespace
"""
import re
import unicodedata


# Matches leading patterns like "2026-555 -", "2026/04:", "REF-001 |", "[123]" etc.
_PREFIX_RE = re.compile(
    r"^(?:"
    r"\[?[\w\-/]{1,20}\]?\s*[-:|]\s*"   # alphanumeric ref + separator
    r"|#\d+\s+"                           # #123
    r"|\d{4,}\s*[-:]\s*"                  # 4+ digit year/id prefix
    r")+",
    re.IGNORECASE,
)

# Unicode categories that are emoji / symbols / misc
_EMOJI_CATS = {"So", "Sm", "Sk", "Cs", "Co"}


def _strip_leading_emoji(text: str) -> str:
    """Remove leading emoji/symbol characters."""
    i = 0
    while i < len(text):
        cat = unicodedata.category(text[i])
        if cat in _EMOJI_CATS or ord(text[i]) > 0x2000:
            i += 1
        else:
            break
    return text[i:]


def _strip_trailing_emoji(text: str) -> str:
    """Remove trailing emoji/symbol characters."""
    i = len(text) - 1
    while i >= 0:
        cat = unicodedata.category(text[i])
        if cat in _EMOJI_CATS or ord(text[i]) > 0x2000:
            i -= 1
        else:
            break
    return text[: i + 1]


def clean_title(title: str) -> str:
    """Return a cleaned version of a job title."""
    if not title:
        return title

    t = title.strip()
    t = _strip_leading_emoji(t)
    t = _PREFIX_RE.sub("", t)
    t = _strip_trailing_emoji(t)

    # Collapse multiple spaces
    t = re.sub(r"\s{2,}", " ", t).strip()

    # Remove stray leading punctuation left after prefix removal
    t = re.sub(r"^[-|:,\s]+", "", t).strip()

    return t if t else title  # fallback to original if we stripped everything
