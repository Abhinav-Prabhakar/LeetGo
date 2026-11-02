"""Domain exceptions and error-reference helpers."""

from __future__ import annotations

import secrets


class LeetGoError(Exception):
    """Base class for expected application errors."""


class ValidationError(LeetGoError):
    """Raised when user input fails validation."""


class UsernameTakenError(LeetGoError):
    """Raised when a LeetCode username is already linked to another account."""


class LeetCodeError(LeetGoError):
    """Base class for LeetCode API failures."""


class UserNotFoundError(LeetCodeError):
    """Raised when a LeetCode username does not exist."""


class InvalidUsernameError(LeetCodeError):
    """Raised when a username does not match LeetCode's format."""


class RateLimitedError(LeetCodeError):
    """Raised when LeetCode rate limits the bot."""

    def __init__(self, retry_after: float = 30.0) -> None:
        super().__init__("LeetCode rate limit reached")
        self.retry_after = retry_after


class ServiceUnavailableError(LeetCodeError):
    """Raised when LeetCode cannot be reached after retries."""


class NotLinkedError(LeetGoError):
    """Raised when a Discord user has no linked LeetCode account."""


class CohortError(LeetGoError):
    """Base class for cohort failures."""


class CohortExistsError(CohortError):
    """Raised when a cohort name is already in use."""


class CohortLimitError(CohortError):
    """Raised when a guild has reached its cohort limit."""


def new_error_id() -> str:
    """Return a short, non-sensitive reference ID for logs and user replies."""
    return secrets.token_hex(4)
