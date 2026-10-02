import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import httpx
import pytest

from waterpolo.models import MatchCategory, MatchStatus
from waterpolo.scraper.fpn import (
    FPNArenaClient,
    FPNArenaHTTPError,
    FPNCompetitionNotFoundError,
    FPNGame,
    FPNGameStructureError,
    FPNResponseError,
)
from waterpolo.scraper.fpn.scraper import (
    filter_team_games,
    find_team_identities,
    map_fpn_category,
    parse_competition,
    parse_game,
    to_matches,
)
from waterpolo.scraper.fpn.venues import FPNVenueMapping

COMPETITION_ID = "competition-123"
COMPETITION_NAME = "Campeonato Portugal A2 Masculinos"
FOCA_ID = "foca-team-id-from-api"


def competition_response() -> dict[str, Any]:
    return {
        "entity": {
            "id": COMPETITION_ID,
            "displayName": COMPETITION_NAME,
            "category": "senior",
        }
    }


def team(index: int, team_id: str, name: str, score: int | None) -> dict[str, Any]:
    return {
        "teamIndex": index,
        "teamId": team_id,
        "score": score,
        "team": {"id": team_id, "name": name, "displayName": name},
    }


def game_response(
    game_id: str = "game-1",
    *,
    home_name: str = "FOCA",
    away_name: str = "SCP B",
    home_score: int | None = 12,
    away_score: int | None = 9,
) -> dict[str, Any]:
    home_id = FOCA_ID if home_name == "FOCA" else f"{home_name}-id"
    away_id = FOCA_ID if away_name == "FOCA" else f"{away_name}-id"
    return {
        "id": game_id,
        "gameDate": "2026-01-10T16:00:00",
        "gameNumber": 9,
        "journey": 2,
        "round": 1,
        "location": {"name": "Piscina Municipal"},
        "state": "1",
        "homeTeamPlaceholder": home_name,
        "awayTeamPlaceholder": away_name,
        "gameTeams": [
            team(1, home_id, home_name, home_score),
            team(2, away_id, away_name, away_score),
        ],
    }


def parse_test_game(payload: dict[str, Any]) -> FPNGame:
    return parse_game(
        payload,
        competition_id=COMPETITION_ID,
        competition_name=COMPETITION_NAME,
        competition_category="senior",
    )


@contextmanager
def mocked_client(handler: httpx.MockTransport) -> Iterator[FPNArenaClient]:
    with httpx.Client(
        base_url="https://api-web.arenadisplay.test",
        transport=handler,
    ) as http_client:
        yield FPNArenaClient(client=http_client)


def test_get_competition_resolves_domain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/competition/GetByDomain/po02_25-26"
        return httpx.Response(200, json=competition_response())

    with mocked_client(httpx.MockTransport(handler)) as client:
        competition = client.get_competition("po02_25-26")

    assert competition.id == COMPETITION_ID
    assert competition.name == COMPETITION_NAME
    assert competition.domain == "po02_25-26"


def test_parse_competition() -> None:
    competition = parse_competition(competition_response(), "po02_25-26")

    assert competition.model_dump() == {
        "id": COMPETITION_ID,
        "name": COMPETITION_NAME,
        "domain": "po02_25-26",
        "category": "senior",
    }


def test_parse_game() -> None:
    game = parse_test_game(game_response())

    assert game.id == "game-1"
    assert game.competition_id == COMPETITION_ID
    assert game.competition_name == COMPETITION_NAME
    assert game.game_number == 9
    assert game.journey == 2
    assert game.round == 1
    assert game.game_date == datetime.fromisoformat("2026-01-10T16:00:00")
    assert game.location == "Piscina Municipal"
    assert game.state == "1"


def test_home_and_away_use_team_index_not_array_order() -> None:
    payload = game_response(home_name="FOCA", away_name="SCP B")
    payload["gameTeams"].reverse()

    game = parse_test_game(payload)

    assert game.home_team_id == FOCA_ID
    assert game.home_team_name == "FOCA"
    assert game.away_team_name == "SCP B"


def test_game_with_score() -> None:
    game = parse_test_game(game_response(home_score=17, away_score=8))

    assert game.home_score == 17
    assert game.away_score == 8


def test_to_matches_maps_senior_category_and_completed_result() -> None:
    payload = game_response(
        home_name="FOCA", away_name="CNPO B", home_score=18, away_score=11
    )
    payload["gameTeams"].reverse()
    game = parse_test_game(payload)

    match = to_matches([game], season="2025/26")[0]

    assert match.category is MatchCategory.SENIOR
    assert match.home == "FOCA"
    assert match.away == "CNPO B"
    assert match.score_home == 18
    assert match.score_away == 11
    assert match.status is MatchStatus.COMPLETED


