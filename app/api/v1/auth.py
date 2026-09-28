"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user) -> TokenResponse:  # noqa: ANN001
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient account",
    responses={409: {"description": "Email already registered"}},
)
async def signup(payload: SignupRequest, session: SessionDep) -> TokenResponse:
    """Create an account and return an access token, so the client need not
    immediately call `/auth/login`."""
    user = await auth_service.register_user(
        session,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        phone=payload.phone,
    )
    return _token_for(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for an access token",
    responses={401: {"description": "Incorrect email or password"}},
)
async def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    user = await auth_service.authenticate_user(
        session, email=payload.email, password=payload.password
    )
    return _token_for(user)


@router.get("/me", response_model=UserResponse, summary="Current authenticated user")
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)
