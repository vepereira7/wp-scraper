"""Errors raised by the ANNP integration."""


class ANNPError(RuntimeError):
    """Base error for ANNP operations."""


class ANNPHTTPError(ANNPError):
    """An HTTP or network operation failed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ANNPResponseError(ANNPError):
    """ANNP returned an invalid or unexpected HTML response."""


class ANNPCompetitionNotFoundError(ANNPError):
    """The requested ANNP competition does not exist or is ambiguous."""
