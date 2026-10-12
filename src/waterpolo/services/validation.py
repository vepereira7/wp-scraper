"""Validation and transactional publication helpers for calendar outputs."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from waterpolo.models import Match
from waterpolo.services.ics_export import match_uid

JSON_MATCH_FIELDS = {
    "external_id",
    "season",
    "home",
    "away",
    "competition",
    "date",
    "time",
    "status",
}


def validate_match_snapshot(matches: Sequence[Match], *, allow_empty: bool = False) -> None:
    """Validate invariants shared by the JSON and ICS representations."""
    if not matches and not allow_empty:
        raise ValueError("A recolha sem jogos foi rejeitada; os outputs anteriores foram mantidos")

    external_ids = [match.external_id for match in matches]
    duplicate_external_ids = _duplicates(external_ids)
    if duplicate_external_ids:
        raise ValueError(
            "external_id duplicado no snapshot: " + ", ".join(sorted(duplicate_external_ids))
        )

    uids = [match_uid(match) for match in matches]
    duplicate_uids = _duplicates(uids)
    if duplicate_uids:
        raise ValueError("UID duplicado no snapshot: " + ", ".join(sorted(duplicate_uids)))


def validate_json_payload(
    payload: Any,
    *,
    expected_external_ids: set[str] | None = None,
    allow_empty: bool = False,
) -> None:
    """Validate the public JSON envelope and its required match fields."""
    if not isinstance(payload, Mapping):
        raise TypeError("JSON inválido: o objeto raiz tem de ser um objeto")

    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise TypeError("JSON inválido: matches tem de ser uma lista")
    if not isinstance(payload.get("match_count"), int) or isinstance(
        payload["match_count"], bool
    ):
        raise TypeError("JSON inválido: match_count tem de ser um inteiro")
    if payload["match_count"] != len(matches):
        raise ValueError("JSON inválido: match_count não corresponde a matches")
    if not matches and not allow_empty:
        raise ValueError("JSON inválido: calendário vazio não é permitido por omissão")

    external_ids: list[str] = []
    for index, match in enumerate(matches):
        if not isinstance(match, Mapping):
            raise TypeError(f"JSON inválido: matches[{index}] não é um objeto")
        missing = sorted(
            field
            for field in JSON_MATCH_FIELDS
            if field not in match
            or (field != "time" and not _has_value(match.get(field)))
            or (
                field == "time"
                and match.get(field) is not None
                and not _has_value(match.get(field))
            )
        )
        if missing:
            raise ValueError(
                f"JSON inválido: matches[{index}] sem campos obrigatórios: {', '.join(missing)}"
            )
        external_ids.append(str(match["external_id"]))

    duplicate_external_ids = _duplicates(external_ids)
    if duplicate_external_ids:
        raise ValueError(
            "JSON inválido: external_id duplicado: "
            + ", ".join(sorted(duplicate_external_ids))
        )
    if expected_external_ids is not None and set(external_ids) != expected_external_ids:
        raise ValueError("JSON inválido: os jogos não correspondem ao snapshot recolhido")


def validate_json_file(
    path: Path,
    *,
    expected_external_ids: set[str] | None = None,
    allow_empty: bool = False,
) -> None:
    """Read and validate one staged JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc
    validate_json_payload(
        payload,
        expected_external_ids=expected_external_ids,
        allow_empty=allow_empty,
    )


def validate_ics_file(
    path: Path,
    *,
    expected_uids: set[str] | None = None,
    expected_event_count: int | None = None,
) -> None:
    """Validate the structural iCalendar invariants needed for publication."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"ICS inválido em {path}: {exc}") from exc

    lines = _unfold_ics(content)
    if "BEGIN:VCALENDAR" not in lines or "END:VCALENDAR" not in lines:
        raise ValueError("ICS inválido: faltam BEGIN:VCALENDAR/END:VCALENDAR")

    begin_events = sum(line == "BEGIN:VEVENT" for line in lines)
    end_events = sum(line == "END:VEVENT" for line in lines)
    if begin_events != end_events:
        raise ValueError("ICS inválido: BEGIN:VEVENT e END:VEVENT não correspondem")
    if expected_event_count is not None and begin_events != expected_event_count:
        raise ValueError(
            f"ICS inválido: esperados {expected_event_count} VEVENT(s), encontrados {begin_events}"
        )

    uids = [line.removeprefix("UID:") for line in lines if line.startswith("UID:")]
    if len(uids) != begin_events:
        raise ValueError("ICS inválido: tem de existir um UID por VEVENT")
    duplicate_uids = _duplicates(uids)
    if duplicate_uids:
        raise ValueError("ICS inválido: UID duplicado: " + ", ".join(sorted(duplicate_uids)))
    if expected_uids is not None and set(uids) != expected_uids:
        raise ValueError("ICS inválido: os VEVENTs não correspondem ao snapshot recolhido")


def publish_staged_pair(
    staged_json: Path,
    json_output: Path,
    staged_ics: Path,
    ics_output: Path,
) -> None:
    """Publish two staged files with atomic renames and in-process rollback.

    A filesystem has no portable two-path transaction primitive. Existing
    outputs are therefore moved to same-directory backups before either staged
    file is published. If any rename fails, all backups are restored so a
    failed run does not leave one new artefact alongside one old artefact.
    """
    destinations = ((staged_json, json_output), (staged_ics, ics_output))
    if json_output.resolve() == ics_output.resolve():
        raise ValueError("JSON e ICS têm de ter destinos diferentes")

    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for _, destination in destinations:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backups[destination] = _temporary_sibling(destination, ".previous-")
                os.replace(destination, backups[destination])

        for staged, destination in destinations:
            os.replace(staged, destination)
            published.append(destination)
    except Exception:
        _rollback_publication(destinations, backups, published)
        raise


def publish_staged_file(staged: Path, destination: Path) -> None:
    """Atomically replace one output with a validated staged file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, destination)


def create_staged_path(destination: Path) -> Path:
    """Create an empty staging path on the same filesystem as its destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    return Path(name)


def _rollback_publication(
    destinations: tuple[tuple[Path, Path], ...],
    backups: dict[Path, Path],
    published: list[Path],
) -> None:
    for _, destination in destinations:
        backup = backups.get(destination)
        try:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            elif destination in published:
                destination.unlink(missing_ok=True)
        except OSError:
            # Preserve the original publication error. The caller still gets a
            # nonzero exit code and the logger contains its traceback.
            continue


def _temporary_sibling(destination: Path, prefix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.{prefix}", dir=destination.parent)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _unfold_ics(content: str) -> list[str]:
    lines = content.splitlines()
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _duplicates(values: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _has_value(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))
