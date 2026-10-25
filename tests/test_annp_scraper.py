"""Current ANNP HTML and output-contract regression tests."""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from waterpolo.models import Match, MatchStatus
from waterpolo.scraper.annp import ANNPClient
from waterpolo.scraper.annp.domain import (
    annp_public_path,
    normalize_annp_season,
)
from waterpolo.scraper.annp.errors import (
    ANNPCompetitionNotFoundError,
    ANNPHTTPError,
    ANNPResponseError,
)
from waterpolo.scraper.annp.scraper import (
    filter_team_games,
    map_annp_state,
    parse_current_calendar,
    parse_current_competitions,
    to_matches,
)
from waterpolo.services.ics_export import export_matches_ics, match_uid
from waterpolo.services.json_export import export_matches_json

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "annp"
NAMES = {"1": "juniores", "2": "juvenis", "3": "infantis"}
EXPECTED = {
    "1": ("Juniores Masculinos", 20, 8),
    "2": ("Juvenis Masculinos", 42, 12),
    "3": ("Infantis Mistos", 42, 12),
}


def fixture(competition_id: str) -> str:
    return (FIXTURE_DIR / f"current_calendar_{NAMES[competition_id]}_2627.html").read_text()


def competition(competition_id: str):
    return next(
        item
        for item in parse_current_competitions(fixture("1"), season="2627")
        if item.id == competition_id
    )


def games(competition_id: str, html: str | None = None):
    return parse_current_calendar(
        html or fixture(competition_id),
        season="2627",
        competition=competition(competition_id),
        source_url=f"https://provas.annp.pt/polo/20262027/calendario/{competition_id}",
    )


def mock_client(handler):
    http_client = httpx.Client(
        base_url="https://provas.annp.pt", transport=httpx.MockTransport(handler)
    )
    return ANNPClient(client=http_client), http_client


@pytest.mark.parametrize(
    ("logical", "public"),
    [("2526", "20252026"), ("2627", "20262027"), ("2728", "20272028")],
)
def test_season_resolution(logical: str, public: str) -> None:
    assert normalize_annp_season(logical) == logical
    assert annp_public_path(logical) == f"/polo/{public}/"


@pytest.mark.parametrize("invalid", ["", "26", "2628", "abcd", "20262027", "9998"])
def test_invalid_season(invalid: str) -> None:
    with pytest.raises(ValueError, match="Invalid ANNP season"):
        annp_public_path(invalid)


def test_competition_discovery_has_all_current_ids_and_names() -> None:
    found = parse_current_competitions(fixture("1"), season="2627")
    assert [(item.id, item.name) for item in found] == [
        ("1", "Juniores Masculinos"),
        ("2", "Juvenis Masculinos"),
        ("3", "Infantis Mistos"),
        ("4", "Cadetes Mistos"),
        ("7", "Benjamins Mistos"),
    ]


@pytest.mark.parametrize("html", ["", "<p>maintenance</p>"])
def test_invalid_competition_markup(html: str) -> None:
    with pytest.raises(ANNPResponseError):
        parse_current_competitions(html, season="2627")


def test_competition_links_must_match_requested_season() -> None:
    with pytest.raises(ANNPResponseError, match="invalid season"):
        parse_current_competitions(fixture("1"), season="2728")


@pytest.mark.parametrize("competition_id", ["1", "2", "3"])
def test_full_current_fixtures_and_foca_home_or_away(competition_id: str) -> None:
    name, total, foca_total = EXPECTED[competition_id]
    parsed = games(competition_id)
    selected = filter_team_games(parsed, "foca")
    assert len(parsed) == total
    assert len(selected) == foca_total
    assert all(game.competition_id == competition_id for game in selected)
    assert all(game.competition_name == name for game in selected)
    assert any(game.home_team_name == "FOCA" for game in selected)
    assert any(game.away_team_name == "FOCA" for game in selected)
    assert filter_team_games(parsed, "FOC") == []


