"""HTTP client for the current public ANNP polo calendars."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from waterpolo.models.benjamins_schedule import BenjaminsScheduleEntry
from waterpolo.scraper.annp.benjamins import parse_benjamins_schedule
from waterpolo.scraper.annp.domain import (
    DEFAULT_BASE_URL,
    annp_public_path,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import (
    ANNPCompetitionNotFoundError,
    ANNPHTTPError,
    ANNPResponseError,
)
from waterpolo.scraper.annp.models import ANNPCompetition, ANNPGame
from waterpolo.scraper.annp.scraper import (
    filter_team_games,
    parse_current_calendar,
    parse_current_competitions,
)

DEFAULT_TIMEOUT = 20.0


class ANNPClient:
    """Fetch competition metadata and complete calendar HTML with one connection pool."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _request_html(self, path: str) -> str:
        try:
            response = self._client.get(path)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ANNPHTTPError(
                f"ANNP returned HTTP {exc.response.status_code} for GET {exc.request.url}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ANNPHTTPError(f"ANNP request failed for GET {path}: {exc}") from exc

        content_type = response.headers.get("content-type", "").casefold()
        if content_type and "html" not in content_type:
            raise ANNPResponseError(
                f"ANNP returned unexpected content type {content_type!r} "
                f"for GET {response.request.url}"
            )
        return response.text

    def get_competitions(self, season: str) -> list[ANNPCompetition]:
        path = f"{annp_public_path(season)}calendario"
        return parse_current_competitions(self._request_html(path), season=season)

    def resolve_competition(
        self,
        season: str,
        *,
        category: str | None = None,
        competition_id: str | None = None,
    ) -> ANNPCompetition:
        if bool(category) == bool(competition_id):
            raise ValueError("provide exactly one of category or competition_id")
        return self._resolve_from_competitions(
            self.get_competitions(season),
            category=category,
            competition_id=competition_id,
        )

    @staticmethod
    def _resolve_from_competitions(
        competitions: list[ANNPCompetition],
        *,
        category: str | None,
        competition_id: str | None,
    ) -> ANNPCompetition:
        if competition_id:
            matches = [item for item in competitions if item.id == competition_id.strip()]
        else:
            requested = " ".join((category or "").casefold().split())
            matches = [
                item
                for item in competitions
                if " ".join(item.category.casefold().split()) == requested
            ]
        if not matches:
            available = ", ".join(f"{item.id}={item.name}" for item in competitions)
            raise ANNPCompetitionNotFoundError(
                f"ANNP competition not found: {competition_id or category!r}; "
                f"available: {available}"
            )
        if len(matches) != 1:
            raise ANNPCompetitionNotFoundError(
                f"ANNP competition selector is ambiguous: {category!r}"
            )
        return matches[0]

    def get_games(self, season: str, competition: ANNPCompetition) -> list[ANNPGame]:
        logical_season = normalize_annp_season(season)
        path = f"{annp_public_path(logical_season)}calendario/{competition.id}"
        source_url = f"{str(self._client.base_url).rstrip('/')}{path}"
        return parse_current_calendar(
            self._request_html(path),
            season=logical_season,
            competition=competition,
            source_url=source_url,
        )

    def get_team_games(
        self,
        *,
        season: str,
        team: str,
        category: str | None = None,
        competition_id: str | None = None,
    ) -> tuple[ANNPCompetition, list[ANNPGame]]:
        competition = self.resolve_competition(
            season, category=category, competition_id=competition_id
        )
        games = self.get_games(season, competition)
        if not games:
            raise ANNPResponseError(
                f"ANNP returned an empty calendar for competition {competition.id}"
            )
        return competition, filter_team_games(games, team)

    def discover_team_competitions(
        self, season: str, team: str
    ) -> list[tuple[ANNPCompetition, list[ANNPGame]]]:
        found: list[tuple[ANNPCompetition, list[ANNPGame]]] = []
        for competition in self.get_competitions(season):
            games = self.get_games(season, competition)
            team_games = filter_team_games(games, team)
            if team_games:
                found.append((competition, team_games))
        return found

    def get_benjamins_schedule(
        self, season: str, *, competition_id: str
    ) -> list[BenjaminsScheduleEntry]:
        """Resolve the current competition, then read its action cards."""
        if competition_id != "7":
            raise ValueError("ANNP schedule is supported only for competition 7")
        competition = self.resolve_competition(season, competition_id=competition_id)
        path = f"{annp_public_path(season)}calendario/{competition.id}"
        return parse_benjamins_schedule(
            self._request_html(path), season=season, competition=competition
        )
