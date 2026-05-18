class AppError(Exception):
    """Base application error."""


class NotMigratedYetError(AppError):
    """Raised for logic that still lives in the legacy script."""

