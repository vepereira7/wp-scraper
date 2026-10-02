"""Command-line entry point for water polo scraper operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from waterpolo.scraper.fpn import FPNArenaClient
from waterpolo.scraper.fpn.scraper import to_matches
from waterpolo.services.ics_export import export_matches_ics
from waterpolo.services.json_export import export_matches_json
from waterpolo.services.run_logger import RunLogger

RUN_LOG_DIR = Path("data/logs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="waterpolo")
    commands = parser.add_subparsers(dest="command")
    export = commands.add_parser("export", help="export normalized matches")
    sources = export.add_subparsers(dest="source", required=True)
    fpn = sources.add_parser("fpn", help="export FPN matches")
    fpn.add_argument("--domain", required=True)
    fpn.add_argument("--team", required=True)
    fpn.add_argument("--output", required=True, type=Path)
    fpn.add_argument("--format", choices=("json", "ics"), default="json")
    return parser


def export_fpn(
    domain: str,
    team: str,
    output: Path,
    output_format: str = "json",
    *,
    log_dir: Path | None = None,
    command: str | None = None,
) -> int:
    """Fetch, normalize, and write one FPN team's matches."""
    expected_suffix = f".{output_format}"
    command = command or (
        f"python -m waterpolo.main export fpn --domain {domain} --team {team} "
        f"--format {output_format} --output {output}"
    )
    logger = RunLogger(log_dir or RUN_LOG_DIR, command=command, team=team, output_format=output_format)
    details = [
        f"Domínio: {domain}",
        f"Equipa: {team}",
        f"Formato: {output_format}",
        f"Output: {output}",
    ]
    try:
        if output.suffix.casefold() != expected_suffix:
            raise ValueError(
                f"Formato {output_format} requer extensão {expected_suffix}; recebido {output.suffix or '(sem extensão)'}"
            )
        with FPNArenaClient() as client:
            games = client.get_team_games(domain=domain, team=team)
            matches = to_matches(games, domain=domain)
        if output_format == "json":
            payload = export_matches_json(matches, source="FPN")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            calendar_name = matches[0].competition if matches else None
            export_matches_ics(matches, output, calendar_name=calendar_name)
    except Exception as exc:  # noqa: BLE001 -- log every run failure, then return nonzero.
        logger.error(exc)
        logger.finish(status="ERROR", details=details)
        return 1

    logger.info(f"Fonte: FPN\nDomínio: {domain}\nEquipa: {team}\nNº jogos: {len(matches)}\nFicheiro: {output}")
    logger.finish(status="SUCCESS", details=[*details, f"Nº jogos encontrados/exportados: {len(matches)}"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export" and args.source == "fpn":
        return export_fpn(
            args.domain,
            args.team,
            args.output,
            args.format,
            command=" ".join(sys.argv if argv is None else ["python", "-m", "waterpolo.main", *argv]),
        )
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
