"""Reusable HTTP client for the public ANNP polo HTML endpoints."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self
from urllib.parse import urlencode

import httpx

from waterpolo.scraper.annp.domain import (
    DEFAULT_BASE_URL,
    annp_polo_path,
    annp_source_seasons,
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
    parse_calendar,
    parse_competitions,
)

DEFAULT_TIMEOUT = 20.0


class ANNPClient:
    """Fetch ANNP competitions and calendar fragments with one connection pool."""

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
        self._competition_sources: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        """Close the internally managed HTTP connection pool."""
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

    def _request_html(self, path: str, **kwargs: Any) -> str:
        try:
            response = self._client.get(path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ANNPHTTPError(
                f"ANNP returned HTTP {exc.response.status_code} for GET {exc.request.url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ANNPHTTPError(f"ANNP request failed for GET {path}: {exc}") from exc

        content_type = response.headers.get("content-type", "").casefold()
        if content_type and "html" not in content_type:
            raise ANNPResponseError(
                f"ANNP returned unexpected content type {content_type!r} for GET {response.request.url}"
            )
        return response.text

    def get_competitions(self, season: str) -> list[ANNPCompetition]:
        """Fetch competition metadata from the first usable physical source."""
        logical_season = normalize_annp_season(season)
        failures: list[Exception] = []
        for source_season in annp_source_seasons(logical_season):
            try:
                return self._get_competitions_from_source(
                    logical_season=logical_season,
                    source_season=source_season,
                )
            except (ANNPHTTPError, ANNPResponseError) as exc:
                failures.append(exc)
        self._raise_source_failures(logical_season, failures)

    def resolve_competition(
        self,
        season: str,
        *,
        category: str | None = None,
        competition_id: str | None = None,
    ) -> ANNPCompetition:
        """Resolve exactly one competition by stable ID or real display label."""
        if bool(category) == bool(competition_id):
            raise ValueError("provide exactly one of category or competition_id")

        logical_season = normalize_annp_season(season)
        competitions = self.get_competitions(logical_season)
        return self._resolve_from_competitions(
            competitions,
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
            requested_id = competition_id.strip()
            matches = [item for item in competitions if item.id == requested_id]
        else:
            requested_category = " ".join((category or "").casefold().split())
            matches = [
                item
                for item in competitions
                if " ".join(item.category.casefold().split()) == requested_category
            ]
        if not matches:
            selector = competition_id or category
            available = ", ".join(f"{item.id}={item.name}" for item in competitions)
            raise ANNPCompetitionNotFoundError(
                f"ANNP competition not found: {selector!r}; available: {available}"
            )
        if len(matches) > 1:
            raise ANNPCompetitionNotFoundError(
                f"ANNP competition selector is ambiguous: {category!r}"
            )
        return matches[0]

    def get_games(
        self,
        season: str,
        competition: ANNPCompetition,
        *,
        source_season: str | None = None,
    ) -> list[ANNPGame]:
        """Fetch games using a physical source independently of logical season."""
        logical_season = normalize_annp_season(season)
        resolved_source_season = source_season or self._competition_sources.get(
            (logical_season, competition.id), logical_season
        )
        return self._get_games_from_source(
            logical_season=logical_season,
            source_season=resolved_source_season,
            competition=competition,
        )

    def _get_games_from_source(
        self,
        *,
        logical_season: str,
        source_season: str,
        competition: ANNPCompetition,
    ) -> list[ANNPGame]:
        path = f"{annp_polo_path(source_season)}calendario.php"
        params = {
            "competicao": competition.id,
            "temjogos": "1" if competition.has_games else "0",
        }
        source_url = f"{str(self._client.base_url).rstrip('/')}{path}?{urlencode(params)}"
        html = self._request_html(path, params=params)
        return parse_calendar(
            html,
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
        """Resolve one competition and return only games involving ``team``."""
        logical_season = normalize_annp_season(season)
        failures: list[Exception] = []
        for source_season in annp_source_seasons(logical_season):
            try:
                competitions = self._get_competitions_from_source(
                    logical_season=logical_season,
                    source_season=source_season,
                )
                competition = self._resolve_from_competitions(
                    competitions,
                    category=category,
                    competition_id=competition_id,
                )
                games = self._get_games_from_source(
                    logical_season=logical_season,
                    source_season=source_season,
                    competition=competition,
                )
                if competition.has_games and not games:
                    raise ANNPResponseError(
                        f"ANNP source provas{source_season} returned an empty calendar "
                        f"for competition {competition.id}"
                    )
                return competition, filter_team_games(games, team)
            except (
                ANNPCompetitionNotFoundError,
                ANNPHTTPError,
                ANNPResponseError,
            ) as exc:
                failures.append(exc)
        self._raise_source_failures(logical_season, failures)

    def discover_team_competitions(
        self, season: str, team: str
    ) -> list[tuple[ANNPCompetition, list[ANNPGame]]]:
        """Return every advertised competition containing at least one team game."""
        logical_season = normalize_annp_season(season)
        failures: list[Exception] = []
        for source_season in annp_source_seasons(logical_season):
            try:
                found: list[tuple[ANNPCompetition, list[ANNPGame]]] = []
                competitions = self._get_competitions_from_source(
                    logical_season=logical_season,
                    source_season=source_season,
                )
                for competition in competitions:
                    games = self._get_games_from_source(
                        logical_season=logical_season,
                        source_season=source_season,
                        competition=competition,
                    )
                    if competition.has_games and not games:
                        raise ANNPResponseError(
                            f"ANNP source provas{source_season} returned an empty "
                            f"calendar for competition {competition.id}"
                        )
                    team_games = filter_team_games(games, team)
                    if team_games:
                        found.append((competition, team_games))
                return found
            except (ANNPHTTPError, ANNPResponseError) as exc:
                failures.append(exc)
        self._raise_source_failures(logical_season, failures)

    def _get_competitions_from_source(
        self,
        *,
        logical_season: str,
        source_season: str,
    ) -> list[ANNPCompetition]:
        path = f"{annp_polo_path(source_season)}competicoes.php"
        competitions = parse_competitions(
            self._request_html(path, params={"opcao": "1"})
        )
        for competition in competitions:
            self._competition_sources[(logical_season, competition.id)] = source_season
        return competitions

    @staticmethod
    def _raise_source_failures(
        logical_season: str, failures: list[Exception]
    ) -> None:
        if len(failures) == 1:
            raise failures[0]
        details = "; ".join(str(failure) for failure in failures)
        raise ANNPResponseError(
            f"No usable ANNP source for logical season {logical_season}: {details}"
        ) from failures[-1] if failures else None
