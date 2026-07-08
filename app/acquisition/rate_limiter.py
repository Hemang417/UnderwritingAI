import time
import uuid

from redis.asyncio import Redis


class RateLimiter:
    """Fixed-window rate limiter per DataSource (ADR-005's "Redis token
    bucket" simplified to a fixed window: at most `max_calls` per
    `window_seconds`). A true continuous token bucket would need a Lua
    script for atomicity; this fixed-window version is a deliberate,
    documented approximation -- correct enough to bound request volume to
    a source, with the known limitation that it permits a short burst at
    window boundaries.
    """

    def __init__(self, redis: Redis, max_calls: int = 30, window_seconds: int = 60):
        self.redis = redis
        self.max_calls = max_calls
        self.window_seconds = window_seconds

    def _key(self, source_id: uuid.UUID) -> str:
        window = int(time.time() // self.window_seconds)
        return f"ratelimit:{source_id}:{window}"

    async def try_acquire(self, source_id: uuid.UUID) -> bool:
        key = self._key(source_id)
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.window_seconds)
        return count <= self.max_calls
