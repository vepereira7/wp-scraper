"""Public API for the ANNP integration."""

from waterpolo.scraper.annp.client import ANNPClient
from waterpolo.scraper.annp.domain import (
    annp_polo_path,
    annp_season_bounds,
    annp_season_label,
    annp_source_seasons,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import (
    ANNPCompetitionNotFoundError,
    ANNPError,
    ANNPHTTPError,
    ANNPResponseError,
)
from waterpolo.scraper.annp.models import ANNPCompetition, ANNPGame
from waterpolo.scraper.annp.scraper import (
    filter_team_games,
    map_annp_category,
    map_annp_state,
    to_matches,
)

__all__ = [
    "ANNPClient",
    "ANNPCompetition",
    "ANNPCompetitionNotFoundError",
    "ANNPError",
    "ANNPGame",
    "ANNPHTTPError",
    "ANNPResponseError",
    "annp_polo_path",
    "annp_season_bounds",
    "annp_season_label",
    "annp_source_seasons",
    "filter_team_games",
    "map_annp_category",
    "map_annp_state",
    "normalize_annp_season",
    "to_matches",
]
