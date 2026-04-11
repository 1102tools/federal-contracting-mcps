# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""USASpending.gov MCP server.

Provides access to federal contract, grant, loan, and award data from
USASpending.gov. No API key required.

All tools are read-only. The server wraps the USASpending REST API at
https://api.usaspending.gov with actionable error handling and sensible
defaults matching common federal acquisition workflows.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    ALL_SB_SET_ASIDE_CODES,
    AWARD_TYPE_GROUPS,
    BASE_URL,
    COMPETED_CODES,
    DEFAULT_CONTRACT_FIELDS,
    DEFAULT_IDV_FIELDS,
    DEFAULT_LOAN_FIELDS,
    DEFAULT_TIMEOUT,
    NOT_COMPETED_CODES,
    SPENDING_CATEGORIES,
    USER_AGENT,
)

mcp = FastMCP("usaspending")


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
        )
    return _client


def _format_http_error(e: httpx.HTTPStatusError) -> str:
    """Translate common USASpending API errors into actionable messages."""
    status = e.response.status_code
    try:
        body = e.response.json()
        detail = body.get("detail") or body.get("messages") or body
    except Exception:
        detail = e.response.text[:500]

    detail_str = str(detail)

    # Known error patterns with actionable guidance
    if status == 422 and "award_type_codes" in detail_str and "one group" in detail_str:
        return (
            "HTTP 422: award_type_codes mixed across groups. "
            "Contracts [A,B,C,D], IDVs [IDV_*], Grants [02-05], "
            "Loans [07,08], Direct Payments [06,10], Other [09,11,-1] "
            "must each be used in separate requests. "
            f"API response: {detail}"
        )
    if status == 422 and "psc_codes" in detail_str:
        return (
            "HTTP 422: psc_codes filter malformed. "
            "Use a simple list like ['R499','D399']. "
            "Do not include an empty 'exclude' key. "
            f"API response: {detail}"
        )
    if status == 422 and "limit" in detail_str:
        return (
            "HTTP 422: limit exceeds maximum. "
            "Search endpoints max 100; transactions endpoint max 5000. "
            "Paginate with the 'page' parameter. "
            f"API response: {detail}"
        )
    if status == 400 and "Sort value not found in requested fields" in detail_str:
        return (
            "HTTP 400: sort field not present in fields list. "
            "The field you're sorting by must also appear in the fields array. "
            f"API response: {detail}"
        )
    if status == 400 and "keywords" in detail_str:
        return (
            "HTTP 400: empty keywords array. "
            "Omit the 'keywords' filter entirely rather than passing an empty list. "
            f"API response: {detail}"
        )
    if status == 400 and "Loan Award mappings" in detail_str:
        return (
            "HTTP 400: loan search used 'Award Amount' field. "
            "For loans (codes 07, 08) use 'Loan Value' instead. "
            f"API response: {detail}"
        )
    if status == 404:
        return (
            f"HTTP 404: resource not found. "
            f"For award detail endpoints, verify the generated_internal_id is correct. "
            f"API response: {detail}"
        )
    if status == 429:
        return (
            "HTTP 429: rate limited. "
            "Add 0.3s delay between batch requests, or reduce concurrency. "
            f"API response: {detail}"
        )

    return f"HTTP {status}: {detail}"


