"""Dedicated ANNP Benjamins schedule and report integration tests."""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError

from waterpolo.main import main as scraper_main
from waterpolo.models.benjamins_schedule import BenjaminsScheduleEntry
from waterpolo.models.match import Match
from waterpolo.report.__main__ import main as report_main
from waterpolo.scraper.annp import ANNPClient
from waterpolo.scraper.annp.benjamins import parse_benjamins_schedule
from waterpolo.scraper.annp.errors import ANNPResponseError
from waterpolo.scraper.annp.scraper import (
    filter_team_games,
    parse_current_calendar,
    parse_current_competitions,
    to_matches,
)
from waterpolo.services.benjamins_schedule import (
    export_benjamins_ics,
    export_benjamins_json,
    schedule_uid,
    validate_benjamins_json,
)
from waterpolo.services.json_export import export_matches_json
from waterpolo.services.validation import validate_ics_file, validate_json_payload

ANNP_FIXTURES = Path(__file__).parent / "fixtures" / "annp"
REPORT_FIXTURES = Path(__file__).parent / "fixtures" / "report"
BENJAMINS_HTML = (
    ANNP_FIXTURES / "current_calendar_benjamins_2627.html"
).read_text()
JUNIORES_HTML = (ANNP_FIXTURES / "current_calendar_juniores_2627.html").read_text()


def parse(html: str = BENJAMINS_HTML) -> list[BenjaminsScheduleEntry]:
    competition = next(
        item for item in parse_current_competitions(html, season="2627")
        if item.id == "7"
    )
    return parse_benjamins_schedule(html, season="2627", competition=competition)


def test_current_benjamins_cards_are_actions_not_matches() -> None:
    entries = parse()
    assert len(entries) == 10
    assert all(isinstance(item, BenjaminsScheduleEntry) for item in entries)
    assert (entries[0].date, entries[0].time, entries[0].venue) == (
        date(2026, 10, 31), time(15, 30), "Felgueiras"
    )
    assert (entries[1].date, entries[1].time, entries[1].venue) == (
        date(2026, 11, 14), None, None
    )
    assert entries[2].venue == "Guimarães"
    assert entries[-1].date == date(2027, 6, 19)
    assert all(item.competition_id == "7" for item in entries)
    assert all(item.competition_name == "Benjamins Mistos" for item in entries)
    assert not {"home", "away", "home_score", "away_score"} & set(
        BenjaminsScheduleEntry.model_fields
    )


def test_schedule_model_rejects_match_semantics() -> None:
    item = parse()[0]
    with pytest.raises(ValidationError):
        BenjaminsScheduleEntry.model_validate(
            {**item.model_dump(), "home_team": "-----"}
        )


def test_schedule_identity_is_date_and_occurrence_based() -> None:
    original = parse()
    assert original[0].external_id == "2627-7-20261031-1"
    changed_venue = BENJAMINS_HTML.replace("Felgueiras", "Lousada", 1)
    changed_time = BENJAMINS_HTML.replace("15:30", "10:05", 1)
    assert parse(changed_venue)[0].external_id == original[0].external_id
    assert parse(changed_time)[0].external_id == original[0].external_id
    moved = BENJAMINS_HTML.replace("31 out 2026", "1 nov 2026", 1)
    assert parse(moved)[0].external_id == "2627-7-20261101-1"
    soup = BeautifulSoup(BENJAMINS_HTML, "lxml")
    first_card = soup.select_one(".seccao-calendario .dia article.cartao")
    first_card.insert_after(BeautifulSoup(str(first_card), "lxml").article)
    repeated = parse(str(soup))
    assert repeated[0].external_id == "2627-7-20261031-1"
    assert repeated[1].external_id == "2627-7-20261031-2"


def test_schedule_parser_rejects_wrong_competition_and_malformed_cards() -> None:
    competition = parse_current_competitions(JUNIORES_HTML, season="2627")[0]
    with pytest.raises(ANNPResponseError, match="competition 7"):
        parse_benjamins_schedule(
            JUNIORES_HTML, season="2627", competition=competition
        )
    changed = BENJAMINS_HTML.replace("31 out 2026", "31 out 2025", 1)
    with pytest.raises(ANNPResponseError, match="outside season"):
        parse(changed)
    changed = BENJAMINS_HTML.replace("15:30", "invalid", 1)
    with pytest.raises(ANNPResponseError, match="Invalid ANNP time"):
        parse(changed)
    changed = BENJAMINS_HTML.replace("31 out 2026", "", 1)
    with pytest.raises(ANNPResponseError, match="Invalid ANNP date"):
        parse(changed)


def test_client_uses_only_current_routes_for_benjamins() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.url.path.startswith("/polo/20262027/calendario")
        content = BENJAMINS_HTML if request.url.path.endswith("/7") else JUNIORES_HTML
        return httpx.Response(
            200, text=content, headers={"content-type": "text/html"}
        )

    with httpx.Client(
        base_url="https://provas.annp.pt", transport=httpx.MockTransport(handler)
    ) as http_client:
        adapter = ANNPClient(client=http_client)
        assert len(adapter.get_benjamins_schedule("2627", competition_id="7")) == 10
        with pytest.raises(ValueError, match="only"):
            adapter.get_benjamins_schedule("2627", competition_id="1")
    assert paths == [
        "/polo/20262027/calendario",
        "/polo/20262027/calendario/7",
    ]


