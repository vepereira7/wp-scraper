"""Helpers for interpreting FPN competition domains."""

from __future__ import annotations

import re

_SEASON_SUFFIX = re.compile(r"_(\d{2})-(\d{2})$")


def extract_fpn_season(domain: str) -> str:
    """Convert a competition domain suffix to the app season identifier."""
    match = _SEASON_SUFFIX.search(domain)
    if match is None:
        raise ValueError(f"Could not extract season from FPN domain: {domain}")
    first, second = match.groups()
    return f"S{first}{second}"
