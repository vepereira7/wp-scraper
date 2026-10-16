from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup, Tag

from waterpolo.models import MatchCategory, MatchSource, MatchStatus
from waterpolo.scraper.annp import (
    ANNPClient,
    ANNPCompetition,
    ANNPCompetitionNotFoundError,
    ANNPHTTPError,
    ANNPResponseError,
    annp_polo_path,
    annp_season_label,
    annp_source_seasons,
    normalize_annp_season,
)
from waterpolo.scraper.annp.scraper import (
    _parse_time,
    filter_team_games,
    map_annp_category,
    map_annp_state,
    parse_calendar,
    parse_competitions,
    to_matches,
)
from waterpolo.services.ics_export import export_matches_ics
from waterpolo.services.json_export import export_matches_json

FIXTURES = Path(__file__).parent / "fixtures" / "annp"
COMPETITIONS_HTML = (FIXTURES / "competitions.html").read_text()
JUNIORES_HTML = (FIXTURES / "calendar_juniores.html").read_text()
JUVENIS_HTML = (FIXTURES / "calendar_juvenis.html").read_text()
EMPTY_HTML = (FIXTURES / "empty_calendar.html").read_text()
RECENT_TIME_PLACEHOLDER_HTML = (
    FIXTURES / "calendar_juniores_2627_time_placeholder.html"
).read_text()
RECENT_SINGLE_DIGIT_MINUTE_HTML = (
    FIXTURES / "calendar_juvenis_2627_single_digit_minute.html"
).read_text()
JUNIORES_2627_HTML = JUNIORES_HTML.replace("2025", "2026")


@contextmanager
def mocked_client(handler: httpx.MockTransport) -> Iterator[ANNPClient]:
    with httpx.Client(
        base_url="https://provas.annp.test",
        transport=handler,
    ) as http_client:
        yield ANNPClient(client=http_client)


def competition(identifier: str = "1", name: str = "Juniores Masculinos") -> ANNPCompetition:
    return ANNPCompetition(id=identifier, name=name, category=name)


def parse_juniores(html: str = JUNIORES_HTML):
    return parse_calendar(
        html,
        season="2526",
        competition=competition(),
        source_url=(
            "https://provas.annp.test/provas2526/polo/calendario.php"
            "?competicao=1&temjogos=1"
        ),
    )


def parse_time_element(time_element: str | None) -> time | None:
    element = time_element or ""
    soup = BeautifulSoup(
        "<div class='match-card'><div class='match-header'>"
        "<span class='local-info'><span>Fluvial</span></span>"
        f"{element}</div></div>",
        "lxml",
    )
    card = soup.select_one(".match-card")
    assert isinstance(card, Tag)
    return _parse_time(card)


@pytest.mark.parametrize("season", ["2526", "S2526", "s2526"])
def test_season_is_normalized_and_builds_url(season: str) -> None:
    assert normalize_annp_season(season) == "2526"
    assert annp_season_label(season) == "S2526"
    assert annp_polo_path(season) == "/provas2526/polo/"


def test_logical_2627_source_candidates_prefer_correct_path_then_legacy() -> None:
    assert annp_source_seasons("2627") == ("2627", "2526")


@pytest.mark.parametrize("season", ["", "2025/26", "2527", "202526", "abcd"])
def test_invalid_season_is_rejected(season: str) -> None:
    with pytest.raises(ValueError, match="Invalid ANNP season"):
        normalize_annp_season(season)


def test_competition_discovery_parses_real_ids_and_names() -> None:
    assert [item.model_dump() for item in parse_competitions(COMPETITIONS_HTML)] == [
        {
            "id": "1",
            "name": "Juniores Masculinos",
            "category": "Juniores Masculinos",
            "has_games": True,
        },
        {
            "id": "2",
            "name": "Juvenis Masculinos",
            "category": "Juvenis Masculinos",
            "has_games": True,
        },
    ]


