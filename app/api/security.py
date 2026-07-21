from datetime import UTC, datetime, timedelta
import secrets
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_app_settings
from app.config.settings import Settings

bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(settings: Settings) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    return jwt.encode({"sub": settings.api_admin_username, "exp": expires_at}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_app_settings),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from error
    subject = payload.get("sub")
    if not isinstance(subject, str) or not secrets.compare_digest(subject, settings.api_admin_username):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    return subject
