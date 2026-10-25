"""Parse the current ANNP Benjamins action calendar without creating Matches."""

from __future__ import annotations

from collections import Counter

from bs4 import BeautifulSoup

from waterpolo.models.benjamins_schedule import BenjaminsScheduleEntry
from waterpolo.scraper.annp.domain import (
    annp_season_bounds,
    annp_season_label,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import ANNPResponseError
from waterpolo.scraper.annp.models import ANNPCompetition
from waterpolo.scraper.annp.scraper import (
    _parse_date,
    _parse_location,
    _parse_time,
    _validate_selected_competition,
)


def parse_benjamins_schedule(
    html: str, *, season: str, competition: ANNPCompetition
) -> list[BenjaminsScheduleEntry]:
    """Read every competition 7 card as an action, regardless of team placeholders."""
    logical_season = normalize_annp_season(season)
    if competition.id != "7" or competition.name != "Benjamins Mistos":
        raise ANNPResponseError("ANNP schedule requires competition 7 — Benjamins Mistos")

    soup = BeautifulSoup(html, "lxml")
    _validate_selected_competition(soup, logical_season, competition)
    sections = soup.select("section.seccao-calendario")
    if len(sections) != 1:
        raise ANNPResponseError("ANNP schedule must contain one calendar section")
    section = sections[0]
    days = section.select(".dia")
    if not days:
        raise ANNPResponseError("ANNP Benjamins schedule contains no days")

    start, end = annp_season_bounds(logical_season)
    occurrences: Counter[str] = Counter()
    entries: list[BenjaminsScheduleEntry] = []
    for day in days:
        titles = day.select(":scope > .dia-titulo")
        containers = day.select(":scope > .cartoes")
        if len(titles) != 1 or len(containers) != 1:
            raise ANNPResponseError("ANNP Benjamins day has an unexpected structure")
        cards = containers[0].select(":scope > article.cartao")
        if not cards:
            raise ANNPResponseError("ANNP Benjamins day contains no action cards")
        action_date = _parse_date(titles[0].get_text(" ", strip=True))
        if not start <= action_date <= end:
            raise ANNPResponseError(
                f"ANNP Benjamins date {action_date.isoformat()} outside season {logical_season}"
            )
        for card in cards:
            date_key = action_date.isoformat()
            occurrences[date_key] += 1
            entries.append(
                BenjaminsScheduleEntry(
                    external_id=(
                        f"{logical_season}-7-{action_date:%Y%m%d}-{occurrences[date_key]}"
                    ),
                    season=annp_season_label(logical_season),
                    competition_name=competition.name,
                    date=action_date,
                    time=_parse_time(card),
                    venue=_parse_location(card),
                )
            )
    if len(section.select("article")) != len(entries):
        raise ANNPResponseError("ANNP Benjamins article outside a valid day group")
    return entries