def test_current_fixtures_dates_times_venues_scores_and_statuses() -> None:
    junior = filter_team_games(games("1"), "FOCA")
    juvenile = filter_team_games(games("2"), "FOCA")
    infant = filter_team_games(games("3"), "FOCA")
    assert (junior[0].date, junior[0].time, junior[0].location) == (
        date(2026, 10, 11), time(10), "Fluvial"
    )
    assert (junior[0].home_score, junior[0].away_score) == (22, 3)
    assert (junior[2].time, junior[2].location) == (None, None)
    assert (junior[2].home_score, junior[2].away_score) == (None, None)
    assert (juvenile[0].time, juvenile[0].state) == (None, "Finalizado")
    assert (juvenile[0].home_score, juvenile[0].away_score) == (9, 19)
    assert any(game.date.year == 2027 for game in junior + juvenile + infant)
    assert any(game.time == time(14, 5) for game in infant)
    assert map_annp_state("Agendado") is MatchStatus.SCHEDULED
    assert map_annp_state("Finalizado") is MatchStatus.COMPLETED
    with pytest.raises(ANNPResponseError, match="Unknown"):
        map_annp_state("estado novo")


def test_page_must_confirm_selected_competition() -> None:
    with pytest.raises(ANNPResponseError, match="selected competition"):
        games("2", fixture("1"))
    incorrect_name = fixture("1").replace(
        ">Juniores Masculinos</a>", ">Nome incorreto</a>", 1
    )
    with pytest.raises(ANNPResponseError):
        games("1", incorrect_name)


def test_article_outside_day_group_cannot_be_ignored() -> None:
    soup = BeautifulSoup(fixture("1"), "lxml")
    section = soup.select_one("section.seccao-calendario")
    card = section.select_one("article.cartao")
    section.append(BeautifulSoup(str(card), "lxml").article)
    with pytest.raises(ANNPResponseError, match="outside a valid day"):
        games("1", str(soup))


@pytest.mark.parametrize(
    "old,new",
    [
        ('<h2 class="dia-titulo">11 out 2026</h2>', '<h2 class="dia-titulo"></h2>'),
        ("<span>FOCA</span>", "<span></span>"),
        ('<div class="estado">Finalizado</div>', ""),
        ('<div class="resultado">22 : 3</div>', '<div class="resultado">22 :</div>'),
        ('<div class="estado">Finalizado</div>', '<div class="estado">novo</div>'),
    ],
)
def test_incomplete_card_fails_explicitly(old: str, new: str) -> None:
    html = fixture("1")
    assert old in html
    with pytest.raises(ANNPResponseError):
        games("1", html.replace(old, new, 1))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("9:0", time(9)), ("9:05", time(9, 5)), ("09:5", time(9, 5)),
     ("09:05", time(9, 5)), ("00:00", time.min), ("----", None)],
)
def test_current_time_values(raw: str, expected: time | None) -> None:
    html = fixture("1").replace("10:00", raw, 1)
    assert games("1", html)[0].time == expected


@pytest.mark.parametrize("raw", ["25:00", "12:60", "9:", "9h30"])
def test_invalid_time_fails(raw: str) -> None:
    with pytest.raises(ANNPResponseError, match="Invalid ANNP time"):
        games("1", fixture("1").replace("10:00", raw, 1))


def test_missing_time_and_venue_elements_are_null() -> None:
    soup = BeautifulSoup(fixture("1"), "lxml")
    card = soup.select_one("section.seccao-calendario article.cartao")
    card.select_one(".hora").decompose()
    card.select_one(".local").decompose()
    first = games("1", str(soup))[0]
    assert (first.time, first.location) == (None, None)


def test_completed_zero_zero_is_a_real_score() -> None:
    content = (FIXTURE_DIR / "current_calendar_cadetes_2627.html").read_text()
    comp = next(
        item for item in parse_current_competitions(content, season="2627")
        if item.id == "4"
    )
    parsed = parse_current_calendar(
        content, season="2627", competition=comp, source_url="https://example.test"
    )
    assert any((game.home_score, game.away_score) == (0, 0) for game in parsed)


def test_placeholder_teams_in_current_benjamins_fail_explicitly() -> None:
    content = (FIXTURE_DIR / "current_calendar_benjamins_2627.html").read_text()
    comp = next(
        item for item in parse_current_competitions(content, season="2627")
        if item.id == "7"
    )
    with pytest.raises(ANNPResponseError, match="placeholder team"):
        parse_current_calendar(
            content, season="2627", competition=comp, source_url="https://example.test"
        )


