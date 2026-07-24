from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.services.container import ServiceContainer
from app.services.login_rate_limiter import LoginRateLimiter


def test_limiter_blocks_at_boundary_then_expires() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(
        max_attempts=2,
        window_seconds=30,
        max_entries=10,
        clock=lambda: now[0],
    )
    key = limiter.build_key(" Admin ", "10.0.0.1")

    assert limiter.retry_after(key) is None
    assert limiter.record_failure(key) is None
    assert limiter.record_failure(key) == 30
    assert limiter.retry_after(key) == 30

    now[0] = 131.0
    assert limiter.retry_after(key) is None


def test_success_reset_and_key_isolation() -> None:
    limiter = LoginRateLimiter(2, 30, 10)
    first = limiter.build_key("admin", "10.0.0.1")
    normalized = limiter.build_key(" Admin ", "10.0.0.1")
    second = limiter.build_key("admin", "10.0.0.2")

    limiter.record_failure(first)
    limiter.reset(first)

    assert limiter.retry_after(first) is None
    assert first == normalized
    assert first != second


def test_expired_unblocked_failures_start_a_new_window() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(3, 30, 10, clock=lambda: now[0])
    key = limiter.build_key("admin", "10.0.0.1")
    assert limiter.record_failure(key) is None
    assert limiter.record_failure(key) is None

    now[0] = 130.0

    assert limiter.record_failure(key) is None
    assert limiter.retry_after(key) is None


def test_capacity_evicts_oldest_entry_without_exceeding_bound() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(2, 60, 2, clock=lambda: now[0])
    oldest = limiter.build_key("oldest", "10.0.0.1")
    newer = limiter.build_key("newer", "10.0.0.1")
    newest = limiter.build_key("newest", "10.0.0.1")
    limiter.record_failure(oldest)
    now[0] += 1
    limiter.record_failure(newer)
    now[0] += 1

    limiter.record_failure(newest)
    assert limiter.record_failure(oldest) is None


def test_capacity_remains_bounded_under_concurrent_new_keys() -> None:
    limiter = LoginRateLimiter(3, 60, 10)
    keys = [limiter.build_key(f"user-{index}", "10.0.0.1") for index in range(100)]

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(limiter.record_failure, keys))

    assert len(limiter._attempts) == 10


def test_capacity_does_not_evict_in_flight_password_evaluations() -> None:
    limiter = LoginRateLimiter(2, 60, 2)
    first_key = limiter.build_key("first", "10.0.0.1")
    second_key = limiter.build_key("second", "10.0.0.1")
    overflow_key = limiter.build_key("overflow", "10.0.0.1")
    first = limiter.admit(first_key)
    second = limiter.admit(second_key)

    denied = limiter.admit(overflow_key)

    assert first.allowed is True
    assert second.allowed is True
    assert denied.allowed is False
    assert denied.retry_after == 60
    assert set(limiter._attempts) == {first_key, second_key}


def test_concurrent_boundary_failures_do_not_extend_block() -> None:
    now = [100.0]
    limiter = LoginRateLimiter(2, 30, 10, clock=lambda: now[0])
    key = limiter.build_key("admin", "10.0.0.1")
    limiter.record_failure(key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: limiter.record_failure(key), range(8)))

    assert results == [30] * 8
    now[0] = 101.0
    assert limiter.retry_after(key) == 29


def test_container_returns_one_limiter_during_concurrent_first_access() -> None:
    container = ServiceContainer(
        SimpleNamespace(
            login_rate_limit_attempts=2,
            login_rate_limit_window_seconds=30,
            login_rate_limit_max_entries=10,
        )
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        limiters = list(executor.map(lambda _: container.login_limiter, range(100)))

    assert all(limiter is limiters[0] for limiter in limiters)


@pytest.mark.parametrize(
    ("max_attempts", "window_seconds", "max_entries"),
    [(0, 30, 10), (2, 0, 10), (2, 30, 0)],
)
def test_rejects_non_positive_limits(
    max_attempts: int,
    window_seconds: int,
    max_entries: int,
) -> None:
    with pytest.raises(ValueError):
        LoginRateLimiter(max_attempts, window_seconds, max_entries)
