"""FPN-specific resolution of missing venue names."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from waterpolo.models import Match, MatchSource

DEFAULT_MAPPING_PATH = Path(__file__).with_name("fpn_venues.json")


@dataclass(frozen=True)
class FPNVenueMapping:
    """Configured default pools by home team and per-game exceptions."""

    team_venues: Mapping[str, str]
    match_overrides: Mapping[str, str]


@lru_cache(maxsize=1)
def load_fpn_venue_mapping() -> FPNVenueMapping:
    """Load the checked-in FPN venue configuration."""
    return load_fpn_venue_mapping_from_path(DEFAULT_MAPPING_PATH)


def load_fpn_venue_mapping_from_path(path: Path) -> FPNVenueMapping:
    """Load and validate a venue mapping JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load FPN venue mapping {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("FPN venue mapping must be a JSON object")

    team_venues = _string_mapping(payload.get("team_venues", {}), "team_venues")
    match_overrides = _string_mapping(payload.get("match_overrides", {}), "match_overrides")
    return FPNVenueMapping(team_venues=team_venues, match_overrides=match_overrides)


def resolve_fpn_location(
    match: Match, venue_mapping: FPNVenueMapping | None = None
) -> Match:
    """Fill missing FPN locations, preferring API locations and game overrides."""
    if match.source is not MatchSource.FPN:
        return match

    api_location = _clean_location(match.location)
    if api_location is not None:
        return match.model_copy(update={"location": api_location})

    mapping = venue_mapping or load_fpn_venue_mapping()
    resolved = mapping.match_overrides.get(match.external_id)
    if resolved is None:
        home_key = _normalized_team_key(match.home)
        if home_key is not None:
            for team_name, venue in mapping.team_venues.items():
                if _normalized_team_key(team_name) == home_key:
                    resolved = venue
                    break
    return match.model_copy(update={"location": _clean_location(resolved)})


def _string_mapping(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError(f"FPN venue mapping {field_name} must be an object")
    result: dict[str, str] = {}
    for key, venue in value.items():
        if not isinstance(key, str) or not isinstance(venue, str) or not venue.strip():
            raise ValueError(f"FPN venue mapping {field_name} must contain non-empty text pairs")
        result[key] = venue.strip()
    return result


def _normalized_team_key(value: str) -> str | None:
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _clean_location(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.casefold() in {"none", "null"}:
        return None
    try:
        UUID(normalized)
    except ValueError:
        return normalized
    return None
