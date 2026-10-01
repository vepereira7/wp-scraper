from datetime import date, time
from pathlib import Path

from waterpolo.models import Match, MatchCategory, MatchSource, MatchStatus
from waterpolo.services.ics_export import export_matches_ics


def match(**overrides) -> Match:
    values = {
        "external_id": "technical-secret-123",
        "source": MatchSource.FPN,
        "season": "2025/26",
        "category": MatchCategory.SENIOR,
        "competition": "CAMPEONATO PORTUGAL A2 MASCULINOS",
        "home": "FOCA",
        "away": "CNPO B",
        "date": date(2026, 10, 4),
        "time": time(16, 0),
        "score_home": 18,
        "score_away": 11,
        "status": MatchStatus.COMPLETED,
    }
    return Match(**(values | overrides))


def test_export_matches_ics_writes_calendar_and_a2_summary(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "matches.ics"

    export_matches_ics([match()], output)

    ics = output.read_text()
    unfolded = ics.replace("\n ", "")
    for expected in (
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "X-WR-CALNAME:CAMPEONATO PORTUGAL A2 MASCULINOS",
        "NAME:CAMPEONATO PORTUGAL A2 MASCULINOS",
        "UID:FPN-technical-secret-123@waterpolo",
        "DTSTAMP:",
        "LAST-MODIFIED:",
        "SEQUENCE:0",
        "SUMMARY:A2 | Foca x CNPO B",
        "DTSTART:20261004T150000Z",
        "DTEND:20261004T170000Z",
        "DESCRIPTION:",
        "END:VEVENT",
        "END:VCALENDAR",
    ):
        assert expected in unfolded
    description = next(line for line in unfolded.splitlines() if line.startswith("DESCRIPTION:"))
    assert "18-11" not in description
    assert "Resultado" not in description
    assert "LOCATION:" not in ics
    assert "18-11" not in description
    assert "technical-secret-123" not in description
    assert "Categoria: Seniores" in description


def test_a1_summary_and_no_score_description(tmp_path: Path) -> None:
    output = tmp_path / "a1.ics"
    export_matches_ics(
        [
            match(
                competition="CAMPEONATO A1",
                away="SCP",
                score_home=None,
                score_away=None,
                status=MatchStatus.SCHEDULED,
            )
        ],
        output,
    )
    ics = output.read_text()
    assert "SUMMARY:A1 | Foca x SCP" in ics
    assert " vs " not in ics
    assert "18-11" not in ics


def test_formation_summaries_use_age_group_prefixes(tmp_path: Path) -> None:
    cases = (
        (MatchCategory.JUNIOR, "CAMPEONATO PORTUGAL JUNIORES MASCULINOS", "U18"),
        (MatchCategory.JUVENIS, "CAMPEONATO PORTUGAL JUVENIS", "U16"),
        (MatchCategory.INFANTIS, "CAMPEONATO PORTUGAL INFANTIS", "U14"),
    )
    for category, competition, prefix in cases:
        output = tmp_path / f"{prefix}.ics"
        export_matches_ics(
            [match(category=category, competition=competition, away="CFP", score_home=None, score_away=None)],
            output,
        )
        ics = output.read_text()
        assert f"SUMMARY:{prefix} | Foca x CFP" in ics
        assert f"X-WR-CALNAME:{competition}" in ics
        assert f"NAME:{competition}" in ics
        label = {
            MatchCategory.JUNIOR: "Juniores",
            MatchCategory.JUVENIS: "Juvenis",
            MatchCategory.INFANTIS: "Infantis",
        }[category]
        assert f"Categoria: {label}" in ics.replace("\n ", "")
        assert competition not in next(
            line for line in ics.splitlines() if line.startswith("SUMMARY:")
        )


def test_unknown_category_uses_competition_fallback_without_full_title(tmp_path: Path) -> None:
    output = tmp_path / "unknown.ics"
    export_matches_ics(
        [match(category=MatchCategory.UNKNOWN, competition="CAMPEONATO JUNIORES", away="CFP")],
        output,
    )
    ics = output.read_text()
    assert "SUMMARY:U18 | Foca x CFP" in ics


def test_ics_escapes_special_text_and_emits_location_only_when_known(tmp_path: Path) -> None:
    output = tmp_path / "special.ics"
    export_matches_ics(
        [match(competition="Copa, A2; Final\\Sul\nRonda", location="Piscina, Norte; Bloco\\A")],
        output,
    )
    ics = output.read_text()
    assert "Copa\\, A2\\; Final\\\\Sul\\nRonda" in ics
    assert "LOCATION:Piscina\\, Norte\\; Bloco\\\\A" in ics


def test_ics_exporter_has_no_fpn_dependency() -> None:
    source = (Path(__file__).parents[1] / "src/waterpolo/services/ics_export.py").read_text()
    assert "waterpolo.scraper.fpn" not in source


def test_uid_is_stable_when_match_date_changes(tmp_path: Path) -> None:
    original_path = tmp_path / "original.ics"
    changed_path = tmp_path / "changed.ics"
    export_matches_ics([match()], original_path)
    export_matches_ics([match(date=date(2026, 10, 11), time=time(18, 30))], changed_path)

    original = original_path.read_text()
    changed = changed_path.read_text()
    original_lines = original.splitlines()
    changed_lines = changed.splitlines()
    original_uid = next(line for line in original_lines if line.startswith("UID:"))
    changed_uid = next(line for line in changed_lines if line.startswith("UID:"))
    assert original_uid == changed_uid == "UID:FPN-technical-secret-123@waterpolo"
    assert next(line for line in original_lines if line.startswith("DTSTART:")) != next(
        line for line in changed_lines if line.startswith("DTSTART:")
    )
    assert next(line for line in original_lines if line.startswith("DTEND:")) != next(
        line for line in changed_lines if line.startswith("DTEND:")
    )
