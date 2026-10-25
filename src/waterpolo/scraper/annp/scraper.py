"""Parse the current ANNP calendar HTML into the shared Match contract."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import date, time
from hashlib import sha256

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from waterpolo.models import (
    Match,
    MatchCategory,
    MatchSource,
    MatchStatus,
    normalize_category,
)
from waterpolo.scraper.annp.domain import (
    annp_public_path,
    annp_season_bounds,
    annp_season_label,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import ANNPResponseError
from waterpolo.scraper.annp.models import ANNPCompetition, ANNPGame

_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
_EMPTY_LOCATION_VALUES = frozenset({"", "-", "--", "---", "----", "-----", "—"})
_EMPTY_TEAM_VALUES = frozenset({"-", "--", "---", "----", "-----", "—"})
_EMPTY_TIME_VALUES = frozenset({"", "----"})
_EMPTY_CALENDAR_TEXTS = frozenset({
    "nao existem jogos definidos", "nao existem jogos", "sem jogos",
})
_COMPETITION_PATH = re.compile(r"^/polo/(\d{8})/calendario/(\d+)/?$")


def _normalized_text(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def parse_current_competitions(html: str, *, season: str) -> list[ANNPCompetition]:
    """Read all competition IDs and names advertised for the requested season."""
    soup = BeautifulSoup(html, "lxml")
    expected_years = annp_public_path(season).split("/")[2]
    navs = soup.select("nav.competicoes")
    if len(navs) != 1:
        raise ANNPResponseError("ANNP calendar must contain one competition navigation")

    competitions: list[ANNPCompetition] = []
    seen_ids: set[str] = set()
    links = navs[0].select("a.btn-competicao")
    if not links:
        raise ANNPResponseError("ANNP calendar contains no competitions")
    for link in links:
        path = _COMPETITION_PATH.fullmatch(str(link.get("href", "")).strip())
        name = link.get_text(" ", strip=True)
        if path is None or path.group(1) != expected_years or not name:
            raise ANNPResponseError("ANNP competition link has invalid season, ID or name")
        competition_id = path.group(2)
        if competition_id in seen_ids:
            raise ANNPResponseError(f"ANNP contains duplicate competition ID {competition_id}")
        seen_ids.add(competition_id)
        competitions.append(
            ANNPCompetition(id=competition_id, name=name, category=name)
        )
    return competitions


def _validate_selected_competition(
    soup: BeautifulSoup, season: str, competition: ANNPCompetition
) -> None:
    advertised = parse_current_competitions(str(soup), season=season)
    matches = [item for item in advertised if item.id == competition.id]
    if len(matches) != 1 or matches[0].name != competition.name:
        raise ANNPResponseError(
            f"ANNP calendar does not advertise competition {competition.id} "
            f"as {competition.name!r}"
        )
    active = soup.select("nav.competicoes a.btn-competicao.ativo")
    expected_href = f"{annp_public_path(season)}calendario/{competition.id}"
    if (
        len(active) != 1
        or active[0].get("href") != expected_href
        or active[0].get_text(" ", strip=True) != competition.name
    ):
        raise ANNPResponseError(
            f"ANNP calendar does not confirm selected competition {competition.id}"
        )
    title = soup.select_one("title")
    if title is not None and competition.name not in title.get_text(" ", strip=True):
        raise ANNPResponseError("ANNP calendar title disagrees with selected competition")


def parse_current_calendar(
    html: str,
    *,
    season: str,
    competition: ANNPCompetition,
    source_url: str,
) -> list[ANNPGame]:
    """Parse every card after confirming the page belongs to the selected ID."""
    logical_season = normalize_annp_season(season)
    soup = BeautifulSoup(html, "lxml")
    _validate_selected_competition(soup, logical_season, competition)
    sections = soup.select("section.seccao-calendario")
    if len(sections) != 1:
        raise ANNPResponseError("ANNP calendar must contain one calendar section")
    section = sections[0]
    days = section.select(".dia")
    if not days:
        page_text = _normalized_text(section.get_text(" ", strip=True))
        if any(marker in page_text for marker in _EMPTY_CALENDAR_TEXTS):
            return []
        raise ANNPResponseError("ANNP calendar contains no match cards")

    occurrences: Counter[tuple[str, str]] = Counter()
    season_start, season_end = annp_season_bounds(logical_season)
    games: list[ANNPGame] = []
    for day in days:
        date_nodes = day.select(":scope > .dia-titulo")
        containers = day.select(":scope > .cartoes")
        if len(date_nodes) != 1 or len(containers) != 1:
            raise ANNPResponseError("ANNP calendar day has an unexpected structure")
        cards = containers[0].select(":scope > article.cartao")
        if not cards:
            raise ANNPResponseError("ANNP calendar day contains no match cards")
        game_date = _parse_date(date_nodes[0].get_text(" ", strip=True))
        if not season_start <= game_date <= season_end:
            raise ANNPResponseError(
                f"ANNP returned date {game_date.isoformat()} outside requested "
                f"season {logical_season}"
            )
        for card in cards:
            home, away = _parse_teams(card)
            key = (_normalized_text(home), _normalized_text(away))
            occurrences[key] += 1
            game_id = _stable_game_id(
                logical_season, competition.id, home, away, occurrences[key]
            )
            state = _one_text(card, ":scope > .estado", "state")
            status = map_annp_state(state)
            scores = _parse_score(_one_text(card, ".equipas > .resultado", "result"))
            if status is MatchStatus.COMPLETED and scores[0] is None:
                raise ANNPResponseError(f"Completed ANNP game {game_id} has no result")
            if status is MatchStatus.SCHEDULED and scores[0] is not None:
                raise ANNPResponseError(f"Scheduled ANNP game {game_id} has a result")
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
                        home_score=scores[0],
                        away_score=scores[1],
                        location=_parse_location(card),
                        state=state,
                        source_url=source_url,
                    )
                )
            except ValidationError as exc:
                raise ANNPResponseError(f"Invalid ANNP game {game_id}: {exc}") from exc
    if len(section.select("article")) != len(games):
        raise ANNPResponseError(
            "ANNP calendar contains an article outside a valid day card group"
        )
    return games


def _one_text(card: Tag, selector: str, label: str) -> str:
    nodes = card.select(selector)
    if len(nodes) != 1:
        raise ANNPResponseError(f"ANNP match card must contain exactly one {label}")
    value = nodes[0].get_text(" ", strip=True)
    if not value:
        raise ANNPResponseError(f"ANNP match card contains an empty {label}")
    return value


def _parse_teams(card: Tag) -> tuple[str, str]:
    nodes = card.select(".equipas > .equipa")
    if len(nodes) != 2:
        raise ANNPResponseError("ANNP match card must contain exactly two teams")
    teams = (
        _one_text(nodes[0], ":scope > span", "home team"),
        _one_text(nodes[1], ":scope > span", "away team"),
    )
    if any(team in _EMPTY_TEAM_VALUES for team in teams):
        raise ANNPResponseError("ANNP match card contains a placeholder team")
    return teams


def _parse_score(value: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d*)\s*:\s*(\d*)", value)
    if match is None:
        raise ANNPResponseError(f"Invalid ANNP score {value!r}")
    home, away = match.groups()
    if not home and not away:
        return None, None
    if not home or not away:
        raise ANNPResponseError(f"Incomplete ANNP score {value!r}")
    return int(home), int(away)


def _parse_date(value: str) -> date:
    match = re.fullmatch(r"(\d{1,2}) ([a-z]{3}) (\d{4})", _normalized_text(value))
    if match is None or match.group(2) not in _MONTHS:
        raise ANNPResponseError(f"Invalid ANNP date {value!r}")
    try:
        return date(int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)))
    except ValueError as exc:
        raise ANNPResponseError(f"Invalid ANNP date {value!r}") from exc


def _header(card: Tag) -> Tag:
    headers = card.select(":scope > .cartao-topo")
    if len(headers) != 1:
        raise ANNPResponseError("ANNP match card must contain exactly one header")
    header = headers[0]
    if any(
        node.name != "span" or not ({"local", "hora"} & set(node.get("class", [])))
        for node in header.find_all(recursive=False)
    ):
        raise ANNPResponseError("ANNP match card has an unexpected header structure")
    return header


def _parse_time(card: Tag) -> time | None:
    nodes = _header(card).select(":scope > span.hora")
    if len(nodes) > 1:
        raise ANNPResponseError("ANNP match card has multiple times")
    if not nodes:
        return None
    value = nodes[0].get_text(" ", strip=True)
    if value in _EMPTY_TIME_VALUES:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", value)
    if match is None:
        raise ANNPResponseError(f"Invalid ANNP time {value!r}")
    try:
        return time(int(match.group(1)), int(match.group(2)))
    except ValueError as exc:
        raise ANNPResponseError(f"Invalid ANNP time {value!r}") from exc


def _parse_location(card: Tag) -> str | None:
    nodes = _header(card).select(":scope > span.local")
    if len(nodes) > 1:
        raise ANNPResponseError("ANNP match card has multiple locations")
    if not nodes:
        return None
    value = " ".join(nodes[0].get_text(" ", strip=True).split())
    return None if value in _EMPTY_LOCATION_VALUES else value


def _stable_game_id(
    season: str, competition_id: str, home: str, away: str, occurrence: int
) -> str:
    """Keep the project's season/competition/teams/occurrence identity algorithm."""
    identity = ":".join(
        (
            season,
            competition_id,
            _normalized_text(home),
            _normalized_text(away),
            str(occurrence),
        )
    )
    return f"{season}-{competition_id}-{sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def map_annp_state(state: str | None) -> MatchStatus:
    """Map the lifecycle labels found on the current public calendar."""
    mapping = {
        "agendado": MatchStatus.SCHEDULED,
        "finalizado": MatchStatus.COMPLETED,
    }
    normalized = _normalized_text(state)
    if normalized not in mapping:
        raise ANNPResponseError(f"Unknown ANNP match state {state!r}")
    return mapping[normalized]


def map_annp_category(value: str) -> MatchCategory:
    return normalize_category(value)


def filter_team_games(games: Sequence[ANNPGame], team: str) -> list[ANNPGame]:
    requested = _normalized_text(team)
    if not requested:
        raise ValueError("team must not be empty")
    return [
        game
        for game in games
        if requested in {
            _normalized_text(game.home_team_name),
            _normalized_text(game.away_team_name),
        }
    ]


def to_matches(games: Sequence[ANNPGame], *, season: str) -> list[Match]:
    """Convert source games to the unchanged model used by JSON and ICS."""
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
            time=game.time,
            location=game.location,
            score_home=game.home_score,
            score_away=game.away_score,
            status=map_annp_state(game.state),
        )
        for game in games
    ]
