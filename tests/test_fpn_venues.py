from datetime import date, datetime, time
from pathlib import Path

import pytest

from waterpolo.models import Match, MatchCategory, MatchSource, MatchStatus
from waterpolo.scraper.fpn.models import FPNGame
from waterpolo.scraper.fpn.scraper import to_matches
from waterpolo.scraper.fpn.venues import (
    FPNVenueMapping,
    load_fpn_venue_mapping,
    load_fpn_venue_mapping_from_path,
    resolve_fpn_location,
)
from waterpolo.services.ics_export import export_matches_ics
from waterpolo.services.json_export import export_matches_json


def make_match(
    *,
    home: str = "FOCA",
    away: str = "SCP",
    external_id: str = "game-1",
    location: str | None = None,
    source: MatchSource = MatchSource.FPN,
) -> Match:
    return Match(
        external_id=external_id,
        source=source,
        season="2025/26",
        category=MatchCategory.SENIOR,
        competition="Competition",
        home=home,
        away=away,
        date=date(2026, 1, 1),
        time=time(12, 0),
        location=location,
        status=MatchStatus.SCHEDULED,
    )


def test_api_location_takes_precedence_over_override_and_team_mapping() -> None:
    mapping = FPNVenueMapping(
        team_venues={"FOCA": "Piscina da equipa"},
        match_overrides={"game-1": "Piscina override"},
    )

    resolved = resolve_fpn_location(
        make_match(location="  Piscina da API  "), mapping
    )

    assert resolved.location == "Piscina da API"


def test_specific_match_override_precedes_home_team_mapping() -> None:
    mapping = FPNVenueMapping(
        team_venues={"FOCA": "Piscina da equipa"},
        match_overrides={"game-1": "Piscina neutra"},
    )

    assert resolve_fpn_location(make_match(), mapping).location == "Piscina neutra"


def test_missing_location_uses_exact_case_and_space_insensitive_home_match() -> None:
    mapping = FPNVenueMapping(
        team_venues={"  fOcA   Clube ": "Felgueiras"},
        match_overrides={},
    )

    resolved = resolve_fpn_location(make_match(home=" FOCA   CLUBE "), mapping)

    assert resolved.location == "Felgueiras"


def test_unmapped_home_team_keeps_location_none() -> None:
    mapping = FPNVenueMapping(team_venues={"FOCA": "Piscina FOCA"}, match_overrides={})

    assert resolve_fpn_location(make_match(home="OUTRA"), mapping).location is None


@pytest.mark.parametrize("value", ["None", " null ", "b7d2f656-2794-4fd9-88d5-ef3a5ae7d350"])
def test_sentinel_or_uuid_is_never_used_as_location(value: str) -> None:
    mapping = FPNVenueMapping(team_venues={"FOCA": value}, match_overrides={})

    assert resolve_fpn_location(make_match(), mapping).location is None


def test_default_foca_mapping_is_used_during_fpn_conversion() -> None:
    game = FPNGame(
        id="foca-home",
        competition_id="competition-1",
        competition_name="Competição",
        competition_category="senior",
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name="SCP",
    )

    normalized = to_matches([game], domain="po01_25-26")[0]
    payload = export_matches_json([normalized])

    assert normalized.location == "Felgueiras"
    assert payload["matches"][0]["location"] == "Felgueiras"


def test_api_location_is_kept_in_fpn_conversion() -> None:
    game = FPNGame(
        id="api-location-game",
        competition_id="competition-1",
        competition_name="Competição",
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name="SCP",
        location="Piscina específica da API",
    )

    normalized = to_matches([game], domain="po01_25-26")[0]

    assert normalized.location == "Piscina específica da API"


def test_fpn_location_flows_to_common_ics_export(tmp_path: Path) -> None:
    game = FPNGame(
        id="foca-home-ics",
        competition_id="competition-1",
        competition_name="Competição",
        game_date=datetime.fromisoformat("2026-01-10T16:00:00"),
        home_team_name="FOCA",
        away_team_name="SCP",
    )
    normalized = to_matches([game], domain="po01_25-26")[0]
    output = tmp_path / "matches.ics"

    export_matches_ics([normalized], output)

    assert "LOCATION:Felgueiras" in output.read_text()


def test_ics_omits_location_when_match_location_is_none(tmp_path: Path) -> None:
    output = tmp_path / "matches.ics"
    export_matches_ics([make_match(location=None)], output)

    assert "LOCATION:" not in output.read_text()


def test_away_foca_uses_mapped_home_opponent_pool() -> None:
    mapping = FPNVenueMapping(
        team_venues={"FOCA": "Piscina FOCA", "SCP": "Piscina do SCP"},
        match_overrides={},
    )

    resolved = resolve_fpn_location(make_match(home="SCP", away="FOCA"), mapping)

    assert resolved.location == "Piscina do SCP"
    assert resolved.location != mapping.team_venues["FOCA"]


def test_away_foca_without_home_team_mapping_keeps_location_none() -> None:
    mapping = FPNVenueMapping(team_venues={"FOCA": "Felgueiras"}, match_overrides={})

    resolved = resolve_fpn_location(make_match(home="OUTRA", away="FOCA"), mapping)

    assert resolved.location is None


def test_fpn_mapping_does_not_apply_to_ANNP() -> None:
    mapping = FPNVenueMapping(team_venues={"FOCA": "Piscina FOCA"}, match_overrides={})

    resolved = resolve_fpn_location(make_match(source=MatchSource.ANNP), mapping)

    assert resolved.location is None


def test_default_venue_mapping_has_checked_in_configuration() -> None:
    assert load_fpn_venue_mapping().team_venues["FOCA"] == "Felgueiras"


def test_venue_mapping_loads_team_and_match_entries(tmp_path: Path) -> None:
    path = tmp_path / "venues.json"
    path.write_text(
        '{"team_venues":{"FOCA":" Piscina A "},"match_overrides":{"id-1":"Piscina B"}}'
    )

    mapping = load_fpn_venue_mapping_from_path(path)

    assert mapping.team_venues == {"FOCA": "Piscina A"}
    assert mapping.match_overrides == {"id-1": "Piscina B"}


def test_invalid_mapping_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "venues.json"
    path.write_text('{"team_venues":{"FOCA":null}}')

    with pytest.raises(ValueError, match="non-empty text pairs"):
        load_fpn_venue_mapping_from_path(path)


@pytest.mark.parametrize("path", ["services/json_export.py", "services/ics_export.py"])
def test_common_exporters_do_not_import_fpn_venue_resolution(path: str) -> None:
    source = Path(__file__).parents[1] / "src" / "waterpolo" / path
    code = source.read_text(encoding="utf-8")
    assert "waterpolo.scraper.fpn" not in code
    assert "resolve_fpn_location" not in code
