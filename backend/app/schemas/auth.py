import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignUpIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class SignInIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None
    auth_provider: str
    created_at: datetime


class GoogleSignInIn(BaseModel):
    id_token: str = Field(min_length=10, max_length=8192)


class AuthConfigOut(BaseModel):
    google_enabled: bool
    # Public OAuth client ID (not a secret); null when Google is disabled.
    google_client_id: str | None = None
