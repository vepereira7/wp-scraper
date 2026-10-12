"""Pure HTML parsing, filtering, and Match normalization for ANNP."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import date, time
from hashlib import sha256

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from waterpolo.models import Match, MatchCategory, MatchSource, MatchStatus
from waterpolo.scraper.annp.domain import (
    annp_season_bounds,
    annp_season_label,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import ANNPResponseError
from waterpolo.scraper.annp.models import ANNPCompetition, ANNPGame

_MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}
_EMPTY_CALENDAR_TEXT = "nao existem jogos definidos"
_EMPTY_LOCATION_VALUES = frozenset({"", "-", "--", "---", "----", "-----", "—"})


def _normalized_text(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def parse_competitions(html: str) -> list[ANNPCompetition]:
    """Parse competition IDs and real display names from the ANNP button fragment."""
    soup = BeautifulSoup(html, "lxml")
    competitions: list[ANNPCompetition] = []
    seen_ids: set[str] = set()
    for button in soup.select("button.btn-set2[value]"):
        competition_id = str(button.get("value", "")).strip()
        name = button.get_text(" ", strip=True)
        if not competition_id or not name:
            raise ANNPResponseError("ANNP competition button is missing value or name")
        if competition_id in seen_ids:
            raise ANNPResponseError(
                f"ANNP competition response contains duplicate ID {competition_id!r}"
            )
        seen_ids.add(competition_id)
        competitions.append(
            ANNPCompetition(
                id=competition_id,
                name=name,
                category=name,
                has_games=str(button.get("data-temjogos", "1")).strip() != "0",
            )
        )

    if not competitions:
        raise ANNPResponseError("ANNP competition response contains no competitions")
    return competitions


def parse_calendar(
    html: str,
    *,
    season: str,
    competition: ANNPCompetition,
    source_url: str,
) -> list[ANNPGame]:
    """Parse a complete ANNP calendar fragment into source-specific games."""
    normalized_season = normalize_annp_season(season)
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".match-card")
    if not cards:
        if _EMPTY_CALENDAR_TEXT in _normalized_text(soup.get_text(" ", strip=True)):
            return []
        raise ANNPResponseError("ANNP calendar response contains no match cards")

    occurrences: Counter[tuple[str, str]] = Counter()
    season_start, season_end = annp_season_bounds(normalized_season)
    games: list[ANNPGame] = []
    for card in cards:
        group = card.find_parent("div", class_="mb-10")
        date_heading = group.select_one("h3") if isinstance(group, Tag) else None
        if date_heading is None:
            raise ANNPResponseError("ANNP match card is missing its date heading")

        home, away = _parse_teams(card)
        occurrence_key = (_normalized_text(home), _normalized_text(away))
        occurrences[occurrence_key] += 1
        occurrence = occurrences[occurrence_key]
        game_id = _stable_game_id(
            normalized_season,
            competition.id,
            home,
            away,
            occurrence,
        )
        score_home, score_away = _parse_score(card)
        state_node = card.select_one(".match-status")
        state = state_node.get_text(" ", strip=True) if state_node else None
        status = map_annp_state(state)
        if status in {MatchStatus.CANCELLED, MatchStatus.POSTPONED}:
            score_home = score_away = None

        game_date = _parse_date(date_heading.get_text(" ", strip=True))
        if not season_start <= game_date <= season_end:
            raise ANNPResponseError(
                f"ANNP returned date {game_date.isoformat()} outside requested season "
                f"{normalized_season} ({season_start.isoformat()} to {season_end.isoformat()})"
            )

        try:
            games.append(
                ANNPGame(
                    id=game_id,
                    competition_id=competition.id,
                    competition_name=competition.name,
                    competition_category=competition.category,
                    date=game_date,
                    time=_parse_time(card),
                    home_team_name=home,
                    away_team_name=away,
                    home_score=score_home,
                    away_score=score_away,
                    location=_parse_location(card),
                    state=state,
                    source_url=source_url,
                )
            )
        except ValidationError as exc:
            raise ANNPResponseError(f"Invalid ANNP game {game_id}: {exc}") from exc
    return games


def _parse_teams(card: Tag) -> tuple[str, str]:
    teams = [
        node.get_text(" ", strip=True)
        for node in card.select(".teams .team .font-semibold")
    ]
    if len(teams) != 2 or not all(teams):
        raise ANNPResponseError("ANNP match card must contain exactly two team names")
    return teams[0], teams[1]


def _parse_score(card: Tag) -> tuple[int | None, int | None]:
    score_node = card.select_one(".teams .score")
    if score_node is None:
        raise ANNPResponseError("ANNP match card is missing its score")
    score = score_node.get_text(" ", strip=True)
    match = re.fullmatch(r"(\d*)\s*:\s*(\d*)", score)
    if match is None:
        raise ANNPResponseError(f"Invalid ANNP score {score!r}")
    home, away = match.groups()
    if not home and not away:
        return None, None
    if not home or not away:
        raise ANNPResponseError(f"Incomplete ANNP score {score!r}")
    return int(home), int(away)


def _parse_date(value: str) -> date:
    normalized = _normalized_text(value)
    match = re.fullmatch(r"(\d{1,2}) ([a-z]{3}) (\d{4})", normalized)
    if match is None or match.group(2) not in _MONTHS:
        raise ANNPResponseError(f"Invalid ANNP date {value!r}")
    try:
        return date(int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)))
    except ValueError as exc:
        raise ANNPResponseError(f"Invalid ANNP date {value!r}") from exc


def _parse_time(card: Tag) -> time:
    header = card.select_one(".match-header")
    value = header.get_text(" ", strip=True) if header else ""
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", value)
    if match is None:
        raise ANNPResponseError("ANNP match card is missing a valid time")
    try:
        return time(int(match.group(1)), int(match.group(2)))
    except ValueError as exc:
        raise ANNPResponseError(f"Invalid ANNP time {match.group(0)!r}") from exc


def _parse_location(card: Tag) -> str | None:
    node = card.select_one(".match-header .local-info span")
    if node is None:
        raise ANNPResponseError("ANNP match card is missing its location")
    location = " ".join(node.get_text(" ", strip=True).split())
    return None if location in _EMPTY_LOCATION_VALUES else location


def _stable_game_id(
    season: str,
    competition_id: str,
    home: str,
    away: str,
    occurrence: int,
) -> str:
    """Derive identity only from fields invariant under schedule/result updates.

    ANNP does not expose its database game ID in the public HTML. The ordinal
    disambiguates repeated fixtures with the same home and away teams without
    incorporating mutable date, time, location, score, or state fields.
    """
    identity = ":".join(
        (
            season,
            competition_id,
            _normalized_text(home),
            _normalized_text(away),
            str(occurrence),
        )
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{season}-{competition_id}-{digest}"


def map_annp_state(state: str | None) -> MatchStatus:
    """Map ANNP Portuguese lifecycle labels to the shared status enum."""
    normalized = _normalized_text(state)
    if normalized in {"nao iniciado", "agendado", "por realizar"}:
        return MatchStatus.SCHEDULED
    if normalized in {"finalizado", "terminado", "concluido"}:
        return MatchStatus.COMPLETED
    if normalized in {"adiado", "postponed"}:
        return MatchStatus.POSTPONED
    if normalized in {"cancelado", "anulado", "cancelled"}:
        return MatchStatus.CANCELLED
    return MatchStatus.UNKNOWN


def map_annp_category(value: str) -> MatchCategory:
    """Map real ANNP competition labels to the existing normalized categories."""
    normalized = _normalized_text(value)
    patterns = (
        (r"\bsenior(?:es)?\b", MatchCategory.SENIOR),
        (r"\bjunior(?:es)?\b", MatchCategory.JUNIOR),
        (r"\bjuven(?:il|is)\b", MatchCategory.JUVENIS),
        (r"\binfant(?:il|is)\b", MatchCategory.INFANTIS),
        (r"\b(?:sub|u)[ -]?18\b", MatchCategory.U18),
        (r"\b(?:sub|u)[ -]?16\b", MatchCategory.U16),
        (r"\b(?:sub|u)[ -]?14\b", MatchCategory.U14),
        (r"\b(?:sub|u)[ -]?12\b", MatchCategory.U12),
    )
    matches = [category for pattern, category in patterns if re.search(pattern, normalized)]
    return matches[0] if len(matches) == 1 else MatchCategory.UNKNOWN


def filter_team_games(games: Sequence[ANNPGame], team: str) -> list[ANNPGame]:
    """Return games whose exact normalized home or away name matches ``team``."""
    requested = _normalized_text(team)
    if not requested:
        raise ValueError("team must not be empty")
    return [
        game
        for game in games
        if requested
        in {
            _normalized_text(game.home_team_name),
            _normalized_text(game.away_team_name),
        }
    ]


def to_matches(games: Sequence[ANNPGame], *, season: str) -> list[Match]:
    """Convert ANNP games to the same source-independent Match used by FPN."""
    normalized_season = annp_season_label(season)
    return [
        Match(
            external_id=game.id,
            source=MatchSource.ANNP,
            source_url=game.source_url,
            season=normalized_season,
            category=map_annp_category(game.competition_category),
            competition=game.competition_name,
            home=game.home_team_name,
            away=game.away_team_name,
            date=game.date,
            # ANNP uses 00:00 as a placeholder for a time that has not yet
            # been scheduled. Keep this source-specific semantic out of the
            # shared model and exporters.
            time=None if game.time == time.min else game.time,
            location=game.location,
            score_home=game.home_score,
            score_away=game.away_score,
            status=map_annp_state(game.state),
        )
        for game in games
    ]
