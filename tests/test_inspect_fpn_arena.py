import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "inspect_fpn_arena.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("inspect_fpn_arena", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
INSPECT_SCRIPT = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(INSPECT_SCRIPT)
find_game = INSPECT_SCRIPT.find_game


def test_find_game_in_all_phases_by_number() -> None:
    payload = {
        "entity": {
            "phases": [
                {"id": "phase-1", "name": "1ª Fase", "games": []},
                {
                    "id": "phase-2",
                    "name": "2ª Fase",
                    "games": [{"id": "game-21", "gameNumber": 21}],
                },
            ]
        }
    }

    phase, game = find_game(payload, game_id=None, game_number=21)

    assert phase["id"] == "phase-2"
    assert game["id"] == "game-21"


def test_find_game_reports_duplicate_game_number_candidates() -> None:
    payload = {
        "entity": {
            "phases": [
                {"id": "phase-1", "name": "One", "games": [{"id": "a", "gameNumber": 21}]},
                {"id": "phase-2", "name": "Two", "games": [{"id": "b", "gameNumber": 21}]},
            ]
        }
    }

    with pytest.raises(ValueError, match="ambíguo") as error:
        find_game(payload, game_id=None, game_number=21)

    assert '"id": "a"' in str(error.value)
    assert '"id": "b"' in str(error.value)


def test_find_game_reports_missing_id() -> None:
    with pytest.raises(ValueError, match="não encontrado"):
        find_game({"entity": {"phases": []}}, game_id="missing", game_number=None)
