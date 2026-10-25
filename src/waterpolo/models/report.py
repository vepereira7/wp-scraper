"""Presentation-only models for deterministic calendar reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from waterpolo.models.benjamins_schedule import BenjaminsScheduleEntry
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

    def as_entry(self) -> ReportEntry:
        return ReportEntry(
            date=self.match.date,
            time=self.match.time,
            season=self.match.season,
            label=self.label,
            description=f"{self.match.home} x {self.match.away}",
            venue=self.match.location,
            home_sort=self.match.home,
            away_sort=self.match.away,
        )


@dataclass(frozen=True, slots=True)
class ReportSchedule:
    """A Benjamins action associated with its report label."""

    label: str
    schedule: BenjaminsScheduleEntry

    def as_entry(self) -> ReportEntry:
        return ReportEntry(
            date=self.schedule.date,
            time=self.schedule.time,
            season=self.schedule.season,
            label=self.label,
            description="-",
            venue=self.schedule.venue,
            home_sort="",
            away_sort="",
        )


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """Presentation-only row shared by matches and actions."""

    date: date
    time: time | None
    season: str
    label: str
    description: str
    venue: str | None
    home_sort: str
    away_sort: str

    @property
    def display_date(self) -> str:
        return self.date.strftime("%d/%m/%Y")

    @property
    def display_time(self) -> str:
        return self.time.strftime("%H:%M") if self.time else "Por definir"

    @property
    def display_location(self) -> str:
        return self.venue if self.venue is not None and self.venue.strip() else "Por definir"


ReportItem = ReportMatch | ReportSchedule


@dataclass(frozen=True, slots=True)
class MonthGroup:
    """Chronological group of report matches for one month and year."""

    year: int
    month: int
    matches: tuple[ReportItem, ...]

    @property
    def heading(self) -> str:
        return f"{MONTH_NAMES_PT[self.month]} {self.year}"
