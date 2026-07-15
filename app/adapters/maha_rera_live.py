"""Async port of REDO_Platform's MahaRERA client + parser, adapted to this
codebase's async-everywhere convention (the original is sync `requests`;
this uses `httpx.AsyncClient` so it fits `BaseSourceAdapter`'s async
interface without blocking the event loop).

Two tiers, per REDO_Platform's architecture:
- Tier 1 (search): MAHARERA's public project-search HTML page. No auth.
- Tier 2 (detail): MAHARERA's own internal JSON API. Requires a bearer JWT
  obtained by a *human* solving a CAPTCHA (scripts/setup_maharera_session.py)
  -- there is no automated way to get one, and this module never attempts
  to. See app.adapters.maha_rera_session.load_token.

Scope: only the fields this platform currently tracks (possession_date) or
needs for identity resolution (name, developer, district/state, status).
NOT ported: litigation/complaint/professional/document endpoints -- they
exist on the real API but nothing in this platform's FieldCatalog or Risk
engine consumes them yet. Also confirmed absent from every wrapped
endpoint: unit count. MAHARERA's public API simply doesn't expose it, so
the live adapter never claims to have it (see maha_rera.py).
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.adapters.maha_rera_session import load_token
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_LIST_URL = "https://maharera.maharashtra.gov.in/projects-search-result"
_API_BASE = (
    "https://maharerait.maharashtra.gov.in"
    "/api/maha-rera-public-view-project-registration-service"
    "/public/projectregistartion"  # typo is intentional -- MAHARERA's own API path
)
_DETAIL_SUBDOMAIN = "https://maharerait.maharashtra.gov.in"
_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)

_CARD_SELECTOR = "div.row.shadow.p-3.mb-5.bg-body.rounded"
_REG_NUMBER_SELECTOR = ".col-xl-4 > p.p-0"
_PROJECT_NAME_SELECTOR = ".col-xl-4 h4.title4"
_DEVELOPER_NAME_SELECTOR = ".col-xl-4 p.darkBlue.bold"
_DETAIL_URL_SELECTOR = ".col-xl-2 a.click-projectmodal.viewLink"

LIST_PAGE_FIXED_PARAMS = {
    "project_name": "",
    "project_location": "",
    "project_completion_date": "",
    "project_state": 27,  # Maharashtra
    "carpetAreas": "",
    "completionPercentages": "",
    "project_division": "",
    "op": "",
}

# API field mappings -- MAHARERA's own field names have typos; map to clean
# names here rather than propagate them into this platform's DataPoints.
_GENERAL_FIELDS = {
    "projectRegistartionNo": "registration_number",  # typo: "registartion"
    "projectName": "project_name",
    "projectTypeName": "project_type",
    "projectStatusName": "status_name",
    "projectProposeComplitionDate": "proposed_completion_date",  # typo: "complition"
    "originalProjectProposeCompletionDate": "original_completion_date",
    "reraRegistrationDate": "registration_date",
    "isProjectLapsed": "is_lapsed",
    "userProfileId": "promoter_profile_id",
}
_PROMOTER_FIELDS = {"promoterName": "developer_name"}
_ADDRESS_FIELDS = {
    "districtName": "district",
    "talukaName": "taluka",
    "stateName": "state",
    "villageName": "village",
}


class MahaRERALiveError(Exception):
    """Base for live-adapter failures."""


class MahaRERAAuthError(MahaRERALiveError):
    """JWT missing or rejected -- needs a human to re-run
    scripts/setup_maharera_session.py to obtain a fresh session token."""


class MahaRERANotFoundError(MahaRERALiveError):
    """Search returned no matching project."""


def build_list_page_params(page_num: int, project_name: str = "") -> dict:
    """Build the full query param dict MAHARERA's search page requires.
    Omitting the fixed (empty) params causes the site to silently ignore
    the request; `project_name` is the one param this module actually
    varies -- it's the site's own project-name search filter."""
    return {**LIST_PAGE_FIXED_PARAMS, "project_name": project_name, "project_district": 0, "page": page_num}


def _extract_labelled_value(card: Tag, label: str) -> str | None:
    for grey_div in card.select(".greyColor"):
        if grey_div.get_text(strip=True) == label:
            value_el = grey_div.find_next_sibling("p")
            if value_el:
                return value_el.get_text(strip=True)
    return None


def _parse_card(card: Tag) -> dict | None:
    reg_el = card.select_one(_REG_NUMBER_SELECTOR)
    reg_number = reg_el.get_text(strip=True).lstrip("# ") if reg_el else None

    name_el = card.select_one(_PROJECT_NAME_SELECTOR)
    project_name = name_el.get_text(strip=True) if name_el else None

    dev_el = card.select_one(_DEVELOPER_NAME_SELECTOR)
    developer_name = dev_el.get_text(strip=True) if dev_el else None

    district = _extract_labelled_value(card, "District")

    detail_el = card.select_one(_DETAIL_URL_SELECTOR)
    detail_url = detail_el.get("href", "") if detail_el else None
    if detail_url and detail_url.startswith("/"):
        detail_url = f"{_DETAIL_SUBDOMAIN}{detail_url}"

    project_id = None
    if detail_url:
        match = re.search(r"/view/(\d+)", detail_url)
        if match:
            project_id = match.group(1)

    if not reg_number or not project_id:
        return None

    return {
        "registration_number": reg_number,
        "project_name": project_name or "",
        "developer_name": developer_name or "",
        "district": district or "",
        "project_id": project_id,
    }


def parse_list_page(html: str) -> list[dict]:
    """Extract project stubs (registration_number, project_name,
    developer_name, district, project_id) from a MAHARERA search-results
    HTML page. Pure function -- no I/O, testable offline."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(_CARD_SELECTOR)
    if not cards:
        logger.warning("No project cards found on MAHARERA search page -- selector may need updating")
    stubs = [stub for card in cards if (stub := _parse_card(card)) is not None]
    return stubs