def test_calendar_parses_dates_times_locations_scores_and_states() -> None:
    games = parse_juniores()

    assert len(games) == 3
    assert games[0].date == date(2025, 10, 11)
    assert games[0].time == time(10, 0)
    assert games[0].location == "Fluvial"
    assert (games[0].home_score, games[0].away_score) == (22, 3)
    assert map_annp_state(games[0].state) is MatchStatus.COMPLETED
    assert games[2].location is None
    assert (games[2].home_score, games[2].away_score) == (None, None)
    assert map_annp_state(games[2].state) is MatchStatus.SCHEDULED


@pytest.mark.parametrize(
    ("time_element", "expected"),
    [
        ("<span>⏰ 9:0</span>", time(9, 0)),
        ("<span>⏰ 9:5</span>", time(9, 5)),
        ("<span>⏰ 9:30</span>", time(9, 30)),
        ("<span>⏰ 09:0</span>", time(9, 0)),
        ("<span>⏰ 09:05</span>", time(9, 5)),
        ("<span>⏰ 14:5</span>", time(14, 5)),
        ("<span>⏰ 14:30</span>", time(14, 30)),
        ("<span>⏰ 0:0</span>", None),
        ("<span>⏰ 00:00</span>", None),
        (None, None),
        ("<span></span>", None),
        ("<span>   \n  </span>", None),
        ("<span>⏰ ----</span>", None),
    ],
)
def test_parse_time_accepts_valid_and_known_undefined_values(
    time_element: str | None, expected: time | None
) -> None:
    assert parse_time_element(time_element) == expected


@pytest.mark.parametrize(
    "value",
    [
        "25:00",
        "12:60",
        "9:",
        ":30",
        "9:000",
        "abc",
        "9h30",
        "-1:30",
        "09:5x",
    ],
)
def test_parse_time_rejects_present_invalid_value(value: str) -> None:
    with pytest.raises(ANNPResponseError, match="Invalid ANNP time"):
        parse_time_element(f"<span>⏰ {value}</span>")


def test_parse_time_rejects_unexpected_markup() -> None:
    with pytest.raises(ANNPResponseError, match="unexpected time structure"):
        parse_time_element("<div>⏰ 14:30</div>")


def test_recent_calendar_keeps_all_games_when_one_time_is_undefined(
    tmp_path: Path,
) -> None:
    games = parse_calendar(
        RECENT_TIME_PLACEHOLDER_HTML,
        season="2627",
        competition=competition(),
        source_url=(
            "https://provas.annp.pt/provas2526/polo/calendario.php"
            "?competicao=1&temjogos=1"
        ),
    )

    assert len(games) == 3
    assert [game.time for game in games] == [time(9, 30), None, time(14, 30)]

    matches = to_matches(games, season="2627")
    payload = export_matches_json(matches, source="ANNP")
    assert [item["time"] for item in payload["matches"]] == [
        "09:30:00",
        None,
        "14:30:00",
    ]

    output = tmp_path / "recent-annp.ics"
    export_matches_ics(matches, output)
    ics = output.read_text().replace("\n ", "")
    assert "DTSTART;VALUE=DATE:20261024" in ics
    assert "DTEND;VALUE=DATE:20261025" in ics
    assert ics.count("BEGIN:VEVENT") == 3


def test_recent_calendar_parses_single_digit_minute() -> None:
    games = parse_calendar(
        RECENT_SINGLE_DIGIT_MINUTE_HTML,
        season="2627",
        competition=competition("2", "Juvenis Masculinos"),
        source_url=(
            "https://provas.annp.pt/provas2526/polo/calendario.php"
            "?competicao=2&temjogos=1"
        ),
    )

    assert len(games) == 1
    assert games[0].date == date(2027, 1, 10)
    assert (games[0].home_team_name, games[0].away_team_name) == ("CNPO", "LSXXI")
    assert games[0].time == time(9, 0)


