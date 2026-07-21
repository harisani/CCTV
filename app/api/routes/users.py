from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.dependencies import get_user_repository
from app.api.schemas import Page, PasswordReset, UserCreate, UserResponse, UserUpdate
from app.api.security import require_roles
from app.models import User, UserRole
from app.repository import UserRepository
from app.services.user_service import UserService

router = APIRouter(prefix="/users", dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))])


@router.get("", response_model=Page[UserResponse])
async def list_users(
    search: str | None = Query(default=None, max_length=150),
    role: UserRole | None = None,
    is_active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: UserRepository = Depends(get_user_repository),
) -> Page[UserResponse]:
    items, total = await repository.list_filtered(
        search=search, role=role, is_active=is_active, offset=offset, limit=limit
    )
    return Page[UserResponse](items=items, total=total, offset=offset, limit=limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: UserRepository = Depends(get_user_repository),
) -> User:
    return await UserService(repository).create(payload, actor)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: UserRepository = Depends(get_user_repository),
) -> User:
    user = await repository.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await UserService(repository).update(user, payload, actor)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: UUID,
    payload: PasswordReset,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await repository.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await UserService(repository).reset_password(user, payload.password, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
