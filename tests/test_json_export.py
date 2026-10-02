import json
from datetime import date, datetime, time
from pathlib import Path

import pytest

from waterpolo.models import Match, MatchCategory, MatchSource
from waterpolo.scraper.fpn.models import FPNGame
from waterpolo.scraper.fpn.scraper import to_matches
from waterpolo.services.ics_export import export_matches_ics
from waterpolo.services.json_export import export_matches_json


def make_match() -> Match:
    return Match(
        external_id="fpn-123",
        source=MatchSource.FPN,
        source_url="https://example.test/fpn/123",
        season="2026/27",
        category=MatchCategory.U16,
        competition="Campeonato Nacional",
        home="FOCA",
        away="Vitória SC",
        date=date(2026, 10, 4),
        time=time(15, 0),
        location="Piscina Municipal",
        raw={"source_key": "source value"},
    )


def test_export_has_utc_generated_at_count_and_source() -> None:
    payload = export_matches_json([make_match()], source="FPN")

    generated_at = payload["generated_at"]
    assert isinstance(generated_at, str)
    assert generated_at.endswith("Z")
    parsed_timestamp = datetime.fromisoformat(generated_at)
    assert parsed_timestamp.utcoffset() is not None
    assert payload["match_count"] == 1
    assert payload["source"] == "FPN"


def test_export_is_json_serializable_and_excludes_raw_by_default() -> None:
    payload = export_matches_json([make_match()])

    json.dumps(payload)
    assert "raw" not in payload["matches"][0]


def test_export_includes_raw_when_requested() -> None:
    payload = export_matches_json([make_match()], include_raw=True)

    assert payload["matches"][0]["raw"] == {"source_key": "source value"}
    assert payload["matches"][0]["date"] == "2026-10-04"
    assert payload["matches"][0]["time"] == "15:00:00"


def test_export_preserves_missing_location_as_null() -> None:
    match = make_match().model_copy(update={"location": None})

    payload = export_matches_json([match])

    assert payload["matches"][0]["location"] is None


def test_json_export_preserves_normalized_category() -> None:
    labels = {
        MatchCategory.SENIOR: "Seniores",
        MatchCategory.JUNIOR: "Juniores",
        MatchCategory.INFANTIS: "Infantis",
        MatchCategory.JUVENIS: "Juvenis",
        MatchCategory.UNKNOWN: "Unknown",
    }
    for category, expected_label in labels.items():
        match = make_match().model_copy(update={"category": category})
        payload = export_matches_json([match])
        assert payload["matches"][0]["category"] == expected_label


def test_json_category_is_shared_label_for_ics(tmp_path: Path) -> None:
    match = make_match().model_copy(update={"category": MatchCategory.JUNIOR})
    json_category = export_matches_json([match])["matches"][0]["category"]
    ics_path = tmp_path / "matches.ics"
    export_matches_ics([match], ics_path)
    ics = ics_path.read_text().replace("\n ", "")
    description = next(line for line in ics.splitlines() if line.startswith("DESCRIPTION:"))

    assert json_category == "Juniores"
    assert f"Categoria: {json_category}" in description


@pytest.mark.parametrize(
    ("raw_category", "competition_name", "expected"),
    [
        ("senior", "CAMPEONATO PORTUGAL A2 MASCULINOS", "Seniores"),
        ("junior", "CAMPEONATO PORTUGAL JUNIORES MASCULINOS", "Juniores"),
        ("junior", "CAMPEONATO PORTUGAL JUNIOR 2025-2026", "Juniores"),
        ("junior", "CAMPEONATO PORTUGAL JÚNIOR 2025-2026", "Juniores"),
        ("under15", "CAMPEONATO INFANTIS", "Infantis"),
        ("under15", "CAMPEONATO PORTUGAL INFANTIL 2025-2026", "Infantis"),
        ("under15", "CAMPEONATO JUVENIS", "Juvenis"),
        ("under15", "CAMPEONATO PORTUGAL JUVENIL 2025-2026", "Juvenis"),
        ("under15", "CAMPEONATO SUB 15", "Unknown"),
        (None, "CAMPEONATO INFANTIS", "Infantis"),
        (None, "CAMPEONATO PORTUGAL X 2025-2026", "Unknown"),
    ],
)
def test_fpn_category_labels_are_shared_by_json_and_ics(
    tmp_path: Path,
    raw_category: str | None,
    competition_name: str,
    expected: str,
) -> None:
    game = FPNGame(
        id="game-category-test",
        competition_id="competition-category-test",
        competition_name=competition_name,
        competition_category=raw_category,
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name="CFP",
    )
    normalized_match = to_matches(
        [game],
        domain="po01_25-26",
        now=datetime.fromisoformat("2026-01-01T12:00:00"),
    )[0]

    json_category = export_matches_json([normalized_match])["matches"][0]["category"]
    ics_path = tmp_path / "category.ics"
    export_matches_ics([normalized_match], ics_path)
    ics = ics_path.read_text().replace("\n ", "")
    description = next(line for line in ics.splitlines() if line.startswith("DESCRIPTION:"))
    summary = next(line for line in ics.splitlines() if line.startswith("SUMMARY:"))
    expected_prefix = {
        "Seniores": "A2 |",
        "Juniores": "U18 |",
        "Juvenis": "U16 |",
        "Infantis": "U14 |",
        "Unknown": "Foca x CFP",
    }[expected]

    assert json_category == expected
    assert f"Categoria: {expected}" in description
    assert summary.startswith(f"SUMMARY:{expected_prefix}")
    assert json_category not in {"senior", "junior", "under15"}


def test_json_exporter_has_no_fpn_dependency() -> None:
    exporter_source = (
        Path(__file__).parents[1] / "src" / "waterpolo" / "services" / "json_export.py"
    ).read_text()

    assert "waterpolo.scraper.fpn" not in exporter_source
