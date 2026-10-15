from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_production_update.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("run_production_update", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
runner = importlib.util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = runner
SCRIPT_SPEC.loader.exec_module(runner)


def fpn_calendar(**overrides: Any) -> runner.CalendarConfig:
    values = {
        "source": "fpn",
        "calendar_id": "fpn_po01_26-27_foca",
        "ics_filename": "foca-seniores-a1.ics",
        "params": {"domain": "po01_26-27", "team": "FOCA"},
    }
    values.update(overrides)
    return runner.CalendarConfig(**values)


def annp_calendar(**overrides: Any) -> runner.CalendarConfig:
    values = {
        "source": "annp",
        "calendar_id": "annp_2627_juniores_foca",
        "ics_filename": "foca-juniores-annp.ics",
        "params": {"season": "2627", "team": "FOCA", "competition_id": "1"},
    }
    values.update(overrides)
    return runner.CalendarConfig(**values)


def config_item(calendar: runner.CalendarConfig) -> dict[str, Any]:
    return {
        "source": calendar.source,
        "calendar_id": calendar.calendar_id,
        "ics_filename": calendar.ics_filename,
        "params": dict(calendar.params),
    }


def write_config(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    path = tmp_path / "calendars.json"
    path.write_text(json.dumps({"calendars": items}), encoding="utf-8")
    return path


def match_payload(calendar: runner.CalendarConfig, external_id: str = "game-1") -> dict[str, Any]:
    return {
        "external_id": external_id,
        "source": calendar.expected_source,
        "source_url": None,
        "season": calendar.expected_season,
        "category": "Seniores",
        "competition": "Campeonato",
        "home": "FOCA",
        "away": "Visitante",
        "date": "2026-10-10",
        "time": "16:00:00",
        "location": "Piscina",
        "score_home": None,
        "score_away": None,
        "status": "SCHEDULED",
    }


def json_payload(
    calendar: runner.CalendarConfig,
    external_ids: tuple[str, ...] = ("game-1",),
) -> dict[str, Any]:
    matches = [match_payload(calendar, external_id) for external_id in external_ids]
    return {
        "generated_at": "2026-10-13T10:00:00Z",
        "source": calendar.expected_source,
        "match_count": len(matches),
        "matches": matches,
    }


def import_response(**overrides: Any) -> dict[str, Any]:
    payload = {
        "calendar_id": "fpn_po01_26-27_foca",
        "matches_found": 14,
        "created": 0,
        "updated": 0,
        "unchanged": 14,
        "mapped": 14,
        "unresolved": 0,
        "resolution_status": "MAPPED",
        "resolution_reasons": [],
        "team_id": None,
    }
    payload.update(overrides)
    return payload


def ics_content(calendar: runner.CalendarConfig, external_ids: tuple[str, ...] = ("game-1",)) -> str:
    events = "".join(
        "BEGIN:VEVENT\n"
        f"UID:{calendar.expected_source}-{external_id}@waterpolo\n"
        "END:VEVENT\n"
        for external_id in external_ids
    )
    return f"BEGIN:VCALENDAR\n{events}END:VCALENDAR\n"


def write_artifacts_from_command(command: list[str], calendar: runner.CalendarConfig) -> None:
    json_path = Path(command[command.index("--json-output") + 1])
    ics_path = Path(command[command.index("--ics-output") + 1])
    json_path.write_text(json.dumps(json_payload(calendar)), encoding="utf-8")
    ics_path.write_text(ics_content(calendar), encoding="utf-8")


class FakeAPI:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, int]] = []

    def import_calendar(self, calendar_id: str, *, expected_total: int) -> runner.ImportCounts:
        self.calls.append((calendar_id, expected_total))
        if self.failure is not None:
            raise self.failure
        return runner.ImportCounts(total=expected_total, mapped=expected_total, unresolved=0)