def test_external_id_ignores_mutable_fields_and_occurrence() -> None:
    original = games("1")[0]
    changed = (
        fixture("1")
        .replace("11 out 2026", "12 out 2026", 1)
        .replace("10:00", "18:45", 1)
        .replace("Fluvial", "Felgueiras", 1)
        .replace("22 : 3", "24 : 4", 1)
    )
    assert games("1", changed)[0].id == original.id
    changed_state = changed.replace(
        '<div class="resultado">24 : 4</div>', '<div class="resultado"> : </div>', 1
    ).replace('<div class="estado">Finalizado</div>', '<div class="estado">Agendado</div>', 1)
    assert games("1", changed_state)[0].id == original.id
    soup = BeautifulSoup(fixture("1"), "lxml")
    first_card = soup.select_one("section.seccao-calendario article.cartao")
    first_card.insert_after(BeautifulSoup(str(first_card), "lxml").article)
    repeated = games("1", str(soup))
    assert repeated[0].id != repeated[1].id
    assert repeated[0].id == original.id


def test_http_only_current_routes_and_errors() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append(path)
        assert path.startswith("/polo/20262027/calendario")
        content = fixture("1")
        return httpx.Response(200, text=content, headers={"content-type": "text/html"})

    adapter, http_client = mock_client(handler)
    with http_client:
        selected, found = adapter.get_team_games(
            season="2627", team="FOCA", competition_id="1"
        )
    assert (selected.name, len(found)) == ("Juniores Masculinos", 8)
    assert requests == [
        "/polo/20262027/calendario",
        "/polo/20262027/calendario/1",
    ]


@pytest.mark.parametrize("status", [404, 503])
def test_http_failure_is_explicit(status: int) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(status)

    adapter, http_client = mock_client(handler)
    with http_client, pytest.raises(ANNPHTTPError, match=f"HTTP {status}"):
        adapter.get_competitions("2627")
    assert requests == ["/polo/20262027/calendario"]


def test_network_failure_is_explicit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    adapter, http_client = mock_client(handler)
    with http_client, pytest.raises(ANNPHTTPError, match="request failed"):
        adapter.get_competitions("2627")


def test_invalid_response_and_missing_id_fail() -> None:
    adapter, http_client = mock_client(
        lambda request: httpx.Response(
            200, text=fixture("1"), headers={"content-type": "text/html"}
        )
    )
    with http_client, pytest.raises(ANNPCompetitionNotFoundError, match="available"):
        adapter.resolve_competition("2627", competition_id="999")
    adapter, http_client = mock_client(
        lambda request: httpx.Response(
            200, json={"unexpected": True}, headers={"content-type": "application/json"}
        )
    )
    with http_client, pytest.raises(ANNPResponseError, match="content type"):
        adapter.get_competitions("2627")


def test_shared_match_json_and_ics_contract(tmp_path: Path) -> None:
    selected = filter_team_games(games("1"), "FOCA")
    matches = to_matches(selected, season="2627")
    assert all(isinstance(match, Match) for match in matches)
    assert all(match.season == "S2627" for match in matches)
    payload = export_matches_json(matches, source="ANNP")
    assert payload["match_count"] == 8
    assert set(payload) == {"generated_at", "source", "match_count", "matches"}
    assert set(payload["matches"][0]) == set(matches[0].model_dump(exclude={"raw"}))
    no_time = next(item for item in payload["matches"] if item["time"] is None)
    assert no_time["location"] is None
    assert no_time["score_home"] is None
    assert no_time["score_away"] is None
    assert payload["matches"][0]["date"] == "2026-10-11"
    assert payload["matches"][0]["time"] == "10:00:00"
    assert payload["matches"][0]["status"] == "COMPLETED"
    output = tmp_path / "juniores.ics"
    export_matches_ics(matches, output)
    ics = output.read_text()
    assert ics.count("BEGIN:VEVENT") == 8
    assert "DTSTART;VALUE=DATE:20261024" in ics
    assert f"UID:{match_uid(matches[0])}" in ics
    assert json.loads(json.dumps(payload))["matches"][0]["external_id"] == matches[0].external_id


def test_adapter_source_contains_no_retired_endpoint() -> None:
    source_dir = Path(__file__).parents[1] / "src" / "waterpolo" / "scraper" / "annp"
    source = "\n".join(path.read_text() for path in source_dir.glob("*.py"))
    forbidden = (
        "competicoes" + ".php",
        "calendario" + ".php",
        "/provas" + "2526/",
        "/provas" + "2627/",
    )
    assert all(value not in source for value in forbidden)
