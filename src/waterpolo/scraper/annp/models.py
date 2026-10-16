"""Source-specific models for the ANNP HTML endpoints."""

from datetime import date
from datetime import time as dt_time

from pydantic import BaseModel, ConfigDict


class ANNPCompetition(BaseModel):
    """A competition advertised by ``competicoes.php``."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str
    has_games: bool = True


class ANNPGame(BaseModel):
    """A game parsed from one ``calendario.php`` match card."""

    model_config = ConfigDict(frozen=True)

    id: str
    competition_id: str
    competition_name: str
    competition_category: str
    date: date
    time: dt_time | None
    home_team_name: str
    away_team_name: str
    home_score: int | None = None
    away_score: int | None = None
    location: str | None = None
    state: str | None = None
    source_url: str
