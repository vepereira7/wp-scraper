"""Reusable HTTP client for the public FPN ArenaDisplay API."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from waterpolo.scraper.fpn.errors import (
    FPNArenaHTTPError,
    FPNCompetitionNotFoundError,
    FPNResponseError,
)
from waterpolo.scraper.fpn.models import FPNCompetition, FPNGame, FPNTeamIdentity
from waterpolo.scraper.fpn.scraper import (
    filter_team_games,
    find_team_identities,
    parse_competition,
    parse_games,
)

DEFAULT_BASE_URL = "https://api-web.arenadisplay.live"
DEFAULT_TIMEOUT = 20.0


class FPNArenaClient:
    """Fetch and normalize FPN competitions and games from ArenaDisplay."""

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
            headers={"Accept": "application/json"},
        )
        self._competition_names: dict[str, str] = {}
        self._competition_categories: dict[str, str | None] = {}

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

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise FPNArenaHTTPError(
                f"ArenaDisplay returned HTTP {status} for {method} {exc.request.url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FPNArenaHTTPError(
                f"ArenaDisplay request failed for {method} {path}: {exc}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise FPNResponseError(
                f"ArenaDisplay returned invalid JSON for {method} {response.request.url}"
            ) from exc

    def get_competition(self, domain: str) -> FPNCompetition:
        """Resolve an ArenaDisplay domain to its competition identity."""
        normalized_domain = domain.strip()
        if not normalized_domain:
            raise ValueError("domain must not be empty")

        path = f"/api/competition/GetByDomain/{normalized_domain}"
        try:
            payload = self._request_json("GET", path)
        except FPNArenaHTTPError as exc:
            cause = exc.__cause__
            if isinstance(cause, httpx.HTTPStatusError):
                response = cause.response
                missing_domain = response.status_code == 404
                if response.status_code == 500:
                    try:
                        error_payload = response.json()
                    except ValueError:
                        error_payload = None
                    missing_domain = isinstance(error_payload, dict) and (
                        "object reference not set"
                        in str(error_payload.get("ErrorMessage", "")).casefold()
                    )
                if missing_domain:
                    raise FPNCompetitionNotFoundError(
                        f"Competition domain not found: {normalized_domain}"
                    ) from exc
            raise

        if isinstance(payload, dict) and payload.get("entity") is None:
            raise FPNCompetitionNotFoundError(
                f"Competition domain not found: {normalized_domain}"
            )

        competition = parse_competition(payload, normalized_domain)
        self._competition_names[competition.id] = competition.name
        self._competition_categories[competition.id] = competition.category
        return competition

    def get_games(
        self,
        competition_id: str,
        *,
        competition_name: str | None = None,
    ) -> list[FPNGame]:
        """Fetch all normalized games for a resolved competition."""
        normalized_id = competition_id.strip()
        if not normalized_id:
            raise ValueError("competition_id must not be empty")

        resolved_name = competition_name or self._competition_names.get(normalized_id)
        if resolved_name is None:
            raise ValueError(
                "competition_name is required when competition_id was not resolved "
                "by this client"
            )

        body = {
            "filterCollections": [
                {
                    "filterOperation": 0,
                    "filterExpression": 0,
                    "propertyName": "CompetitionId",
                    "value": normalized_id,
                }
            ],
            "orderCollection": [
                {"propertyName": "GameDate", "orderType": 0},
                {"propertyName": "GameNumber", "orderType": 0},
            ],
        }
        payload = self._request_json("POST", "/api/game/GetFiltered/", json=body)
        return parse_games(
            payload,
            competition_id=normalized_id,
            competition_name=resolved_name,
            competition_category=self._competition_categories.get(normalized_id),
        )

    def get_team_games(self, *, domain: str, team: str) -> list[FPNGame]:
        """Resolve a competition and return only games involving the given team."""
        competition = self.get_competition(domain)
        games = self.get_games(competition.id)
        return filter_team_games(games, team)

    def get_foca_games(self, domain: str) -> list[FPNGame]:
        """Return only FOCA games, discovering its ID from the API response."""
        return self.get_team_games(domain=domain, team="FOCA")

    @staticmethod
    def find_team_identities(
        games: list[FPNGame], team: str
    ) -> list[FPNTeamIdentity]:
        """Expose team identities discovered in normalized games."""
        return find_team_identities(games, team)
