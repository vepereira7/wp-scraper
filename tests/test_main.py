import json
from datetime import datetime
from pathlib import Path

from waterpolo.main import main
from waterpolo.scraper.fpn.models import FPNGame


def make_game() -> FPNGame:
    return FPNGame(
        id="game-1",
        competition_id="competition-1",
        competition_name="Campeonato Nacional",
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name="SCP B",
    )


def test_fpn_export_cli_writes_matches_json(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "nested" / "matches.json"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_team_games(self, *, domain: str, team: str):
            assert domain == "po02_25-26"
            assert team == "FOCA"
            return [make_game()]

    monkeypatch.setattr("waterpolo.main.FPNArenaClient", FakeClient)
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")

    result = main(
        [
            "export",
            "fpn",
            "--domain",
            "po02_25-26",
            "--team",
            "FOCA",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    payload = json.loads(output.read_text())
    assert payload["source"] == "FPN"
    assert payload["match_count"] == 1
    assert payload["matches"][0]["home"] == "FOCA"


def test_fpn_export_failure_does_not_create_output(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "matches.json"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_team_games(self, *, domain: str, team: str):
            raise OSError("collection failed")

    monkeypatch.setattr("waterpolo.main.FPNArenaClient", FakeClient)
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", log_dir)

    result = main(
        ["export", "fpn", "--domain", "domain", "--team", "FOCA", "--output", str(output)]
    )

    assert result == 1
    assert not output.exists()
    log = next(log_dir.glob("*.txt")).read_text()
    assert "Status: ERROR" in log
    assert "Traceback:" in log


def test_fpn_export_cli_writes_ics_and_success_log(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "matches.ics"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_team_games(self, *, domain: str, team: str):
            return [make_game()]

    monkeypatch.setattr("waterpolo.main.FPNArenaClient", FakeClient)
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", log_dir)

    assert main(
        ["export", "fpn", "--domain", "d", "--team", "FOCA", "--format", "ics", "--output", str(output)]
    ) == 0

    assert "BEGIN:VCALENDAR" in output.read_text()
    log = next(log_dir.glob("*.txt")).read_text()
    assert "Status: SUCCESS" in log
    assert "Nº jogos encontrados/exportados: 1" in log
    assert str(output) in log


def test_fpn_export_cli_rejects_invalid_format() -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["export", "fpn", "--domain", "d", "--team", "FOCA", "--format", "csv", "--output", "x.csv"])


def test_fpn_export_cli_rejects_incompatible_extension(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("waterpolo.main.RUN_LOG_DIR", tmp_path / "logs")
    result = main(
        ["export", "fpn", "--domain", "d", "--team", "FOCA", "--format", "ics", "--output", str(tmp_path / "wrong.json")]
    )
    assert result == 1
    log = next((tmp_path / "logs").glob("*.txt")).read_text()
    assert "Status: ERROR" in log
    assert "requer extensão .ics" in log


def test_logs_are_git_ignored() -> None:
    gitignore = Path(__file__).parents[1] / ".gitignore"
    assert "data/logs/" in gitignore.read_text()
