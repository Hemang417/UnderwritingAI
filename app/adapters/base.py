import enum
from abc import ABC
from typing import ClassVar


class AdapterCapability(enum.Enum):
    SEARCH_PROJECT = "search_project"
    GET_PROJECT = "get_project"
    GET_DOCUMENTS = "get_documents"
    GET_PROGRESS = "get_progress"
    GET_INVENTORY = "get_inventory"
    GET_QUARTERLY_REPORTS = "get_quarterly_reports"


class AdapterCapabilityError(Exception):
    """Raised when a method is called that this adapter's source doesn't
    support. The orchestrator should check `capabilities` before calling and
    skip inapplicable methods rather than relying on this as control flow --
    it exists as a clear failure signal for programmer error, not a normal
    per-request outcome."""


class AdapterTransientError(Exception):
    """A retryable failure: timeout, 5xx, rate-limited (429), or similar.
    The orchestrator retries these with backoff."""


class AdapterPermanentError(Exception):
    """A non-retryable failure: 404, auth failure, CAPTCHA wall, or similar.
    The orchestrator does not retry these -- retrying a dead end just wastes
    the retry budget and delays surfacing the real problem."""


class BaseSourceAdapter(ABC):
    """Common contract every external data source implements.

    Adapters retrieve and return structured data only -- no business logic,
    no sequencing, no retries, no conflict resolution. That all belongs to
    the orchestrator/normalization layer. Every method here raises
    AdapterCapabilityError by default; a concrete adapter overrides only the
    methods matching its declared `capabilities` (e.g. a news adapter
    realistically only supports search_project/get_documents).
    """

    source_type: ClassVar[str]
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    async def search_project(self, criteria: dict) -> list[dict]:
        raise AdapterCapabilityError(f"{self.source_type} does not support search_project")

    async def get_project(self, external_ref: str) -> dict:
        raise AdapterCapabilityError(f"{self.source_type} does not support get_project")

    async def get_documents(self, external_ref: str) -> list[dict]:
        raise AdapterCapabilityError(f"{self.source_type} does not support get_documents")

    async def get_progress(self, external_ref: str) -> dict:
        raise AdapterCapabilityError(f"{self.source_type} does not support get_progress")

    async def get_inventory(self, external_ref: str) -> dict:
        raise AdapterCapabilityError(f"{self.source_type} does not support get_inventory")

    async def get_quarterly_reports(self, external_ref: str) -> list[dict]:
        raise AdapterCapabilityError(f"{self.source_type} does not support get_quarterly_reports")
