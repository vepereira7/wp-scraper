"""Normalized models for the FPN ArenaDisplay API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FPNCompetition(BaseModel):
    """An ArenaDisplay competition resolved from its public domain."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    domain: str


class FPNTeamIdentity(BaseModel):
    """A team identity observed in an ArenaDisplay game."""

    model_config = ConfigDict(frozen=True)

    id: str | None = None
    name: str | None = None
    display_name: str | None = None


class FPNGame(BaseModel):
    """A source-specific game normalized from ArenaDisplay."""

    model_config = ConfigDict(frozen=True)

    id: str
    competition_id: str
    competition_name: str
    game_number: int | str | None = None
    journey: int | str | None = None
    round: int | str | None = None
    game_date: datetime | None = None

    home_team_id: str | None = None
    home_team_name: str | None = None
    home_team_display_name: str | None = None
    home_score: int | None = None

    away_team_id: str | None = None
    away_team_name: str | None = None
    away_team_display_name: str | None = None
    away_score: int | None = None

    location: str | None = None
    state: str | None = None
