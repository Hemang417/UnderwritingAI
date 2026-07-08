from dataclasses import dataclass, field

from app.adapters.base import AdapterPermanentError, AdapterTransientError


@dataclass
class FixtureClient:
    """Stand-in for a real HTTP client while live scraping stays gated behind
    legal sign-off (see ARD/SAD). Adapters call this instead of a real
    network request; tests construct one directly with `fail_count`/
    `always_fail` set to simulate transient outages and prove the
    orchestrator's retry/circuit-breaker behavior without touching a
    network at all.
    """

    fixtures: dict[str, dict]
    fail_count: int = 0
    always_fail: bool = False
    call_count: int = field(default=0, init=False)

    async def fetch(self, key: str) -> dict:
        self.call_count += 1
        if self.always_fail:
            raise AdapterTransientError(f"simulated persistent failure fetching '{key}'")
        if self.fail_count > 0:
            self.fail_count -= 1
            raise AdapterTransientError(f"simulated transient failure fetching '{key}'")
        if key not in self.fixtures:
            raise AdapterPermanentError(f"no record found for '{key}'")
        return self.fixtures[key]