def test_external_id_ignores_schedule_result_and_state_changes() -> None:
    original = parse_juniores()[0]
    changed_html = (
        JUNIORES_HTML.replace("11 out 2025", "12 out 2025", 1)
        .replace("Fluvial", "Felgueiras", 1)
        .replace("10:00", "18:45", 1)
        .replace("22 : 3", "24 : 4", 1)
        .replace("Finalizado", "Não iniciado", 1)
    )
    changed = parse_juniores(changed_html)[0]

    assert changed.id == original.id
    assert changed.date != original.date
    assert changed.time != original.time
    assert changed.location != original.location
    assert changed.home_score != original.home_score
    assert changed.state != original.state


def test_repeated_home_away_fixtures_get_distinct_stable_ids() -> None:
    one_card = JUNIORES_HTML.split('<div class="mb-10">', 2)[1]
    one_card = '<div class="mb-10">' + one_card.split('<div class="mb-10">', 1)[0]
    games = parse_juniores(one_card + one_card)

    assert len(games) == 2
    assert games[0].id != games[1].id


def test_foca_filter_and_match_normalization() -> None:
    games = filter_team_games(parse_juniores(), "foca")
    matches = to_matches(games, season="2526")

    assert len(matches) == 2
    assert all("FOCA" in {match.home, match.away} for match in matches)
    assert matches[0].source is MatchSource.ANNP
    assert matches[0].season == "S2526"
    assert matches[0].category is MatchCategory.U18
    assert matches[0].competition == "Juniores Masculinos"
    assert matches[0].source_url.endswith("competicao=1&temjogos=1")


def test_annp_midnight_is_unknown_but_real_time_is_preserved() -> None:
    from waterpolo.services.ics_export import match_uid

    juvenile_competition = competition("2", "Juvenis Masculinos")
    source_url = (
        "https://provas.annp.test/provas2526/polo/calendario.php"
        "?competicao=2&temjogos=1"
    )
    timed_game = parse_calendar(
        JUVENIS_HTML,
        season="2526",
        competition=juvenile_competition,
        source_url=source_url,
    )[1]
    unknown_game = parse_calendar(
        JUVENIS_HTML.replace("14:30", "00:00"),
        season="2526",
        competition=juvenile_competition,
        source_url=source_url,
    )[1]

    timed_match = to_matches([timed_game], season="2526")[0]
    unknown_match = to_matches([unknown_game], season="2526")[0]

    assert timed_match.time == time(14, 30)
    assert unknown_match.time is None
    assert unknown_match.external_id == timed_match.external_id
    assert match_uid(unknown_match) == match_uid(timed_match)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Seniores Masculinos", MatchCategory.SENIOR),
        ("Juniores Masculinos", MatchCategory.U18),
        ("Juvenis Masculinos", MatchCategory.U16),
        ("Infantis Mistos", MatchCategory.U14),
        ("Sub-18 Femininos", MatchCategory.U18),
        ("Sub 16", MatchCategory.U16),
        ("U14", MatchCategory.U14),
        ("Sub-12", MatchCategory.U12),
        ("Absolutos", MatchCategory.UNKNOWN),
    ],
)
def test_category_mapping(raw: str, expected: MatchCategory) -> None:
    assert map_annp_category(raw) is expected


