import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import get_app_settings
from app.api.schemas import TokenResponse
from app.api.security import create_access_token
from app.config.settings import Settings

router = APIRouter(prefix="/auth")


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form: OAuth2PasswordRequestForm = Depends(), settings: Settings = Depends(get_app_settings)
) -> TokenResponse:
    valid_user = secrets.compare_digest(form.username, settings.api_admin_username)
    valid_password = secrets.compare_digest(form.password, settings.api_admin_password)
    if not (valid_user and valid_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return TokenResponse(access_token=create_access_token(settings))
