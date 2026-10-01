"""Errors raised by the FPN ArenaDisplay integration."""


class FPNArenaError(RuntimeError):
    """Base error for FPN ArenaDisplay operations."""


class FPNArenaHTTPError(FPNArenaError):
    """An HTTP or network operation failed."""


class FPNCompetitionNotFoundError(FPNArenaError):
    """The requested ArenaDisplay competition domain does not exist."""


class FPNResponseError(FPNArenaError):
    """The API returned an invalid or unexpected response."""


class FPNGameStructureError(FPNResponseError):
    """A game contains an invalid team structure."""
