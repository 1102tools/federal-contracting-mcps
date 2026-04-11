# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""SAM.gov MCP server.

Provides access to SAM.gov entity registration, exclusion/debarment records,
contract opportunity data, and contract award data (FPDS replacement).
Authentication via environment variable SAM_API_KEY.

The server wraps four SAM.gov REST APIs:
- Entity Management v3 (/entity-information/v3/entities)
- Exclusions v4 (/entity-information/v4/exclusions)
- Get Opportunities v2 (/opportunities/v2/search)
- Contract Awards v1 (/contract-awards/v1/search)
- Product/Service Code lookup (/prod/locationservices/v1/api/publicpscdetails)

All tools are read-only. API keys expire every 90 days; on 401/403 errors
the server returns an actionable regeneration message.
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    CONTRACT_AWARDS_MAX_LIMIT,
    CONTRACT_AWARDS_PATH,
    DEFAULT_TIMEOUT,
    ENTITY_MAX_SIZE,
    ENTITY_PATH,
    EXCLUSION_MAX_SIZE,
    EXCLUSIONS_PATH,
    OPPORTUNITIES_PATH,
    OPPORTUNITY_DESC_PATH,
    OPPORTUNITY_MAX_LIMIT,
    PSC_PATH,
    USER_AGENT,
)

mcp = FastMCP("sam-gov")


