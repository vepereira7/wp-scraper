import json
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pytest

from waterpolo.main import main
from waterpolo.scraper.fpn.models import FPNGame
from waterpolo.services.validation import validate_ics_file


def make_game(game_id: str = "game-1") -> FPNGame:
    return FPNGame(
        id=game_id,
        competition_id="competition-1",
        competition_name="Campeonato Portugal A1",
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name=f"SCP {game_id}",
    )


class FakeClient:
    calls = 0
    games: ClassVar[list[FPNGame]] = [make_game()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get_team_games(self, *, domain: str, team: str):
        type(self).calls += 1
        assert domain == "po01_26-27"
        assert team == "FOCA"
        return list(type(self).games)


@pytest.fixture
def publish_setup(tmp_path: Path, monkeypatch):
    FakeClient.calls = 0
    FakeClient.games = [make_game()]
    monkeypatch.setattr("waterpolo.main.FPNArenaClient", FakeClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    json_output = tmp_path / "published" / "fpn_po01_26-27_foca.json"
    ics_output = tmp_path / "published" / "foca-seniores-a1.ics"
    return json_output, ics_output


def run_publish(json_output: Path, ics_output: Path) -> int:
    return main(
        [
            "publish",
            "fpn",
            "--domain",
            "po01_26-27",
            "--team",
            "FOCA",
            "--json-output",
            str(json_output),
            "--ics-output",
            str(ics_output),
        ]
    )


def test_publish_collects_once_and_both_outputs_use_same_snapshot(publish_setup) -> None:
    json_output, ics_output = publish_setup

    assert run_publish(json_output, ics_output) == 0
    assert FakeClient.calls == 1

    payload = json.loads(json_output.read_text())
    assert payload["match_count"] == 1
    external_id = payload["matches"][0]["external_id"]
    ics = ics_output.read_text()
    assert f"UID:FPN-{external_id}@waterpolo" in ics
    assert ics.count("BEGIN:VEVENT") == payload["match_count"]
    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics


def test_empty_response_is_rejected_and_preserves_previous_outputs(publish_setup) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")
    FakeClient.games = []

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_duplicate_external_id_is_rejected(publish_setup) -> None:
    json_output, ics_output = publish_setup
    FakeClient.games = [make_game("duplicate"), make_game("duplicate")]

    assert run_publish(json_output, ics_output) == 1
    assert not json_output.exists()
    assert not ics_output.exists()


def test_invalid_json_does_not_replace_previous_outputs(publish_setup, monkeypatch) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")
    monkeypatch.setattr("waterpolo.main.export_matches_json", lambda *args, **kwargs: {})

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_invalid_ics_does_not_replace_previous_outputs(publish_setup, monkeypatch) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")

    def write_invalid_ics(matches, output_path, **kwargs):
        output_path.write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n")

    monkeypatch.setattr("waterpolo.main.export_matches_ics", write_invalid_ics)

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_failure_generating_second_artifact_does_not_publish_first(
    publish_setup, monkeypatch
) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")

    def fail_ics(*args, **kwargs):
        raise OSError("ICS generation failed")

    monkeypatch.setattr("waterpolo.main.export_matches_ics", fail_ics)

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_publication_replaces_both_outputs(publish_setup) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")

    assert run_publish(json_output, ics_output) == 0
    assert json.loads(json_output.read_text())["match_count"] == 1
    assert "BEGIN:VCALENDAR" in ics_output.read_text()


def test_rename_failure_rolls_back_both_outputs(publish_setup, monkeypatch) -> None:
    json_output, ics_output = publish_setup
    json_output.parent.mkdir(parents=True)
    json_output.write_text("old json")
    ics_output.write_text("old ics")
    from waterpolo.services import validation

    real_replace = validation.os.replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if Path(destination).resolve() == ics_output.resolve() and not failed:
            failed = True
            raise OSError("simulated second rename failure")
        return real_replace(source, destination)

    monkeypatch.setattr(validation.os, "replace", fail_once)

    assert run_publish(json_output, ics_output) == 1
    assert json_output.read_text() == "old json"
    assert ics_output.read_text() == "old ics"


def test_duplicate_uid_is_rejected_by_ics_validation(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.ics"
    path.write_text(
        """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:FPN-1@waterpolo
END:VEVENT
BEGIN:VEVENT
UID:FPN-1@waterpolo
END:VEVENT
END:VCALENDAR
"""
    )

    with pytest.raises(ValueError, match="UID duplicado"):
        validate_ics_file(path, expected_event_count=2)
