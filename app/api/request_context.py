from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def choose_correlation_id(candidate: str | None, max_length: int) -> str:
    if (
        candidate
        and len(candidate) <= max_length
        and _SAFE_ID.fullmatch(candidate) is not None
    ):
        return candidate
    return str(uuid4())


def bind_correlation_id(value: str) -> Token[str | None]:
    return _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)
