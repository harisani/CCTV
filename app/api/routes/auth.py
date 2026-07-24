from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import (
    get_app_settings,
    get_login_rate_limiter,
    get_user_repository,
)
from app.api.schemas import PasswordChange, TokenResponse, UserResponse
from app.api.security import create_access_token, require_authenticated_user
from app.config.settings import Settings
from app.models import User
from app.repository import UserRepository
from app.services.login_rate_limiter import LoginRateLimiter
from app.services.user_service import UserService

router = APIRouter(prefix="/auth")


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_app_settings),
    repository: UserRepository = Depends(get_user_repository),
    limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> TokenResponse:
    client_host = request.client.host if request.client else "unknown"
    key = limiter.build_key(form.username, client_host)
    retry_after = limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        user = await UserService(repository).authenticate(
            form.username,
            form.password,
            settings,
        )
    except HTTPException as error:
        if error.status_code == status.HTTP_401_UNAUTHORIZED:
            retry_after = limiter.record_failure(key)
            if retry_after is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many login attempts",
                    headers={"Retry-After": str(retry_after)},
                ) from error
        raise
    limiter.reset(key)
    return TokenResponse(access_token=create_access_token(settings, user))


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: User = Depends(require_authenticated_user)) -> User:
    return user


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: PasswordChange,
    user: User = Depends(require_authenticated_user),
    settings: Settings = Depends(get_app_settings),
    repository: UserRepository = Depends(get_user_repository),
) -> TokenResponse:
    import asyncio

    service = UserService(repository)
    persisted_user = await repository.get(user.id)
    if persisted_user is None or not await asyncio.to_thread(
        service.passwords.verify, payload.current_password, persisted_user.password_hash
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    try:
        persisted_user.password_hash = await asyncio.to_thread(service.passwords.hash, payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    persisted_user.must_change_password = False
    persisted_user.token_version += 1
    await service.audit.record(
        actor_user_id=user.id,
        action="USER_PASSWORD_CHANGED",
        resource_type="user",
        resource_id=str(user.id),
    )
    await repository.session.commit()
    return TokenResponse(access_token=create_access_token(settings, persisted_user))
