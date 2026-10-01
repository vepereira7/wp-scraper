"""Public API for the FPN ArenaDisplay integration."""

from waterpolo.scraper.fpn.client import FPNArenaClient
from waterpolo.scraper.fpn.errors import (
    FPNArenaError,
    FPNArenaHTTPError,
    FPNCompetitionNotFoundError,
    FPNGameStructureError,
    FPNResponseError,
)
from waterpolo.scraper.fpn.models import FPNCompetition, FPNGame, FPNTeamIdentity
from waterpolo.scraper.fpn.scraper import is_foca_team

__all__ = [
    "FPNArenaClient",
    "FPNArenaError",
    "FPNArenaHTTPError",
    "FPNCompetition",
    "FPNCompetitionNotFoundError",
    "FPNGame",
    "FPNGameStructureError",
    "FPNResponseError",
    "FPNTeamIdentity",
    "is_foca_team",
]
