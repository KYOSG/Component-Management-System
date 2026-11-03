from __future__ import annotations

import threading
import time
from collections import deque

WINDOW_SECONDS = 15 * 60
MAX_PER_ACCOUNT = 10
MAX_PER_IP = 30


class LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def _count(self, key: str, now: float) -> int:
        bucket = self._failures.get(key)
        if not bucket:
            return 0
        while bucket and bucket[0] <= now - WINDOW_SECONDS:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            return 0
        return len(bucket)

    def blocked(self, ip: str, account: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return (
                self._count(f"acct:{ip}:{account}", now) >= MAX_PER_ACCOUNT
                or self._count(f"ip:{ip}", now) >= MAX_PER_IP
            )

    def fail(self, ip: str, account: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in (f"acct:{ip}:{account}", f"ip:{ip}"):
                self._failures.setdefault(key, deque()).append(now)

    def succeed(self, ip: str, account: str) -> None:
        with self._lock:
            self._failures.pop(f"acct:{ip}:{account}", None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginLimiter()
