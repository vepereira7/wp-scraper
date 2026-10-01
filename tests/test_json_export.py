import json
from datetime import date, datetime, time
from pathlib import Path

from waterpolo.models import Match, MatchCategory, MatchSource
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


def test_json_exporter_has_no_fpn_dependency() -> None:
    exporter_source = (
        Path(__file__).parents[1] / "src" / "waterpolo" / "services" / "json_export.py"
    ).read_text()

    assert "waterpolo.scraper.fpn" not in exporter_source
