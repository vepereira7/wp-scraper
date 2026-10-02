import pytest

from waterpolo.scraper.fpn.domain import extract_fpn_season


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("po01_26-27", "S2627"),
        ("po02_25-26", "S2526"),
        ("po12_25-26", "S2526"),
    ],
)
def test_extract_fpn_season(domain: str, expected: str) -> None:
    assert extract_fpn_season(domain) == expected


@pytest.mark.parametrize("domain", ["po01", "26-27", "", "abc", "po01_2026-2027"])
def test_extract_fpn_season_rejects_invalid_domains(domain: str) -> None:
    with pytest.raises(ValueError, match="Could not extract season from FPN domain"):
        extract_fpn_season(domain)
