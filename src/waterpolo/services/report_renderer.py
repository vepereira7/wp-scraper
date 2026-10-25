"""Deterministic standalone HTML and PDF calendar report rendering."""

from __future__ import annotations

import base64
import html
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from waterpolo.models.report import MonthGroup, ReportItem, ReportMatch, ReportSchedule

TEMPLATE_DIR = Path(__file__).with_name("templates")
HTML_TEMPLATE_PATH = TEMPLATE_DIR / "calendar_report.html"
CSS_PATH = TEMPLATE_DIR / "calendar_report.css"
LOGO_PATH = Path(__file__).parents[1] / "report" / "assets" / "foca-logo.png"
PDF_DOCKER_IMAGE = "waterpolo-report-weasyprint:70.0"
FIRST_PAGE_CAPACITY = 10
FOLLOWING_PAGE_CAPACITY = 15


def sort_report_matches(matches: Sequence[ReportItem]) -> list[ReportItem]:
    """Apply the report's complete and stable global ordering."""
    return sorted(
        matches,
        key=lambda item: (
            item.as_entry().date,
            item.as_entry().time is None,
            item.as_entry().time,
            item.as_entry().label.casefold(),
            item.as_entry().home_sort.casefold(),
            item.as_entry().away_sort.casefold(),
        ),
    )


def group_matches_by_month(matches: Sequence[ReportItem]) -> list[MonthGroup]:
    """Group sorted matches by both year and month."""
    grouped: dict[tuple[int, int], list[ReportItem]] = defaultdict(list)
    for item in sort_report_matches(matches):
        date = item.as_entry().date
        grouped[(date.year, date.month)].append(item)
    return [
        MonthGroup(year=year, month=month, matches=tuple(grouped[(year, month)]))
        for year, month in sorted(grouped)
    ]


def paginate_month_groups(groups: Sequence[MonthGroup]) -> list[tuple[MonthGroup, ...]]:
    """Assign complete month groups to deterministic logical pages."""
    pages: list[tuple[MonthGroup, ...]] = []
    current: list[MonthGroup] = []
    used_capacity = 0
    page_capacity = FIRST_PAGE_CAPACITY
    for group in groups:
        group_size = len(group.matches) + 2
        if current and used_capacity + group_size > page_capacity:
            pages.append(tuple(current))
            current = []
            used_capacity = 0
            page_capacity = FOLLOWING_PAGE_CAPACITY
        current.append(group)
        used_capacity += group_size
    if current:
        pages.append(tuple(current))
    return pages


def report_title(matches: Sequence[ReportItem]) -> str:
    """Derive a deterministic season title from the normalized input."""
    seasons = {item.as_entry().season for item in matches}
    if len(seasons) == 1:
        season = next(iter(seasons))
        compact = re.fullmatch(r"S?(\d{2})(\d{2})", season, flags=re.IGNORECASE)
        expanded = re.fullmatch(r"(\d{4})/(\d{2}|\d{4})", season)
        if compact:
            start, end = compact.groups()
            return f"Quadro de Ações 20{start}/20{end}"
        if expanded:
            start, end = expanded.groups()
            end = f"{start[:2]}{end}" if len(end) == 2 else end
            return f"Quadro de Ações {start}/{end}"

    years = sorted({item.as_entry().date.year for item in matches})
    if len(years) == 1:
        return f"Quadro de Ações {years[0]}"
    return f"Quadro de Ações {years[0]}/{years[-1]}"


def render_html(matches: Sequence[ReportItem]) -> str:
    """Render one complete standalone HTML document."""
    if not matches:
        raise ValueError("não existem jogos para incluir no relatório")

    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8").rstrip()
    logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    logo_data_uri = f"data:image/png;base64,{logo_data}"
    title = report_title(matches)
    action_layout = any(isinstance(item, ReportSchedule) for item in matches)
    pages = paginate_month_groups(group_matches_by_month(matches))
    sections = "\n".join(_render_page(page, action_layout=action_layout) for page in pages)
    return (
        template.replace("{{REPORT_TITLE}}", html.escape(title))
        .replace("{{REPORT_CSS}}", css)
        .replace("{{REPORT_LOGO_DATA_URI}}", logo_data_uri)
        .replace("{{REPORT_SECTIONS}}", sections)
    )


def write_html(matches: Sequence[ReportItem], destination: Path) -> None:
    """Write the deterministic HTML report, creating parent directories."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_html(matches), encoding="utf-8")


def write_pdf(html_source: Path, destination: Path) -> None:
    """Convert the already-written HTML with an offline WeasyPrint container."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = pdf_docker_command(html_source, destination)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("Docker não está instalado ou não está disponível") from exc
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"falha ao gerar PDF com WeasyPrint em Docker: {details}")


def pdf_docker_command(html_source: Path, destination: Path) -> list[str]:
    """Build the network-isolated Docker command used for PDF conversion."""
    source = html_source.resolve()
    output_directory = destination.parent.resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
        "--env=HOME=/tmp",
        "--env=XDG_CACHE_HOME=/tmp/cache",
    ]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.append(f"--user={os.getuid()}:{os.getgid()}")
    command.extend(
        [
            f"--mount=type=bind,src={source},dst=/input/report.html,readonly",
            f"--mount=type=bind,src={output_directory},dst=/output",
            PDF_DOCKER_IMAGE,
            "/input/report.html",
            f"/output/{destination.name}",
        ]
    )
    return command


def _render_page(groups: Sequence[MonthGroup], *, action_layout: bool) -> str:
    months = "\n".join(_render_month(group, action_layout=action_layout) for group in groups)
    return f"""    <div class="report-page">
{months}
    </div>"""


def _render_month(group: MonthGroup, *, action_layout: bool) -> str:
    rows = "\n".join(_render_row(item, action_layout=action_layout) for item in group.matches)
    if action_layout:
        return f"""    <section class="month">
      <h2>{html.escape(group.heading)}</h2>
      <table>
        <colgroup>
          <col class="date-column">
          <col class="category-column">
          <col style="width: 36%">
          <col class="time-column">
          <col class="location-column">
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Escalão</th>
            <th scope="col">Jogo/Ação</th>
            <th scope="col">Hora</th>
            <th scope="col">Local</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>"""
    return f"""    <section class="month">
      <h2>{html.escape(group.heading)}</h2>
      <table>
        <colgroup>
          <col class="date-column">
          <col class="time-column">
          <col class="category-column">
          <col class="team-column">
          <col class="team-column">
          <col class="location-column">
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Hora</th>
            <th scope="col">Escalão</th>
            <th scope="col">Casa</th>
            <th scope="col">Fora</th>
            <th scope="col">Local</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </section>"""


def _render_row(item: ReportItem, *, action_layout: bool) -> str:
    if action_layout:
        entry = item.as_entry()
        values = (
            entry.display_date,
            entry.label,
            entry.description,
            entry.display_time,
            entry.display_location,
        )
        cells = "\n".join(f"            <td>{html.escape(value)}</td>" for value in values)
        return f"""          <tr>
{cells}
          </tr>"""
    if not isinstance(item, ReportMatch):
        raise TypeError("Schedule entries require the action report layout")
    values = (
        item.display_date,
        item.display_time,
        item.label,
        item.match.home,
        item.match.away,
        item.display_location,
    )
    cells = "\n".join(f"            <td>{html.escape(value)}</td>" for value in values)
    return f"""          <tr>
{cells}
          </tr>"""
