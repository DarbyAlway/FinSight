"""Password hashing, session cookie helpers, and the current_user dependency."""
import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request, Response

from webapp import accounts

_ph = PasswordHasher()

COOKIE_NAME = "session"
SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "30"))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(request: Request) -> dict:
    """FastAPI dependency: the logged-in user, or 401."""
    user = accounts.user_for_session(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
