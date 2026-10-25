"""Command-line entry point for water polo scraper operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from waterpolo.models import Match, MatchSource
from waterpolo.scraper.annp import ANNPClient
from waterpolo.scraper.annp.scraper import to_matches as annp_to_matches
from waterpolo.scraper.fpn import FPNArenaClient
from waterpolo.scraper.fpn.scraper import to_matches as fpn_to_matches
from waterpolo.services.benjamins_schedule import (
    export_benjamins_ics,
    export_benjamins_json,
    schedule_uid,
    validate_benjamins_json,
)
from waterpolo.services.ics_export import export_matches_ics, match_uid
from waterpolo.services.json_export import export_matches_json
from waterpolo.services.run_logger import RunLogger
from waterpolo.services.validation import (
    create_staged_path,
    publish_staged_file,
    publish_staged_pair,
    validate_ics_file,
    validate_json_file,
    validate_match_snapshot,
)

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
    publish = commands.add_parser("publish", help="recolher uma vez e publicar JSON + ICS")
    publish_sources = publish.add_subparsers(dest="source", required=True)
    publish_fpn = publish_sources.add_parser("fpn", help="publicar calendário FPN")
    publish_fpn.add_argument("--domain", required=True)
    publish_fpn.add_argument("--team", required=True)
    publish_fpn.add_argument("--json-output", required=True, type=Path)
    publish_fpn.add_argument("--ics-output", required=True, type=Path)
    publish_annp = publish_sources.add_parser("annp", help="publicar calendário ANNP")
    publish_annp.add_argument("--season", required=True)
    publish_annp.add_argument("--team", required=True)
    annp_selector = publish_annp.add_mutually_exclusive_group(required=True)
    annp_selector.add_argument("--category")
    annp_selector.add_argument("--competition-id")
    publish_annp.add_argument("--json-output", required=True, type=Path)
    publish_annp.add_argument("--ics-output", required=True, type=Path)
    publish_schedule = publish_sources.add_parser(
        "annp-schedule", help="publicar ações de Benjamins ANNP"
    )
    publish_schedule.add_argument("--season", required=True)
    publish_schedule.add_argument("--competition-id", required=True)
    publish_schedule.add_argument("--json-output", required=True, type=Path)
    publish_schedule.add_argument("--ics-output", type=Path)
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
    logger = RunLogger(
        log_dir or RUN_LOG_DIR,
        command=command,
        team=team,
        output_format=output_format,
        source="FPN",
    )
    details = [
        f"Domínio: {domain}",
        f"Equipa: {team}",
        f"Formato: {output_format}",
        f"Output: {output}",
    ]
    staged_output: Path | None = None
    try:
        if output.suffix.casefold() != expected_suffix:
            raise ValueError(
                f"Formato {output_format} requer extensão {expected_suffix}; recebido {output.suffix or '(sem extensão)'}"
            )
        with FPNArenaClient() as client:
            games = client.get_team_games(domain=domain, team=team)
            matches = fpn_to_matches(games, domain=domain)
        validate_match_snapshot(matches)
        staged_output = create_staged_path(output)
        if output_format == "json":
            payload = export_matches_json(matches, source="FPN")
            staged_output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            validate_json_file(staged_output, expected_external_ids={match.external_id for match in matches})
        else:
            calendar_name = matches[0].competition if matches else None
            export_matches_ics(matches, staged_output, calendar_name=calendar_name)
            validate_ics_file(
                staged_output,
                expected_uids={match_uid(match) for match in matches},
                expected_event_count=len(matches),
            )
        publish_staged_file(staged_output, output)
    except Exception as exc:  # noqa: BLE001 -- log every run failure, then return nonzero.
        logger.error(exc)
        logger.finish(status="ERROR", details=details)
        return 1
    finally:
        if staged_output is not None:
            staged_output.unlink(missing_ok=True)

    logger.info(f"Fonte: FPN\nDomínio: {domain}\nEquipa: {team}\nNº jogos: {len(matches)}\nFicheiro: {output}")
    logger.finish(status="SUCCESS", details=[*details, f"Nº jogos encontrados/exportados: {len(matches)}"])
    return 0


def publish_fpn(
    domain: str,
    team: str,
    json_output: Path,
    ics_output: Path,
    *,
    log_dir: Path | None = None,
    command: str | None = None,
) -> int:
    """Fetch once and publish a validated JSON/ICS pair from one snapshot."""
    command = command or (
        f"python -m waterpolo.main publish fpn --domain {domain} --team {team} "
        f"--json-output {json_output} --ics-output {ics_output}"
    )
    details = [
        f"Domínio: {domain}",
        f"Equipa: {team}",
        f"JSON: {json_output}",
        f"ICS: {ics_output}",
    ]

    def fetch_matches() -> list[Match]:
        with FPNArenaClient() as client:
            games = client.get_team_games(domain=domain, team=team)
            return fpn_to_matches(games, domain=domain)

    return _publish_matches(
        source=MatchSource.FPN,
        team=team,
        json_output=json_output,
        ics_output=ics_output,
        fetch_matches=fetch_matches,
        details=details,
        success_context=f"Domínio: {domain}",
        log_dir=log_dir,
        command=command,
    )


def publish_annp(
    season: str,
    team: str,
    json_output: Path,
    ics_output: Path,
    *,
    category: str | None = None,
    competition_id: str | None = None,
    log_dir: Path | None = None,
    command: str | None = None,
) -> int:
    """Fetch one ANNP competition and publish it through the shared pipeline."""
    selector_flag = (
        f"--competition-id {competition_id}"
        if competition_id is not None
        else f"--category {category}"
    )
    command = command or (
        f"python -m waterpolo.main publish annp --season {season} --team {team} "
        f"{selector_flag} --json-output {json_output} --ics-output {ics_output}"
    )
    selector_detail = (
        f"ID da competição: {competition_id}"
        if competition_id is not None
        else f"Escalão: {category}"
    )
    details = [
        f"Época: {season}",
        selector_detail,
        f"Equipa: {team}",
        f"JSON: {json_output}",
        f"ICS: {ics_output}",
    ]

    def fetch_matches() -> list[Match]:
        with ANNPClient() as client:
            _, games = client.get_team_games(
                season=season,
                team=team,
                category=category,
                competition_id=competition_id,
            )
            return annp_to_matches(games, season=season)

    return _publish_matches(
        source=MatchSource.ANNP,
        team=team,
        json_output=json_output,
        ics_output=ics_output,
        fetch_matches=fetch_matches,
        details=details,
        success_context=f"Época: {season}\n{selector_detail}",
        log_dir=log_dir,
        command=command,
    )


def publish_annp_schedule(
    season: str,
    competition_id: str,
    json_output: Path,
    ics_output: Path | None = None,
    *,
    log_dir: Path | None = None,
    command: str | None = None,
) -> int:
    """Publish Benjamins actions through their own validated output contract."""
    command = command or (
        f"python -m waterpolo.main publish annp-schedule --season {season} "
        f"--competition-id {competition_id} --json-output {json_output}"
    )
    logger = RunLogger(
        log_dir or RUN_LOG_DIR,
        command=command,
        team="Benjamins",
        output_format="json+ics" if ics_output else "json",
        source="ANNP-SCHEDULE",
    )
    details = [
        f"Época: {season}",
        f"ID da competição: {competition_id}",
        f"JSON: {json_output}",
        f"ICS: {ics_output or '(não pedido)'}",
    ]
    staged_json: Path | None = None
    staged_ics: Path | None = None
    try:
        if json_output.suffix.casefold() != ".json":
            raise ValueError("Output JSON requer extensão .json")
        if ics_output is not None:
            if ics_output.suffix.casefold() != ".ics":
                raise ValueError("Output ICS requer extensão .ics")
            if json_output.resolve() == ics_output.resolve():
                raise ValueError("JSON e ICS têm de ter destinos diferentes")
        with ANNPClient() as client:
            entries = client.get_benjamins_schedule(
                season, competition_id=competition_id
            )
        payload = export_benjamins_json(entries)
        staged_json = create_staged_path(json_output)
        staged_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_benjamins_json(json.loads(staged_json.read_text(encoding="utf-8")))
        if ics_output is not None:
            staged_ics = create_staged_path(ics_output)
            export_benjamins_ics(entries, staged_ics)
            validate_ics_file(
                staged_ics,
                expected_uids={schedule_uid(entry) for entry in entries},
                expected_event_count=len(entries),
            )
            publish_staged_pair(staged_json, json_output, staged_ics, ics_output)
        else:
            publish_staged_file(staged_json, json_output)
    except Exception as exc:  # noqa: BLE001 -- CLI must log failure and return nonzero.
        logger.error(exc)
        logger.finish(status="ERROR", details=details)
        return 1
    finally:
        if staged_json is not None:
            staged_json.unlink(missing_ok=True)
        if staged_ics is not None:
            staged_ics.unlink(missing_ok=True)

    logger.info(
        f"Fonte: ANNP schedule\nÉpoca: {season}\nID da competição: {competition_id}\n"
        f"Nº ações: {len(entries)}\nJSON: {json_output}\nICS: {ics_output or '(não pedido)'}"
    )
    logger.finish(status="SUCCESS", details=[*details, f"Nº ações: {len(entries)}"])
    return 0


def _publish_matches(
    *,
    source: MatchSource,
    team: str,
    json_output: Path,
    ics_output: Path,
    fetch_matches: Callable[[], list[Match]],
    details: list[str],
    success_context: str,
    log_dir: Path | None,
    command: str,
) -> int:
    """Publish any source snapshot with the shared transactional contract."""
    logger = RunLogger(
        log_dir or RUN_LOG_DIR,
        command=command,
        team=team,
        output_format="json+ics",
        source=source.value,
    )
    staged_json: Path | None = None
    staged_ics: Path | None = None
    try:
        if json_output.suffix.casefold() != ".json":
            raise ValueError(f"Output JSON requer extensão .json; recebido {json_output.suffix or '(sem extensão)'}")
        if ics_output.suffix.casefold() != ".ics":
            raise ValueError(f"Output ICS requer extensão .ics; recebido {ics_output.suffix or '(sem extensão)'}")
        if json_output.resolve() == ics_output.resolve():
            raise ValueError("JSON e ICS têm de ter destinos diferentes")

        # Both exporters receive this exact, single normalized snapshot.
        matches = fetch_matches()
        validate_match_snapshot(matches)

        payload = export_matches_json(matches, source=source.value)
        expected_external_ids = {match.external_id for match in matches}
        expected_uids = {match_uid(match) for match in matches}
        staged_json = create_staged_path(json_output)
        staged_ics = create_staged_path(ics_output)
        staged_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        export_matches_ics(matches, staged_ics, calendar_name=matches[0].competition)
        validate_json_file(staged_json, expected_external_ids=expected_external_ids)
        validate_ics_file(
            staged_ics,
            expected_uids=expected_uids,
            expected_event_count=len(matches),
        )
        publish_staged_pair(staged_json, json_output, staged_ics, ics_output)
    except Exception as exc:  # noqa: BLE001 -- log every run failure, then return nonzero.
        logger.error(exc)
        logger.finish(status="ERROR", details=details)
        return 1
    finally:
        if staged_json is not None:
            staged_json.unlink(missing_ok=True)
        if staged_ics is not None:
            staged_ics.unlink(missing_ok=True)

    logger.info(
        f"Fonte: {source.value}\n{success_context}\nEquipa: {team}\nNº jogos: {len(matches)}\n"
        f"JSON: {json_output}\nICS: {ics_output}"
    )
    logger.finish(status="SUCCESS", details=[*details, f"Nº jogos publicados: {len(matches)}"])
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
    if args.command == "publish" and args.source == "fpn":
        return publish_fpn(
            args.domain,
            args.team,
            args.json_output,
            args.ics_output,
            command=" ".join(sys.argv if argv is None else ["python", "-m", "waterpolo.main", *argv]),
        )
    if args.command == "publish" and args.source == "annp":
        return publish_annp(
            args.season,
            args.team,
            args.json_output,
            args.ics_output,
            category=args.category,
            competition_id=args.competition_id,
            command=" ".join(
                sys.argv if argv is None else ["python", "-m", "waterpolo.main", *argv]
            ),
        )
    if args.command == "publish" and args.source == "annp-schedule":
        return publish_annp_schedule(
            args.season,
            args.competition_id,
            args.json_output,
            args.ics_output,
            command=" ".join(
                sys.argv if argv is None else ["python", "-m", "waterpolo.main", *argv]
            ),
        )
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
