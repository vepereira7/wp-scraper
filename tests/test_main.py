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

    result = main(
        ["export", "fpn", "--domain", "domain", "--team", "FOCA", "--output", str(output)]
    )

    assert result == 1
    assert not output.exists()