def _map_fields(response_object: dict, field_map: dict[str, str]) -> dict:
    return {
        clean_key: (str(val) if (val := response_object.get(api_key)) is not None else None)
        for api_key, clean_key in field_map.items()
    }


def map_general_details(response_object: dict) -> dict:
    return _map_fields(response_object or {}, _GENERAL_FIELDS)


def map_promoter_details(response_object: dict) -> dict:
    promoter = (response_object or {}).get("promoterDetails") or {}
    return _map_fields(promoter, _PROMOTER_FIELDS)


def map_address(response_object) -> dict:
    item = response_object[0] if isinstance(response_object, list) and response_object else response_object
    return _map_fields(item if isinstance(item, dict) else {}, _ADDRESS_FIELDS)


class MahaRERALiveClient:
    """Async client for MAHARERA's public search page (Tier 1, no auth) and
    authenticated detail API (Tier 2, needs a human-obtained JWT). One
    instance per call site -- cheap to construct, not held open across
    requests.
    """

    def __init__(self):
        settings = get_settings()
        self._timeout = settings.maharera_request_timeout_seconds
        self._rate_limit_delay = settings.maharera_rate_limit_delay_seconds
        self._max_retries = settings.maharera_max_retries
        self._user_agent = settings.maharera_user_agent

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
            retry=retry_if_exception_type(MahaRERALiveError),
            reraise=True,
        ):
            with attempt:
                await asyncio.sleep(self._rate_limit_delay)
                try:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.request(method, url, **kwargs)
                except httpx.RequestError as exc:
                    raise MahaRERALiveError(f"Request failed for {url}: {exc}") from exc
                if response.status_code in _RETRY_STATUS_CODES:
                    raise MahaRERALiveError(f"HTTP {response.status_code} from {url}")
                return response
        # Unreachable: reraise=True means AsyncRetrying always re-raises the
        # last exception instead of falling through the loop.
        raise MahaRERALiveError(f"Exhausted retries for {url}")  # pragma: no cover

    async def search(self, *, project_name: str = "", page: int = 1) -> list[dict]:
        """Tier 1: search the public list page. No auth required."""
        response = await self._request_with_retry(
            "GET",
            _LIST_URL,
            params=build_list_page_params(page, project_name),
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )
        return parse_list_page(response.text)

    async def get_general_details(self, project_id: str) -> dict | None:
        return await self._post("getProjectGeneralDetailsByProjectId", {"projectId": project_id})

    async def get_promoter_details(self, project_id: str) -> dict | None:
        return await self._post("getProjectAndAssociatedPromoterDetails", {"projectId": project_id})

    async def get_land_address(self, project_id: str) -> dict | None:
        return await self._post("getProjectLandAddressDetails", {"projectId": project_id})

    async def _post(self, endpoint: str, body: dict) -> dict | None:
        jwt = load_token()
        if not jwt:
            raise MahaRERAAuthError(
                "No MAHARERA session token found -- run "
                "`python scripts/setup_maharera_session.py` to obtain one (solves a "
                "CAPTCHA in a real browser window)."
            )
        response = await self._request_with_retry(
            "POST",
            f"{_API_BASE}/{endpoint}",
            json=body,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": f"{_DETAIL_SUBDOMAIN}/",
                "Origin": _DETAIL_SUBDOMAIN,
                "Authorization": f"Bearer {jwt}",
            },
        )
        if response.status_code == 401:
            raise MahaRERAAuthError(
                "MAHARERA session token expired or invalid -- re-run "
                "`python scripts/setup_maharera_session.py` to get a fresh one."
            )
        if not response.is_success:
            logger.warning("Non-200 from %s: status=%d", endpoint, response.status_code)
            return None
        try:
            return response.json().get("responseObject")
        except ValueError:
            return None
