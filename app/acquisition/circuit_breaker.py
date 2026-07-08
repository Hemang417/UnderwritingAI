import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0


class CircuitBreaker:
    """Per-DataSource circuit breaker, Redis-backed so state is shared
    across worker/API processes (ADR-005). Only transient failures should
    ever be recorded here -- a 404-style "this project isn't listed" isn't
    the source being down.
    """

    def __init__(self, redis: Redis, config: CircuitBreakerConfig | None = None):
        self.redis = redis
        self.config = config or CircuitBreakerConfig()

    def _state_key(self, source_id: uuid.UUID) -> str:
        return f"circuit:{source_id}:state"

    def _failures_key(self, source_id: uuid.UUID) -> str:
        return f"circuit:{source_id}:failures"

    def _opened_at_key(self, source_id: uuid.UUID) -> str:
        return f"circuit:{source_id}:opened_at"

    async def is_open(self, source_id: uuid.UUID) -> bool:
        state = await self.redis.get(self._state_key(source_id))
        if state != "open":
            return False

        opened_at = await self.redis.get(self._opened_at_key(source_id))
        if opened_at is None:
            return False

        elapsed = time.time() - float(opened_at)
        # Cooldown elapsed: allow exactly one half-open trial call through
        # rather than resetting outright -- record_success/record_failure
        # decide whether that trial actually closes or re-opens the circuit.
        return elapsed < self.config.cooldown_seconds

    async def record_success(self, source_id: uuid.UUID) -> None:
        await self.redis.delete(
            self._state_key(source_id), self._failures_key(source_id), self._opened_at_key(source_id)
        )

    async def record_failure(self, source_id: uuid.UUID) -> None:
        failures = await self.redis.incr(self._failures_key(source_id))
        if failures >= self.config.failure_threshold:
            await self.redis.set(self._state_key(source_id), "open")
            await self.redis.set(self._opened_at_key(source_id), time.time())