async def _post(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """POST helper with actionable error translation."""
    try:
        r = await _get_client().post(path, json=json)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET helper with actionable error translation."""
    try:
        r = await _get_client().get(path, params=params or {})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e


# ---------------------------------------------------------------------------
# Filter construction helpers
# ---------------------------------------------------------------------------

def _build_filters(
    *,
    keywords: list[str] | None = None,
    award_type_codes: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    recipient_uei: str | None = None,
    award_ids: list[str] | None = None,
    naics_codes: list[str] | None = None,
    psc_codes: list[str] | None = None,
    set_aside_type_codes: list[str] | None = None,
    extent_competed_type_codes: list[str] | None = None,
    contract_pricing_type_codes: list[str] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    def_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Build a USASpending filters object from flattened parameters."""
    filters: dict[str, Any] = {}

    if keywords:
        # USASpending API requires each keyword to be at least 3 characters
        short = [k for k in keywords if len(k) < 3]
        if short:
            raise ValueError(
                f"USASpending requires keywords of at least 3 characters. "
                f"Too short: {short}. Use more specific terms."
            )
        filters["keywords"] = keywords
    if award_type_codes:
        filters["award_type_codes"] = award_type_codes

    agencies = []
    # Awarding agency: if subagency is specified, use a single subtier entry
    # with toptier_name context. Otherwise use the toptier alone.
    if awarding_subagency:
        entry: dict[str, Any] = {
            "type": "awarding",
            "tier": "subtier",
            "name": awarding_subagency,
        }
        if awarding_agency:
            entry["toptier_name"] = awarding_agency
        agencies.append(entry)
    elif awarding_agency:
        agencies.append({
            "type": "awarding",
            "tier": "toptier",
            "name": awarding_agency,
        })
    if funding_agency:
        agencies.append({
            "type": "funding",
            "tier": "toptier",
            "name": funding_agency,
        })
    if agencies:
        filters["agencies"] = agencies

    if recipient_name:
        filters["recipient_search_text"] = [recipient_name]
    if recipient_uei:
        filters["recipient_id"] = recipient_uei
    if award_ids:
        filters["award_ids"] = award_ids
    if naics_codes:
        filters["naics_codes"] = naics_codes
    if psc_codes:
        filters["psc_codes"] = psc_codes
    if set_aside_type_codes:
        filters["set_aside_type_codes"] = set_aside_type_codes
    if extent_competed_type_codes:
        filters["extent_competed_type_codes"] = extent_competed_type_codes
    if contract_pricing_type_codes:
        filters["contract_pricing_type_codes"] = contract_pricing_type_codes
    if time_period_start or time_period_end:
        filters["time_period"] = [{
            "start_date": time_period_start or "2007-10-01",
            "end_date": time_period_end or "2099-09-30",
        }]
    if award_amount_min is not None or award_amount_max is not None:
        bounds: dict[str, float] = {}
        if award_amount_min is not None:
            bounds["lower_bound"] = award_amount_min
        if award_amount_max is not None:
            bounds["upper_bound"] = award_amount_max
        filters["award_amounts"] = [bounds]
    if place_of_performance_state:
        filters["place_of_performance_locations"] = [{
            "country": "USA",
            "state": place_of_performance_state,
        }]
    if def_codes:
        filters["def_codes"] = def_codes

    return filters


def _resolve_award_type(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"]
) -> list[str]:
    """Resolve an award type group name to its list of codes."""
    if award_type not in AWARD_TYPE_GROUPS:
        raise ValueError(
            f"Unknown award_type '{award_type}'. "
            f"Valid: {list(AWARD_TYPE_GROUPS.keys())}"
        )
    return AWARD_TYPE_GROUPS[award_type]


# ---------------------------------------------------------------------------
# Search tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_awards(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str] | None = None,
    psc_codes: list[str] | None = None,
    set_aside_type_codes: list[str] | None = None,
    extent_competed_type_codes: list[str] | None = None,
    contract_pricing_type_codes: list[str] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    award_ids: list[str] | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search federal awards (contracts, IDVs, grants, loans, etc.) on USASpending.gov.

    This is the primary workhorse for finding awards. Returns matching awards
    with standard fields (Award ID, Recipient, Description, Amount, Agencies,
    NAICS, PSC, dates). Use get_award_detail() with the generated_internal_id
    from results to get full award details.

    Important rules:
    - award_type groups cannot be mixed; pick one category per call
    - time_period_start/end use YYYY-MM-DD format
    - award_amount_min/max are in USD
    - place_of_performance_state is a 2-letter USPS code (e.g. 'MD', 'VA')
    - For loans, use award_type='loans' and sort='Loan Value'

    Filtering to specific contracting commands (NAVSEA, AFRL, etc.):
    USASpending's subtier level is at the service branch (Department of the
    Navy, Army, Air Force), not the contracting command. To filter to a
    specific command, use keywords with the PIID office prefix instead:
    - NAVSEA contracts:  keywords=['N00024']
    - Army Contracting:  keywords=['W91CRB']
    - AFRL:              keywords=['FA8650']
    - NAVAIR:            keywords=['N00019']
    This performs a substring match on the PIID field and is more reliable
    than the award_ids filter for partial matches.

    Common filter value references:
    - set_aside_type_codes: SBA, SBP, 8A, 8AN, HZC, HZS, SDVOSBS, SDVOSBC,
      WOSB, WOSBSS, EDWOSB, EDWOSBSS, VSA
    - extent_competed_type_codes: A (Full & Open), B, C, D, E, F, G, CDO, NDO
    - contract_pricing_type_codes: J (FFP), Y (T&M), Z (LH), U (CPFF),
      V (CPIF), R (CPAF), L (FP Incentive), M (FP Award Fee)
    """
    codes = _resolve_award_type(award_type)

    if award_type == "contracts":
        fields = list(DEFAULT_CONTRACT_FIELDS)
    elif award_type == "idvs":
        fields = list(DEFAULT_IDV_FIELDS)
    elif award_type == "loans":
        fields = list(DEFAULT_LOAN_FIELDS)
    else:
        fields = list(DEFAULT_CONTRACT_FIELDS)

    # Default sort differs for loans
    if sort is None:
        sort = "Loan Value" if award_type == "loans" else "Award Amount"

    # CRITICAL: sort field MUST be in fields array
    if sort not in fields:
        fields.append(sort)

    filters = _build_filters(
        keywords=keywords,
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        recipient_name=recipient_name,
        award_ids=award_ids,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
        place_of_performance_state=place_of_performance_state,
    )

    payload = {
        "subawards": False,
        "limit": min(limit, 100),
        "page": page,
        "sort": sort,
        "order": order,
        "filters": filters,
        "fields": fields,
    }
    return await _post("/api/v2/search/spending_by_award/", payload)


@mcp.tool()
async def get_award_count(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str] | None = None,
    psc_codes: list[str] | None = None,
    set_aside_type_codes: list[str] | None = None,
    extent_competed_type_codes: list[str] | None = None,
    contract_pricing_type_codes: list[str] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
) -> dict[str, Any]:
    """Count awards matching filters, broken down by award category.

    Returns counts grouped by: contracts, idvs, grants, loans, direct_payments, other.
    Use this for dimensional analysis: how many FFP vs T&M awards, how many
    competed vs sole-source, how many small business set-asides, etc.

    Unlike search_awards, this returns total counts across ALL award categories
    in a single call (not just the one specified in award_type). The award_type
    parameter is ignored here; filters apply to the count query directly.
    """
    filters = _build_filters(
        keywords=keywords,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        funding_agency=funding_agency,
        recipient_name=recipient_name,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        extent_competed_type_codes=extent_competed_type_codes,
        contract_pricing_type_codes=contract_pricing_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
        place_of_performance_state=place_of_performance_state,
    )
    return await _post("/api/v2/search/spending_by_award_count/", {"filters": filters})


@mcp.tool()
async def spending_over_time(
    group: Literal["fiscal_year", "quarter", "month"] = "fiscal_year",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str] | None = None,
    psc_codes: list[str] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
) -> dict[str, Any]:
    """Aggregate spending amounts over time, grouped by fiscal year, quarter, or month.

    Use this to visualize spending trends, identify fiscal-year-end spikes,
    or compare spending patterns across years.

    Note: The API returns fiscal_year as a STRING. Cast to int for numeric
    comparisons.
    """
    award_type_codes = _resolve_award_type(award_type) if award_type else None
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        recipient_name=recipient_name,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
    )
    return await _post(
        "/api/v2/search/spending_over_time/",
        {"group": group, "filters": filters},
    )


@mcp.tool()
async def spending_by_category(
    category: Literal[
        "awarding_agency", "awarding_subagency", "funding_agency", "funding_subagency",
        "recipient", "cfda", "naics", "psc", "country", "county", "district",
        "state_territory", "federal_account", "defc"
    ],
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    naics_codes: list[str] | None = None,
    psc_codes: list[str] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    set_aside_type_codes: list[str] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    limit: int = 10,
    page: int = 1,
) -> dict[str, Any]:
    """Aggregate spending by a dimension (top vendors, top agencies, top NAICS, etc.).

    The 'category' parameter controls the grouping dimension. Common uses:
    - category='recipient': top vendors for a filter set (vendor landscape analysis)
    - category='awarding_subagency': which contracting offices within an agency
    - category='naics': which work categories got the most spending
    - category='psc': which product/service codes got the most spending
    - category='state_territory': geographic distribution
    - category='cfda': grant assistance listings

    Note: recipient category returns vendor names in ALL CAPS and may contain
    duplicates (subsidiaries, rebrands, re-registrations). For precise market
    share, apply name normalization to the returned 'name' field.
    """
    award_type_codes = _resolve_award_type(award_type) if award_type else None
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        awarding_subagency=awarding_subagency,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
    )
    return await _post(
        f"/api/v2/search/spending_by_category/{category}/",
        {"filters": filters, "limit": limit, "page": page},
    )


# ---------------------------------------------------------------------------
# Detail tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_award_detail(generated_award_id: str) -> dict[str, Any]:
    """Fetch full details for a single award by its generated_internal_id.

    Use the generated_internal_id value returned by search_awards to fetch
    the complete award record. Returns: PIID, full description, total
    obligation, recipient details, parent award info, latest transaction
    contract data (competition, set-aside, pricing type), period of
    performance, place of performance, NAICS hierarchy, PSC hierarchy,
    base and all options value, and sub-award totals.

    Example generated_award_id format: CONT_AWD_N0002424C0085_9700_N0002421D0001_9700
    """
    return await _get(f"/api/v2/awards/{generated_award_id}/")


@mcp.tool()
async def get_transactions(
    generated_award_id: str,
    limit: int = 100,
    page: int = 1,
    sort: str = "action_date",
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Fetch the full transaction (modification) history for an award.

    Every modification, option exercise, and de-obligation is a transaction.
    Modification number '0' is the original base award. Use to understand
    the full lifecycle of a contract including its descriptive text at each
    point in time.

    Returns per transaction: id, type, action_date, action_type,
    modification_number, description, federal_action_obligation.
    """
    return await _post(
        "/api/v2/transactions/",
        {
            "award_id": generated_award_id,
            "limit": min(limit, 5000),
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


@mcp.tool()
async def get_award_funding(
    generated_award_id: str,
    limit: int = 50,
    page: int = 1,
    sort: str = "reporting_fiscal_date",
    order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """Fetch File C funding data for an award: federal account, object class, program activity.

    Shows which Treasury accounts, object classes, and program activities
    funded an award. Useful for appropriations analysis and understanding
    what colors of money paid for what.

    Sort fields: reporting_fiscal_date, account_title,
    transaction_obligated_amount, object_class.
    """
    return await _post(
        "/api/v2/awards/funding/",
        {
            "award_id": generated_award_id,
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


@mcp.tool()
async def get_idv_children(
    generated_idv_id: str,
    child_type: Literal["child_awards", "child_idvs", "grandchild_awards"] = "child_awards",
    limit: int = 50,
    page: int = 1,
    sort: str = "period_of_performance_start_date",
    order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """Fetch child awards (task/delivery orders) under an IDV.

    For a Multiple Award IDV, child_awards returns the task orders or delivery
    orders placed against it. For a parent IDV, child_idvs returns the
    downstream IDV structure. grandchild_awards walks the hierarchy.

    Field name differences from search_awards: children use 'piid' (not
    'Award ID'), 'obligated_amount' (not 'Award Amount'), and
    'generated_unique_award_id' (not 'generated_internal_id').
    """
    return await _post(
        "/api/v2/idvs/awards/",
        {
            "award_id": generated_idv_id,
            "type": child_type,
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


# ---------------------------------------------------------------------------
# Workflow / convenience tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_piid(piid: str, limit: int = 5) -> dict[str, Any]:
    """Look up awards by PIID or PIID prefix with automatic award-type detection.

    Convenience tool: tries contracts first, then IDVs if no match. Uses
    keyword search under the hood, which behaves as a substring match on
    the PIID field, so you can pass a full PIID or a contracting-office
    prefix (e.g. 'N00024' for NAVSEA, 'W91CRB' for Army Contracting Command,
    'FA8650' for AFRL).

    Returns the matching awards with basic fields. Use get_award_detail()
    with the returned generated_internal_id for the full record.

    Handy for enriching PRISM, Contract Court, or FPDS exports where you
    have a PIID but don't know whether it's a contract or IDV.
    """
    # Try contracts first via keyword search (more reliable than award_ids filter)
    contracts_result = await _post(
        "/api/v2/search/spending_by_award/",
        {
            "subawards": False,
            "limit": min(limit, 100),
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
            "filters": {
                "keywords": [piid],
                "award_type_codes": AWARD_TYPE_GROUPS["contracts"],
            },
            "fields": [
                "Award ID", "Recipient Name", "Description",
                "Award Amount", "Start Date", "End Date",
                "Awarding Agency", "Awarding Sub Agency",
                "generated_internal_id",
            ],
        },
    )
    if contracts_result.get("results"):
        return {"award_type": "contract", **contracts_result}

    # Fall back to IDVs
    idvs_result = await _post(
        "/api/v2/search/spending_by_award/",
        {
            "subawards": False,
            "limit": min(limit, 100),
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
            "filters": {
                "keywords": [piid],
                "award_type_codes": AWARD_TYPE_GROUPS["idvs"],
            },
            "fields": [
                "Award ID", "Recipient Name", "Description",
                "Award Amount", "Start Date", "Last Date to Order",
                "Awarding Agency", "Awarding Sub Agency",
                "generated_internal_id",
            ],
        },
    )
    if idvs_result.get("results"):
        return {"award_type": "idv", **idvs_result}

    return {
        "award_type": None,
        "results": [],
        "message": (
            f"No contracts or IDVs found matching '{piid}'. "
            "Try grants/loans/direct_payments via search_awards with the "
            "appropriate award_type parameter, or widen the time_period range."
        ),
    }


# ---------------------------------------------------------------------------
# Autocomplete tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def autocomplete_psc(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete lookup for Product/Service Codes (PSC).

    Works best with code prefixes ('R499', 'D3', 'AJ') or single keywords
    ('professional', 'application'). Returns matching PSC entries with
    code and description.
    """
    return await _post(
        "/api/v2/autocomplete/psc/",
        {"search_text": search_text, "limit": limit},
    )


@mcp.tool()
async def autocomplete_naics(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete lookup for NAICS codes.

    Accepts partial codes ('541') or keywords ('software'). Returns matching
    NAICS entries with code and description.
    """
    return await _post(
        "/api/v2/autocomplete/naics/",
        {"search_text": search_text, "limit": limit},
    )


# ---------------------------------------------------------------------------
# Reference tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_toptier_agencies() -> dict[str, Any]:
    """List all top-tier federal agencies tracked by USASpending.

    Returns agency codes, names, abbreviations, and current-year budgetary
    resources. Use the returned 'toptier_code' values with get_agency_overview().
    """
    return await _get("/api/v2/references/toptier_agencies/")


@mcp.tool()
async def get_agency_overview(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get summary information for a specific agency in a given fiscal year.

    toptier_code is the 3- or 4-digit agency code (e.g. '097' for DoD,
    '075' for HHS, '080' for NASA). Get valid codes via list_toptier_agencies().
    """
    if not toptier_code or not toptier_code.strip().isdigit():
        raise ValueError(
            f"toptier_code must be a numeric agency code (e.g. '097'). "
            f"Got {toptier_code!r}. Use list_toptier_agencies() to find valid codes."
        )
    params = {}
    if fiscal_year is not None:
        params["fiscal_year"] = str(fiscal_year)
    return await _get(f"/api/v2/agency/{toptier_code.strip()}/", params=params)


@mcp.tool()
async def get_agency_awards(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get award summary totals for an agency in a given fiscal year.

    Returns obligation totals by award category.
    """
    if not toptier_code or not toptier_code.strip().isdigit():
        raise ValueError(
            f"toptier_code must be a numeric agency code (e.g. '097'). "
            f"Got {toptier_code!r}."
        )
    params = {}
    if fiscal_year is not None:
        params["fiscal_year"] = str(fiscal_year)
    return await _get(f"/api/v2/agency/{toptier_code.strip()}/awards/", params=params)


@mcp.tool()
async def get_naics_details(code: str) -> dict[str, Any]:
    """Get details for a NAICS code (2-6 digits).

    Returns the NAICS description, parent categories, and child subcategories
    if applicable.
    """
    if not code or not code.strip().isdigit():
        raise ValueError(
            f"NAICS code must be numeric (2, 4, or 6 digits). Got {code!r}."
        )
    return await _get(f"/api/v2/references/naics/{code.strip()}/")


@mcp.tool()
async def get_psc_filter_tree(
    path: str = "",
) -> dict[str, Any]:
    """Get the PSC hierarchy tree.

    Pass an empty path for the top-level. Drill down with paths like
    'Service/R/' to get the service professional services tree, or
    'Product/5' for product codes starting with 5.
    """
    endpoint = "/api/v2/references/filter_tree/psc/"
    if path:
        endpoint = f"{endpoint}{path.lstrip('/')}"
    return await _get(endpoint)


@mcp.tool()
async def get_state_profile(state_fips: str) -> dict[str, Any]:
    """Get spending profile for a US state by its 2-digit FIPS code.

    Examples: '06' = California, '48' = Texas, '24' = Maryland, '51' = Virginia.
    Returns award totals, top agencies, top recipients, and district data.
    """
    if not state_fips or not state_fips.strip().isdigit() or len(state_fips.strip()) != 2:
        raise ValueError(
            f"state_fips must be a 2-digit numeric FIPS code (e.g., '06' for CA, '51' for VA). "
            f"Got {state_fips!r}."
        )
    return await _get(f"/api/v2/recipient/state/{state_fips.strip()}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
