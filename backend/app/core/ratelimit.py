"""Rate limiter sliding-window di memori (NFR-01).

Cukup untuk aplikasi pribadi dengan satu proses API. Jika API dijalankan dengan
beberapa proses, pindahkan ke Redis.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque

from .errors import AppError


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, math.ceil(self.window - (now - hits[0])))
            raise AppError(
                "rate_limited",
                f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik.",
                429,
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()