def runner_paths(tmp_path: Path) -> runner.RunnerPaths:
    return runner.RunnerPaths(
        wp_stats_calendar_dir=tmp_path / "wp-stats",
        staging_dir=tmp_path / "staging",
        current_dir=tmp_path / "current",
        public_ics_dir=tmp_path / "public",
    )


def test_load_config_accepts_current_fpn_format(tmp_path: Path) -> None:
    path = write_config(tmp_path, [config_item(fpn_calendar())])

    calendars = runner.load_config(path)

    assert calendars == [fpn_calendar()]
    assert calendars[0].expected_season == "S2627"


def test_load_config_accepts_annp_format(tmp_path: Path) -> None:
    path = write_config(tmp_path, [config_item(annp_calendar())])

    calendars = runner.load_config(path)

    assert calendars == [annp_calendar()]
    assert calendars[0].expected_season == "S2627"


def test_load_config_rejects_unknown_source(tmp_path: Path) -> None:
    item = config_item(fpn_calendar())
    item["source"] = "other"

    with pytest.raises(runner.ConfigError, match="source desconhecida"):
        runner.load_config(write_config(tmp_path, [item]))


def test_load_config_rejects_incomplete_fpn_params(tmp_path: Path) -> None:
    item = config_item(fpn_calendar())
    item["params"] = {"team": "FOCA"}

    with pytest.raises(runner.ConfigError, match="domain"):
        runner.load_config(write_config(tmp_path, [item]))


def test_load_config_rejects_incomplete_annp_params(tmp_path: Path) -> None:
    item = config_item(annp_calendar())
    item["params"] = {"season": "2627", "team": "FOCA"}

    with pytest.raises(runner.ConfigError, match="competition_id"):
        runner.load_config(write_config(tmp_path, [item]))


def test_build_publish_command_fpn(tmp_path: Path) -> None:
    command = runner.build_publish_command(
        fpn_calendar(), tmp_path / "out.json", tmp_path / "out.ics"
    )

    assert command == [
        sys.executable,
        "-m",
        "waterpolo.main",
        "publish",
        "fpn",
        "--domain",
        "po01_26-27",
        "--team",
        "FOCA",
        "--json-output",
        str(tmp_path / "out.json"),
        "--ics-output",
        str(tmp_path / "out.ics"),
    ]


def test_build_publish_command_annp(tmp_path: Path) -> None:
    command = runner.build_publish_command(
        annp_calendar(), tmp_path / "out.json", tmp_path / "out.ics"
    )

    assert command[:6] == [sys.executable, "-m", "waterpolo.main", "publish", "annp", "--season"]
    assert command[6:] == [
        "2627",
        "--team",
        "FOCA",
        "--competition-id",
        "1",
        "--json-output",
        str(tmp_path / "out.json"),
        "--ics-output",
        str(tmp_path / "out.ics"),
    ]


def test_run_publish_success_uses_no_shell() -> None:
    observed: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    result = runner.run_publish(["python", "-m", "waterpolo.main"], run=fake_run)

    assert result.returncode == 0
    assert observed == {"capture_output": True, "text": True, "check": False}
    assert "shell" not in observed


def test_run_publish_failure_includes_captured_output() -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 7, "partial", "publish exploded")

    with pytest.raises(runner.PublishError, match=r"exit code 7.*publish exploded"):
        runner.run_publish(["python"], run=fake_run)


def test_validate_json_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "calendar.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON inválido"):
        runner.validate_json(path, fpn_calendar())


def test_validate_json_rejects_empty_calendar(tmp_path: Path) -> None:
    calendar = fpn_calendar()
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(json_payload(calendar, ())), encoding="utf-8")

    with pytest.raises(ValueError, match="calendário vazio"):
        runner.validate_json(path, calendar)


def test_validate_json_rejects_duplicate_external_id(tmp_path: Path) -> None:
    calendar = fpn_calendar()
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(json_payload(calendar, ("same", "same"))), encoding="utf-8")

    with pytest.raises(ValueError, match="external_id duplicado"):
        runner.validate_json(path, calendar)


