from __future__ import annotations

import hashlib
import hmac
import time

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_session(user_id: int, session_token: str, secret: str, ttl_seconds: int) -> str:
    expires = int(time.time()) + ttl_seconds
    body = f"{user_id}.{session_token}.{expires}"
    return f"{body}.{_sign(body, secret)}"


def read_session(token: str, secret: str) -> tuple[int, str] | None:
    try:
        user_text, session_token, expires_text, signature = token.split(".")
        body = f"{user_text}.{session_token}.{expires_text}"
        if not hmac.compare_digest(_sign(body, secret), signature):
            return None
        if int(expires_text) < int(time.time()):
            return None
        return int(user_text), session_token
    except (TypeError, ValueError):
        return None
