import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.acquisition.rate_limiter import RateLimiter

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def test_allows_calls_up_to_max(redis):
    limiter = RateLimiter(redis, max_calls=3, window_seconds=60)
    source_id = uuid.uuid4()

    assert await limiter.try_acquire(source_id) is True
    assert await limiter.try_acquire(source_id) is True
    assert await limiter.try_acquire(source_id) is True
    assert await limiter.try_acquire(source_id) is False


async def test_limits_are_independent_per_source(redis):
    limiter = RateLimiter(redis, max_calls=1, window_seconds=60)
    source_a, source_b = uuid.uuid4(), uuid.uuid4()

    assert await limiter.try_acquire(source_a) is True
    assert await limiter.try_acquire(source_a) is False
    assert await limiter.try_acquire(source_b) is True
