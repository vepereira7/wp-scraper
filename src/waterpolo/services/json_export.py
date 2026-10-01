"""JSON-compatible exports for normalized matches."""

from datetime import UTC, datetime
from typing import Any

from waterpolo.models import Match, format_match_category


def export_matches_json(
    matches: list[Match],
    source: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Build a JSON-serializable payload without writing it to disk."""
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    excluded_fields = set() if include_raw else {"raw"}
    exported_matches = []
    for match in matches:
        exported_match = match.model_dump(mode="json", exclude=excluded_fields)
        exported_match["category"] = format_match_category(match.category)
        exported_matches.append(exported_match)

    return {
        "generated_at": generated_at,
        "source": source,
        "match_count": len(matches),
        "matches": exported_matches,
    }
