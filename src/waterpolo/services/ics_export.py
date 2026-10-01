"""Calendar exports for source-independent matches."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from waterpolo.models import Match, MatchCategory, format_match_category

PORTUGAL = ZoneInfo("Europe/Lisbon")


def export_matches_ics(
    matches: list[Match],
    output_path: Path,
    calendar_name: str | None = None,
    default_duration_minutes: int = 120,
) -> None:
    """Write matches as a standards friendly iCalendar file."""
    if default_duration_minutes <= 0:
        raise ValueError("default_duration_minutes must be greater than zero")

    # Build everything before opening the destination, so invalid input cannot
    # leave a truncated or partial calendar behind.
    resolved_calendar_name = _calendar_name(matches, calendar_name)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WaterPolo Scraper//Match Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(resolved_calendar_name)}",
        f"NAME:{_escape(resolved_calendar_name)}",
    ]
    generated = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for match in matches:
        if match.date is None or match.time is None:
            raise ValueError(f"Match {match.external_id!r} has no date or time")
        start_local = datetime.combine(match.date, match.time, tzinfo=PORTUGAL)
        start_utc = start_local.astimezone(UTC)
        end_utc = start_utc + timedelta(minutes=default_duration_minutes)
        start = start_utc.strftime("%Y%m%dT%H%M%SZ")
        end = end_utc.strftime("%Y%m%dT%H%M%SZ")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_uid(match)}",
                f"DTSTAMP:{generated}",
                f"LAST-MODIFIED:{generated}",
                # Sequence stays at zero because this exporter has no persisted
                # history for comparing a new export with an earlier one.
                "SEQUENCE:0",
                f"DTSTART:{start}",
                f"DTEND:{end}",
                f"SUMMARY:{_escape(_summary(match))}",
                f"DESCRIPTION:{_escape(_description(match))}",
            ]
        )
        if match.location:
            lines.append(f"LOCATION:{_escape(match.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
    )


def _uid(match: Match) -> str:
    if match.external_id:
        return f"{match.source.value}-{match.external_id}@waterpolo"

    # Match currently requires external_id. If that changes, this fallback
    # avoids schedule fields; same-competition rematches between identical
    # teams could collide without a source-provided stable identifier.
    stable_key = (
        f"{match.source.value}:{match.season}:{match.competition}:"
        f"{match.category.value}:{match.home}:{match.away}"
    )
    digest = sha256(stable_key.encode("utf-8")).hexdigest()
    return f"{match.source.value}-{digest}@waterpolo"


def _team_title(name: str) -> str:
    if name.casefold() == "foca":
        return "Foca"
    return name


def _summary(match: Match) -> str:
    prefix = _competition_prefix(match)
    teams = f"{_team_title(match.home)} x {_team_title(match.away)}"
    return f"{prefix} | {teams}" if prefix else teams


def _calendar_name(matches: list[Match], explicit_name: str | None) -> str:
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()
    competitions = {match.competition.strip() for match in matches if match.competition.strip()}
    if len(competitions) == 1:
        return competitions.pop()
    return "Water Polo Matches"


def _normalized_competition_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip().casefold()


def _competition_prefix(match: Match) -> str | None:
    category_prefixes = {
        MatchCategory.JUNIOR: "U18",
        MatchCategory.JUVENIS: "U16",
        MatchCategory.INFANTIS: "U14",
        MatchCategory.U18: "U18",
        MatchCategory.U16: "U16",
        MatchCategory.U14: "U14",
    }
    if match.category in category_prefixes:
        return category_prefixes[match.category]

    name = _normalized_competition_name(match.competition)
    if match.category is MatchCategory.SENIOR:
        for prefix in ("A1", "A2"):
            if re.search(rf"\b{prefix.casefold()}\b", name):
                return prefix
        return None

    if match.category is MatchCategory.UNKNOWN:
        for pattern, prefix in (
            (r"\bjunior(?:es)?\b", "U18"),
            (r"\bjuven(?:il|is)\b", "U16"),
            (r"\binfant(?:il|is)\b", "U14"),
        ):
            if re.search(pattern, name):
                return prefix
        for prefix in ("A1", "A2"):
            if re.search(rf"\b{prefix.casefold()}\b", name):
                return prefix
    return None


def _description(match: Match) -> str:
    return "\n".join(
        [
            f"Competição: {match.competition}",
            f"Categoria: {format_match_category(match.category)}",
            f"Estado: {match.status.value}",
            f"Fonte: {match.source.value}",
        ]
    )


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets without splitting UTF-8 characters."""
    parts: list[str] = []
    current = ""
    octets = 0
    for character in line:
        size = len(character.encode("utf-8"))
        if octets + size > 75:
            parts.append(current)
            current = " "
            octets = 1
        current += character
        octets += size
    parts.append(current)
    return "\r\n".join(parts)
