"""Canonical match-category values and source-label normalization."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class MatchCategory(str, Enum):
    """Canonical age and senior match categories."""

    U12 = "Sub-12"
    U14 = "Sub-14"
    U16 = "Sub-16"
    U18 = "Sub-18"
    SENIOR = "Seniores"
    UNKNOWN = "Unknown"


_CATEGORY_PATTERNS = (
    (r"\bsenior(?:es)?\b", MatchCategory.SENIOR),
    (r"\bjunior(?:es)?\b", MatchCategory.U18),
    (r"\bjuven(?:il|is)\b", MatchCategory.U16),
    (r"\binfant(?:il|is)\b", MatchCategory.U14),
    (r"\bcadetes?\b", MatchCategory.U12),
    (r"\b(?:sub|u)[ -]?18\b", MatchCategory.U18),
    (r"\b(?:sub|u)[ -]?16\b", MatchCategory.U16),
    (r"\b(?:sub|u)[ -]?14\b", MatchCategory.U14),
    (r"\b(?:sub|u)[ -]?12\b", MatchCategory.U12),
)


def _normalized_category_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def normalize_category(value: str | MatchCategory | None) -> MatchCategory:
    """Map an unambiguous source label to the shared canonical category.

    The model's existing ``UNKNOWN`` value is retained for missing, unrecognized,
    or ambiguous labels. No category is guessed when multiple age groups occur.
    """
    if isinstance(value, MatchCategory):
        return value
    if value is None:
        return MatchCategory.UNKNOWN

    normalized = _normalized_category_text(value)
    if normalized == MatchCategory.UNKNOWN.value.casefold():
        return MatchCategory.UNKNOWN

    matches = {
        category
        for pattern, category in _CATEGORY_PATTERNS
        if re.search(pattern, normalized)
    }
    return matches.pop() if len(matches) == 1 else MatchCategory.UNKNOWN


def format_match_category(category: MatchCategory) -> str:
    """Return the canonical external label for a normalized category."""
    return category.value