def test_validate_ics_rejects_invalid_envelope(tmp_path: Path) -> None:
    path = tmp_path / "calendar.ics"
    path.write_text("BEGIN:VEVENT\nEND:VEVENT\n", encoding="utf-8")

    with pytest.raises(ValueError, match="BEGIN:VCALENDAR"):
        runner.validate_ics(path, payload=json_payload(fpn_calendar()), source="fpn")


def test_validate_ics_rejects_duplicate_uid(tmp_path: Path) -> None:
    calendar = fpn_calendar()
    path = tmp_path / "calendar.ics"
    path.write_text(ics_content(calendar, ("same", "same")), encoding="utf-8")
    payload = json_payload(calendar, ("one", "two"))

    with pytest.raises(ValueError, match="UID duplicado"):
        runner.validate_ics(path, payload=payload, source="fpn")


def test_validate_ics_rejects_json_ics_count_mismatch(tmp_path: Path) -> None:
    calendar = fpn_calendar()
    path = tmp_path / "calendar.ics"
    path.write_text(ics_content(calendar), encoding="utf-8")
    payload = json_payload(calendar, ("one", "two"))

    with pytest.raises(ValueError, match="esperados 2 VEVENT"):
        runner.validate_ics(path, payload=payload, source="fpn")


def test_login_success_uses_expected_contract() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "secret-token"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        token = runner.login(
            client,
            runner.WPStatsConfig("https://stats.example.test", "user@example.test", "password"),
        )

    assert token == "secret-token"
    assert observed == {
        "path": "/api/v1/auth/login",
        "authorization": None,
        "body": {"email": "user@example.test", "password": "password"},
    }


def test_login_failure_is_reported_without_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "password=do-not-log"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(runner.WPStatsError, match="HTTP 401") as error,
    ):
        runner.login(
            client,
            runner.WPStatsConfig("https://stats.example.test", "user", "do-not-log"),
        )

    assert "do-not-log" not in str(error.value)


def test_import_http_error_and_request_has_no_json_body() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["body"] = request.content
        observed["authorization"] = request.headers["Authorization"]
        return httpx.Response(503, json={"detail": "unavailable"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(runner.WPStatsError, match="HTTP 503"),
    ):
        runner.import_calendar(
            client,
            runner.WPStatsConfig("https://stats.example.test", "user", "password"),
            token="bearer-value",
            calendar_id="calendar-one",
        )

    assert observed == {"body": b"", "authorization": "Bearer bearer-value"}


def test_validate_import_accepts_unchanged_matches() -> None:
    counts = runner.validate_import_response(
        import_response(),
        expected_calendar_id="fpn_po01_26-27_foca",
        expected_total=14,
    )

    assert counts == runner.ImportCounts(total=14, mapped=14, unresolved=0)


def test_validate_import_accepts_first_import() -> None:
    counts = runner.validate_import_response(
        import_response(created=14, unchanged=0),
        expected_calendar_id="fpn_po01_26-27_foca",
        expected_total=14,
    )

    assert counts == runner.ImportCounts(total=14, mapped=14, unresolved=0)


def test_validate_import_accepts_mixed_changes() -> None:
    counts = runner.validate_import_response(
        import_response(created=3, updated=4, unchanged=7),
        expected_calendar_id="fpn_po01_26-27_foca",
        expected_total=14,
    )

    assert counts == runner.ImportCounts(total=14, mapped=14, unresolved=0)


def test_validate_import_rejects_different_calendar_id() -> None:
    with pytest.raises(runner.WPStatsError, match="calendar_id"):
        runner.validate_import_response(
            import_response(calendar_id="another-calendar"),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_matches_found_different_from_json_count() -> None:
    with pytest.raises(runner.WPStatsError, match="artefacto validado contém 13"):
        runner.validate_import_response(
            import_response(),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=13,
        )


def test_validate_import_rejects_inconsistent_change_counts() -> None:
    with pytest.raises(runner.WPStatsError, match="created/updated/unchanged"):
        runner.validate_import_response(
            import_response(unchanged=13),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_inconsistent_resolution_counts() -> None:
    with pytest.raises(runner.WPStatsError, match="mapped/unresolved"):
        runner.validate_import_response(
            import_response(unresolved=1),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_unresolved_matches() -> None:
    with pytest.raises(runner.WPStatsError, match="jogos não resolvidos: unresolved=1"):
        runner.validate_import_response(
            import_response(mapped=13, unresolved=1),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_mapped_different_from_matches_found() -> None:
    with pytest.raises(runner.WPStatsError, match="mapped=13, matches_found=14"):
        runner.validate_import_response(
            import_response(mapped=13),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_non_mapped_resolution_status() -> None:
    with pytest.raises(runner.WPStatsError, match="resolution_status='MAPPED'"):
        runner.validate_import_response(
            import_response(resolution_status="UNRESOLVED"),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


@pytest.mark.parametrize(
    "missing_field",
    [
        "calendar_id",
        "matches_found",
        "created",
        "updated",
        "unchanged",
        "mapped",
        "unresolved",
        "resolution_status",
        "resolution_reasons",
    ],
)
def test_validate_import_rejects_missing_required_field(missing_field: str) -> None:
    payload = import_response()
    payload.pop(missing_field)

    with pytest.raises(runner.WPStatsError, match=missing_field):
        runner.validate_import_response(
            payload,
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("matches_found", "14"),
        ("created", True),
        ("updated", -1),
        ("unchanged", None),
        ("mapped", 14.0),
        ("unresolved", "0"),
        ("resolution_reasons", {}),
    ],
)
def test_validate_import_rejects_invalid_field_types(field: str, invalid_value: Any) -> None:
    with pytest.raises(runner.WPStatsError, match=field):
        runner.validate_import_response(
            import_response(**{field: invalid_value}),
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_validate_import_rejects_non_object_response() -> None:
    with pytest.raises(runner.WPStatsError, match="JSON inesperada"):
        runner.validate_import_response(
            [],
            expected_calendar_id="fpn_po01_26-27_foca",
            expected_total=14,
        )


def test_successful_pipeline_promotes_snapshot_and_public_ics(
    tmp_path: Path, caplog
) -> None:
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)
    api = FakeAPI()

    def publish(command: list[str]) -> None:
        write_artifacts_from_command(command, calendar)

    caplog.set_level(logging.INFO, logger="waterpolo.production")
    counts = runner.process_calendar(calendar, paths=paths, api=api, publish_runner=publish)

    assert counts == runner.ImportCounts(1, 1, 0)
    current_json = paths.current_dir / f"{calendar.calendar_id}.json"
    current_ics = paths.current_dir / calendar.ics_filename
    public_ics = paths.public_ics_dir / calendar.ics_filename
    assert json.loads(current_json.read_text())["match_count"] == 1
    assert current_ics.read_text(encoding="utf-8") == ics_content(calendar)
    assert public_ics.read_text(encoding="utf-8") == ics_content(calendar)
    assert not (paths.public_ics_dir / f"{calendar.calendar_id}.json").exists()
    installed = json.loads(
        (paths.wp_stats_calendar_dir / f"{calendar.calendar_id}.json").read_text()
    )
    assert installed["match_count"] == 1
    assert f"[{calendar.calendar_id}] promoting current snapshot" in caplog.text
    assert f"[{calendar.calendar_id}] publishing public ICS" in caplog.text
    assert f"[{calendar.calendar_id}] success" in caplog.text


def test_failure_before_import_preserves_current_and_public_files(tmp_path: Path) -> None:
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)
    current_json = paths.current_dir / f"{calendar.calendar_id}.json"
    current_ics = paths.current_dir / calendar.ics_filename
    public_ics = paths.public_ics_dir / calendar.ics_filename
    current_json.parent.mkdir(parents=True)
    public_ics.parent.mkdir(parents=True)
    current_json.write_text("old current JSON", encoding="utf-8")
    current_ics.write_text("old current ICS", encoding="utf-8")
    public_ics.write_text("old public ICS", encoding="utf-8")
    api = FakeAPI()

    def publish(command: list[str]) -> None:
        raise runner.PublishError("generation failed")

    with pytest.raises(runner.PublishError, match="generation failed"):
        runner.process_calendar(calendar, paths=paths, api=api, publish_runner=publish)

    assert api.calls == []
    assert current_json.read_text(encoding="utf-8") == "old current JSON"
    assert current_ics.read_text(encoding="utf-8") == "old current ICS"
    assert public_ics.read_text(encoding="utf-8") == "old public ICS"


def test_unresolved_import_preserves_current_public_and_wp_stats_files(
    tmp_path: Path,
) -> None:
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)
    current_json = paths.current_dir / f"{calendar.calendar_id}.json"
    current_ics = paths.current_dir / calendar.ics_filename
    current_ics.parent.mkdir(parents=True)
    current_json.write_text("last valid current JSON", encoding="utf-8")
    current_ics.write_text("last valid ICS", encoding="utf-8")
    public_ics = paths.public_ics_dir / calendar.ics_filename
    public_ics.parent.mkdir(parents=True)
    public_ics.write_text("last valid public ICS", encoding="utf-8")
    installed_json = paths.wp_stats_calendar_dir / f"{calendar.calendar_id}.json"
    installed_json.parent.mkdir(parents=True)
    installed_json.write_text("last valid JSON", encoding="utf-8")

    def publish(command: list[str]) -> None:
        write_artifacts_from_command(command, calendar)

    with pytest.raises(runner.WPStatsError, match="unresolved"):
        runner.process_calendar(
            calendar,
            paths=paths,
            api=FakeAPI(failure=runner.WPStatsError("unresolved=1")),
            publish_runner=publish,
        )

    assert current_json.read_text(encoding="utf-8") == "last valid current JSON"
    assert current_ics.read_text(encoding="utf-8") == "last valid ICS"
    assert public_ics.read_text(encoding="utf-8") == "last valid public ICS"
    assert installed_json.read_text(encoding="utf-8") == "last valid JSON"


def test_publication_failure_preserves_complete_files_and_leaves_no_temporary(
    tmp_path: Path, monkeypatch
) -> None:
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)
    current_json = paths.current_dir / f"{calendar.calendar_id}.json"
    current_ics = paths.current_dir / calendar.ics_filename
    public_ics = paths.public_ics_dir / calendar.ics_filename
    current_json.parent.mkdir(parents=True)
    public_ics.parent.mkdir(parents=True)
    current_json.write_text("old current JSON", encoding="utf-8")
    current_ics.write_text("old current ICS", encoding="utf-8")
    public_ics.write_text("old public ICS", encoding="utf-8")
    real_replace = runner.os.replace

    def fail_public_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == public_ics:
            raise OSError("public directory unavailable")
        real_replace(source, destination)

    def publish(command: list[str]) -> None:
        write_artifacts_from_command(command, calendar)

    monkeypatch.setattr(runner.os, "replace", fail_public_replace)

    with pytest.raises(OSError, match="public directory unavailable"):
        runner.process_calendar(calendar, paths=paths, api=FakeAPI(), publish_runner=publish)

    assert current_json.read_text(encoding="utf-8") == "old current JSON"
    assert current_ics.read_text(encoding="utf-8") == "old current ICS"
    assert public_ics.read_text(encoding="utf-8") == "old public ICS"
    assert list(paths.public_ics_dir.iterdir()) == [public_ics]


def test_public_ics_replacement_is_atomic(tmp_path: Path, monkeypatch) -> None:
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)
    public_ics = paths.public_ics_dir / calendar.ics_filename
    public_ics.parent.mkdir(parents=True)
    public_ics.write_text("old public ICS", encoding="utf-8")
    real_replace = runner.os.replace
    replacements: list[tuple[Path, Path]] = []

    def observed_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def publish(command: list[str]) -> None:
        write_artifacts_from_command(command, calendar)

    monkeypatch.setattr(runner.os, "replace", observed_replace)

    runner.process_calendar(calendar, paths=paths, api=FakeAPI(), publish_runner=publish)

    public_replacements = [item for item in replacements if item[1] == public_ics]
    assert len(public_replacements) == 1
    temporary, destination = public_replacements[0]
    assert destination == public_ics
    assert temporary.parent == public_ics.parent
    assert temporary != public_ics
    assert public_ics.read_text(encoding="utf-8") == ics_content(calendar)


def test_atomic_copy_uses_replace_and_leaves_no_temporary(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.json"
    destination = tmp_path / "target" / "calendar.json"
    source.write_text("new", encoding="utf-8")
    destination.parent.mkdir()
    destination.write_text("old", encoding="utf-8")
    real_replace = runner.os.replace
    replacements: list[tuple[Path, Path]] = []

    def observed_replace(source_path: str | Path, destination_path: str | Path) -> None:
        replacements.append((Path(source_path), Path(destination_path)))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(runner.os, "replace", observed_replace)

    runner.atomic_copy(source, destination)

    assert destination.read_text(encoding="utf-8") == "new"
    assert replacements[-1][1] == destination
    assert replacements[-1][0].parent == destination.parent
    assert list(destination.parent.glob("*.tmp")) == []


def test_two_calendars_are_processed_sequentially(tmp_path: Path, monkeypatch) -> None:
    calendars = [fpn_calendar(), annp_calendar()]
    order: list[str] = []

    def fake_process(calendar: runner.CalendarConfig, **kwargs: Any) -> runner.ImportCounts:
        order.append(calendar.calendar_id)
        return runner.ImportCounts(1, 1, 0)

    monkeypatch.setattr(runner, "process_calendar", fake_process)

    failed = runner.process_calendars(calendars, paths=runner_paths(tmp_path), api=FakeAPI())

    assert failed == []
    assert order == [calendar.calendar_id for calendar in calendars]


def test_failure_in_one_calendar_does_not_block_or_change_others(
    tmp_path: Path, monkeypatch
) -> None:
    first = fpn_calendar()
    second = annp_calendar()
    order: list[str] = []

    def fake_process(calendar: runner.CalendarConfig, **kwargs: Any) -> runner.ImportCounts:
        order.append(calendar.calendar_id)
        if calendar is first:
            raise runner.PublishError("source unavailable")
        return runner.ImportCounts(1, 1, 0)

    monkeypatch.setattr(runner, "process_calendar", fake_process)

    failed = runner.process_calendars(
        [first, second], paths=runner_paths(tmp_path), api=FakeAPI()
    )

    assert failed == [first.calendar_id]
    assert order == [first.calendar_id, second.calendar_id]


def test_process_lock_prevents_concurrent_execution(tmp_path: Path) -> None:
    lock_file = tmp_path / "calendar-update.lock"

    with (
        runner.process_lock(lock_file),
        pytest.raises(runner.LockUnavailable, match="execução ativa"),
        runner.process_lock(lock_file),
    ):
        pytest.fail("second lock must not be acquired")


def test_password_and_token_never_appear_in_logs(tmp_path: Path, caplog) -> None:
    password = "super-secret-password"
    token = "super-secret-token"
    calendar = fpn_calendar()
    paths = runner_paths(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": token})
        return httpx.Response(
            200,
            json=import_response(
                matches_found=1,
                unchanged=1,
                mapped=0,
                unresolved=1,
            ),
        )

    def publish(command: list[str]) -> None:
        write_artifacts_from_command(command, calendar)

    caplog.set_level(logging.INFO, logger="waterpolo.production")
    config = runner.WPStatsConfig("https://stats.example.test", "user", password)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        failed = runner.process_calendars(
            [calendar],
            paths=paths,
            api=runner.WPStatsAPI(config, client),
            publish_runner=publish,
        )

    assert failed == [calendar.calendar_id]
    assert password not in caplog.text
    assert token not in caplog.text


def test_fpn_and_annp_use_the_same_pipeline(tmp_path: Path) -> None:
    calendars = [fpn_calendar(), annp_calendar()]
    paths = runner_paths(tmp_path)
    api = FakeAPI()
    commands: list[list[str]] = []

    def publish(command: list[str]) -> None:
        commands.append(command)
        source = command[4]
        calendar = next(item for item in calendars if item.source == source)
        write_artifacts_from_command(command, calendar)

    failed = runner.process_calendars(
        calendars,
        paths=paths,
        api=api,
        publish_runner=publish,
    )

    assert failed == []
    assert [command[4] for command in commands] == ["fpn", "annp"]
    assert api.calls == [(calendars[0].calendar_id, 1), (calendars[1].calendar_id, 1)]
    for calendar in calendars:
        assert (paths.current_dir / f"{calendar.calendar_id}.json").exists()
        assert (paths.current_dir / calendar.ics_filename).exists()
        assert (paths.public_ics_dir / calendar.ics_filename).exists()
        assert not (paths.public_ics_dir / f"{calendar.calendar_id}.json").exists()


def test_load_environment_uses_file_with_environment_override(tmp_path: Path) -> None:
    env_file = tmp_path / "wp-stats.env"
    env_file.write_text(
        "WP_STATS_BASE_URL=https://from-file.example.test\n"
        "WP_STATS_EMAIL=file@example.test\n"
        "WP_STATS_PASSWORD='file password#value'\n",
        encoding="utf-8",
    )

    config = runner.load_environment(
        env_file,
        {"WP_STATS_EMAIL": "override@example.test"},
    )

    assert config.base_url == "https://from-file.example.test"
    assert config.email == "override@example.test"
    assert config.password == "file password#value"


def test_load_environment_uses_default_base_url_when_omitted(tmp_path: Path) -> None:
    env_file = tmp_path / "wp-stats.env"
    env_file.write_text(
        "WP_STATS_EMAIL=file@example.test\n"
        "WP_STATS_PASSWORD=file-password\n",
        encoding="utf-8",
    )

    config = runner.load_environment(env_file, {})

    assert config.base_url == "https://129.146.159.13"
    assert config.email == "file@example.test"
    assert config.password == "file-password"


def test_load_environment_explicit_base_url_overrides_default() -> None:
    config = runner.load_environment(
        None,
        {
            "WP_STATS_BASE_URL": "https://override.example.test",
            "WP_STATS_EMAIL": "runner@example.test",
            "WP_STATS_PASSWORD": "password",
        },
    )

    assert config.base_url == "https://override.example.test"


def test_load_environment_requires_email() -> None:
    with pytest.raises(runner.ConfigError, match="WP_STATS_EMAIL"):
        runner.load_environment(None, {"WP_STATS_PASSWORD": "password"})


def test_load_environment_requires_password() -> None:
    with pytest.raises(runner.ConfigError, match="WP_STATS_PASSWORD"):
        runner.load_environment(None, {"WP_STATS_EMAIL": "runner@example.test"})


def test_cli_defaults_match_production_layout() -> None:
    args = runner.build_parser().parse_args([])

    assert args.config == Path("/etc/waterpolo-calendar/calendars.json")
    assert args.wp_stats_calendar_dir == Path("/opt/wp-stats/data/calendars")
    assert args.staging_dir == Path("/var/lib/waterpolo/staging")
    assert args.current_dir == Path("/var/lib/waterpolo/current")
    assert args.public_ics_dir == Path("/var/www/waterpolo-calendars")
    assert args.lock_file == Path("/var/lib/waterpolo/calendar-update.lock")