# ---------------------------------------------------------------------------
# Auth and HTTP client
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Fetch the SAM.gov API key from the environment on every call.

    Reading per-call (rather than at import time) lets users update the env
    without restarting the server and keeps the key out of module state.
    """
    key = os.environ.get("SAM_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "SAM_API_KEY environment variable is not set. "
            "Get a free API key at https://sam.gov/profile/details "
            "(Public API Key section) and set it in your Claude Desktop "
            "mcpServers config under 'env'."
        )
    if not key.startswith("SAM-"):
        raise RuntimeError(
            f"SAM_API_KEY is set but has an unexpected format "
            f"(expected SAM-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx, "
            f"got something starting with {key[:10]!r}). "
            "Verify the key at https://sam.gov/profile/details."
        )
    return key


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            # CRITICAL: do not set Accept: application/json; the Exclusions
            # endpoint returns 406 Not Acceptable when that header is present.
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: str) -> str:
    """Translate common SAM.gov errors into actionable messages."""
    # 401/403: key expired or invalid. Response is often HTML, not JSON.
    if status in (401, 403):
        return (
            f"HTTP {status}: SAM.gov API key rejected. "
            "SAM.gov keys expire every 90 days. "
            "Log into sam.gov, go to Profile > Public API Key, and "
            "regenerate the key. Then update your SAM_API_KEY env var "
            "(in Claude Desktop mcpServers config or your shell profile)."
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. "
            "The SAM.gov Exclusions endpoint rejects requests that include "
            "an Accept: application/json header. This server does not set "
            "that header by default; if you see this error, check that no "
            "proxy is injecting one."
        )
    if status == 429:
        return (
            "HTTP 429: Rate limited. "
            "Daily API limits: 10/day (no SAM role), 1000/day (personal), "
            "10000/day (federal system account). "
            "Wait until the next day or switch to a system account key."
        )
    if status == 400:
        # Surface specific 400 patterns
        lower = body.lower()
        if "size cannot exceed 10" in lower:
            return (
                "HTTP 400: Entity Management has a hard cap of size=10 per request. "
                "To retrieve more records, paginate with the 'page' parameter. "
                "This cap does NOT apply to Opportunities (which accepts limit=1000+)."
            )
        if "invalid_search_parameter" in lower or "invalid search" in lower:
            return (
                f"HTTP 400: Invalid search parameter. "
                f"Exclusions uses 'size' not 'limit'. "
                f"Opportunities requires postedFrom and postedTo (MM/DD/YYYY). "
                f"Dates must be MM/DD/YYYY, not ISO 8601. "
                f"API response: {body[:400]}"
            )
        if "date" in lower and ("range" in lower or "format" in lower):
            return (
                f"HTTP 400: Date parameter error. "
                f"SAM.gov uses MM/DD/YYYY format (not ISO 8601). "
                f"Opportunity postedFrom/postedTo range max is 364 days. "
                f"API response: {body[:400]}"
            )
        return f"HTTP 400: {body[:500]}"
    if status == 414:
        return (
            "HTTP 414: URI Too Long. The query string exceeds SAM.gov's URL "
            "length limit. Shorten your search parameters (entity names, "
            "free text) and try again."
        )
    return f"HTTP {status}: {body[:500]}"


async def _get(
    path: str,
    params: dict[str, Any],
    *,
    base_url: str = BASE_URL,
) -> dict[str, Any]:
    """GET helper. Handles SAM.gov auth, error translation, and HTML 401 bodies."""
    api_key = _get_api_key()
    query = dict(params)
    query["api_key"] = api_key

    # Build URL manually so we can preserve brackets/tildes used for OR/NOT
    # in SAM.gov multi-value params.
    query_str = urllib.parse.urlencode(query, safe="[],~/!*")
    full_url = f"{base_url}{path}?{query_str}"

    try:
        r = await _get_client().get(full_url)
        r.raise_for_status()
        # Most endpoints return JSON; opportunity description endpoint returns
        # a JSON object with a "description" HTML field.
        content_type = r.headers.get("content-type", "")
        if "json" in content_type:
            return r.json()
        # Contract Awards returns plain text for certain errors even on 200
        # (e.g. "Max value allowed for parameter \"limit\" is 100").
        # Also returns HTML for auth errors (e.g. <h1>API_KEY_INVALID</h1>).
        body = r.text.strip()
        if body and not body.startswith("{"):
            raise RuntimeError(f"SAM.gov returned non-JSON response: {body[:500]}")
        # Sometimes SAM.gov returns text/html for errors even on 200
        return {"raw_response": r.text}
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text)) from e
    except httpx.RequestError as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["reset", "closed", "connection", "timeout", "eof"]):
            raise RuntimeError(
                f"SAM.gov dropped the connection. This often happens when the "
                f"request URL contains characters that trigger their web application "
                f"firewall (single quotes, angle brackets, SQL keywords, path "
                f"traversal sequences like '../'). Remove special characters "
                f"from your search parameters and try again. "
                f"Original error: {e}"
            ) from e
        raise RuntimeError(f"Network error calling SAM.gov: {e}") from e


# ---------------------------------------------------------------------------
# Entity Management tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_entity_by_uei(
    uei: str,
    include_sections: list[
        Literal[
            "entityRegistration",
            "coreData",
            "assertions",
            "pointsOfContact",
            "repsAndCerts",
            "integrityInformation",
            "All",
        ]
    ] | None = None,
    sam_registered: Literal["Yes", "No"] = "Yes",
) -> dict[str, Any]:
    """Look up a federal entity by its Unique Entity ID (UEI).

    Returns the full entity record from SAM.gov Entity Management v3.
    The UEI is a 12-character alphanumeric identifier assigned by SAM.gov.

    include_sections controls response size:
    - entityRegistration: UEI, CAGE, name, status, activation/expiration dates (ALWAYS include)
    - coreData: addresses, POCs at high level, business types, hierarchy
    - assertions: NAICS and PSC codes (in goodsAndServices subsection)
    - pointsOfContact: detailed POC records (name, title, address; email/phone FOUO only)
    - repsAndCerts: FAR/DFARS certification responses (must be explicitly requested)
    - integrityInformation: FAPIIS proceedings data (must be explicitly requested)
    - All: entityRegistration + coreData + assertions + pointsOfContact (but NOT repsAndCerts/integrityInformation)

    Default: entityRegistration + coreData. Always include entityRegistration
    alongside any other section or the response loses entity identification.

    sam_registered='Yes' (default) returns only fully registered entities.
    Use 'No' to find entities with a UEI assigned but incomplete registration.
    """
    if not uei or not uei.strip():
        return {"totalRecords": 0, "entityData": [], "_note": "Empty UEI provided."}

    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]
    elif "entityRegistration" not in include_sections and "All" not in include_sections:
        include_sections = ["entityRegistration"] + list(include_sections)

    params = {
        "ueiSAM": uei.strip(),
        "samRegistered": sam_registered,
        "includeSections": ",".join(include_sections),
    }
    return await _get(ENTITY_PATH, params)


@mcp.tool()
async def lookup_entity_by_cage(
    cage_code: str,
    include_sections: list[str] | None = None,
) -> dict[str, Any]:
    """Look up a federal entity by its CAGE code.

    CAGE (Commercial and Government Entity) codes are 5-character alphanumeric
    identifiers assigned by DLA. Useful when you have a CAGE but no UEI.
    """
    if not cage_code or not cage_code.strip():
        return {"totalRecords": 0, "entityData": [], "_note": "Empty CAGE code provided."}

    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]
    params = {
        "cageCode": cage_code.strip(),
        "samRegistered": "Yes",
        "includeSections": ",".join(include_sections),
    }
    return await _get(ENTITY_PATH, params)


@mcp.tool()
async def search_entities(
    legal_business_name: str | None = None,
    primary_naics: str | None = None,
    any_naics: str | None = None,
    psc_code: str | None = None,
    business_type_code: str | None = None,
    state_code: str | None = None,
    registration_status: Literal["A", "E", "D", "I"] = "A",
    purpose_of_registration: Literal["Z1", "Z2", "Z5"] | None = None,
    free_text: str | None = None,
    include_sections: list[str] | None = None,
    page: int = 0,
    size: int = 10,
) -> dict[str, Any]:
    """Search SAM.gov entities with flexible filters.

    All filters are AND-ed together. Returns paginated results; note that
    Entity Management has a HARD CAP of 10 records per page (size <= 10).
    For more results, increment 'page' and make multiple calls.

    Key filter notes:
    - legal_business_name does partial matching with no relevance ranking.
      Cannot contain & or parentheses (API strips them, returns 0 results).
      For exact lookup use UEI or CAGE.
    - primary_naics matches the entity's designated primary NAICS only.
    - any_naics matches any NAICS the entity has on file.
    - business_type_code uses codes like QF (SDVOSB), A2 (Women-Owned),
      8W (WOSB), 23 (Minority-Owned). SDVOSB is NOT XS (that's S-Corp).
    - state_code is 2-letter USPS.
    - purpose_of_registration: Z1=Federal Assistance only, Z2=All Awards,
      Z5=Supplemental grants only.
    - free_text (q parameter) ANDs multiple words together. "cybersecurity cloud"
      returns entities matching BOTH words, not either.

    Default registration_status is 'A' (Active); use 'E' for expired registrations.
    """
    if size > ENTITY_MAX_SIZE:
        raise ValueError(
            f"Entity Management has a hard cap of size={ENTITY_MAX_SIZE}. "
            f"You passed size={size}. Paginate with the 'page' parameter instead."
        )
    if size < 1:
        raise ValueError(
            f"size must be at least 1 (got {size}). "
            f"Entity Management returns 1-10 records per page."
        )
    if include_sections is None:
        include_sections = ["entityRegistration", "coreData"]

    params: dict[str, Any] = {
        "samRegistered": "Yes",
        "registrationStatus": registration_status,
        "includeSections": ",".join(include_sections),
        "page": str(page),
        "size": str(size),
    }
    if legal_business_name:
        params["legalBusinessName"] = legal_business_name
    if primary_naics:
        params["primaryNaics"] = primary_naics
    if any_naics:
        params["naicsCode"] = any_naics
    if psc_code:
        params["pscCode"] = psc_code
    if business_type_code:
        params["businessTypeCode"] = business_type_code
    if state_code:
        params["physicalAddressProvinceOrStateCode"] = state_code
    if purpose_of_registration:
        params["purposeOfRegistrationCode"] = purpose_of_registration
    if free_text:
        params["q"] = free_text

    return await _get(ENTITY_PATH, params)


@mcp.tool()
async def get_entity_reps_and_certs(uei: str) -> dict[str, Any]:
    """Fetch FAR/DFARS representations and certifications for an entity by UEI.

    repsAndCerts is NOT included in the default response or even in
    includeSections=All. It must be explicitly requested. Returns the
    entity's responses to standard FAR 52.212-3, FAR 52.204-17, FAR 52.209-2,
    FAR 52.219-1, FAR 52.222-18, FAR 52.225-2, DFARS 252.204-7016, and other
    certification clauses.

    Combined with entityRegistration for identification context.
    """
    params = {
        "ueiSAM": uei,
        "samRegistered": "Yes",
        "includeSections": "entityRegistration,repsAndCerts",
    }
    return await _get(ENTITY_PATH, params)


@mcp.tool()
async def get_entity_integrity_info(uei: str) -> dict[str, Any]:
    """Fetch FAPIIS proceedings integrity information for an entity by UEI.

    integrityInformation is NOT included in the default response or even
    includeSections=All. Requires explicit request plus proceedingsData=Yes
    query parameter. Returns proceedings disclosures per FAR 52.209-7/9.
    """
    params = {
        "ueiSAM": uei,
        "samRegistered": "Yes",
        "includeSections": "entityRegistration,integrityInformation",
        "proceedingsData": "Yes",
    }
    return await _get(ENTITY_PATH, params)


# ---------------------------------------------------------------------------
# Exclusion tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def check_exclusion_by_uei(uei: str) -> dict[str, Any]:
    """Check if an entity has any exclusion/debarment records by UEI.

    Returns exclusion records from the consolidated Excluded Parties List.
    totalRecords=0 means the entity is not currently excluded. totalRecords>0
    means one or more exclusion records exist; check recordStatus='Active' on
    each entry to determine if the exclusion is currently in effect.

    This is the single most important check for FAR 9.104-1 responsibility
    determinations and FAR 9.405 debarment prohibitions.
    """
    if not uei or not uei.strip():
        return {"totalRecords": 0, "excludedEntity": [], "_note": "Empty UEI provided."}
    params = {"ueiSAM": uei.strip()}
    return await _get(EXCLUSIONS_PATH, params)


@mcp.tool()
async def search_exclusions(
    entity_name: str | None = None,
    cage_code: str | None = None,
    classification: Literal["Firm", "Individual", "Vessel", "Special Entity Designation"] | None = None,
    exclusion_program: Literal["Reciprocal", "NonProcurement", "Procurement"] | None = None,
    excluding_agency_code: str | None = None,
    state_province: str | None = None,
    country: str | None = None,
    activation_date_range: str | None = None,
    free_text: str | None = None,
    page: int = 0,
    size: int = 10,
) -> dict[str, Any]:
    """Search SAM.gov exclusion records with flexible filters.

    All filters are AND-ed. Unlike Entity Management, Exclusions uses 'size'
    (not 'limit') for pagination. Size can go up to 100 per page.

    Key filter notes:
    - entity_name: firm name for classification=Firm; for individuals use
      the full name. Cannot contain &, |, {, }, ^, backslash.
    - cage_code: 5-character CAGE of the excluded entity.
    - classification: Firm, Individual, Vessel, or Special Entity Designation.
    - exclusion_program: Reciprocal (cross-agency), NonProcurement, or Procurement.
    - excluding_agency_code: agency code that imposed the exclusion (e.g., DOD, HHS).
    - country: MUST be 3-character ISO alpha-3 (USA, CAN, GBR). 2-char codes
      (US, CA, GB) return 0 results.
    - activation_date_range: use bracket format [MM/DD/YYYY,MM/DD/YYYY].
    - free_text (q parameter): supports wildcards (*), AND, OR operators.
      Example: "acme*" matches any company starting with acme.
    """
    if size > EXCLUSION_MAX_SIZE:
        raise ValueError(
            f"Exclusions max size is {EXCLUSION_MAX_SIZE}. "
            f"You passed size={size}. Paginate with the 'page' parameter."
        )
    if size < 1:
        raise ValueError(f"size must be at least 1 (got {size}).")

    params: dict[str, Any] = {
        "page": str(page),
        "size": str(size),
    }
    if entity_name:
        params["entityName"] = entity_name
    if cage_code:
        params["cageCode"] = cage_code
    if classification:
        params["classification"] = classification
    if exclusion_program:
        params["exclusionProgram"] = exclusion_program
    if excluding_agency_code:
        params["excludingAgencyCode"] = excluding_agency_code
    if state_province:
        params["stateProvince"] = state_province
    if country:
        if len(country) != 3:
            raise ValueError(
                f"country must be 3-character ISO alpha-3 (USA, CAN, GBR). "
                f"Got {country!r}."
            )
        params["country"] = country
    if activation_date_range:
        params["activationDate"] = activation_date_range
    if free_text:
        params["q"] = free_text

    return await _get(EXCLUSIONS_PATH, params)


# ---------------------------------------------------------------------------
# Opportunity tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_opportunities(
    posted_from: str,
    posted_to: str,
    notice_type: Literal["p", "o", "k", "r", "g", "s", "i", "a", "u"] | None = None,
    title: str | None = None,
    solicitation_number: str | None = None,
    notice_id: str | None = None,
    naics_code: str | None = None,
    psc_code: str | None = None,
    set_aside: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    response_deadline_from: str | None = None,
    response_deadline_to: str | None = None,
    agency_keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract opportunities on SAM.gov.

    posted_from and posted_to are MANDATORY. Format is MM/DD/YYYY (not ISO 8601).
    The date range cannot exceed 364 days. For older notices or longer ranges,
    chain multiple calls with sequential date windows.

    Notice type codes:
    - p = Presolicitation
    - o = Solicitation
    - k = Combined Synopsis/Solicitation
    - r = Sources Sought
    - s = Special Notice
    - i = Intent to Bundle
    - a = Award Notice
    - u = Justification (J&A)
    - g = Sale of Surplus Property

    WORKING filters: title, solicitation_number, notice_id, notice_type,
    naics_code, psc_code, set_aside, state, zip_code, response_deadline_from,
    response_deadline_to.

    BROKEN filters (do not use): deptname, subtier. The SAM.gov API silently
    ignores these. To filter by agency, use agency_keyword — this tool will
    post-filter the results by checking fullParentPathName for a substring match.

    PSC code filter (psc_code) requires exact 4-character match. Prefix
    matching (e.g. 'R4') returns 0 results; use 'R425'.

    Set-aside codes: SBA, SBP, 8A, 8AN, HZC, HZS, SDVOSBC, SDVOSBS, WOSB,
    WOSBSS, EDWOSB, EDWOSBSS, VSA, VSS.

    The 'description' field in each result is a URL, not inline text. Use
    get_opportunity_description() to fetch the actual description HTML.
    """
    if limit > OPPORTUNITY_MAX_LIMIT:
        raise ValueError(
            f"limit should not exceed {OPPORTUNITY_MAX_LIMIT}. "
            f"You passed limit={limit}."
        )

    params: dict[str, Any] = {
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": str(limit),
        "offset": str(offset),
    }
    if notice_type:
        params["ptype"] = notice_type
    if title:
        params["title"] = title
    if solicitation_number:
        params["solnum"] = solicitation_number
    if notice_id:
        params["noticeid"] = notice_id
    if naics_code:
        params["ncode"] = naics_code
    if psc_code:
        params["ccode"] = psc_code
    if set_aside:
        params["typeOfSetAside"] = set_aside
    if state:
        params["state"] = state
    if zip_code:
        params["zip"] = zip_code
    if response_deadline_from:
        params["rdlfrom"] = response_deadline_from
    if response_deadline_to:
        params["rdlto"] = response_deadline_to

    result = await _get(OPPORTUNITIES_PATH, params)

    # Post-filter by agency if requested (the deptname/subtier API params are broken)
    if agency_keyword and isinstance(result.get("opportunitiesData"), list):
        keyword_upper = agency_keyword.upper()
        filtered = [
            o for o in result["opportunitiesData"]
            if keyword_upper in (o.get("fullParentPathName") or "").upper()
        ]
        result["opportunitiesData"] = filtered
        result["totalRecords_postFilter"] = len(filtered)
        result["_postFilter"] = f"agency_keyword={agency_keyword!r}"

    return result


@mcp.tool()
async def get_opportunity_description(notice_id: str) -> dict[str, Any]:
    """Fetch the full description text for a contract opportunity by notice ID.

    The 'description' field in search_opportunities results is a URL, not
    inline text. This tool handles the second fetch to retrieve the actual
    HTML description. Pass the noticeId from the search results.
    """
    params = {"noticeid": notice_id}
    return await _get(OPPORTUNITY_DESC_PATH, params)


# ---------------------------------------------------------------------------
# PSC lookup tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_psc_code(
    code: str,
    active_only: Literal["Y", "N", "ALL"] = "Y",
) -> dict[str, Any]:
    """Look up a Product/Service Code (PSC) by its code value.

    Returns the PSC name, full name, level 1 and level 2 category information,
    and includes/excludes guidance. Useful for validating PSC codes before
    using them as filters in other searches.
    """
    params = {
        "q": code,
        "searchby": "psc",
        "active": active_only,
    }
    return await _get(PSC_PATH, params)


