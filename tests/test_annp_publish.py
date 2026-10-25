from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path
from typing import ClassVar

from waterpolo.main import main
from waterpolo.scraper.annp.models import ANNPCompetition, ANNPGame


def make_game(
    game_id: str = "2627-1-stable",
    *,
    game_date: date = date(2026, 11, 1),
    game_time: time | None = time(15, 0),
    home: str = "CFP",
    away: str = "FOCA",
) -> ANNPGame:
    return ANNPGame(
        id=game_id,
        competition_id="1",
        competition_name="Juniores Masculinos",
        competition_category="Juniores Masculinos",
        date=game_date,
        time=game_time,
        home_team_name=home,
        away_team_name=away,
        location="Fluvial",
        state="Agendado",
        source_url="https://provas.annp.pt/polo/20262027/calendario/1",
    )


class FakeANNPClient:
    calls = 0
    games: ClassVar[list[ANNPGame]] = [make_game()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_team_games(self, **kwargs):
        type(self).calls += 1
        assert kwargs == {
            "season": "2627",
            "team": "FOCA",
            "category": None,
            "competition_id": "1",
        }
        return (
            ANNPCompetition(
                id="1",
                name="Juniores Masculinos",
                category="Juniores Masculinos",
            ),
            list(type(self).games),
        )


def run_publish(json_output: Path, ics_output: Path) -> int:
    return main(
        [
            "publish",
            "annp",
            "--season",
            "2627",
            "--team",
            "FOCA",
            "--competition-id",
            "1",
            "--json-output",
            str(json_output),
            "--ics-output",
            str(ics_output),
        ]
    )


def test_annp_publish_uses_shared_json_ics_contract(tmp_path: Path, monkeypatch) -> None:
    FakeANNPClient.calls = 0
    FakeANNPClient.games = [make_game()]
    monkeypatch.setattr("waterpolo.main.ANNPClient", FakeANNPClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    json_output = tmp_path / "published" / "annp-juniores.json"
    ics_output = tmp_path / "published" / "annp-juniores.ics"

    assert run_publish(json_output, ics_output) == 0
    assert FakeANNPClient.calls == 1
    payload = json.loads(json_output.read_text())
    assert payload["source"] == "ANNP"
    assert payload["match_count"] == 1
    assert payload["matches"][0]["source"] == "ANNP"
    assert payload["matches"][0]["season"] == "S2627"
    assert payload["matches"][0]["category"] == "Sub-18"
    assert payload["matches"][0]["external_id"] == "2627-1-stable"
    ics = ics_output.read_text()
    assert "UID:ANNP-2627-1-stable@waterpolo" in ics
    assert ics.count("BEGIN:VEVENT") == payload["match_count"]


def test_annp_unknown_time_can_be_published_then_updated_in_place(
    tmp_path: Path, monkeypatch
) -> None:
    FakeANNPClient.calls = 0
    FakeANNPClient.games = [
        make_game(
            game_date=date(2026, 12, 12),
            game_time=None,
            home="PPA",
        )
    ]
    monkeypatch.setattr("waterpolo.main.ANNPClient", FakeANNPClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    unknown_json = tmp_path / "unknown.json"
    unknown_ics = tmp_path / "unknown.ics"

    assert run_publish(unknown_json, unknown_ics) == 0

    unknown_payload = json.loads(unknown_json.read_text())
    unknown_match = unknown_payload["matches"][0]
    unknown_calendar = unknown_ics.read_text().replace("\n ", "")
    unknown_uid = next(
        line for line in unknown_calendar.splitlines() if line.startswith("UID:")
    )
    assert unknown_match["date"] == "2026-12-12"
    assert unknown_match["time"] is None
    assert "DTSTART;VALUE=DATE:20261212" in unknown_calendar
    assert "DTEND;VALUE=DATE:20261213" in unknown_calendar
    assert "T000000" not in unknown_calendar
    assert "Hora: por definir" in unknown_calendar

    FakeANNPClient.games = [
        make_game(
            game_date=date(2026, 12, 12),
            game_time=time(16, 0),
            home="PPA",
        )
    ]
    timed_json = tmp_path / "timed.json"
    timed_ics = tmp_path / "timed.ics"

    assert run_publish(timed_json, timed_ics) == 0

    timed_match = json.loads(timed_json.read_text())["matches"][0]
    timed_calendar = timed_ics.read_text().replace("\n ", "")
    timed_uid = next(
        line for line in timed_calendar.splitlines() if line.startswith("UID:")
    )
    assert timed_match["time"] == "16:00:00"
    assert timed_match["external_id"] == unknown_match["external_id"]
    assert timed_uid == unknown_uid == "UID:ANNP-2627-1-stable@waterpolo"
    assert "DTSTART:20261212T160000Z" in timed_calendar
    assert "DTSTART;VALUE=DATE" not in timed_calendar


def test_annp_empty_response_preserves_previous_outputs(tmp_path: Path, monkeypatch) -> None:
    FakeANNPClient.games = []
    monkeypatch.setattr("waterpolo.main.ANNPClient", FakeANNPClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    json_output = tmp_path / "published" / "annp.json"
    ics_output = tmp_path / "published" / "annp.ics"
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_annp_duplicate_external_ids_are_rejected(tmp_path: Path, monkeypatch) -> None:
    FakeANNPClient.games = [make_game(), make_game()]
    monkeypatch.setattr("waterpolo.main.ANNPClient", FakeANNPClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    json_output = tmp_path / "annp.json"
    ics_output = tmp_path / "annp.ics"

    assert run_publish(json_output, ics_output) == 1
    assert not json_output.exists()
    assert not ics_output.exists()
