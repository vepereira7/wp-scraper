"""Load the project's public calendar JSON contract for reporting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from waterpolo.models import Match
from waterpolo.models.report import ReportMatch
from waterpolo.services.validation import validate_json_payload

CalendarArgument = tuple[str, Path]


def parse_calendar_argument(value: str) -> CalendarArgument:
    """Parse one ``LABEL=PATH`` command-line argument."""
    label, separator, raw_path = value.partition("=")
    label = label.strip()
    raw_path = raw_path.strip()
    if not separator:
        raise argparse.ArgumentTypeError("--calendar deve usar o formato LABEL=PATH")
    if not label:
        raise argparse.ArgumentTypeError("o label de --calendar não pode estar vazio")
    if not raw_path:
        raise argparse.ArgumentTypeError("o caminho de --calendar não pode estar vazio")
    return label, Path(raw_path)


def load_calendar(label: str, path: Path) -> list[ReportMatch]:
    """Load and validate one calendar using the existing Match contract."""
    if not path.is_file():
        raise ValueError(f"ficheiro de calendário não encontrado: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc

    try:
        validate_json_payload(payload)
        matches = [Match.model_validate(item) for item in payload["matches"]]
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(f"estrutura inválida em {path}: {exc}") from exc

    return [ReportMatch(label=label, match=match) for match in matches]


def load_calendars(calendars: list[CalendarArgument]) -> list[ReportMatch]:
    """Load multiple labeled calendars without changing their source files."""
    matches: list[ReportMatch] = []
    for label, path in calendars:
        matches.extend(load_calendar(label, path))
    return matches
