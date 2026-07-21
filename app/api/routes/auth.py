from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import get_app_settings, get_user_repository
from app.api.schemas import PasswordChange, TokenResponse, UserResponse
from app.api.security import create_access_token, require_authenticated_user
from app.config.settings import Settings
from app.models import User
from app.repository import UserRepository
from app.services.user_service import UserService

router = APIRouter(prefix="/auth")


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_app_settings),
    repository: UserRepository = Depends(get_user_repository),
) -> TokenResponse:
    user = await UserService(repository).authenticate(form.username, form.password, settings)
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
