"""CLI for deterministic offline HTML/PDF calendar reports."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from waterpolo.report.loader import (
    CalendarArgument,
    load_calendar,
    load_schedule,
    parse_calendar_argument,
    parse_schedule_argument,
)
from waterpolo.services.report_renderer import write_html, write_pdf

LOGGER = logging.getLogger("waterpolo.report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m waterpolo.report",
        description="Gerar um relatório HTML/PDF offline a partir de calendários JSON.",
    )
    parser.add_argument(
        "--calendar",
        action="append",
        required=True,
        type=parse_calendar_argument,
        metavar="LABEL=PATH",
        help="calendário com o label a apresentar; pode ser repetido",
    )
    parser.add_argument(
        "--schedule",
        action="append",
        type=parse_schedule_argument,
        metavar="LABEL=PATH",
        help="schedule de ações Benjamins; pode ser repetido",
    )
    parser.add_argument("--html", type=Path, help="ficheiro HTML de destino")
    parser.add_argument("--pdf", type=Path, help="ficheiro PDF de destino")
    return parser


def run_report(
    calendars: list[CalendarArgument],
    *,
    schedules: list[CalendarArgument] | None = None,
    html_output: Path | None,
    pdf_output: Path | None,
) -> None:
    """Load calendars and render the requested outputs without network access."""
    matches = []
    for label, path in calendars:
        LOGGER.info("Loading %s: %s", label, path)
        matches.extend(load_calendar(label, path))
    for label, path in schedules or []:
        LOGGER.info("Loading schedule %s: %s", label, path)
        matches.extend(load_schedule(label, path))
    LOGGER.info("Loaded %d report entries", len(matches))

    if html_output is not None:
        LOGGER.info("Rendering HTML: %s", html_output)
        write_html(matches, html_output)
        html_source = html_output
        if pdf_output is not None:
            LOGGER.info("Rendering PDF: %s", pdf_output)
            write_pdf(html_source, pdf_output)
    elif pdf_output is not None:
        with tempfile.TemporaryDirectory(prefix="waterpolo-report-") as temp_dir:
            html_source = Path(temp_dir) / "calendar-report.html"
            write_html(matches, html_source)
            LOGGER.info("Rendering PDF: %s", pdf_output)
            write_pdf(html_source, pdf_output)

    LOGGER.info("Done")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.html is None and args.pdf is None:
        parser.error("indique pelo menos um de --html ou --pdf")
    if (
        args.html is not None
        and args.pdf is not None
        and args.html.resolve() == args.pdf.resolve()
    ):
        parser.error("--html e --pdf têm de apontar para ficheiros diferentes")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run_report(
            args.calendar,
            schedules=args.schedule,
            html_output=args.html,
            pdf_output=args.pdf,
        )
    except Exception as exc:  # noqa: BLE001 -- CLI errors must produce a nonzero exit code.
        LOGGER.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
