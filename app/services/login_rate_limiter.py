"""Bounded, in-memory rate limiting for failed login attempts."""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable


@dataclass(slots=True)
class _Attempt:
    failures: int
    first_failure_at: float
    blocked_until: float | None = None


class LoginRateLimiter:
    """Track failed logins by opaque username/client keys for one process."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._attempts: dict[str, _Attempt] = {}
        self._lock = Lock()

    @staticmethod
    def build_key(username: str, client_host: str) -> str:
        normalized = f"{username.strip().lower()}|{client_host.strip()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def retry_after(self, key: str) -> int | None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is None or attempt.blocked_until is None:
                return None
            return self._remaining_seconds(attempt, now)

    def record_failure(self, key: str) -> int | None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is None:
                self._make_room()
                attempt = _Attempt(failures=0, first_failure_at=now)
                self._attempts[key] = attempt
            elif attempt.blocked_until is not None:
                return self._remaining_seconds(attempt, now)

            attempt.failures += 1
            if attempt.failures >= self.max_attempts:
                attempt.blocked_until = now + self.window_seconds
                return self.window_seconds
            return None

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, attempt in self._attempts.items()
            if (
                attempt.blocked_until is not None
                and attempt.blocked_until <= now
            )
            or (
                attempt.blocked_until is None
                and now - attempt.first_failure_at >= self.window_seconds
            )
        ]
        for key in expired:
            self._attempts.pop(key, None)

    def _make_room(self) -> None:
        if len(self._attempts) < self.max_entries:
            return
        oldest = min(
            self._attempts,
            key=lambda key: self._attempts[key].first_failure_at,
        )
        self._attempts.pop(oldest, None)

    @staticmethod
    def _remaining_seconds(attempt: _Attempt, now: float) -> int:
        if attempt.blocked_until is None:
            raise RuntimeError("Cannot calculate retry time for an unblocked attempt")
        return max(1, math.ceil(attempt.blocked_until - now))
