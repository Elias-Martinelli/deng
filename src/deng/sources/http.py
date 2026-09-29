"""What every API source needs: two error classes.

The split matters for the orchestrator. A rate limit, a 5xx or a network
failure can succeed on a later attempt, so it is retried with growing delays.
A 400, 403 or 404 is about our own request and will fail the same way forever,
so it fails the run immediately instead of spending the request budget.

RetryableApiError is a subclass: code that only cares "did the API fail?"
catches ApiError and gets both.
"""

from __future__ import annotations


class ApiError(Exception):
    """Non-retryable API error (client-side mistake, missing permission, not found)."""

    def __init__(self, status_code: int, message: str) -> None:
        """Store status code and message for structured logging."""
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class RetryableApiError(ApiError):
    """Transient API error (rate limit, server error, network) - safe to retry."""
