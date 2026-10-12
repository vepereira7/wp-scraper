"""Helpers for ANNP season identifiers and URLs."""

from __future__ import annotations

import re
from datetime import date

DEFAULT_BASE_URL = "https://provas.annp.pt"
_SEASON = re.compile(r"^(?:S)?(\d{2})(\d{2})$")
_SOURCE_SEASON_FALLBACKS = {
    # ANNP currently publishes the logical 2026/27 season below the stale
    # provas2526 directory. Keep this routing concern out of Match identity.
    "2627": ("2526",),
}


def normalize_annp_season(season: str) -> str:
    """Return the four-digit ANNP season after validating consecutive years."""
    match = _SEASON.fullmatch(season.strip().upper())
    if match is None:
        raise ValueError(
            f"Invalid ANNP season {season!r}; expected four digits such as 2526"
        )

    first, second = (int(value) for value in match.groups())
    if (first + 1) % 100 != second:
        raise ValueError(
            f"Invalid ANNP season {season!r}; season years must be consecutive"
        )
    return f"{first:02d}{second:02d}"


def annp_season_label(season: str) -> str:
    """Convert an ANNP logical season to the normalized Match season label."""
    return f"S{normalize_annp_season(season)}"


def annp_polo_path(season: str) -> str:
    """Return a physical ANNP polo path for a source directory identifier."""
    return f"/provas{normalize_annp_season(season)}/polo/"


def annp_source_seasons(logical_season: str) -> tuple[str, ...]:
    """Return physical source directories to try for one logical season."""
    normalized = normalize_annp_season(logical_season)
    return (normalized, *_SOURCE_SEASON_FALLBACKS.get(normalized, ()))


def annp_season_bounds(season: str) -> tuple[date, date]:
    """Return the inclusive July-to-June bounds represented by an ANNP season."""
    normalized = normalize_annp_season(season)
    start_year = 2000 + int(normalized[:2])
    end_year = 2000 + int(normalized[2:])
    return date(start_year, 7, 1), date(end_year, 6, 30)
