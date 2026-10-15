import argparse
import base64
import hashlib
import json
import subprocess
from datetime import date, time
from pathlib import Path

import pytest

from waterpolo.models import Match, MatchCategory, MatchSource
from waterpolo.models.report import ReportMatch
from waterpolo.report.__main__ import main
from waterpolo.report.loader import load_calendar, parse_calendar_argument
from waterpolo.services.report_renderer import (
    LOGO_PATH,
    PDF_DOCKER_IMAGE,
    group_matches_by_month,
    paginate_month_groups,
    pdf_docker_command,
    render_html,
    sort_report_matches,
)

FIXTURES = Path(__file__).parent / "fixtures" / "report"


def make_report_match(
    *,
    external_id: str,
    match_date: date,
    match_time: time | None = None,
    label: str = "Seniores",
    home: str = "FOCA",
    away: str = "SCP",
    location: str | None = "Felgueiras",
    score_home: int | None = None,
    score_away: int | None = None,
) -> ReportMatch:
    match = Match(
        external_id=external_id,
        source=MatchSource.FPN,
        season="S2627",
        category=MatchCategory.SENIOR,
        competition="Campeonato",
        home=home,
        away=away,
        date=match_date,
        time=match_time,
        location=location,
        score_home=score_home,
        score_away=score_away,
    )
    return ReportMatch(label=label, match=match)


def test_parse_calendar_argument() -> None:
    assert parse_calendar_argument(" Juniores = data/calendar.json ") == (
        "Juniores",
        Path("data/calendar.json"),
    )


@pytest.mark.parametrize("value", ["calendar.json", "=calendar.json", "Seniores="])
def test_parse_calendar_argument_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_calendar_argument(value)


def test_loads_multiple_json_calendars_with_their_labels() -> None:
    senior = load_calendar("Seniores", FIXTURES / "calendar_a.json")
    junior = load_calendar("Juniores", FIXTURES / "calendar_b.json")

    assert len(senior + junior) == 3
    assert [item.label for item in senior + junior] == [
        "Seniores",
        "Seniores",
        "Juniores",
    ]


def test_global_sorting_uses_all_specified_keys() -> None:
    matches = [
        make_report_match(
            external_id="undefined-time",
            match_date=date(2026, 10, 17),
            match_time=None,
        ),
        make_report_match(
            external_id="away-z",
            match_date=date(2026, 10, 17),
            match_time=time(10),
            label="Juniores",
            home="FOCA",
            away="Z",
        ),
        make_report_match(
            external_id="away-a",
            match_date=date(2026, 10, 17),
            match_time=time(10),
            label="Juniores",
            home="FOCA",
            away="A",
        ),
        make_report_match(
            external_id="earlier-date",
            match_date=date(2026, 10, 16),
            match_time=None,
        ),
        make_report_match(
            external_id="later-time",
            match_date=date(2026, 10, 17),
            match_time=time(11),
            label="Juvenis",
        ),
    ]

    ordered = sort_report_matches(matches)

    assert [item.match.external_id for item in ordered] == [
        "earlier-date",
        "away-a",
        "away-z",
        "later-time",
        "undefined-time",
    ]


def test_grouping_uses_month_and_year() -> None:
    matches = [
        make_report_match(external_id="2027", match_date=date(2027, 1, 1)),
        make_report_match(external_id="2026", match_date=date(2026, 1, 1)),
    ]

    groups = group_matches_by_month(matches)

    assert [(group.year, group.month, group.heading) for group in groups] == [
        (2026, 1, "JANEIRO 2026"),
        (2027, 1, "JANEIRO 2027"),
    ]


def test_pagination_accounts_for_the_first_page_header() -> None:
    matches = [
        make_report_match(
            external_id=f"{month}-{index}",
            match_date=date(year, month, index + 1),
        )
        for year, month, count in (
            (2026, 10, 6),
            (2026, 11, 7),
            (2026, 12, 4),
            (2027, 1, 3),
        )
        for index in range(count)
    ]

    pages = paginate_month_groups(group_matches_by_month(matches))

    assert [[group.month for group in page] for page in pages] == [
        [10],
        [11, 12],
        [1],
    ]

