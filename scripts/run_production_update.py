#!/usr/bin/env python3
"""Orchestrate validated calendar publication and WP Stats imports.

This module deliberately contains no source-specific scraping logic.  It invokes
``python -m waterpolo.main publish`` and adds the operational safeguards needed
by the production timer: a process lock, a second validation barrier, atomic
copies, import validation, and rollback of the WP Stats input on failure.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from waterpolo.scraper.annp.domain import annp_season_label
from waterpolo.scraper.fpn.domain import extract_fpn_season
from waterpolo.services.validation import validate_ics_file, validate_json_payload

DEFAULT_CONFIG = Path("/etc/waterpolo-calendar/calendars.json")
DEFAULT_ENV_FILE = Path("/etc/waterpolo-calendar/wp-stats.env")
DEFAULT_WP_STATS_CALENDAR_DIR = Path("/opt/wp-stats/data/calendars")
DEFAULT_STAGING_DIR = Path("/var/lib/waterpolo/staging")
DEFAULT_CURRENT_DIR = Path("/var/lib/waterpolo/current")
DEFAULT_PUBLIC_ICS_DIR = Path("/var/www/waterpolo-calendars")
DEFAULT_LOCK_FILE = Path("/var/lib/waterpolo/calendar-update.lock")
DEFAULT_TIMEOUT = 30.0
DEFAULT_WP_STATS_BASE_URL = "https://129.146.159.13"

SUPPORTED_SOURCES = {"fpn", "annp"}
REQUIRED_PARAMS = {
    "fpn": frozenset({"domain", "team"}),
    "annp": frozenset({"season", "team", "competition_id"}),
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOGGER = logging.getLogger("waterpolo.production")


class RunnerError(RuntimeError):
    """Base class for expected operational failures."""


class ConfigError(RunnerError):
    """Raised when local configuration is invalid."""


class LockUnavailable(RunnerError):
    """Raised when another runner owns the process lock."""


class PublishError(RunnerError):
    """Raised when the existing publish command fails."""


class WPStatsError(RunnerError):
    """Raised for authentication, HTTP, or import contract failures."""


@dataclass(frozen=True)
class CalendarConfig:
    source: str
    calendar_id: str
    ics_filename: str
    params: Mapping[str, str]

    @property
    def expected_source(self) -> str:
        return self.source.upper()

    @property
    def expected_season(self) -> str:
        if self.source == "fpn":
            return extract_fpn_season(self.params["domain"])
        return annp_season_label(self.params["season"])


@dataclass(frozen=True)
class WPStatsConfig:
    base_url: str
    email: str
    password: str
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class RunnerPaths:
    wp_stats_calendar_dir: Path
    staging_dir: Path
    current_dir: Path
    public_ics_dir: Path


@dataclass(frozen=True)
class ImportCounts:
    total: int
    mapped: int
    unresolved: int


class HTTPClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class WPStatsAPI:
    """Small stateful client which logs in at most once per successful run."""

    def __init__(self, config: WPStatsConfig, client: HTTPClient) -> None:
        self.config = config
        self.client = client
        self._token: str | None = None

    def import_calendar(self, calendar_id: str, *, expected_total: int) -> ImportCounts:
        if self._token is None:
            self._token = login(self.client, self.config)
        payload = import_calendar(
            self.client,
            self.config,
            token=self._token,
            calendar_id=calendar_id,
        )
        return validate_import_response(
            payload,
            expected_calendar_id=calendar_id,
            expected_total=expected_total,
        )


def load_config(path: Path) -> list[CalendarConfig]:
    """Load and strictly validate the multi-calendar configuration."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"não foi possível ler a configuração {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON de configuração inválido em {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError("a raiz de calendars.json tem de ser um objeto")
    raw_calendars = payload.get("calendars")
    if not isinstance(raw_calendars, list):
        raise ConfigError("calendars.json tem de conter uma lista 'calendars'")
    if not raw_calendars:
        raise ConfigError("a lista 'calendars' não pode estar vazia")

    calendars = [_parse_calendar(item, index) for index, item in enumerate(raw_calendars)]
    _reject_duplicate_config_values(calendars, "calendar_id")
    _reject_duplicate_config_values(calendars, "ics_filename")
    return calendars


def _parse_calendar(raw: Any, index: int) -> CalendarConfig:
    label = f"calendars[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} tem de ser um objeto")

    source = _required_string(raw, "source", label).casefold()
    if source not in SUPPORTED_SOURCES:
        raise ConfigError(f"{label}.source desconhecida: {source!r}")
    calendar_id = _safe_filename(_required_string(raw, "calendar_id", label), f"{label}.calendar_id")
    ics_filename = _safe_filename(
        _required_string(raw, "ics_filename", label), f"{label}.ics_filename"
    )
    if Path(ics_filename).suffix.casefold() != ".ics":
        raise ConfigError(f"{label}.ics_filename tem de terminar em .ics")

    params = raw.get("params")
    if not isinstance(params, dict):
        raise ConfigError(f"{label}.params tem de ser um objeto")
    normalized_params: dict[str, str] = {}
    for key, value in params.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{label}.params deve conter apenas strings não vazias")
        normalized_params[key] = value.strip()
    missing = sorted(REQUIRED_PARAMS[source] - normalized_params.keys())
    if missing:
        raise ConfigError(f"{label}.params sem campos obrigatórios: {', '.join(missing)}")

    calendar = CalendarConfig(source, calendar_id, ics_filename, normalized_params)
    try:
        _ = calendar.expected_season
    except ValueError as exc:
        raise ConfigError(f"{label}.params contém época inválida: {exc}") from exc
    return calendar


def _required_string(raw: Mapping[str, Any], field: str, label: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label}.{field} tem de ser uma string não vazia")
    return value.strip()


def _safe_filename(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value) or Path(value).name != value:
        raise ConfigError(f"{label} contém um nome de ficheiro inseguro")
    return value


def _reject_duplicate_config_values(calendars: Sequence[CalendarConfig], field: str) -> None:
    values = [getattr(calendar, field) for calendar in calendars]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ConfigError(f"{field} duplicado: {', '.join(duplicates)}")


def load_environment(
    path: Path | None,
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> WPStatsConfig:
    """Load WP Stats settings without mutating or logging the process environment.

    Values already present in ``environ`` take precedence over the optional env
    file, matching normal systemd Environment/EnvironmentFile overrides.
    """
    supplied = dict(os.environ if environ is None else environ)
    file_values: dict[str, str] = {}
    if path is not None and path.exists():
        file_values = _parse_env_file(path)
    merged = {**file_values, **supplied}

    required = ("WP_STATS_EMAIL", "WP_STATS_PASSWORD")
    missing = [name for name in required if not merged.get(name, "").strip()]
    if missing:
        raise ConfigError("variáveis de ambiente em falta: " + ", ".join(missing))

    base_url = merged.get("WP_STATS_BASE_URL", DEFAULT_WP_STATS_BASE_URL).strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ConfigError("WP_STATS_BASE_URL tem de ser um URL HTTP(S) absoluto")
    if parsed_url.username or parsed_url.password:
        raise ConfigError("WP_STATS_BASE_URL não pode conter credenciais")
    if timeout <= 0:
        raise ConfigError("o timeout HTTP tem de ser positivo")
    return WPStatsConfig(
        base_url=base_url,
        email=merged["WP_STATS_EMAIL"],
        password=merged["WP_STATS_PASSWORD"],
        timeout=timeout,
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"não foi possível ler o ficheiro de ambiente {path}: {exc}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ConfigError(f"linha inválida em {path}:{line_number}")
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ConfigError(f"nome de variável inválido em {path}:{line_number}")
        values[name] = _parse_env_value(raw_value.strip(), path, line_number)
    return values


def _parse_env_value(raw_value: str, path: Path, line_number: int) -> str:
    if not raw_value:
        return ""
    if raw_value[0] in {'"', "'"}:
        try:
            value = ast.literal_eval(raw_value)
        except (SyntaxError, ValueError) as exc:
            raise ConfigError(f"valor quoted inválido em {path}:{line_number}") from exc
        if not isinstance(value, str):
            raise ConfigError(f"valor não textual em {path}:{line_number}")
        return value
    # In unquoted dotenv values, a whitespace-prefixed # starts a comment.
    return re.split(r"\s+#", raw_value, maxsplit=1)[0].rstrip()


def build_publish_command(
    calendar: CalendarConfig,
    json_output: Path,
    ics_output: Path,
) -> list[str]:
    command = [sys.executable, "-m", "waterpolo.main", "publish", calendar.source]
    if calendar.source == "fpn":
        command.extend(
            ["--domain", calendar.params["domain"], "--team", calendar.params["team"]]
        )
    elif calendar.source == "annp":
        command.extend(
            [
                "--season",
                calendar.params["season"],
                "--team",
                calendar.params["team"],
                "--competition-id",
                calendar.params["competition_id"],
            ]
        )
    else:  # Defensive: load_config prevents this for normal callers.
        raise ConfigError(f"source desconhecida: {calendar.source!r}")
    command.extend(["--json-output", str(json_output), "--ics-output", str(ics_output)])
    return command


def run_publish(
    command: Sequence[str],
    *,
    run: Any = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Run the existing publisher without a shell and surface useful output."""
    try:
        result = run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PublishError(f"não foi possível executar publish: {exc}") from exc
    if result.returncode != 0:
        details = _subprocess_details(result.stdout, result.stderr)
        suffix = f": {details}" if details else ""
        raise PublishError(f"publish terminou com exit code {result.returncode}{suffix}")
    return result


def _subprocess_details(stdout: str | None, stderr: str | None) -> str:
    parts = []
    for label, output in (("stdout", stdout), ("stderr", stderr)):
        if output and output.strip():
            compact = output.strip()
            if len(compact) > 4000:
                compact = compact[-4000:]
            parts.append(f"{label}={compact}")
    return "; ".join(parts)


def validate_json(path: Path, calendar: CalendarConfig) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc
    validate_json_payload(payload)
    if payload.get("source") != calendar.expected_source:
        raise ValueError(
            f"JSON inválido: source esperada {calendar.expected_source}, "
            f"recebida {payload.get('source')!r}"
        )

    for index, match in enumerate(payload["matches"]):
        if match.get("source") != calendar.expected_source:
            raise ValueError(
                f"JSON inválido: matches[{index}].source não corresponde a {calendar.expected_source}"
            )
        if match.get("season") != calendar.expected_season:
            raise ValueError(
                f"JSON inválido: matches[{index}].season não corresponde a "
                f"{calendar.expected_season}"
            )
    return payload


def validate_ics(path: Path, *, payload: Mapping[str, Any], source: str) -> None:
    external_ids = {str(match["external_id"]) for match in payload["matches"]}
    expected_uids = {f"{source.upper()}-{external_id}@waterpolo" for external_id in external_ids}
    validate_ics_file(
        path,
        expected_uids=expected_uids,
        expected_event_count=payload["match_count"],
    )


def request_json(
    client: HTTPClient,
    method: str,
    url: str,
    *,
    timeout: float,
    **kwargs: Any,
) -> Mapping[str, Any]:
    """Perform one TLS-verifying request and require a JSON object response."""
    try:
        response = client.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise WPStatsError(f"WP Stats respondeu com HTTP {exc.response.status_code}") from exc
    except httpx.TimeoutException as exc:
        raise WPStatsError("timeout ao contactar WP Stats") from exc
    except httpx.TransportError as exc:
        raise WPStatsError(f"erro de transporte/TLS ao contactar WP Stats: {exc}") from exc
    except httpx.HTTPError as exc:
        raise WPStatsError(f"erro HTTP ao contactar WP Stats: {exc}") from exc
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise WPStatsError("WP Stats devolveu JSON inválido") from exc
    if not isinstance(payload, dict):
        raise WPStatsError("WP Stats devolveu uma resposta JSON inesperada")
    return payload


def login(client: HTTPClient, config: WPStatsConfig) -> str:
    payload = request_json(
        client,
        "POST",
        f"{config.base_url}/api/v1/auth/login",
        timeout=config.timeout,
        json={"email": config.email, "password": config.password},
    )
    token = _extract_token(payload)
    if token is None:
        raise WPStatsError("resposta de login sem Bearer token")
    return token


def _extract_token(payload: Mapping[str, Any]) -> str | None:
    for container in (payload, payload.get("data")):
        if not isinstance(container, Mapping):
            continue
        for key in ("access_token", "token"):
            token = container.get(key)
            if isinstance(token, str) and token.strip():
                return token.strip()
    return None


def import_calendar(
    client: HTTPClient,
    config: WPStatsConfig,
    *,
    token: str,
    calendar_id: str,
) -> Mapping[str, Any]:
    return request_json(
        client,
        "POST",
        f"{config.base_url}/api/v1/calendars/{calendar_id}/import",
        timeout=config.timeout,
        headers={"Authorization": f"Bearer {token}"},
    )


def validate_import_response(
    payload: Any,
    *,
    expected_calendar_id: str,
    expected_total: int,
) -> ImportCounts:
    """Validate the known WP Stats calendar import response contract."""
    if not isinstance(payload, dict):
        raise WPStatsError("WP Stats devolveu uma resposta de import JSON inesperada")

    required = (
        "calendar_id",
        "matches_found",
        "created",
        "updated",
        "unchanged",
        "mapped",
        "unresolved",
        "resolution_status",
        "resolution_reasons",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise WPStatsError("resposta de import sem campos obrigatórios: " + ", ".join(missing))

    if payload["calendar_id"] != expected_calendar_id:
        raise WPStatsError(
            f"import devolveu calendar_id={payload['calendar_id']!r}, "
            f"esperado {expected_calendar_id!r}"
        )

    count_fields = (
        "matches_found",
        "created",
        "updated",
        "unchanged",
        "mapped",
        "unresolved",
    )
    counts = {field: _count_value(payload, field) for field in count_fields}
    if not isinstance(payload["resolution_reasons"], list):
        raise WPStatsError("resposta de import com campo 'resolution_reasons' inválido")

    matches_found = counts["matches_found"]
    created = counts["created"]
    updated = counts["updated"]
    unchanged = counts["unchanged"]
    mapped = counts["mapped"]
    unresolved = counts["unresolved"]

    violations: list[str] = []
    if matches_found != expected_total:
        violations.append(
            f"import matches_found={matches_found}, mas o artefacto validado contém "
            f"{expected_total} jogos"
        )
    if created + updated + unchanged != matches_found:
        violations.append(
            "import com contagens created/updated/unchanged inconsistentes: "
            f"created={created}, updated={updated}, unchanged={unchanged}, "
            f"matches_found={matches_found}"
        )
    if mapped + unresolved != matches_found:
        violations.append(
            "import com contagens mapped/unresolved inconsistentes: "
            f"mapped={mapped}, unresolved={unresolved}, matches_found={matches_found}"
        )
    if unresolved != 0:
        violations.append(f"import com jogos não resolvidos: unresolved={unresolved}")
    if mapped != matches_found:
        violations.append(
            f"import incompleto: mapped={mapped}, matches_found={matches_found}"
        )
    if payload["resolution_status"] != "MAPPED":
        violations.append(
            "import não completou com resolution_status='MAPPED' "
            f"(resolution_status={payload['resolution_status']!r})"
        )
    if violations:
        raise WPStatsError("; ".join(violations))
    return ImportCounts(total=matches_found, mapped=mapped, unresolved=unresolved)


def _count_value(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise WPStatsError(f"resposta de import com contador {key!r} inválido")
    return value


def atomic_copy(source: Path, destination: Path) -> None:
    """Copy a file via a same-directory temporary and atomic replacement."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_mode = (
        stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o644
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as source_file, os.fdopen(descriptor, "wb") as target_file:
            descriptor = -1
            shutil.copyfileobj(source_file, target_file)
            target_file.flush()
            os.fsync(target_file.fileno())
        temporary.chmod(destination_mode)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def installed_file(source: Path, destination: Path) -> Iterator[None]:
    """Install a file atomically and restore the prior version unless committed."""
    backup: Path | None = None
    destination_existed = destination.exists()
    if destination_existed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, backup_name = tempfile.mkstemp(
            prefix=f".{destination.name}.previous-", dir=destination.parent
        )
        os.close(descriptor)
        backup = Path(backup_name)
        try:
            shutil.copy2(destination, backup)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
    committed = False
    try:
        atomic_copy(source, destination)
        yield
        committed = True
    finally:
        if committed:
            if backup is not None:
                backup.unlink(missing_ok=True)
        elif backup is not None:
            atomic_copy(backup, destination)
            backup.unlink(missing_ok=True)
        elif not destination_existed:
            destination.unlink(missing_ok=True)


@contextmanager
def installed_wp_stats_json(source: Path, destination: Path) -> Iterator[None]:
    """Install WP Stats JSON atomically and roll it back when the operation fails."""
    with installed_file(source, destination):
        yield


def process_calendar(
    calendar: CalendarConfig,
    *,
    paths: RunnerPaths,
    api: WPStatsAPI,
    publish_runner: Any | None = None,
) -> ImportCounts:
    """Run the complete fail-safe pipeline for one calendar."""
    calendar_id = calendar.calendar_id
    paths.staging_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{calendar_id}-", dir=paths.staging_dir
    ) as temporary_directory:
        staging = Path(temporary_directory)
        staged_json = staging / f"{calendar_id}.json"
        staged_ics = staging / calendar.ics_filename

        LOGGER.info("[%s] generating", calendar_id)
        command = build_publish_command(calendar, staged_json, staged_ics)
        (publish_runner or run_publish)(command)

        LOGGER.info("[%s] validating", calendar_id)
        payload = validate_json(staged_json, calendar)
        validate_ics(staged_ics, payload=payload, source=calendar.source)

        wp_stats_json = paths.wp_stats_calendar_dir / f"{calendar_id}.json"
        LOGGER.info("[%s] copying JSON", calendar_id)
        with installed_wp_stats_json(staged_json, wp_stats_json):
            LOGGER.info("[%s] importing WP Stats", calendar_id)
            counts = api.import_calendar(calendar_id, expected_total=payload["match_count"])
            LOGGER.info(
                "[%s] mapped=%d unresolved=%d",
                calendar_id,
                counts.mapped,
                counts.unresolved,
            )
            LOGGER.info("[%s] promoting current snapshot", calendar_id)
            current_json = paths.current_dir / f"{calendar_id}.json"
            current_ics = paths.current_dir / calendar.ics_filename
            with (
                installed_file(staged_json, current_json),
                installed_file(staged_ics, current_ics),
            ):
                LOGGER.info("[%s] publishing public ICS", calendar_id)
                public_ics = paths.public_ics_dir / calendar.ics_filename
                atomic_copy(staged_ics, public_ics)
        LOGGER.info("[%s] success", calendar_id)
        return counts


def process_calendars(
    calendars: Sequence[CalendarConfig],
    *,
    paths: RunnerPaths,
    api: WPStatsAPI,
    publish_runner: Any | None = None,
) -> list[str]:
    """Process sequentially, continuing independent calendars after failures."""
    failed: list[str] = []
    for calendar in calendars:
        try:
            process_calendar(
                calendar,
                paths=paths,
                api=api,
                publish_runner=publish_runner,
            )
        except Exception as exc:  # noqa: BLE001 -- isolate each configured calendar.
            failed.append(calendar.calendar_id)
            LOGGER.error("[%s] failed: %s", calendar.calendar_id, exc)
    return failed


@contextmanager
def process_lock(path: Path) -> Iterator[None]:
    """Acquire a non-blocking advisory lock for the full runner lifetime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockUnavailable(f"já existe uma execução ativa (lock: {path})") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--wp-stats-calendar-dir", type=Path, default=DEFAULT_WP_STATS_CALENDAR_DIR
    )
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING_DIR)
    parser.add_argument("--current-dir", type=Path, default=DEFAULT_CURRENT_DIR)
    parser.add_argument("--public-ics-dir", type=Path, default=DEFAULT_PUBLIC_ICS_DIR)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: Any = httpx.Client,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        with process_lock(args.lock_file):
            calendars = load_config(args.config)
            wp_stats_config = load_environment(
                args.env_file,
                environ,
                timeout=args.timeout,
            )
            paths = RunnerPaths(
                wp_stats_calendar_dir=args.wp_stats_calendar_dir,
                staging_dir=args.staging_dir,
                current_dir=args.current_dir,
                public_ics_dir=args.public_ics_dir,
            )
            # No verify=False: httpx's default certificate verification remains active.
            with client_factory() as client:
                api = WPStatsAPI(wp_stats_config, client)
                failed = process_calendars(calendars, paths=paths, api=api)
            if failed:
                LOGGER.error("execution failed for: %s", ", ".join(failed))
                return 1
            return 0
    except LockUnavailable as exc:
        LOGGER.warning("%s", exc)
        return 2
    except (ConfigError, OSError) as exc:
        LOGGER.error("runner failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