@pytest.mark.parametrize(
    ("identifier", "name", "fixture", "expected_category", "expected_ids"),
    [
        (
            "1",
            "Juniores Masculinos",
            JUNIORES_HTML,
            MatchCategory.U18,
            [
                "2526-1-8d7a8a247279e7b8",
                "2526-1-b187aece845d1afd",
                "2526-1-9d10ee638e003203",
            ],
        ),
        (
            "2",
            "Juvenis Masculinos",
            JUVENIS_HTML,
            MatchCategory.U16,
            ["2526-2-ee5a23efbe85ff3d", "2526-2-648dc26b2a0590ca"],
        ),
    ],
)
def test_annp_fixture_matches_keep_competition_and_stable_ids_with_canonical_category(
    identifier: str,
    name: str,
    fixture: str,
    expected_category: MatchCategory,
    expected_ids: list[str],
) -> None:
    games = parse_calendar(
        fixture,
        season="2526",
        competition=competition(identifier, name),
        source_url=f"https://example.test?competicao={identifier}",
    )
    matches = to_matches(games, season="2526")
    exported = export_matches_json(matches)["matches"]

    assert [match.external_id for match in matches] == expected_ids
    assert all(match.competition == name for match in matches)
    assert all(match.category is expected_category for match in matches)
    assert all(item["category"] == expected_category.value for item in exported)
    assert all(item["competition"] == name for item in exported)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Não iniciado", MatchStatus.SCHEDULED),
        ("Finalizado", MatchStatus.COMPLETED),
        ("Adiado", MatchStatus.POSTPONED),
        ("Cancelado", MatchStatus.CANCELLED),
        ("Em curso", MatchStatus.UNKNOWN),
    ],
)
def test_status_mapping(raw: str, expected: MatchStatus) -> None:
    assert map_annp_state(raw) is expected


def test_client_uses_season_endpoints_and_minimal_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("competicoes.php"):
            assert dict(request.url.params) == {"opcao": "1"}
            return httpx.Response(200, text=COMPETITIONS_HTML, headers={"content-type": "text/html"})
        assert request.url.path.endswith("calendario.php")
        assert dict(request.url.params) == {"competicao": "1", "temjogos": "1"}
        return httpx.Response(200, text=JUNIORES_HTML, headers={"content-type": "text/html"})

    with mocked_client(httpx.MockTransport(handler)) as client:
        resolved, games = client.get_team_games(
            season="2526", team="FOCA", competition_id="1"
        )

    assert resolved.name == "Juniores Masculinos"
    assert len(games) == 2
    assert len(requests) == 2
    assert all(request.url.path.startswith("/provas2526/polo/") for request in requests)


def test_logical_2627_falls_back_to_provas2526_and_accepts_2627_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/provas2627/"):
            return httpx.Response(404)
        if request.url.path.endswith("competicoes.php"):
            return httpx.Response(
                200,
                text=COMPETITIONS_HTML,
                headers={"content-type": "text/html"},
            )
        return httpx.Response(
            200,
            text=JUNIORES_2627_HTML,
            headers={"content-type": "text/html"},
        )

    with mocked_client(httpx.MockTransport(handler)) as client:
        resolved, games = client.get_team_games(
            season="2627", team="FOCA", competition_id="1"
        )

    matches = to_matches(games, season="2627")
    assert resolved.id == "1"
    assert len(matches) == 2
    assert matches[0].season == "S2627"
    assert matches[0].external_id.startswith("2627-1-")
    assert "/provas2526/polo/" in (matches[0].source_url or "")
    assert [request.url.path for request in requests] == [
        "/provas2627/polo/competicoes.php",
        "/provas2526/polo/competicoes.php",
        "/provas2526/polo/calendario.php",
    ]


def test_logical_2627_prefers_provas2627_when_it_contains_valid_data() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith("/provas2627/polo/")
        payload = (
            COMPETITIONS_HTML
            if request.url.path.endswith("competicoes.php")
            else JUNIORES_2627_HTML
        )
        return httpx.Response(
            200,
            text=payload,
            headers={"content-type": "text/html"},
        )

    with mocked_client(httpx.MockTransport(handler)) as client:
        _, games = client.get_team_games(
            season="2627", team="FOCA", competition_id="1"
        )

    matches = to_matches(games, season="2627")
    assert len(matches) == 2
    assert matches[0].external_id.startswith("2627-1-")
    assert "/provas2627/polo/" in (matches[0].source_url or "")
    assert len(requests) == 2


