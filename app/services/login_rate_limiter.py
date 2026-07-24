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
    pending: int
    first_failure_at: float
    blocked_until: float | None = None


@dataclass(frozen=True, slots=True)
class LoginAdmission:
    """One reserved authentication attempt.

    ``retry_after`` is set only when authentication must not run. An allowed
    admission can still be the boundary attempt; if that attempt fails, its
    response becomes HTTP 429 while earlier admitted attempts retain HTTP 401.
    """

    key: str
    allowed: bool
    boundary: bool
    retry_after: int | None = None


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

    def admit(self, key: str) -> LoginAdmission:
        """Atomically reserve one password evaluation for ``key``."""
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is not None and attempt.blocked_until is not None:
                return LoginAdmission(
                    key=key,
                    allowed=False,
                    boundary=False,
                    retry_after=self._remaining_seconds(attempt, now),
                )
            if attempt is None:
                if not self._make_room():
                    return LoginAdmission(
                        key=key,
                        allowed=False,
                        boundary=False,
                        retry_after=self.window_seconds,
                    )
                attempt = _Attempt(
                    failures=0,
                    pending=0,
                    first_failure_at=now,
                )
                self._attempts[key] = attempt

            if attempt.failures + attempt.pending >= self.max_attempts:
                attempt.blocked_until = now + self.window_seconds
                return LoginAdmission(
                    key=key,
                    allowed=False,
                    boundary=False,
                    retry_after=self.window_seconds,
                )

            attempt.pending += 1
            boundary = attempt.failures + attempt.pending >= self.max_attempts
            if boundary:
                # Block later requests while this final admitted password check
                # is still running. It is cleared if that admission is released
                # for a non-credential result.
                attempt.blocked_until = now + self.window_seconds
            return LoginAdmission(
                key=key,
                allowed=True,
                boundary=boundary,
            )

    def complete_failure(self, admission: LoginAdmission) -> int | None:
        """Convert a reserved evaluation into a failed credential attempt."""
        if not admission.allowed:
            raise ValueError("Cannot complete a denied login admission")
        with self._lock:
            now = self.clock()
            attempt = self._attempts.get(admission.key)
            if attempt is None:
                if not self._make_room():
                    return self.window_seconds if admission.boundary else None
                attempt = _Attempt(
                    failures=0,
                    pending=0,
                    first_failure_at=now,
                )
                self._attempts[admission.key] = attempt
            elif attempt.pending > 0:
                attempt.pending -= 1
            attempt.failures += 1
            if attempt.failures + attempt.pending >= self.max_attempts:
                attempt.blocked_until = attempt.blocked_until or (
                    now + self.window_seconds
                )
            if admission.boundary:
                attempt.blocked_until = attempt.blocked_until or (
                    now + self.window_seconds
                )
                return self._remaining_seconds(attempt, now)
            return None

    def release(self, admission: LoginAdmission) -> None:
        """Release an admission that did not produce an invalid-password result."""
        if not admission.allowed:
            return
        with self._lock:
            attempt = self._attempts.get(admission.key)
            if attempt is None:
                return
            if attempt.pending > 0:
                attempt.pending -= 1
            if attempt.failures + attempt.pending < self.max_attempts:
                attempt.blocked_until = None
            if attempt.failures == 0 and attempt.pending == 0:
                self._attempts.pop(admission.key, None)

    def record_failure(self, key: str) -> int | None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            attempt = self._attempts.get(key)
            if attempt is None:
                if not self._make_room():
                    return self.window_seconds
                attempt = _Attempt(failures=0, pending=0, first_failure_at=now)
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
                and attempt.pending == 0
            )
            or (
                attempt.blocked_until is None
                and attempt.pending == 0
                and now - attempt.first_failure_at >= self.window_seconds
            )
        ]
        for key in expired:
            self._attempts.pop(key, None)

    def _make_room(self) -> bool:
        if len(self._attempts) < self.max_entries:
            return True
        candidates = [
            key for key, attempt in self._attempts.items() if attempt.pending == 0
        ]
        if not candidates:
            return False
        oldest = min(
            candidates,
            key=lambda key: self._attempts[key].first_failure_at,
        )
        self._attempts.pop(oldest, None)
        return True

    @staticmethod
    def _remaining_seconds(attempt: _Attempt, now: float) -> int:
        if attempt.blocked_until is None:
            raise RuntimeError("Cannot calculate retry time for an unblocked attempt")
        return max(1, math.ceil(attempt.blocked_until - now))