def test_to_matches_maps_unknown_competition_category() -> None:
    game = parse_game(
        game_response(),
        competition_id=COMPETITION_ID,
        competition_name=COMPETITION_NAME,
        competition_category="youth-unknown",
    )

    assert to_matches([game], season="2025/26")[0].category is MatchCategory.UNKNOWN


@pytest.mark.parametrize(
    ("raw_category", "display_name", "expected"),
    [
        ("senior", "CAMPEONATO PORTUGAL A2 MASCULINOS", MatchCategory.SENIOR),
        (" Senior ", "qualquer competição", MatchCategory.SENIOR),
        ("junior", "CAMPEONATO NACIONAL JUNIORES", MatchCategory.JUNIOR),
        ("under15", "CAMPEONATO INFANTIS", MatchCategory.INFANTIS),
        ("under15", "CAMPEONATO JUVENIS", MatchCategory.JUVENIS),
        ("under15", "CAMPEONATO SUB 15", MatchCategory.UNKNOWN),
        ("under15", "INFANTIS E JUVENIS", MatchCategory.UNKNOWN),
        (None, "CAMPEONATO INFANTIS", MatchCategory.INFANTIS),
        ("", "CAMPEONATO INFANTIS", MatchCategory.INFANTIS),
        ("unknown", "CAMPEONATO JUVENIS", MatchCategory.JUVENIS),
        ("under15", "campeonato infantis", MatchCategory.INFANTIS),
        ("under15", "CAMPEONATO PORTUGAL INFANTIL 2025-2026", MatchCategory.INFANTIS),
        ("under15", "Campeonato   Infantis", MatchCategory.INFANTIS),
        ("under15", "CAMPEONATO PORTUGAL JUVENIL 2025-2026", MatchCategory.JUVENIS),
        ("under15", "Campeonato Juvénis", MatchCategory.JUVENIS),
        ("under15", "CAMPEONATO PORTUGAL JUVENIS 2025-2026", MatchCategory.JUVENIS),
        ("junior", "CAMPEONATO PORTUGAL JUNIOR 2025-2026", MatchCategory.JUNIOR),
        ("junior", "CAMPEONATO PORTUGAL JUNIORES 2025-2026", MatchCategory.JUNIOR),
        ("junior", "CAMPEONATO PORTUGAL JÚNIOR 2025-2026", MatchCategory.JUNIOR),
    ],
)
def test_map_fpn_category(
    raw_category: str | None, display_name: str, expected: MatchCategory
) -> None:
    assert map_fpn_category(raw_category, display_name) is expected


def test_future_zero_zero_is_scheduled_without_scores() -> None:
    payload = game_response(home_score=0, away_score=0)
    payload["gameDate"] = "2026-02-07T16:00:00"
    game = parse_test_game(payload)

    match = to_matches(
        [game], season="2025/26", now=datetime.fromisoformat("2026-02-07T15:00:00")
    )[0]

    assert match.score_home is None
    assert match.score_away is None
    assert match.status is MatchStatus.SCHEDULED


def test_past_zero_zero_is_completed_with_zero_scores() -> None:
    payload = game_response(home_score=0, away_score=0)
    payload["gameDate"] = "2026-02-07T14:00:00"
    game = parse_test_game(payload)

    match = to_matches(
        [game], season="2025/26", now=datetime.fromisoformat("2026-02-07T15:00:00")
    )[0]

    assert match.score_home == 0
    assert match.score_away == 0
    assert match.status is MatchStatus.COMPLETED


def test_future_nonzero_scores_are_completed() -> None:
    payload = game_response(home_score=3, away_score=2)
    payload["gameDate"] = "2026-02-07T16:00:00"
    game = parse_test_game(payload)

    match = to_matches(
        [game], season="2025/26", now=datetime.fromisoformat("2026-02-07T15:00:00")
    )[0]

    assert match.score_home == 3
    assert match.score_away == 2
    assert match.status is MatchStatus.COMPLETED


def test_past_nonzero_scores_are_completed() -> None:
    payload = game_response(home_score=3, away_score=2)
    payload["gameDate"] = "2026-02-07T14:00:00"
    game = parse_test_game(payload)

    match = to_matches(
        [game], season="2025/26", now=datetime.fromisoformat("2026-02-07T15:00:00")
    )[0]

    assert match.score_home == 3
    assert match.score_away == 2
    assert match.status is MatchStatus.COMPLETED


def test_game_without_teams_keeps_scores_missing_and_is_not_completed() -> None:
    payload = game_response()
    payload["gameTeams"] = None
    payload["state"] = "2"

    match = to_matches(
        [parse_test_game(payload)],
        season="2025/26",
        venue_mapping=FPNVenueMapping(team_venues={}, match_overrides={}),
    )[0]

    assert match.score_home is None
    assert match.score_away is None
    assert match.status is MatchStatus.SCHEDULED


