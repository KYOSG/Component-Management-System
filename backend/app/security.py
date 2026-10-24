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


def sign_session(user_id: int, secret: str, ttl_seconds: int) -> str:
    expires = int(time.time()) + ttl_seconds
    body = f"{user_id}.{expires}"
    signature = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def read_session(token: str, secret: str) -> int | None:
    try:
        user_text, expires_text, signature = token.split(".", 2)
        body = f"{user_text}.{expires_text}"
        expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        if int(expires_text) < int(time.time()):
            return None
        return int(user_text)
    except (TypeError, ValueError):
        return None