def test_presentation_fallbacks_and_results() -> None:
    missing = make_report_match(
        external_id="missing",
        match_date=date(2026, 10, 17),
        location=None,
    )
    completed = make_report_match(
        external_id="completed",
        match_date=date(2026, 10, 18),
        match_time=time(9, 5),
        location="Fluvial",
        score_home=22,
        score_away=3,
    )

    assert missing.display_date == "17/10/2026"
    assert missing.display_time == "Por definir"
    assert missing.display_location == "Por definir"
    assert missing.display_result == "—"
    assert completed.display_time == "09:05"
    assert completed.display_location == "Fluvial"
    assert completed.display_result == "22–3"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "{}",
        '{"match_count": 0, "matches": []}',
        '{"match_count": 1, "matches": []}',
    ],
)
def test_load_calendar_rejects_empty_or_invalid_inputs(tmp_path: Path, content: str) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_calendar("Seniores", source)


def test_load_calendar_rejects_invalid_match_structure(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "calendar_b.json").read_text(encoding="utf-8"))
    payload["matches"][0]["date"] = "17/10/2026"
    source = tmp_path / "invalid-match.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="estrutura inválida"):
        load_calendar("Juniores", source)


def test_html_is_deterministic_and_matches_snapshot() -> None:
    matches = [
        *load_calendar("Seniores", FIXTURES / "calendar_a.json"),
        *load_calendar("Juniores", FIXTURES / "calendar_b.json"),
    ]

    first = render_html(matches)
    second = render_html(matches)

    assert first == second
    assert hashlib.sha256(first.encode()).hexdigest() == (
        "cc100127088b8dcc89d54d0cede37ac49eb4950154b5c3056c5f8964f5eac36e"
    )
    assert "Quadro de Ações 2026/2027" in first
    assert "OUTUBRO 2026" in first
    assert "JANEIRO 2027" in first
    assert "FOCA &amp; Amigos" in first
    assert "Resultado" not in first
    assert "generated_at" not in first


def test_html_embeds_the_versioned_logo_as_a_data_uri() -> None:
    matches = load_calendar("Juniores", FIXTURES / "calendar_b.json")

    rendered = render_html(matches)
    marker = 'src="data:image/png;base64,'
    encoded_logo = rendered.split(marker, maxsplit=1)[1].split('"', maxsplit=1)[0]

    assert base64.b64decode(encoded_logo) == LOGO_PATH.read_bytes()
    assert 'class="report-logo"' in rendered
    assert "width: 32mm" in rendered


def test_pdf_docker_command_forbids_network_and_remote_pulls(tmp_path: Path) -> None:
    html_source = tmp_path / "report.html"
    pdf_output = tmp_path / "report.pdf"
    html_source.touch()

    command = pdf_docker_command(html_source, pdf_output)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--pull=never" in command
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert PDF_DOCKER_IMAGE in command


def test_cli_requires_calendar_and_at_least_one_output() -> None:
    with pytest.raises(SystemExit):
        main(["--html", "report.html"])
    with pytest.raises(SystemExit):
        main(["--calendar", "Seniores=calendar.json"])


def test_cli_writes_html_and_creates_parent_directories(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "report.html"

    result = main(
        [
            "--calendar",
            f"Seniores={FIXTURES / 'calendar_a.json'}",
            "--html",
            str(output),
        ]
    )

    assert result == 0
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_returns_nonzero_for_missing_calendar(tmp_path: Path) -> None:
    result = main(
        [
            "--calendar",
            f"Seniores={tmp_path / 'missing.json'}",
            "--html",
            str(tmp_path / "report.html"),
        ]
    )

    assert result != 0


def test_cli_writes_pdf_from_temporary_html(tmp_path: Path) -> None:
    image = subprocess.run(
        ["docker", "image", "inspect", PDF_DOCKER_IMAGE],
        capture_output=True,
        check=False,
    )
    if image.returncode != 0:
        pytest.skip(f"imagem Docker local {PDF_DOCKER_IMAGE} não disponível")

    output = tmp_path / "nested" / "report.pdf"

    result = main(
        [
            "--calendar",
            f"Juniores={FIXTURES / 'calendar_b.json'}",
            "--pdf",
            str(output),
        ]
    )

    assert result == 0
    assert output.stat().st_size > 4
    assert output.read_bytes().startswith(b"%PDF")
