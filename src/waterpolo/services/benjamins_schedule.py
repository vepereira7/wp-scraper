"""JSON and ICS exports for ANNP Benjamins actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from waterpolo.models.benjamins_schedule import BenjaminsScheduleEntry
from waterpolo.services.ics_export import PORTUGAL, _escape, _fold


def export_benjamins_json(entries: list[BenjaminsScheduleEntry]) -> dict[str, Any]:
    """Build a separate schedule payload, preserving published action order."""
    _validate_entries(entries)
    first = entries[0]
    return {
        "source": first.source,
        "season": first.season,
        "competition_id": first.competition_id,
        "competition_name": first.competition_name,
        "entry_count": len(entries),
        "entries": [
            {
                "external_id": entry.external_id,
                "date": entry.date.isoformat(),
                "time": entry.time.strftime("%H:%M") if entry.time is not None else None,
                "venue": entry.venue,
            }
            for entry in entries
        ],
    }


def validate_benjamins_json(payload: Any) -> list[BenjaminsScheduleEntry]:
    """Validate the schedule schema without accepting a Match calendar."""
    if not isinstance(payload, dict):
        raise TypeError("Benjamins schedule must be a JSON object")
    expected = {
        "source", "season", "competition_id", "competition_name", "entry_count", "entries"
    }
    if set(payload) != expected or not isinstance(payload["entries"], list):
        raise ValueError("Invalid Benjamins schedule envelope")
    if (
        not isinstance(payload["entry_count"], int)
        or isinstance(payload["entry_count"], bool)
        or payload["entry_count"] != len(payload["entries"])
    ):
        raise ValueError("Invalid Benjamins entry_count")
    entries: list[BenjaminsScheduleEntry] = []
    for item in payload["entries"]:
        if not isinstance(item, dict) or set(item) != {
            "external_id", "date", "time", "venue"
        }:
            raise ValueError("Invalid Benjamins schedule entry")
        entries.append(
            BenjaminsScheduleEntry.model_validate(
                {
                    **item,
                    "source": payload["source"],
                    "season": payload["season"],
                    "competition_id": payload["competition_id"],
                    "competition_name": payload["competition_name"],
                }
            )
        )
    _validate_entries(entries)
    return entries


def schedule_uid(entry: BenjaminsScheduleEntry) -> str:
    return f"ANNP-SCHEDULE-{entry.external_id}@waterpolo"


def export_benjamins_ics(
    entries: list[BenjaminsScheduleEntry], output_path: Path
) -> None:
    """Write one event per action with date-only events for unknown times."""
    _validate_entries(entries)
    generated = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WaterPolo Scraper//Benjamins Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(entries[0].competition_name)}",
        f"NAME:{_escape(entries[0].competition_name)}",
    ]
    for entry in entries:
        if entry.time is None:
            start = f"DTSTART;VALUE=DATE:{entry.date:%Y%m%d}"
            end = f"DTEND;VALUE=DATE:{entry.date + timedelta(days=1):%Y%m%d}"
        else:
            local = datetime.combine(entry.date, entry.time, tzinfo=PORTUGAL)
            utc_start = local.astimezone(UTC)
            utc_end = utc_start + timedelta(hours=2)
            start = f"DTSTART:{utc_start:%Y%m%dT%H%M%SZ}"
            end = f"DTEND:{utc_end:%Y%m%dT%H%M%SZ}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{schedule_uid(entry)}",
                f"DTSTAMP:{generated}",
                f"LAST-MODIFIED:{generated}",
                "SEQUENCE:0",
                start,
                end,
                "SUMMARY:Ação de Benjamins",
                f"DESCRIPTION:Competição: {_escape(entry.competition_name)}",
            ]
        )
        if entry.venue:
            lines.append(f"LOCATION:{_escape(entry.venue)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
    )


def _validate_entries(entries: list[BenjaminsScheduleEntry]) -> None:
    if not entries:
        raise ValueError("Benjamins schedule is empty")
    identities = [entry.external_id for entry in entries]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate Benjamins external_id")
    first = entries[0]
    if any(
        (entry.source, entry.season, entry.competition_id, entry.competition_name)
        != (first.source, first.season, first.competition_id, first.competition_name)
        for entry in entries
    ):
        raise ValueError("Benjamins entries disagree on competition metadata")
