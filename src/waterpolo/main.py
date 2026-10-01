"""Command-line entry point for water polo scraper operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from waterpolo.scraper.fpn import FPNArenaClient
from waterpolo.scraper.fpn.errors import FPNArenaError
from waterpolo.scraper.fpn.scraper import to_matches
from waterpolo.services.json_export import export_matches_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="waterpolo")
    commands = parser.add_subparsers(dest="command")
    export = commands.add_parser("export", help="export normalized matches")
    sources = export.add_subparsers(dest="source", required=True)
    fpn = sources.add_parser("fpn", help="export FPN matches")
    fpn.add_argument("--domain", required=True)
    fpn.add_argument("--team", required=True)
    fpn.add_argument("--output", required=True, type=Path)
    return parser


def export_fpn(domain: str, team: str, output: Path) -> int:
    """Fetch, normalize, and write one FPN team's matches."""
    try:
        with FPNArenaClient() as client:
            games = client.get_team_games(domain=domain, team=team)
            matches = to_matches(games, season=domain)
        payload = export_matches_json(matches, source="FPN")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except (FPNArenaError, ValueError, OSError) as exc:
        print(f"Erro ao exportar jogos FPN: {exc}", file=sys.stderr)
        return 1

    print(
        f"Fonte: FPN\nDomínio: {domain}\nEquipa: {team}\n"
        f"Nº jogos: {len(matches)}\nFicheiro: {output}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export" and args.source == "fpn":
        return export_fpn(args.domain, args.team, args.output)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
