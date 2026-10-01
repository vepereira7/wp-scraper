from datetime import date, time

import pytest
from pydantic import ValidationError

from waterpolo.models import Match, MatchCategory, MatchSource, MatchStatus


def valid_match_data() -> dict[str, object]:
    return {
        "external_id": "fpn-123",
        "source": MatchSource.FPN,
        "source_url": "https://example.test/fpn/123",
        "season": "2026/27",
        "category": MatchCategory.U16,
        "competition": "Campeonato Nacional",
        "home": "FOCA",
        "away": "Vitória SC",
        "date": date(2026, 10, 4),
        "time": time(15, 0),
        "location": "Piscina Municipal",
    }


def test_create_valid_match() -> None:
    match = Match(**valid_match_data())

    assert match.external_id == "fpn-123"
    assert match.source is MatchSource.FPN
    assert match.category is MatchCategory.U16
    assert match.status is MatchStatus.SCHEDULED


@pytest.mark.parametrize(
    "field",
    ["external_id", "season", "competition", "home", "away"],
)
@pytest.mark.parametrize("empty_value", ["", "   "])
def test_required_text_cannot_be_empty(field: str, empty_value: str) -> None:
    data = valid_match_data()
    data[field] = empty_value

    with pytest.raises(ValidationError):
        Match(**data)


@pytest.mark.parametrize("field", ["score_home", "score_away"])
def test_score_cannot_be_negative(field: str) -> None:
    data = valid_match_data()
    data.update(score_home=1, score_away=1)
    data[field] = -1

    with pytest.raises(ValidationError):
        Match(**data)


@pytest.mark.parametrize(
    ("score_home", "score_away"),
    [(1, None), (None, 1)],
)
def test_scores_must_be_set_as_a_pair(
    score_home: int | None, score_away: int | None
) -> None:
    data = valid_match_data()
    data.update(score_home=score_home, score_away=score_away)

    with pytest.raises(ValidationError):
        Match(**data)


def test_match_with_both_scores_is_valid() -> None:
    match = Match(**valid_match_data(), score_home=12, score_away=9)

    assert match.score_home == 12
    assert match.score_away == 9


def test_match_with_missing_location_is_valid() -> None:
    data = valid_match_data()
    data["location"] = None

    match = Match(**data)

    assert match.location is None


def test_json_serialization_formats_date_and_time() -> None:
    serialized = Match(**valid_match_data()).model_dump(mode="json")

    assert serialized["date"] == "2026-10-04"
    assert serialized["time"] == "15:00:00"
