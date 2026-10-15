import pytest

from waterpolo.models import MatchCategory, normalize_category


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Seniores", MatchCategory.SENIOR),
        ("Juniores", MatchCategory.U18),
        ("Juvenis", MatchCategory.U16),
        ("Infantis", MatchCategory.U14),
        ("Cadetes", MatchCategory.U12),
        ("Sub-18", MatchCategory.U18),
        ("Sub-16", MatchCategory.U16),
        ("Sub-14", MatchCategory.U14),
        ("Sub-12", MatchCategory.U12),
    ],
)
def test_normalize_category_maps_source_and_canonical_labels(
    raw: str, expected: MatchCategory
) -> None:
    assert normalize_category(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" U18 ", MatchCategory.U18),
        ("u16", MatchCategory.U16),
        ("Sub 14", MatchCategory.U14),
        ("sub 12", MatchCategory.U12),
        ("JÚNIOR", MatchCategory.U18),
        ("Cadete", MatchCategory.U12),
    ],
)
def test_normalize_category_supports_explicit_variants(
    raw: str, expected: MatchCategory
) -> None:
    assert normalize_category(raw) is expected


@pytest.mark.parametrize("raw", [None, "Absolutos", "Infantis e Juvenis"])
def test_normalize_category_does_not_guess_unknown_or_ambiguous_labels(
    raw: str | None,
) -> None:
    assert normalize_category(raw) is MatchCategory.UNKNOWN


def test_normalize_category_is_idempotent_for_enum_values() -> None:
    for category in MatchCategory:
        assert normalize_category(category) is category