def test_game_with_only_one_score_keeps_both_scores_missing() -> None:
    payload = game_response()
    payload["gameTeams"] = [team(1, FOCA_ID, "FOCA", 18)]

    match = to_matches([parse_test_game(payload)], season="2025/26")[0]

    assert match.score_home is None
    assert match.score_away is None
    assert match.status is MatchStatus.SCHEDULED


def test_null_location_stays_null_in_match() -> None:
    payload = game_response()
    payload["location"] = None

    match = to_matches(
        [parse_test_game(payload)],
        season="2025/26",
        venue_mapping=FPNVenueMapping(team_venues={}, match_overrides={}),
    )[0]

    assert match.location is None


def test_unplayed_game_with_null_scores() -> None:
    game = parse_test_game(game_response(home_score=None, away_score=None))

    assert game.home_score is None
    assert game.away_score is None


def test_game_allows_missing_optional_fields() -> None:
    game = parse_test_game({"id": "minimal-game"})

    assert game.game_date is None
    assert game.home_team_id is None
    assert game.home_team_name is None
    assert game.home_score is None
    assert game.away_team_id is None
    assert game.away_team_name is None
    assert game.away_score is None
    assert game.location is None
    assert game.state is None


def test_game_preserves_null_location_from_api() -> None:
    payload = game_response()
    payload["location"] = None

    game = parse_test_game(payload)

    assert game.location is None


def test_filter_foca_as_home() -> None:
    games = [
        parse_test_game(game_response("foca-home")),
        parse_test_game(game_response("other", home_name="CAP", away_name="SCP B")),
    ]

    filtered = filter_team_games(games, "FOCA")

    assert [game.id for game in filtered] == ["foca-home"]
    assert find_team_identities(games, "FOCA")[0].id == FOCA_ID


def test_filter_foca_as_away() -> None:
    games = [
        parse_test_game(
            game_response("foca-away", home_name="SCP B", away_name="FOCA")
        )
    ]

    filtered = filter_team_games(games, "foca")

    assert [game.id for game in filtered] == ["foca-away"]


def test_filter_excludes_game_without_foca() -> None:
    games = [parse_test_game(game_response(home_name="CAP", away_name="SCP B"))]

    assert filter_team_games(games, "FOCA") == []


def test_get_team_games_fetches_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=competition_response())
        assert request.method == "POST"
        request_body = json.loads(request.content)
        assert request_body["filterCollections"][0]["value"] == COMPETITION_ID
        return httpx.Response(
            200,
            json={
                "entity": [
                    game_response("foca-game"),
                    game_response("other", home_name="CAP", away_name="SCP B"),
                ]
            },
        )

    with mocked_client(httpx.MockTransport(handler)) as client:
        games = client.get_team_games(domain="po02_25-26", team="FOCA")

    assert [game.id for game in games] == ["foca-game"]
    assert games[0].competition_category == "senior"


def test_endpoint_error_is_not_silenced() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    with (
        mocked_client(transport) as client,
        pytest.raises(FPNArenaHTTPError, match="HTTP 503"),
    ):
        client.get_competition("po02_25-26")


def test_nonexistent_domain_has_specific_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))

    with (
        mocked_client(transport) as client,
        pytest.raises(FPNCompetitionNotFoundError, match="missing-domain"),
    ):
        client.get_competition("missing-domain")


def test_api_null_reference_for_missing_domain_has_specific_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            500,
            json={
                "ErrorCode": 0,
                "ErrorMessage": "Object reference not set to an instance of an object.",
                "Data": None,
            },
        )
    )

    with (
        mocked_client(transport) as client,
        pytest.raises(FPNCompetitionNotFoundError, match="missing-domain"),
    ):
        client.get_competition("missing-domain")


def test_competition_without_id_is_rejected() -> None:
    with pytest.raises(FPNResponseError, match="entity.id"):
        parse_competition({"entity": {"displayName": "No ID"}}, "po02_25-26")


def test_games_response_without_entity_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=competition_response())
        return httpx.Response(200, json={"data": []})

    with mocked_client(httpx.MockTransport(handler)) as client:
        competition = client.get_competition("po02_25-26")
        with pytest.raises(FPNResponseError, match="missing entity"):
            client.get_games(competition.id)


@pytest.mark.parametrize(
    "game_teams",
    [
        "not-an-array",
        [{"teamIndex": 3, "team": None}],
        [{"teamIndex": 1}, {"teamIndex": 1}],
        [{"score": 18}],
    ],
)
def test_unexpected_game_teams_structure_is_rejected(game_teams: Any) -> None:
    with pytest.raises(FPNGameStructureError):
        parse_test_game({"id": "bad-game", "gameTeams": game_teams})
