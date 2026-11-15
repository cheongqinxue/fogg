"""Google Maps client errors."""


class GoogleMapsApiError(Exception):
    """Raised when a Google Maps HTTP call fails after retries or with a non-retryable error."""

    def __init__(self, message: str) -> None:
        """Store a user-facing error message (no stack trace required in logs)."""
        super().__init__(message)
        self.message = message


class GmapsQuotaExceededError(Exception):
    """Raised when a local free-tier cap would be exceeded (enforcement enabled)."""

    def __init__(
        self,
        message: str,
        *,
        sku: str,
        used: int,
        cap: int,
        units_requested: int,
    ) -> None:
        """Store quota context for callers and logs."""
        super().__init__(message)
        self.message = message
        self.sku = sku
        self.used = used
        self.cap = cap
        self.units_requested = units_requested
