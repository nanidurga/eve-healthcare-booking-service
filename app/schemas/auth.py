"""Request/response models for authentication."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_BYTES

MIN_PASSWORD_LENGTH = 8


class SignupRequest(BaseModel):
    email: EmailStr = Field(examples=["asha@example.com"])
    full_name: str = Field(min_length=1, max_length=120, examples=["Asha Verma"])
    phone: str | None = Field(default=None, max_length=20, examples=["+919876543210"])
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH, examples=["correct-horse-battery"]
    )

    @field_validator("password")
    @classmethod
    def _within_bcrypt_limit(cls, value: str) -> str:
        # bcrypt hashes at most 72 bytes and raises beyond that. Rejecting here
        # turns a 500 into a clear 422.
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} bytes.")
        return value


class LoginRequest(BaseModel):
    """Login deliberately does not apply the signup password policy.

    Rejecting a short password with 422 would tell an attacker their guess was
    too short to be a real password, and would lock out users whose password
    predates a policy change. Any non-empty string gets one honest 401.
    """

    email: EmailStr = Field(examples=["asha@example.com"])
    password: str = Field(min_length=1, examples=["correct-horse-battery"])


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    phone: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserResponse
