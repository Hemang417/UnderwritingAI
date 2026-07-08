import asyncio
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.acquisition.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def test_circuit_closed_initially(redis):
    cb = CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
    assert await cb.is_open(uuid.uuid4()) is False


async def test_circuit_opens_after_threshold_failures(redis):
    cb = CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
    source_id = uuid.uuid4()

    await cb.record_failure(source_id)
    await cb.record_failure(source_id)
    assert await cb.is_open(source_id) is False  # 2 of 3 -- still closed

    await cb.record_failure(source_id)
    assert await cb.is_open(source_id) is True  # 3rd failure trips it


async def test_circuit_stays_closed_below_threshold_across_sources(redis):
    cb = CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=60))
    source_a, source_b = uuid.uuid4(), uuid.uuid4()

    await cb.record_failure(source_a)
    await cb.record_failure(source_a)
    assert await cb.is_open(source_a) is True
    assert await cb.is_open(source_b) is False  # per-source, not global


async def test_record_success_resets_circuit(redis):
    cb = CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=60))
    source_id = uuid.uuid4()

    await cb.record_failure(source_id)
    await cb.record_failure(source_id)
    assert await cb.is_open(source_id) is True

    await cb.record_success(source_id)
    assert await cb.is_open(source_id) is False


async def test_circuit_allows_half_open_trial_after_cooldown(redis):
    cb = CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=0.1))
    source_id = uuid.uuid4()

    await cb.record_failure(source_id)
    assert await cb.is_open(source_id) is True

    await asyncio.sleep(0.15)
    assert await cb.is_open(source_id) is False  # cooldown elapsed -- one trial call let through
