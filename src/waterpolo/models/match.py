"""Normalized water polo match model."""

from __future__ import annotations

from datetime import date
from datetime import time as dt_time
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator

from waterpolo.models.category import MatchCategory, normalize_category


class MatchSource(str, Enum):
    """Supported match data sources."""

    FPN = "FPN"
    ANNP = "ANNP"


class MatchStatus(str, Enum):
    """Known match lifecycle states."""

    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class Match(BaseModel):
    """A match normalized independently of its source website."""

    external_id: str
    source: MatchSource
    source_url: str | None = None

    season: str
    category: MatchCategory
    competition: str

    home: str
    away: str

    date: date
    time: dt_time | None = None
    location: str | None = None

    score_home: int | None = None
    score_away: int | None = None

    status: MatchStatus = MatchStatus.SCHEDULED

    raw: dict[str, Any] | None = None

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value: Any) -> Any:
        """Canonicalize known aliases while retaining rejection of unknown strings."""
        if isinstance(value, MatchCategory):
            return value
        normalized = normalize_category(value) if isinstance(value, str) else value
        if normalized is not MatchCategory.UNKNOWN:
            return normalized
        if isinstance(value, str) and value.strip().casefold() == "unknown":
            return MatchCategory.UNKNOWN
        return value

    @field_validator(
        "external_id",
        "season",
        "competition",
        "home",
        "away",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Reject empty required text and remove incidental outer whitespace."""
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("score_home", "score_away")
    @classmethod
    def validate_score(cls, value: int | None) -> int | None:
        """Reject negative scores while allowing an unplayed match."""
        if value is not None and value < 0:
            raise ValueError("score must not be negative")
        return value

    @model_validator(mode="after")
    def validate_score_pair(self) -> Self:
        """Require both score values to be present or absent together."""
        if (self.score_home is None) != (self.score_away is None):
            raise ValueError("score_home and score_away must both be set or both be None")
        return self
