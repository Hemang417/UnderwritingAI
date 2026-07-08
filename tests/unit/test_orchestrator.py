import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.acquisition.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.acquisition.models import AcquisitionRunStatus
from app.acquisition.orchestrator import AcquisitionOrchestrator
from app.acquisition.rate_limiter import RateLimiter
from app.adapters.fixture_client import FixtureClient
from app.adapters.maha_rera import MahaRERAAdapter

pytestmark = pytest.mark.asyncio

FIXTURES = {"P51900001234": {"unit_count": 450, "possession_date": "2027-12-31"}}


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


def _orchestrator(redis, *, failure_threshold: int = 3, max_attempts: int = 3) -> AcquisitionOrchestrator:
    return AcquisitionOrchestrator(
        circuit_breaker=CircuitBreaker(redis, CircuitBreakerConfig(failure_threshold=failure_threshold)),
        rate_limiter=RateLimiter(redis, max_calls=1000, window_seconds=60),
        max_attempts=max_attempts,
    )


async def test_retries_transient_failures_then_succeeds(redis):
    client = FixtureClient(fixtures=FIXTURES, fail_count=2)
    adapter = MahaRERAAdapter(client=client)
    orchestrator = _orchestrator(redis, max_attempts=3)
    source_id = uuid.uuid4()

    result = await orchestrator.execute_get_project(
        data_source_id=source_id, adapter=adapter, external_ref="P51900001234"
    )

    assert result.status == AcquisitionRunStatus.SUCCESS
    assert result.attempt_count == 3  # failed twice, succeeded on the 3rd
    assert result.raw_payload == FIXTURES["P51900001234"]
    assert await orchestrator.circuit_breaker.is_open(source_id) is False


async def test_exhausted_retries_return_failed_without_opening_circuit_yet(redis):
    client = FixtureClient(fixtures=FIXTURES, always_fail=True)
    adapter = MahaRERAAdapter(client=client)
    orchestrator = _orchestrator(redis, failure_threshold=3, max_attempts=2)
    source_id = uuid.uuid4()

    result = await orchestrator.execute_get_project(
        data_source_id=source_id, adapter=adapter, external_ref="P51900001234"
    )

    assert result.status == AcquisitionRunStatus.FAILED
    assert result.error_detail is not None
    assert await orchestrator.circuit_breaker.is_open(source_id) is False  # 1 of 3 failures so far


async def test_circuit_opens_after_repeated_failures_and_then_skips(redis):
    client = FixtureClient(fixtures=FIXTURES, always_fail=True)
    adapter = MahaRERAAdapter(client=client)
    orchestrator = _orchestrator(redis, failure_threshold=2, max_attempts=1)
    source_id = uuid.uuid4()

    first = await orchestrator.execute_get_project(
        data_source_id=source_id, adapter=adapter, external_ref="P51900001234"
    )
    second = await orchestrator.execute_get_project(
        data_source_id=source_id, adapter=adapter, external_ref="P51900001234"
    )
    assert first.status == AcquisitionRunStatus.FAILED
    assert second.status == AcquisitionRunStatus.FAILED
    assert await orchestrator.circuit_breaker.is_open(source_id) is True

    calls_before_third = client.call_count
    third = await orchestrator.execute_get_project(
        data_source_id=source_id, adapter=adapter, external_ref="P51900001234"
    )

    assert third.status == AcquisitionRunStatus.SKIPPED
    assert client.call_count == calls_before_third  # never even attempted the adapter call


async def test_permanent_error_fails_immediately_without_opening_circuit(redis):
    client = FixtureClient(fixtures={})  # ref will never be found -> AdapterPermanentError
    adapter = MahaRERAAdapter(client=client)
    orchestrator = _orchestrator(redis, failure_threshold=2, max_attempts=3)
    source_id = uuid.uuid4()

    for _ in range(5):
        result = await orchestrator.execute_get_project(
            data_source_id=source_id, adapter=adapter, external_ref="unknown-ref"
        )
        assert result.status == AcquisitionRunStatus.FAILED
        assert result.attempt_count == 1  # not retried -- permanent errors aren't transient

    # Repeated 404-style errors for a *missing project* don't mean the
    # source itself is down, so the circuit must never trip from these.
    assert await orchestrator.circuit_breaker.is_open(source_id) is False
