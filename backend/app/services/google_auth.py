"""Google Identity Services ID-token verification.

Flow: frontend loads Google GIS script, user signs in, frontend sends the
ID token (JWT) to POST /api/auth/google. We verify signature/audience/expiry
against Google's JWKS, then upsert the user and issue our own session cookie.
No Google client secret needed; disabled when GOOGLE_CLIENT_ID is empty.
"""

import time

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

settings = get_settings()

_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_jwks_client: PyJWKClient | None = None


class GoogleAuthError(Exception):
    pass


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_GOOGLE_CERTS_URL, cache_keys=True)
    return _jwks_client


def verify_google_id_token(id_token: str) -> dict:
    """Verify a Google ID token. Returns claims (sub, email, name, picture)."""
    if not settings.google_client_id:
        raise GoogleAuthError("Google sign-in is not enabled on this server")
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=["accounts.google.com", "https://accounts.google.com"],
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError(f"Invalid Google token: {exc}") from exc
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleAuthError("Google token is missing sub/email claims")
    if not claims.get("email_verified", True):
        raise GoogleAuthError("Google email is not verified")
    claims["_verified_at"] = time.time()
    return claims
