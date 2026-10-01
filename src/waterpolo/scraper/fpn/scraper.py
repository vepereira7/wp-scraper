"""Pure parsing and team-filtering logic for FPN ArenaDisplay data."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from waterpolo.models import Match, MatchCategory, MatchSource, MatchStatus
from waterpolo.scraper.fpn.errors import FPNGameStructureError, FPNResponseError
from waterpolo.scraper.fpn.models import FPNCompetition, FPNGame, FPNTeamIdentity

HOME_TEAM_INDEX = 1
AWAY_TEAM_INDEX = 2
FOCA_NAMES = frozenset({"foca"})


def scores_and_status(
    game: FPNGame, *, now: datetime
) -> tuple[int | None, int | None, MatchStatus]:
    """Resolve result scores and status from gameTeams and gameDate."""
    complete_scores = game.home_score is not None and game.away_score is not None
    if not complete_scores:
        return None, None, MatchStatus.SCHEDULED

    home_score = game.home_score
    away_score = game.away_score
    if home_score != 0 or away_score != 0:
        return home_score, away_score, MatchStatus.COMPLETED

    if game.game_date is None:
        return None, None, MatchStatus.SCHEDULED

    if game.game_date.tzinfo is None or game.game_date.utcoffset() is None:
        # ArenaDisplay returns local wall time without an offset. Compare it with
        # local wall time too, keeping both values naive and deterministic in tests.
        comparison_now = (
            now.astimezone().replace(tzinfo=None)
            if now.tzinfo is not None and now.utcoffset() is not None
            else now
        )
        is_future = game.game_date > comparison_now
    else:
        comparison_now = now.astimezone(game.game_date.tzinfo)
        is_future = game.game_date > comparison_now

    if is_future:
        return None, None, MatchStatus.SCHEDULED
    return 0, 0, MatchStatus.COMPLETED


def to_matches(
    games: Sequence[FPNGame], *, season: str, now: datetime | None = None
) -> list[Match]:
    """Convert FPN games to source-independent matches."""
    current_time = now or datetime.now().astimezone()
    matches: list[Match] = []
    for game in games:
        if game.game_date is None:
            raise FPNResponseError(f"Game {game.id} has no date")
        if not game.home_team_name or not game.away_team_name:
            raise FPNResponseError(f"Game {game.id} is missing a team name")

        score_home, score_away, status = scores_and_status(game, now=current_time)
        category = map_fpn_category(game.competition_category, game.competition_name)
        matches.append(
            Match(
                external_id=game.id,
                source=MatchSource.FPN,
                season=season,
                category=category,
                competition=game.competition_name,
                home=game.home_team_name,
                away=game.away_team_name,
                date=game.game_date.date(),
                time=game.game_date.time(),
                location=game.location,
                score_home=score_home,
                score_away=score_away,
                status=status,
            )
        )
    return matches


def map_fpn_category(
    raw_category: str | None, competition_display_name: str | None
) -> MatchCategory:
    """Map ArenaDisplay category and competition title to a normalized category."""
    raw = (raw_category or "").strip().casefold()
    if raw == "senior":
        return MatchCategory.SENIOR
    if raw == "junior":
        return MatchCategory.JUNIOR

    display = unicodedata.normalize("NFKD", competition_display_name or "")
    display = "".join(char for char in display if not unicodedata.combining(char))
    display = re.sub(r"\s+", " ", display).strip().casefold()
    category_matches = []
    for pattern, category in (
        (r"\binfant(?:il|is)\b", MatchCategory.INFANTIS),
        (r"\bjuven(?:il|is)\b", MatchCategory.JUVENIS),
        (r"\bjunior(?:es)?\b", MatchCategory.JUNIOR),
    ):
        if re.search(pattern, display):
            category_matches.append(category)
    if len(category_matches) != 1:
        return MatchCategory.UNKNOWN
    return category_matches[0]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any, field_name: str) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise FPNResponseError(f"Invalid {field_name}: {value!r}") from exc


def _parse_score(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise FPNGameStructureError(f"Invalid boolean score: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise FPNGameStructureError(f"Invalid score: {value!r}") from exc


def parse_competition(payload: Any, domain: str) -> FPNCompetition:
    """Parse a GetByDomain response into a competition."""
    if not isinstance(payload, Mapping):
        raise FPNResponseError("Competition response must be a JSON object")

    entity = payload.get("entity")
    if not isinstance(entity, Mapping):
        raise FPNResponseError("Competition response is missing an object entity")

    competition_id = _text(entity.get("id"))
    if competition_id is None:
        raise FPNResponseError("Competition response is missing entity.id")

    competition_name = _text(entity.get("displayName")) or _text(entity.get("name"))
    if competition_name is None:
        raise FPNResponseError("Competition response is missing entity.displayName")

    return FPNCompetition(
        id=competition_id,
        name=competition_name,
        domain=domain,
        category=_text(entity.get("category")),
    )


def _parse_team(team_data: Any) -> FPNTeamIdentity:
    if team_data is None:
        return FPNTeamIdentity()
    if not isinstance(team_data, Mapping):
        raise FPNGameStructureError("Each gameTeams item must be a JSON object")

    nested_team = team_data.get("team")
    if nested_team is None:
        nested_team = {}
    if not isinstance(nested_team, Mapping):
        raise FPNGameStructureError("gameTeams.team must be an object or null")

    return FPNTeamIdentity(
        id=_text(team_data.get("teamId")) or _text(nested_team.get("id")),
        name=_text(nested_team.get("name")),
        display_name=_text(nested_team.get("displayName")),
    )


def _teams_by_side(game: Mapping[str, Any]) -> dict[int, tuple[FPNTeamIdentity, int | None]]:
    raw_teams = game.get("gameTeams")
    if raw_teams is None:
        return {}
    if not isinstance(raw_teams, Sequence) or isinstance(raw_teams, (str, bytes)):
        raise FPNGameStructureError("gameTeams must be an array or null")

    teams: dict[int, tuple[FPNTeamIdentity, int | None]] = {}
    for raw_team in raw_teams:
        if not isinstance(raw_team, Mapping):
            raise FPNGameStructureError("Each gameTeams item must be a JSON object")

        raw_index = raw_team.get("teamIndex")
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise FPNGameStructureError(
                f"Invalid or missing gameTeams.teamIndex: {raw_index!r}"
            ) from exc

        if index not in {HOME_TEAM_INDEX, AWAY_TEAM_INDEX}:
            raise FPNGameStructureError(f"Unexpected gameTeams.teamIndex: {index}")
        if index in teams:
            raise FPNGameStructureError(f"Duplicate gameTeams.teamIndex: {index}")

        teams[index] = (_parse_team(raw_team), _parse_score(raw_team.get("score")))

    return teams


def _location_name(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return _text(value)
    if not isinstance(value, Mapping):
        raise FPNResponseError("Game location must be an object, string, or null")
    return (
        _text(value.get("name"))
        or _text(value.get("displayName"))
        or _text(value.get("description"))
    )


def parse_game(
    payload: Any,
    *,
    competition_id: str,
    competition_name: str,
    competition_category: str | None = None,
) -> FPNGame:
    """Normalize one ArenaDisplay game without relying on array order."""
    if not isinstance(payload, Mapping):
        raise FPNResponseError("Each game must be a JSON object")

    game_id = _text(payload.get("id"))
    if game_id is None:
        raise FPNResponseError("Game response is missing id")

    teams = _teams_by_side(payload)
    empty_team = (FPNTeamIdentity(), None)
    home, home_score = teams.get(HOME_TEAM_INDEX, empty_team)
    away, away_score = teams.get(AWAY_TEAM_INDEX, empty_team)

    home_name = home.name or home.display_name or _text(payload.get("homeTeamPlaceholder"))
    away_name = away.name or away.display_name or _text(payload.get("awayTeamPlaceholder"))

    try:
        return FPNGame(
            id=game_id,
            competition_id=competition_id,
            competition_name=competition_name,
            competition_category=competition_category,
            game_number=payload.get("gameNumber"),
            journey=payload.get("journey"),
            round=payload.get("round"),
            game_date=_parse_datetime(payload.get("gameDate"), "gameDate"),
            home_team_id=home.id,
            home_team_name=home_name,
            home_team_display_name=home.display_name,
            home_score=home_score,
            away_team_id=away.id,
            away_team_name=away_name,
            away_team_display_name=away.display_name,
            away_score=away_score,
            location=_location_name(payload.get("location")),
            state=_text(payload.get("state")),
        )
    except ValidationError as exc:
        raise FPNResponseError(f"Invalid game {game_id}: {exc}") from exc


def parse_games(
    payload: Any,
    *,
    competition_id: str,
    competition_name: str,
    competition_category: str | None = None,
) -> list[FPNGame]:
    """Parse a GetFiltered response into normalized games."""
    if not isinstance(payload, Mapping):
        raise FPNResponseError("Games response must be a JSON object")
    if "entity" not in payload:
        raise FPNResponseError("Games response is missing entity")

    entities = payload["entity"]
    if not isinstance(entities, list):
        raise FPNResponseError("Games response entity must be an array")

    return [
        parse_game(
            game,
            competition_id=competition_id,
            competition_name=competition_name,
            competition_category=competition_category,
        )
        for game in entities
    ]


def _normalized_team_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def is_foca_team(
    *,
    team_id: str | None,
    name: str | None,
    display_name: str | None,
    known_team_ids: set[str] | frozenset[str] = frozenset(),
) -> bool:
    """Identify FOCA by a discovered ID, with exact normalized-name fallback."""
    if team_id is not None and team_id in known_team_ids:
        return True
    return any(
        candidate in FOCA_NAMES
        for candidate in (
            _normalized_team_name(name),
            _normalized_team_name(display_name),
        )
        if candidate is not None
    )


def _game_identities(game: FPNGame) -> tuple[FPNTeamIdentity, FPNTeamIdentity]:
    return (
        FPNTeamIdentity(
            id=game.home_team_id,
            name=game.home_team_name,
            display_name=game.home_team_display_name,
        ),
        FPNTeamIdentity(
            id=game.away_team_id,
            name=game.away_team_name,
            display_name=game.away_team_display_name,
        ),
    )


def find_team_identities(games: Sequence[FPNGame], team: str) -> list[FPNTeamIdentity]:
    """Discover all API identities matching a requested team name or ID."""
    requested = _normalized_team_name(team)
    identities: dict[tuple[str | None, str | None, str | None], FPNTeamIdentity] = {}

    for game in games:
        for identity in _game_identities(game):
            names = {
                _normalized_team_name(identity.name),
                _normalized_team_name(identity.display_name),
            }
            if identity.id == team or requested in names:
                key = (identity.id, identity.name, identity.display_name)
                identities[key] = identity

    return list(identities.values())


def filter_team_games(games: Sequence[FPNGame], team: str) -> list[FPNGame]:
    """Return only games involving a dynamically discovered team identity."""
    identities = find_team_identities(games, team)
    known_ids = frozenset(identity.id for identity in identities if identity.id)
    requested = _normalized_team_name(team)
    is_foca_request = requested in FOCA_NAMES

    def identity_matches(identity: FPNTeamIdentity) -> bool:
        if is_foca_request:
            return is_foca_team(
                team_id=identity.id,
                name=identity.name,
                display_name=identity.display_name,
                known_team_ids=known_ids,
            )
        if identity.id is not None and identity.id in known_ids:
            return True
        return requested in {
            _normalized_team_name(identity.name),
            _normalized_team_name(identity.display_name),
        }

    return [
        game
        for game in games
        if any(identity_matches(identity) for identity in _game_identities(game))
    ]
