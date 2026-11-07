"""In-memory sliding-window rate limits for the public board. One process, no dependency."""
import ipaddress
import threading
import time
from collections import deque

from fastapi import Request

from .config import get_settings

MAX_KEYS = 50000
LOOPBACK = ("127.0.0.1", "::1")

# name -> list of (scope, limit, window seconds). scope: device, ip or global.
LIMITS = {
    "device": [("ip", 20, 3600), ("global", 300, 3600)],
    "post_anon": [("device", 6, 600), ("ip", 30, 600)],
    "post_member": [("device", 30, 600)],
    "confirm": [("device", 30, 3600), ("ip", 120, 3600)],
    "photo": [("device", 10, 3600), ("ip", 30, 3600)],
    "read": [("ip", 120, 60)],
    "station": [("device", 60, 60)],
}


class Limiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}

    def hit(self, key: str, limit: int, window_s: int, now: float | None = None) -> int | None:
        """Record a hit. Returns None if allowed, else seconds to wait. Refused hits are not recorded."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = deque()
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                self._hits[key] = q
                return max(1, int(q[0] + window_s - now) + 1)
            q.append(now)
            self._hits.pop(key, None)
            self._hits[key] = q
            while len(self._hits) > MAX_KEYS:
                self._hits.pop(next(iter(self._hits)))
            return None

    def check(self, hits: list[tuple[str, int, int]], now: float | None = None) -> int | None:
        """Apply several rules; a refusal by any rule records nothing in the ones after it."""
        wait = None
        for key, limit, window in hits:
            w = self.hit(key, limit, window, now)
            if w is not None:
                wait = max(wait or 0, w)
                break
        return wait

    def __len__(self):
        return len(self._hits)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if not peer:
        return "unknown"
    header = get_settings().forwarded_ip_header.strip().lower()
    if header and peer in LOOPBACK:
        raw = request.headers.get(header, "")
        if raw:
            cand = raw.split(",")[-1].strip() if header == "x-forwarded-for" else raw.strip()
            try:
                return str(ipaddress.ip_address(cand))
            except ValueError:
                pass
    return peer
