from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import DbDep, UserDep
from app.core.config import get_settings
from app.core.rate_limit import login_limit
from app.core.security import (
    clear_auth_cookie,
    create_access_token,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.models import User
from app.schemas.auth import AuthConfigOut, GoogleSignInIn, SignInIn, SignUpIn, UserOut
from app.services import google_auth

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        google_enabled=bool(settings.google_client_id),
        google_client_id=settings.google_client_id or None,
    )


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignUpIn, db: DbDep, response: Response) -> User:
    email = payload.email.lower()

    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists"
        )

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        name=payload.name.strip(),
        auth_provider="email",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/login", response_model=UserOut, dependencies=[Depends(login_limit)])
async def login(payload: SignInIn, db: DbDep, response: Response) -> User:
    email = payload.email.lower()
    user = await db.scalar(select(User).where(User.email == email))

    # Same generic message for unknown email and wrong password (no user enumeration).
    if user is None or user.hashed_password is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    set_auth_cookie(response, create_access_token(user.id))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    clear_auth_cookie(response)


@router.post("/google", response_model=UserOut, dependencies=[Depends(login_limit)])
async def google_signin(payload: GoogleSignInIn, db: DbDep, response: Response) -> User:
    try:
        claims = google_auth.verify_google_id_token(payload.id_token)
    except google_auth.GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    email = str(claims["email"]).lower()
    google_sub = str(claims["sub"])

    user = await db.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            hashed_password=None,
            name=str(claims.get("name") or email.split("@")[0])[:255],
            avatar_url=str(claims.get("picture") or "")[:2048] or None,
            auth_provider="google",
            google_sub=google_sub,
        )
        db.add(user)
    else:
        user.google_sub = user.google_sub or google_sub
        if user.auth_provider == "email":
            user.auth_provider = "google"
        if claims.get("picture") and not user.avatar_url:
            user.avatar_url = str(claims["picture"])[:2048]

    await db.commit()
    await db.refresh(user)

    set_auth_cookie(response, create_access_token(user.id))
    return user


@router.get("/me", response_model=UserOut)
async def me(user: UserDep) -> User:
    return user
