import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import httpx
import pytest

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
    parse_competition,
    parse_game,
)

COMPETITION_ID = "competition-123"
COMPETITION_NAME = "Campeonato Portugal A2 Masculinos"
FOCA_ID = "foca-team-id-from-api"


def competition_response() -> dict[str, Any]:
    return {
        "entity": {
            "id": COMPETITION_ID,
            "displayName": COMPETITION_NAME,
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
    ],
)
def test_unexpected_game_teams_structure_is_rejected(game_teams: Any) -> None:
    with pytest.raises(FPNGameStructureError):
        parse_test_game({"id": "bad-game", "gameTeams": game_teams})
