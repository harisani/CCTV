from __future__ import annotations

import asyncio

import pytest

import app.database.session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1


def test_session_rolls_back_and_closes_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = FakeSession()
        monkeypatch.setattr(session_module, "SessionLocal", lambda: session)
        dependency = session_module.get_session()

        assert await anext(dependency) is session
        with pytest.raises(RuntimeError, match="boom"):
            await dependency.athrow(RuntimeError("boom"))

        assert session.rollbacks == 1
        assert session.commits == 0
        assert session.closed is True

    asyncio.run(scenario())


def test_session_success_does_not_commit_implicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        session = FakeSession()
        monkeypatch.setattr(session_module, "SessionLocal", lambda: session)
        dependency = session_module.get_session()

        assert await anext(dependency) is session
        await dependency.aclose()

        assert session.rollbacks == 0
        assert session.commits == 0
        assert session.closed is True

    asyncio.run(scenario())