@mcp.tool()
async def search_psc_free_text(
    query: str,
    active_only: Literal["Y", "N", "ALL"] = "Y",
) -> dict[str, Any]:
    """Free-text search for Product/Service Codes (PSC).

    Searches across PSC names, descriptions, and category hierarchy. Returns
    matching PSC codes with full context. Useful for discovering PSCs from
    plain-language descriptions like 'engineering' or 'application development'.
    """
    params = {
        "q": query,
        "active": active_only,
    }
    return await _get(PSC_PATH, params)


# ---------------------------------------------------------------------------
# Contract Awards tools (FPDS replacement)
# ---------------------------------------------------------------------------


def _normalize_awards_response(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the inconsistent Contract Awards response wrapper.

    Populated results: {"awardSummary": [...], "totalRecords": 123, ...}
    Empty results:     {"awardResponse": {"totalRecords": "0", ...}, "message": "No Data..."}

    This normalizes empty results to match the populated shape so callers
    always see {"awardSummary": [...], "totalRecords": int, ...}.
    """
    if "awardResponse" in data and "awardSummary" not in data:
        ar = data["awardResponse"]
        return {
            "awardSummary": [],
            "totalRecords": int(ar.get("totalRecords", 0)),
            "limit": int(ar.get("limit", 10)),
            "offset": int(ar.get("offset", 0)),
            "message": data.get("message", ""),
        }
    # Populated responses sometimes return totalRecords as a string
    if "totalRecords" in data:
        data["totalRecords"] = int(data["totalRecords"])
    return data


@mcp.tool()
async def search_contract_awards(
    awardee_name: str | None = None,
    awardee_uei: str | None = None,
    awardee_cage_code: str | None = None,
    piid: str | None = None,
    naics_code: str | None = None,
    psc_code: str | None = None,
    contracting_department_code: str | None = None,
    contracting_subtier_code: str | None = None,
    contracting_office_code: str | None = None,
    date_signed: str | None = None,
    last_modified_date: str | None = None,
    fiscal_year: str | None = None,
    award_or_idv: Literal["AWARD", "IDV"] | None = None,
    type_of_contract_pricing_code: str | None = None,
    type_of_set_aside_code: str | None = None,
    extent_competed_code: str | None = None,
    dollars_obligated: str | None = None,
    modification_number: str | None = None,
    free_text: str | None = None,
    include_sections: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract award records on SAM.gov (FPDS replacement).

    This is the replacement for FPDS.gov (decommissioned Feb 2026). Same data,
    new endpoint. Uses limit/offset pagination (NOT page/size).

    CRITICAL date format: MM/dd/yyyy for single dates, [MM/dd/yyyy,MM/dd/yyyy]
    for ranges (brackets included). ISO 8601 dates are rejected.

    Boolean operators: use ~ for OR (e.g. naics_code="541512~541511"),
    use ! for NOT (e.g. extent_competed_code="!A").

    Key parameters:
    - awardee_name: awardeeLegalBusinessName (partial match). NOT "vendorName".
    - awardee_uei: awardeeUniqueEntityId (exact match)
    - awardee_cage_code: awardeeCageCode (exact match)
    - piid: Procurement Instrument Identifier. Returns all mods for that PIID.
    - naics_code: 6-digit NAICS. Supports ~ for OR, ! for NOT.
    - psc_code: Product/Service Code (4-char). Supports ~ for OR.
    - contracting_department_code: top-level department (e.g. "9700" for DoD)
    - contracting_subtier_code: subtier agency (e.g. "1700" for Navy)
    - contracting_office_code: contracting office (e.g. "N00039")
    - date_signed: date of award action. MM/dd/yyyy or [MM/dd/yyyy,MM/dd/yyyy]
    - last_modified_date: when record was last modified. Same format.
    - fiscal_year: filter by FY (e.g. "2026")
    - award_or_idv: "AWARD" for contracts/orders, "IDV" for indefinite-delivery vehicles
    - type_of_contract_pricing_code: J=FFP, U=CPFF, etc.
    - type_of_set_aside_code: SBA, 8A, HZC, SDVOSBC, etc.
    - extent_competed_code: A=Full, B=Not Available, CDO=Competed Under SAP, etc.
    - dollars_obligated: bracket range [min,max] as string
    - modification_number: "0" for base award, specific mod number, or range
    - free_text: q parameter for full-text search across all fields
    - include_sections: comma-separated: contractId, coreData, awardDetails (default: all)
    - limit: max records per page (1-100, default 10)
    - offset: 0-based record skip count for pagination

    Returns normalized response with awardSummary list and totalRecords count.
    Each record has up to 3 sections: contractId, coreData, awardDetails.
    """
    if limit > CONTRACT_AWARDS_MAX_LIMIT:
        raise ValueError(
            f"Contract Awards has a hard cap of limit={CONTRACT_AWARDS_MAX_LIMIT}. "
            f"You passed limit={limit}. Use offset for pagination."
        )
    if limit < 1:
        raise ValueError(f"limit must be at least 1 (got {limit}).")

    params: dict[str, Any] = {
        "limit": str(limit),
        "offset": str(offset),
    }
    if awardee_name:
        params["awardeeLegalBusinessName"] = awardee_name
    if awardee_uei:
        params["awardeeUniqueEntityId"] = awardee_uei
    if awardee_cage_code:
        params["awardeeCageCode"] = awardee_cage_code
    if piid:
        params["piid"] = piid
    if naics_code:
        params["naicsCode"] = naics_code
    if psc_code:
        params["productOrServiceCode"] = psc_code
    if contracting_department_code:
        params["contractingDepartmentCode"] = contracting_department_code
    if contracting_subtier_code:
        params["contractingSubtierCode"] = contracting_subtier_code
    if contracting_office_code:
        params["contractingOfficeCode"] = contracting_office_code
    if date_signed:
        params["dateSigned"] = date_signed
    if last_modified_date:
        params["lastModifiedDate"] = last_modified_date
    if fiscal_year:
        params["fiscalYear"] = fiscal_year
    if award_or_idv:
        params["awardOrIDV"] = award_or_idv
    if type_of_contract_pricing_code:
        params["typeOfContractPricingCode"] = type_of_contract_pricing_code
    if type_of_set_aside_code:
        params["typeOfSetAsideCode"] = type_of_set_aside_code
    if extent_competed_code:
        params["extentCompetedCode"] = extent_competed_code
    if dollars_obligated:
        params["dollarsObligated"] = dollars_obligated
    if modification_number:
        params["modificationNumber"] = modification_number
    if free_text:
        params["q"] = free_text
    if include_sections:
        params["includeSections"] = include_sections

    result = await _get(CONTRACT_AWARDS_PATH, params)
    return _normalize_awards_response(result)


@mcp.tool()
async def lookup_award_by_piid(
    piid: str,
    include_sections: str | None = None,
) -> dict[str, Any]:
    """Look up all contract award modifications for a single PIID.

    Returns all modification records for the given Procurement Instrument
    Identifier, sorted by modification number. This is the primary way to
    get the full history of a contract action.

    PIIDs are alphanumeric identifiers assigned by the contracting office.
    Format varies by agency (e.g. "GS-35F-0119Y", "W912BV22P0112",
    "N0003925F7516"). The search is exact match.

    include_sections: comma-separated list of contractId, coreData, awardDetails.
    Defaults to all sections if not specified.

    Returns normalized response with awardSummary list containing all
    modifications. Check totalRecords for the number of mods found.
    """
    if not piid or not piid.strip():
        return {"awardSummary": [], "totalRecords": 0, "_note": "Empty PIID provided."}

    params: dict[str, Any] = {
        "piid": piid.strip(),
        "limit": "100",
        "offset": "0",
    }
    if include_sections:
        params["includeSections"] = include_sections

    result = await _get(CONTRACT_AWARDS_PATH, params)
    return _normalize_awards_response(result)


@mcp.tool()
async def search_deleted_awards(
    piid: str | None = None,
    awardee_name: str | None = None,
    contracting_department_code: str | None = None,
    last_modified_date: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search contract award records that have been deleted from FPDS/SAM.gov.

    Uses the same Contract Awards endpoint with deletedStatus=Y. Deleted
    records are removed from normal search results but remain accessible
    through this parameter. Useful for audit trails and historical research.

    Supports the same date format as search_contract_awards:
    MM/dd/yyyy or [MM/dd/yyyy,MM/dd/yyyy] for ranges.

    limit: 1-100 (default 10). offset: 0-based pagination.
    """
    if limit > CONTRACT_AWARDS_MAX_LIMIT:
        raise ValueError(
            f"Contract Awards has a hard cap of limit={CONTRACT_AWARDS_MAX_LIMIT}. "
            f"You passed limit={limit}."
        )
    if limit < 1:
        raise ValueError(f"limit must be at least 1 (got {limit}).")

    params: dict[str, Any] = {
        "deletedStatus": "Y",
        "limit": str(limit),
        "offset": str(offset),
    }
    if piid:
        params["piid"] = piid
    if awardee_name:
        params["awardeeLegalBusinessName"] = awardee_name
    if contracting_department_code:
        params["contractingDepartmentCode"] = contracting_department_code
    if last_modified_date:
        params["lastModifiedDate"] = last_modified_date

    result = await _get(CONTRACT_AWARDS_PATH, params)
    return _normalize_awards_response(result)


# ---------------------------------------------------------------------------
# Composite workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def vendor_responsibility_check(uei: str) -> dict[str, Any]:
    """Composite pre-award vendor responsibility check per FAR 9.104-1.

    Performs TWO API calls in sequence:
    1. Entity Management lookup (registration status, business types,
       CAGE, activation/expiration dates, exclusion flag on the entity record)
    2. Exclusions lookup (active debarment/suspension records)

    Returns a structured summary with:
    - registration: full registration details or None if not registered
    - exclusion: exclusion record count and active exclusion details
    - flags: list of responsibility concern flags

    Flag meanings:
    - NOT_REGISTERED: entity has no SAM registration (cannot receive award per FAR 4.1102)
    - REGISTRATION_NOT_ACTIVE: registration expired or inactive
    - EXCLUSION_FLAG_ON_ENTITY: entity record indicates exclusion exists
    - ACTIVE_EXCLUSION_FOUND: confirmed active exclusion (FAR 9.405 prohibits award)

    No flags = clear for responsibility determination.
    """
    result: dict[str, Any] = {
        "uei": uei,
        "registration": None,
        "exclusion": None,
        "flags": [],
    }

    if not uei or not uei.strip():
        result["flags"].append("EMPTY_UEI")
        result["_note"] = "Cannot perform responsibility check without a UEI."
        return result

    uei = uei.strip()

    # Step 1: Entity registration + coreData
    try:
        entity_resp = await _get(
            ENTITY_PATH,
            {
                "ueiSAM": uei,
                "samRegistered": "Yes",
                "includeSections": "entityRegistration,coreData",
            },
        )
    except Exception as e:
        result["registration"] = {"error": str(e)}
        result["flags"].append("ENTITY_LOOKUP_FAILED")
        entity_resp = None

    if entity_resp is not None:
        if entity_resp.get("totalRecords", 0) == 0:
            result["flags"].append("NOT_REGISTERED")
        else:
            entity = entity_resp["entityData"][0]
            reg = entity.get("entityRegistration", {}) or {}
            core = entity.get("coreData", {}) or {}
            biz_types = (core.get("businessTypes") or {}).get("businessTypeList") or []
            sba_types = (core.get("businessTypes") or {}).get("sbaBusinessTypeList") or []

            result["registration"] = {
                "legalBusinessName": reg.get("legalBusinessName"),
                "status": reg.get("registrationStatus"),
                "activationDate": reg.get("activationDate"),
                "expirationDate": reg.get("registrationExpirationDate"),
                "cageCode": reg.get("cageCode"),
                "ueiStatus": reg.get("ueiStatus"),
                "exclusionStatusFlag": reg.get("exclusionStatusFlag"),
                "publicDisplayFlag": reg.get("publicDisplayFlag"),
                "businessTypes": [
                    bt.get("businessTypeDesc") for bt in biz_types
                ],
                "sbaBusinessTypes": [
                    st.get("sbaBusinessTypeDesc") for st in sba_types
                ],
            }
            if reg.get("registrationStatus") != "Active":
                result["flags"].append("REGISTRATION_NOT_ACTIVE")
            if reg.get("exclusionStatusFlag") == "Y":
                result["flags"].append("EXCLUSION_FLAG_ON_ENTITY")

    # Small courtesy delay between calls
    await asyncio.sleep(0.3)

    # Step 2: Exclusions check
    try:
        excl_resp = await _get(EXCLUSIONS_PATH, {"ueiSAM": uei})
    except Exception as e:
        result["exclusion"] = {"error": str(e)}
        result["flags"].append("EXCLUSION_LOOKUP_FAILED")
        excl_resp = None

    if excl_resp is not None:
        total = excl_resp.get("totalRecords", 0)
        if total == 0:
            result["exclusion"] = {"totalRecords": 0, "status": "NO_EXCLUSIONS_ON_RECORD"}
        else:
            records = excl_resp.get("excludedEntity", []) or []
            active = []
            for r in records:
                actions = (r.get("exclusionActions") or {}).get("listOfActions") or []
                if any(a.get("recordStatus") == "Active" for a in actions):
                    details = r.get("exclusionDetails") or {}
                    active.append({
                        "exclusionType": details.get("exclusionType"),
                        "exclusionProgram": details.get("exclusionProgram"),
                        "excludingAgency": details.get("excludingAgencyName"),
                        "classification": details.get("classificationType"),
                    })
            result["exclusion"] = {
                "totalRecords": total,
                "activeCount": len(active),
                "activeDetails": active,
            }
            if active:
                result["flags"].append("ACTIVE_EXCLUSION_FOUND")

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
