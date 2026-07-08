import uuid
from dataclasses import dataclass

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.acquisition.circuit_breaker import CircuitBreaker
from app.acquisition.models import AcquisitionRunStatus
from app.acquisition.rate_limiter import RateLimiter
from app.adapters.base import AdapterPermanentError, AdapterTransientError, BaseSourceAdapter


@dataclass
class SourceExecutionResult:
    status: AcquisitionRunStatus
    raw_payload: dict | None
    error_detail: str | None
    attempt_count: int


class AcquisitionOrchestrator:
    """Centralizes resilience policy (ADR-005) so it's consistent across
    every source: retry with backoff, a shared circuit breaker, and rate
    limiting -- none of this lives in the adapters themselves.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        rate_limiter: RateLimiter,
        max_attempts: int = 3,
    ):
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.max_attempts = max_attempts

    async def execute_get_project(
        self, *, data_source_id: uuid.UUID, adapter: BaseSourceAdapter, external_ref: str
    ) -> SourceExecutionResult:
        if await self.circuit_breaker.is_open(data_source_id):
            return SourceExecutionResult(
                status=AcquisitionRunStatus.SKIPPED,
                raw_payload=None,
                error_detail="circuit open: source recently failed repeatedly, skipping until cooldown",
                attempt_count=0,
            )

        if not await self.rate_limiter.try_acquire(data_source_id):
            return SourceExecutionResult(
                status=AcquisitionRunStatus.SKIPPED,
                raw_payload=None,
                error_detail="rate limit exceeded for this source",
                attempt_count=0,
            )

        attempts = 0
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_attempts),
                wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
                retry=retry_if_exception_type(AdapterTransientError),
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    payload = await adapter.get_project(external_ref)
        except AdapterTransientError as exc:
            # Exhausted retries on a genuinely retryable error -- this is
            # the source itself misbehaving, so it counts toward the
            # circuit breaker.
            await self.circuit_breaker.record_failure(data_source_id)
            return SourceExecutionResult(
                status=AcquisitionRunStatus.FAILED,
                raw_payload=None,
                error_detail=str(exc),
                attempt_count=attempts,
            )
        except AdapterPermanentError as exc:
            # Not retryable and not a sign the source is down (e.g. this
            # particular project just isn't listed) -- doesn't open the
            # circuit for every other project on this source.
            return SourceExecutionResult(
                status=AcquisitionRunStatus.FAILED, raw_payload=None, error_detail=str(exc), attempt_count=1
            )

        await self.circuit_breaker.record_success(data_source_id)
        return SourceExecutionResult(
            status=AcquisitionRunStatus.SUCCESS,
            raw_payload=payload,
            error_detail=None,
            attempt_count=attempts,
        )
