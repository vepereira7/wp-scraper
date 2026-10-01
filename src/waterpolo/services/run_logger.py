"""File and terminal logging for export command runs."""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from time import monotonic


class RunLogger:
    """Collect export run output and persist a final text report."""

    def __init__(self, log_dir: Path, *, command: str, team: str, output_format: str):
        self.log_dir = log_dir
        self.command = command
        self.team = team
        self.output_format = output_format
        self.started = datetime.now().astimezone()
        self._clock_started = monotonic()
        self._messages: list[str] = []
        self._error_details: list[str] = []

    def info(self, message: str) -> None:
        self._messages.append(message)
        print(message)

    def finish(self, *, status: str, details: list[str] | None = None) -> Path:
        finished = datetime.now().astimezone()
        elapsed = monotonic() - self._clock_started
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self.started.strftime("%Y%m%d_%H%M%S")
        safe_team = "_".join(self.team.casefold().split()) or "team"
        path = self.log_dir / f"{timestamp}_export_fpn_{safe_team}_{self.output_format}.txt"
        content = [
            f"Início: {self.started.isoformat(timespec='seconds')}",
            f"Comando: {self.command}",
            *(details or []),
            *self._messages,
            f"Status: {status}",
        ]
        content.extend(self._error_details)
        content.extend(
            [
                f"Fim: {finished.isoformat(timespec='seconds')}",
                f"Duração: {elapsed:.3f} segundos",
            ]
        )
        path.write_text("\n".join(content) + "\n", encoding="utf-8")
        return path

    def error(self, exc: BaseException) -> None:
        rendered = traceback.format_exc()
        self._messages.append(f"Erro: {type(exc).__name__}: {exc}")
        print(f"Erro ao exportar jogos FPN: {exc}", file=sys.stderr)
        self._error_details = [
            f"Tipo de erro: {type(exc).__name__}",
            f"Mensagem de erro: {exc}",
            "Traceback:",
            rendered.rstrip(),
        ]
