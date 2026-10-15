"""Presentation-only models for deterministic calendar reports."""

from __future__ import annotations

from dataclasses import dataclass

from waterpolo.models.match import Match

MONTH_NAMES_PT = (
    "",
    "JANEIRO",
    "FEVEREIRO",
    "MARÇO",
    "ABRIL",
    "MAIO",
    "JUNHO",
    "JULHO",
    "AGOSTO",
    "SETEMBRO",
    "OUTUBRO",
    "NOVEMBRO",
    "DEZEMBRO",
)


@dataclass(frozen=True, slots=True)
class ReportMatch:
    """A normalized match associated with its report label."""

    label: str
    match: Match

    @property
    def display_date(self) -> str:
        return self.match.date.strftime("%d/%m/%Y")

    @property
    def display_time(self) -> str:
        if self.match.time is None:
            return "Por definir"
        return self.match.time.strftime("%H:%M")

    @property
    def display_location(self) -> str:
        location = self.match.location
        return location if location is not None and location.strip() else "Por definir"

    @property
    def display_result(self) -> str:
        if self.match.score_home is None or self.match.score_away is None:
            return "—"
        return f"{self.match.score_home}–{self.match.score_away}"


@dataclass(frozen=True, slots=True)
class MonthGroup:
    """Chronological group of report matches for one month and year."""

    year: int
    month: int
    matches: tuple[ReportMatch, ...]

    @property
    def heading(self) -> str:
        return f"{MONTH_NAMES_PT[self.month]} {self.year}"
