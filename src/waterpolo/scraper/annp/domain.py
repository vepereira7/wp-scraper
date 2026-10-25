"""Helpers for ANNP season identifiers and current public URLs."""

from __future__ import annotations

import re
from datetime import date

DEFAULT_BASE_URL = "https://provas.annp.pt"
_SEASON = re.compile(r"^(?:S)?(\d{2})(\d{2})$")


def normalize_annp_season(season: str) -> str:
    """Validate consecutive season years in the project's four-digit format."""
    match = _SEASON.fullmatch(season.strip().upper())
    if match is None:
        raise ValueError(
            f"Invalid ANNP season {season!r}; expected four digits such as 2627"
        )
    first, second = (int(value) for value in match.groups())
    if (first + 1) % 100 != second:
        raise ValueError(
            f"Invalid ANNP season {season!r}; season years must be consecutive"
        )
    return f"{first:02d}{second:02d}"


def annp_season_label(season: str) -> str:
    return f"S{normalize_annp_season(season)}"


def annp_public_path(season: str) -> str:
    """Map 2627 to /polo/20262027/ without hardcoding a season."""
    normalized = normalize_annp_season(season)
    start_year = 2000 + int(normalized[:2])
    end_year = start_year + 1
    return f"/polo/{start_year:04d}{end_year:04d}/"


def annp_season_bounds(season: str) -> tuple[date, date]:
    normalized = normalize_annp_season(season)
    start_year = 2000 + int(normalized[:2])
    return date(start_year, 7, 1), date(start_year + 1, 6, 30)
