"""ANNP Benjamins actions, separate from the two-team Match domain."""

from __future__ import annotations

from datetime import date
from datetime import time as dt_time
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class BenjaminsScheduleEntry(BaseModel):
    """One published action; participants and scores are intentionally absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str
    source: Literal["ANNP"] = "ANNP"
    season: str
    competition_id: Literal["7"] = "7"
    competition_name: str
    date: date
    time: dt_time | None = None
    venue: str | None = None

    @field_validator("external_id", "season", "competition_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value