@pytest.mark.parametrize(
    ("competition_id", "name", "count"),
    [("1", "juniores", 8), ("2", "juvenis", 12), ("3", "infantis", 12)],
)
def test_other_annp_competitions_still_produce_match_json(
    competition_id: str, name: str, count: int
) -> None:
    html = (ANNP_FIXTURES / f"current_calendar_{name}_2627.html").read_text()
    competition = next(
        item for item in parse_current_competitions(html, season="2627")
        if item.id == competition_id
    )
    games = parse_current_calendar(
        html,
        season="2627",
        competition=competition,
        source_url=f"https://provas.annp.pt/polo/20262027/calendario/{competition_id}",
    )
    matches = to_matches(filter_team_games(games, "FOCA"), season="2627")
    assert len(matches) == count
    assert all(isinstance(item, Match) for item in matches)
    assert export_matches_json(matches, source="ANNP")["match_count"] == count


def test_separate_json_schema_and_nulls() -> None:
    entries = parse()
    payload = export_benjamins_json(entries)
    assert set(payload) == {
        "source", "season", "competition_id", "competition_name",
        "entry_count", "entries",
    }
    assert (payload["source"], payload["season"], payload["entry_count"]) == (
        "ANNP", "S2627", 10
    )
    assert payload["entries"][0] == {
        "external_id": "2627-7-20261031-1",
        "date": "2026-10-31",
        "time": "15:30",
        "venue": "Felgueiras",
    }
    assert payload["entries"][1]["time"] is None
    assert payload["entries"][1]["venue"] is None
    assert validate_benjamins_json(json.loads(json.dumps(payload))) == entries
    with pytest.raises(TypeError, match="matches"):
        validate_json_payload(payload)
    with pytest.raises(ValueError, match="entry_count"):
        validate_benjamins_json({**payload, "entry_count": 9})


def test_schedule_ics_date_only_timed_location_and_identity(tmp_path: Path) -> None:
    entries = parse()
    output = tmp_path / "benjamins.ics"
    export_benjamins_ics(entries, output)
    ics = output.read_text()
    assert ics.count("BEGIN:VEVENT") == 10
    assert "SUMMARY:Ação de Benjamins" in ics
    assert "-----" not in ics
    assert "DTSTART:20261031T153000Z" in ics
    assert "DTSTART;VALUE=DATE:20261114" in ics
    assert "DTEND;VALUE=DATE:20261115" in ics
    assert "LOCATION:Felgueiras" in ics
    assert ics.count("LOCATION:") == sum(item.venue is not None for item in entries)
    assert f"UID:{schedule_uid(entries[0])}" in ics
    validate_ics_file(
        output,
        expected_uids={schedule_uid(item) for item in entries},
        expected_event_count=10,
    )


class FakeANNPClient:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_benjamins_schedule(self, season: str, *, competition_id: str):
        assert (season, competition_id) == ("2627", "7")
        return parse()


def test_schedule_cli_writes_optional_ics_without_match_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("waterpolo.main.ANNPClient", FakeANNPClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    json_path = tmp_path / "benjamins.json"
    ics_path = tmp_path / "benjamins.ics"
    base = [
        "publish", "annp-schedule", "--season", "2627",
        "--competition-id", "7", "--json-output", str(json_path),
    ]
    assert scraper_main(base) == 0
    assert json_path.is_file()
    assert not ics_path.exists()
    assert scraper_main([*base, "--ics-output", str(ics_path)]) == 0
    assert ics_path.is_file()
    assert validate_benjamins_json(json.loads(json_path.read_text())) == parse()


def test_report_combines_matches_and_actions_in_date_order(tmp_path: Path) -> None:
    schedule_path = tmp_path / "benjamins.json"
    schedule_path.write_text(
        json.dumps(export_benjamins_json(parse()), ensure_ascii=False), encoding="utf-8"
    )
    html_path = tmp_path / "report.html"
    assert report_main(
        [
            "--calendar", f"Seniores={REPORT_FIXTURES / 'calendar_a.json'}",
            "--calendar", f"Juniores={REPORT_FIXTURES / 'calendar_b.json'}",
            "--schedule", f"Benjamins={schedule_path}",
            "--html", str(html_path),
        ]
    ) == 0
    rendered = html_path.read_text()
    assert "Quadro de Ações 2026/2027" in rendered
    assert "Ação de Benjamins" not in rendered
    assert "Jogo/Ação" not in rendered
    assert ">Jogo<" in rendered
    assert "-----" not in rendered
    assert "FOCA &amp; Amigos" in rendered
    soup = BeautifulSoup(rendered, "html.parser")
    rows = [
        [cell.get_text(" ", strip=True) for cell in row.select("td")]
        for row in soup.select("tbody tr")
    ]
    dates = [
        date(*reversed([int(part) for part in row[0].split("/")]))
        for row in rows
    ]
    assert dates == sorted(dates)
    assert any(row[1:3] == ["Benjamins", "-"] for row in rows)
    assert all(len(row) == 5 for row in rows)
