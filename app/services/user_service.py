"""User lifecycle and bootstrap operations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from fastapi import HTTPException, status

from app.models import User, UserRole
from app.repository import AuditRepository, UserRepository
from app.services.password_service import PasswordService


class UserService:
    def __init__(self, repository: UserRepository, password_service: PasswordService | None = None) -> None:
        self.repository = repository
        self.passwords = password_service or PasswordService()
        self.audit = AuditRepository(repository.session)

    async def authenticate(self, username: str, password: str, settings: Any) -> User:
        user = await self.repository.get_by_username(username)
        now = datetime.now(UTC)
        if user is None:
            await asyncio.to_thread(self.passwords.verify, password, self.passwords.hash("invalid-password-value"))
            raise self._invalid_credentials()
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
        if user.locked_until is not None and user.locked_until > now:
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account is temporarily locked")
        valid = await asyncio.to_thread(self.passwords.verify, password, user.password_hash)
        if not valid:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_attempts = 0
            await self.repository.session.commit()
            raise self._invalid_credentials()
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        await self.audit.record(
            actor_user_id=user.id,
            action="AUTH_LOGIN",
            resource_type="user",
            resource_id=str(user.id),
        )
        await self.repository.session.commit()
        return user

    async def create(self, payload: Any, actor: User) -> User:
        if await self.repository.get_by_username(payload.username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        try:
            password_hash = await asyncio.to_thread(self.passwords.hash, payload.password)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        user = User(
            username=payload.username.strip().lower(),
            full_name=payload.full_name.strip(),
            password_hash=password_hash,
            role=payload.role,
            is_active=payload.is_active,
            must_change_password=True,
        )
        await self.repository.add(user)
        await self.audit.record(
            actor_user_id=actor.id,
            action="USER_CREATED",
            resource_type="user",
            resource_id=str(user.id),
            details={"username": user.username, "role": user.role.value},
        )
        await self.repository.session.commit()
        return user

    async def update(self, user: User, payload: Any, actor: User) -> User:
        changes = payload.model_dump(exclude_unset=True, exclude_none=True)
        if user.id == actor.id and changes.get("is_active") is False:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You cannot deactivate your own account")
        resulting_role = changes.get("role", user.role)
        resulting_active = changes.get("is_active", user.is_active)
        if user.role == UserRole.SUPER_ADMIN and (resulting_role != UserRole.SUPER_ADMIN or not resulting_active):
            if await self.repository.count_active_super_admins(excluding=user.id) == 0:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="At least one active super admin is required")
        for field, value in changes.items():
            setattr(user, field, value.strip() if isinstance(value, str) else value)
        user.token_version += 1
        await self.audit.record(
            actor_user_id=actor.id,
            action="USER_UPDATED",
            resource_type="user",
            resource_id=str(user.id),
            details={"fields": sorted(changes)},
        )
        await self.repository.session.commit()
        await self.repository.session.refresh(user)
        return user

    async def reset_password(self, user: User, password: str, actor: User) -> None:
        if user.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Use the change-password endpoint for your own account",
            )
        try:
            user.password_hash = await asyncio.to_thread(self.passwords.hash, password)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        user.must_change_password = True
        user.token_version += 1
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.audit.record(
            actor_user_id=actor.id,
            action="USER_PASSWORD_RESET",
            resource_type="user",
            resource_id=str(user.id),
        )
        await self.repository.session.commit()

    @staticmethod
    def _invalid_credentials() -> HTTPException:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")


async def ensure_bootstrap_admin(session_factory: Any, settings: Any) -> None:
    """Create the first super admin from .env only when the user table is empty."""
    async with session_factory() as session:
        repository = UserRepository(session)
        if await repository.get_by_username(settings.api_admin_username):
            return
        from sqlalchemy import func, select

        if int(await session.scalar(select(func.count()).select_from(User)) or 0) > 0:
            return
        password_hash = await asyncio.to_thread(
            PasswordService().hash, settings.api_admin_password, enforce_policy=False
        )
        await repository.add(User(
            username=settings.api_admin_username.strip().lower(),
            full_name="System Administrator",
            password_hash=password_hash,
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            must_change_password=False,
        ))
        await session.commit()