def test_discovery_separates_foca_games_by_competition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("competicoes.php"):
            return httpx.Response(
                200, text=COMPETITIONS_HTML, headers={"content-type": "text/html"}
            )
        payload = JUNIORES_HTML if request.url.params["competicao"] == "1" else JUVENIS_HTML
        return httpx.Response(200, text=payload, headers={"content-type": "text/html"})

    with mocked_client(httpx.MockTransport(handler)) as client:
        found = client.discover_team_competitions("2526", "FOCA")

    assert [(item.id, item.name, len(games)) for item, games in found] == [
        ("1", "Juniores Masculinos", 2),
        ("2", "Juvenis Masculinos", 2),
    ]


def test_category_selector_resolves_case_insensitively() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, text=COMPETITIONS_HTML, headers={"content-type": "text/html"}
        )
    )
    with mocked_client(transport) as client:
        resolved = client.resolve_competition("2526", category="juniores masculinos")
    assert resolved.id == "1"


def test_missing_competition_has_specific_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, text=COMPETITIONS_HTML, headers={"content-type": "text/html"}
        )
    )
    with mocked_client(transport) as client, pytest.raises(
        ANNPCompetitionNotFoundError, match="available"
    ):
        client.resolve_competition("2526", competition_id="999")


def test_empty_calendar_is_a_valid_empty_source_response() -> None:
    assert (
        parse_calendar(
            EMPTY_HTML,
            season="2526",
            competition=competition(),
            source_url="https://example.test/calendar",
        )
        == []
    )


@pytest.mark.parametrize("html", ["", "<p>maintenance</p>", "<div class='match-card'></div>"])
def test_invalid_calendar_response_is_rejected(html: str) -> None:
    with pytest.raises(ANNPResponseError):
        parse_calendar(
            html,
            season="2526",
            competition=competition(),
            source_url="https://example.test/calendar",
        )


def test_calendar_date_outside_requested_season_is_rejected() -> None:
    html = JUNIORES_HTML.replace("2025", "2026")
    with pytest.raises(ANNPResponseError, match="outside requested season 2526"):
        parse_juniores(html)


def test_provas2526_content_for_2627_is_rejected_for_logical_2526() -> None:
    with pytest.raises(ANNPResponseError, match="outside requested season 2526"):
        parse_calendar(
            JUNIORES_2627_HTML,
            season="2526",
            competition=competition(),
            source_url=(
                "https://provas.annp.test/provas2526/polo/calendario.php"
                "?competicao=1&temjogos=1"
            ),
        )


def test_same_logical_game_keeps_identity_when_source_path_changes() -> None:
    from waterpolo.services.ics_export import match_uid

    source_2526 = (
        "https://provas.annp.test/provas2526/polo/calendario.php"
        "?competicao=1&temjogos=1"
    )
    source_2627 = source_2526.replace("provas2526", "provas2627")
    first = parse_calendar(
        JUNIORES_2627_HTML,
        season="2627",
        competition=competition(),
        source_url=source_2526,
    )[0]
    second = parse_calendar(
        JUNIORES_2627_HTML,
        season="2627",
        competition=competition(),
        source_url=source_2627,
    )[0]
    first_match = to_matches([first], season="2627")[0]
    second_match = to_matches([second], season="2627")[0]

    assert first.id == second.id
    assert first.id.startswith("2627-1-")
    assert first_match.season == second_match.season == "S2627"
    assert first_match.source_url != second_match.source_url
    assert match_uid(first_match) == match_uid(second_match)


def test_invalid_competition_response_is_rejected() -> None:
    with pytest.raises(ANNPResponseError, match="no competitions"):
        parse_competitions("<p>maintenance</p>")


def test_http_error_is_not_silenced() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with mocked_client(transport) as client, pytest.raises(ANNPHTTPError, match="HTTP 503"):
        client.get_competitions("2526")


def test_non_html_response_is_rejected() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"unexpected": True},
            headers={"content-type": "application/json"},
        )
    )
    with mocked_client(transport) as client, pytest.raises(
        ANNPResponseError, match="content type"
    ):
        client.get_competitions("2526")
