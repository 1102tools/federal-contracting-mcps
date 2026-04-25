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

import re
from datetime import date
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


_HTML_ERROR_RE = re.compile(r"<!doctype html>.*?</html>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML bodies from upstream error responses for clean messages."""
    if "<!doctype html>" in text.lower() or "<html" in text.lower():
        # Try to extract a <title> or <h1> for context
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
        pieces = []
        if title_match:
            pieces.append(title_match.group(1).strip())
        if h1_match and (not title_match or h1_match.group(1).strip() != title_match.group(1).strip()):
            pieces.append(h1_match.group(1).strip())
        return " - ".join(pieces) if pieces else "upstream returned HTML error page"
    return text[:500]


def _format_http_error(e: httpx.HTTPStatusError) -> str:
    """Translate common USASpending API errors into actionable messages."""
    status = e.response.status_code
    try:
        body = e.response.json()
        detail = body.get("detail") or body.get("messages") or body
    except Exception:
        detail = _clean_error_body(e.response.text)

    detail_str = str(detail)
    # Also clean detail_str if it somehow contains HTML
    if "<!doctype html>" in detail_str.lower() or "<html" in detail_str.lower():
        detail = _clean_error_body(detail_str)
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


def _ensure_dict_response(data: Any, *, path: str) -> dict[str, Any]:
    """Guarantee a dict return type. USASpending always responds with a
    JSON object for every endpoint this MCP uses; anything else is a
    transport/infrastructure problem that should surface clearly rather
    than leak a None / list / int into the tool output.
    """
    if isinstance(data, dict):
        return data
    if data is None:
        raise RuntimeError(
            f"USASpending returned an empty body at {path!r}. This usually "
            f"means a CDN / proxy issue rather than a real empty result; "
            f"retry in a few seconds."
        )
    raise RuntimeError(
        f"USASpending returned an unexpected {type(data).__name__} at "
        f"{path!r} (expected JSON object). First 200 chars: {str(data)[:200]!r}"
    )


async def _post(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """POST helper with actionable error translation."""
    try:
        r = await _get_client().post(path, json=json)
        r.raise_for_status()
        return _ensure_dict_response(r.json(), path=path)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET helper with actionable error translation."""
    try:
        r = await _get_client().get(path, params=params or {})
        r.raise_for_status()
        return _ensure_dict_response(r.json(), path=path)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EARLIEST_SEARCH_DATE = "2007-10-01"


def _validate_date(value: str, field_name: str) -> str:
    """Validate YYYY-MM-DD format and parseability."""
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format (e.g. '2026-01-15'). "
            f"Got {value!r}. ISO 8601 datetimes with timezones or 'YYYY/MM/DD' are rejected."
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _current_fiscal_year() -> int:
    """Federal fiscal year (Oct-Sep). FY2026 runs 2025-10-01 to 2026-09-30."""
    today = date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _clamp_limit(limit: int, *, cap: int, field: str = "limit") -> int:
    """Clamp a limit to valid bounds, raising on nonsense values."""
    if limit < 1:
        raise ValueError(f"{field} must be >= 1. Got {limit}.")
    if limit > cap:
        raise ValueError(
            f"{field} exceeds maximum of {cap}. Got {limit}. "
            f"Paginate with the 'page' parameter instead."
        )
    return limit


def _coerce_code_list(codes: list[Any] | None, field: str) -> list[str] | None:
    """Coerce a list of codes (int or str) to strings. Rejects empty arrays
    AND arrays where every entry is empty / whitespace-only."""
    if codes is None:
        return None
    if len(codes) == 0:
        raise ValueError(
            f"{field} was passed as an empty array. Omit the parameter instead of passing []."
        )
    cleaned = [str(c).strip() for c in codes if str(c).strip()]
    if not cleaned:
        raise ValueError(
            f"{field}={codes!r} contains only empty / whitespace strings. "
            f"Pass non-empty codes or omit the parameter."
        )
    return cleaned


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")


def _validate_no_control_chars(value: str | None, *, field: str) -> str | None:
    """Reject null bytes, newlines, tabs, and other control characters.

    USASpending's API either 500s on these (autocomplete, transactions) or
    silently accepts them (keyword search), which makes tool results confusing.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if _CONTROL_CHARS_RE.search(value):
        raise ValueError(
            f"{field}={value!r} contains control characters (null byte, newline, "
            f"tab, etc). Remove them and retry."
        )
    return value


def _validate_strings_no_control_chars(values: list[str] | None, *, field: str) -> None:
    """Apply _validate_no_control_chars to each entry in a list."""
    if values is None:
        return
    for i, v in enumerate(values):
        _validate_no_control_chars(v, field=f"{field}[{i}]")


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
    award_ids: list[str | int] | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    def_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Build a USASpending filters object from flattened parameters."""
    filters: dict[str, Any] = {}

    if keywords is not None:
        if len(keywords) == 0:
            raise ValueError(
                "keywords was passed as an empty array. "
                "Omit the parameter instead of passing []."
            )
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
    coerced_award_ids = _coerce_code_list(award_ids, "award_ids")
    if coerced_award_ids:
        filters["award_ids"] = coerced_award_ids
    coerced_naics = _coerce_code_list(naics_codes, "naics_codes")
    if coerced_naics:
        filters["naics_codes"] = coerced_naics
    coerced_psc = _coerce_code_list(psc_codes, "psc_codes")
    if coerced_psc:
        filters["psc_codes"] = coerced_psc
    coerced_set_aside = _coerce_code_list(set_aside_type_codes, "set_aside_type_codes")
    if coerced_set_aside:
        filters["set_aside_type_codes"] = coerced_set_aside
    coerced_extent = _coerce_code_list(extent_competed_type_codes, "extent_competed_type_codes")
    if coerced_extent:
        filters["extent_competed_type_codes"] = coerced_extent
    coerced_pricing = _coerce_code_list(contract_pricing_type_codes, "contract_pricing_type_codes")
    if coerced_pricing:
        filters["contract_pricing_type_codes"] = coerced_pricing
    if time_period_start or time_period_end:
        start = _validate_date(time_period_start, "time_period_start") if time_period_start else _EARLIEST_SEARCH_DATE
        end = _validate_date(time_period_end, "time_period_end") if time_period_end else "2099-09-30"
        if start > end:
            raise ValueError(
                f"time_period_start ({start}) is after time_period_end ({end}). "
                f"Reverse the values or omit one."
            )
        filters["time_period"] = [{"start_date": start, "end_date": end}]
    if award_amount_min is not None or award_amount_max is not None:
        if (
            award_amount_min is not None
            and award_amount_max is not None
            and award_amount_min > award_amount_max
        ):
            raise ValueError(
                f"award_amount_min ({award_amount_min}) is greater than "
                f"award_amount_max ({award_amount_max}). Reverse the values."
            )
        bounds: dict[str, float] = {}
        if award_amount_min is not None:
            bounds["lower_bound"] = award_amount_min
        if award_amount_max is not None:
            bounds["upper_bound"] = award_amount_max
        filters["award_amounts"] = [bounds]
    if place_of_performance_state:
        state = place_of_performance_state.strip().upper()
        if not re.match(r"^[A-Z]{2}$", state):
            raise ValueError(
                f"place_of_performance_state must be a 2-letter USPS code (e.g. 'MD'). "
                f"Got {place_of_performance_state!r}."
            )
        filters["place_of_performance_locations"] = [{
            "country": "USA",
            "state": state,
        }]
    coerced_def = _coerce_code_list(def_codes, "def_codes")
    if coerced_def:
        filters["def_codes"] = coerced_def

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

@mcp.tool(annotations={"title": "Search Awards", "readOnlyHint": True, "destructiveHint": False})
async def search_awards(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    place_of_performance_state: str | None = None,
    award_ids: list[str | int] | None = None,
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

    IMPORTANT: awarding_agency/funding_agency must be the FULL NAME, not a slug.
    Use 'Department of the Navy', NOT 'department-of-the-navy'. Slugs silently
    return zero results. Use list_toptier_agencies() to find exact names.
    """
    codes = _resolve_award_type(award_type)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")

    # Reject control characters in free-text inputs. USASpending either
    # 500s on these or silently treats them as whitespace, both bad UX.
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(awarding_subagency, field="awarding_subagency")
    _validate_no_control_chars(funding_agency, field="funding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
    # Negative amounts silently return default results as if no filter.
    if award_amount_min is not None and award_amount_min < 0:
        raise ValueError(
            f"award_amount_min must be >= 0. Got {award_amount_min}. "
            f"Negative minimums are silently ignored by USASpending and "
            f"return unfiltered results."
        )
    if award_amount_max is not None and award_amount_max < 0:
        raise ValueError(
            f"award_amount_max must be >= 0. Got {award_amount_max}."
        )

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
    # award_type_codes is always present because we always set it, but it's
    # a scope not a filter. Require at least one real filter so that empty
    # calls don't silently return unfiltered recent awards.
    real_filter_keys = [k for k in filters if k != "award_type_codes"]
    if not real_filter_keys:
        raise ValueError(
            "search_awards requires at least one filter beyond award_type. "
            "Typical: keywords + time_period_start/end, or recipient_name, "
            "or awarding_agency, or naics_codes, or psc_codes. Calling "
            "without filters silently returns recent awards and is usually "
            "a typo in parameter names."
        )

    payload = {
        "subawards": False,
        "limit": limit,
        "page": page,
        "sort": sort,
        "order": order,
        "filters": filters,
        "fields": fields,
    }
    return await _post("/api/v2/search/spending_by_award/", payload)


@mcp.tool(annotations={"title": "Get Award Count", "readOnlyHint": True, "destructiveHint": False})
async def get_award_count(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    funding_agency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    extent_competed_type_codes: list[str | int] | None = None,
    contract_pricing_type_codes: list[str | int] | None = None,
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

    At least one filter is required (the API rejects empty filter sets with HTTP 400).
    Typical usage: pass time_period_start + time_period_end, or a keywords/agency filter.
    """
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
    if award_amount_min is not None and award_amount_min < 0:
        raise ValueError(f"award_amount_min must be >= 0. Got {award_amount_min}.")
    if award_amount_max is not None and award_amount_max < 0:
        raise ValueError(f"award_amount_max must be >= 0. Got {award_amount_max}.")

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
    if not filters:
        raise ValueError(
            "get_award_count requires at least one filter. "
            "Typical: time_period_start + time_period_end, or keywords, or awarding_agency."
        )
    return await _post("/api/v2/search/spending_by_award_count/", {"filters": filters})


@mcp.tool(annotations={"title": "Spending Over Time", "readOnlyHint": True, "destructiveHint": False})
async def spending_over_time(
    group: Literal["fiscal_year", "quarter", "month"] = "fiscal_year",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    recipient_name: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
) -> dict[str, Any]:
    """Aggregate spending amounts over time, grouped by fiscal year, quarter, or month.

    Use this to visualize spending trends, identify fiscal-year-end spikes,
    or compare spending patterns across years.

    Note: The API returns fiscal_year as a STRING. Cast to int for numeric
    comparisons.

    At least one filter is required (the API rejects empty filter sets with HTTP 400).
    Typical usage: pass time_period_start + time_period_end.
    """
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
    _validate_no_control_chars(recipient_name, field="recipient_name")
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
    # award_type_codes alone (without other filters) is not enough — the API
    # treats award_type_codes as a scope, not a filter, and still 400s.
    has_real_filter = any(k for k in filters if k != "award_type_codes")
    if not has_real_filter:
        raise ValueError(
            "spending_over_time requires at least one filter beyond award_type. "
            "Typical: time_period_start + time_period_end, or keywords, or awarding_agency."
        )
    return await _post(
        "/api/v2/search/spending_over_time/",
        {"group": group, "filters": filters},
    )


@mcp.tool(annotations={"title": "Spending by Category", "readOnlyHint": True, "destructiveHint": False})
async def spending_by_category(
    category: Literal[
        "awarding_agency", "awarding_subagency", "funding_agency", "funding_subagency",
        "recipient", "cfda", "naics", "psc", "country", "county", "district",
        "state_territory", "federal_account", "defc"
    ],
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    awarding_subagency: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
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
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    _validate_strings_no_control_chars(keywords, field="keywords")
    _validate_no_control_chars(awarding_agency, field="awarding_agency")
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

@mcp.tool(annotations={"title": "Get Award Detail", "readOnlyHint": True, "destructiveHint": False})
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
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError(
            "generated_award_id cannot be empty. Pass the generated_internal_id "
            "field from search_awards results (e.g. CONT_AWD_...)."
        )
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    return await _get(f"/api/v2/awards/{generated_award_id.strip()}/")


@mcp.tool(annotations={"title": "Get Transactions", "readOnlyHint": True, "destructiveHint": False})
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
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError("generated_award_id cannot be empty.")
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    limit = _clamp_limit(limit, cap=5000)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    return await _post(
        "/api/v2/transactions/",
        {
            "award_id": generated_award_id.strip(),
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


@mcp.tool(annotations={"title": "Get Award Funding", "readOnlyHint": True, "destructiveHint": False})
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
    limit = _clamp_limit(limit, cap=100)
    if not isinstance(generated_award_id, str) or not generated_award_id.strip():
        raise ValueError("generated_award_id cannot be empty.")
    _validate_no_control_chars(generated_award_id, field="generated_award_id")
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    return await _post(
        "/api/v2/awards/funding/",
        {
            "award_id": generated_award_id.strip(),
            "limit": limit,
            "page": page,
            "sort": sort,
            "order": order,
        },
    )


@mcp.tool(annotations={"title": "Get IDV Children", "readOnlyHint": True, "destructiveHint": False})
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
    if not isinstance(generated_idv_id, str) or not generated_idv_id.strip():
        raise ValueError("generated_idv_id cannot be empty.")
    _validate_no_control_chars(generated_idv_id, field="generated_idv_id")
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    return await _post(
        "/api/v2/idvs/awards/",
        {
            "award_id": generated_idv_id.strip(),
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

@mcp.tool(annotations={"title": "Lookup PIID", "readOnlyHint": True, "destructiveHint": False})
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
    piid = (piid or "").strip()
    if len(piid) < 3:
        raise ValueError(
            f"piid must be at least 3 characters (USASpending keyword search minimum). "
            f"Got {piid!r}."
        )
    limit = _clamp_limit(limit, cap=100)
    # Try contracts first via keyword search (more reliable than award_ids filter)
    contracts_result = await _post(
        "/api/v2/search/spending_by_award/",
        {
            "subawards": False,
            "limit": limit,
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
            "limit": limit,
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

@mcp.tool(annotations={"title": "Autocomplete PSC", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_psc(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete lookup for Product/Service Codes (PSC).

    Works best with code prefixes ('R499', 'D3', 'AJ') or keywords
    ('professional', 'application'). Returns matching PSC entries with
    code and description.

    Minimum 2 characters required. Single-character queries return first-N
    alphabetical results from the upstream API (useless for matching) and
    empty strings return HTTP 400.
    """
    _validate_no_control_chars(search_text, field="search_text")
    search_text = (search_text or "").strip()
    if len(search_text) < 2:
        return {
            "results": [],
            "_note": "autocomplete_psc requires at least 2 characters; upstream API returns arbitrary first-N results otherwise.",
        }
    if len(search_text) > 200:
        raise ValueError(
            f"search_text exceeds 200 chars (got {len(search_text)}). "
            f"Autocomplete is intended for prefix / keyword lookups."
        )
    limit = _clamp_limit(limit, cap=100)
    return await _post(
        "/api/v2/autocomplete/psc/",
        {"search_text": search_text, "limit": limit},
    )


@mcp.tool(annotations={"title": "Autocomplete NAICS", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_naics(
    search_text: str,
    limit: int = 10,
    exclude_retired: bool = True,
) -> dict[str, Any]:
    """Autocomplete lookup for NAICS codes.

    Accepts partial codes ('541') or keywords ('software'). Returns matching
    NAICS entries with code and description.

    Minimum 2 characters required. Short queries silently match substrings
    inside parenthetical notes (e.g. 'x' matches 'except') and produce
    nonsense results, so we require 2+ chars.

    exclude_retired defaults to True. The upstream NAICS taxonomy still
    returns codes retired in 2012/2017/2022; these are almost never what
    callers want. Set exclude_retired=False to include them.
    """
    _validate_no_control_chars(search_text, field="search_text")
    search_text = (search_text or "").strip()
    if len(search_text) < 2:
        return {
            "results": [],
            "_note": "autocomplete_naics requires at least 2 characters; upstream substring-matches into parenthetical notes otherwise.",
        }
    if len(search_text) > 200:
        raise ValueError(
            f"search_text exceeds 200 chars (got {len(search_text)})."
        )
    limit = _clamp_limit(limit, cap=100)
    # Request more from upstream so the client-side retired filter still yields
    # enough results. Cap at 50 to avoid runaway.
    upstream_limit = min(limit * 3, 50) if exclude_retired else limit
    response = await _post(
        "/api/v2/autocomplete/naics/",
        {"search_text": search_text, "limit": upstream_limit},
    )
    if exclude_retired:
        results = response.get("results") or []
        active = [r for r in results if r.get("year_retired") is None][:limit]
        response["results"] = active
        response["_note"] = (
            f"Filtered {len(results) - len(active)} retired codes. "
            "Pass exclude_retired=False to include them."
        )
    return response


# ---------------------------------------------------------------------------
# Reference tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "List Toptier Agencies", "readOnlyHint": True, "destructiveHint": False})
async def list_toptier_agencies() -> dict[str, Any]:
    """List all top-tier federal agencies tracked by USASpending.

    Returns agency codes, names, abbreviations, and current-year budgetary
    resources. Use the returned 'toptier_code' values with get_agency_overview().
    """
    return await _get("/api/v2/references/toptier_agencies/")


def _normalize_toptier(toptier_code: str) -> str:
    """Normalize a toptier_code: strip, validate numeric, left-pad to 3 digits."""
    if toptier_code is None:
        raise ValueError("toptier_code is required.")
    code = str(toptier_code).strip()
    if not code or not code.isdigit():
        raise ValueError(
            f"toptier_code must be a numeric agency code (e.g. '097'). "
            f"Got {toptier_code!r}. Use list_toptier_agencies() to find valid codes."
        )
    # API expects 3- or 4-digit codes; left-pad shorter numeric inputs to 3.
    if len(code) < 3:
        code = code.zfill(3)
    return code


def _validate_fiscal_year(fiscal_year: int) -> int:
    """Reject fiscal years outside the API's accepted window (2008 .. current FY)."""
    current = _current_fiscal_year()
    if fiscal_year < 2008:
        raise ValueError(
            f"fiscal_year must be >= 2008 (USASpending data starts FY2008). Got {fiscal_year}."
        )
    if fiscal_year > current:
        raise ValueError(
            f"fiscal_year must be <= {current} (current FY). Got {fiscal_year}."
        )
    return fiscal_year


@mcp.tool(annotations={"title": "Get Agency Overview", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_overview(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get summary information for a specific agency in a given fiscal year.

    toptier_code is the 3- or 4-digit agency code (e.g. '097' for DoD,
    '075' for HHS, '080' for NASA). Shorter inputs like '97' are left-padded
    to '097' automatically. Get valid codes via list_toptier_agencies().
    """
    code = _normalize_toptier(toptier_code)
    params = {}
    if fiscal_year is not None:
        params["fiscal_year"] = str(_validate_fiscal_year(fiscal_year))
    return await _get(f"/api/v2/agency/{code}/", params=params)


@mcp.tool(annotations={"title": "Get Agency Awards", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_awards(
    toptier_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get award summary totals for an agency in a given fiscal year.

    Returns obligation totals by award category. toptier_code is auto-padded
    to 3 digits if a shorter numeric value is supplied.
    """
    code = _normalize_toptier(toptier_code)
    params = {}
    if fiscal_year is not None:
        params["fiscal_year"] = str(_validate_fiscal_year(fiscal_year))
    return await _get(f"/api/v2/agency/{code}/awards/", params=params)


@mcp.tool(annotations={"title": "Get NAICS Details", "readOnlyHint": True, "destructiveHint": False})
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


@mcp.tool(annotations={"title": "Get PSC Filter Tree", "readOnlyHint": True, "destructiveHint": False})
async def get_psc_filter_tree(
    path: str = "",
) -> dict[str, Any]:
    """Get the PSC hierarchy tree.

    Pass an empty path for the top-level. Drill down with paths like
    'Service/R/' to get the service professional services tree, or
    'Product/5' for product codes starting with 5.
    """
    # P2 bug fix in 0.2.8: USASpending PSC filter tree endpoint requires
    # a trailing slash. Without it, the API returns HTTP 301 redirect.
    # Caught by round 6 live audit.
    endpoint = "/api/v2/references/filter_tree/psc/"
    if path:
        endpoint = f"{endpoint}{path.lstrip('/').rstrip('/')}/"
    return await _get(endpoint)


@mcp.tool(annotations={"title": "Get State Profile", "readOnlyHint": True, "destructiveHint": False})
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


# ===========================================================================
# v0.3 expansion: subawards, recipient depth, agency depth, award depth,
# transaction/geography/timeline search, IDV depth, autocomplete helpers,
# reference data, federal accounts.
# ===========================================================================


# ---------------------------------------------------------------------------
# Subawards (FFATA)
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Subawards", "readOnlyHint": True, "destructiveHint": False})
async def search_subawards(
    award_id: str | None = None,
    sort: Literal["amount", "action_date", "subaward_number", "recipient_name", "description"] = "amount",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search FFATA subaward reports on USASpending.

    Returns the FFATA subaward records (subcontracts under prime contracts and
    subawards under prime grants). Complementary to the SAM.gov FFATA endpoints
    but expressed at the USASpending data model.

    award_id: optional generated_internal_id (CONT_AWD_..., ASST_NON_..., etc.)
    to scope subawards to a single prime award. If omitted, returns subawards
    across all primes for the page.

    Pagination uses page (1-indexed) and limit (1-100).
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload: dict[str, Any] = {
        "sort": sort,
        "order": order,
        "limit": limit,
        "page": page,
    }
    if award_id is not None:
        award_id = _validate_no_control_chars(award_id, field="award_id")
        if not award_id.strip():
            raise ValueError("award_id cannot be empty whitespace; omit instead.")
        payload["award_id"] = award_id.strip()
    return await _post("/api/v2/subawards/", payload)


@mcp.tool(annotations={"title": "Spending by Subaward Grouped", "readOnlyHint": True, "destructiveHint": False})
async def spending_by_subaward_grouped(
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_type_codes: list[str] | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    def_codes: list[str | int] | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search subawards using the standard filters object (grouped result set).

    Unlike search_subawards which is scoped to a single prime, this returns
    subawards grouped under their primes given a filter set similar to
    search_awards. Useful for FFATA-wide analysis ("show me all DoD
    subcontracts on cyber awards in FY2026").
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    filters = _build_filters(
        award_type_codes=award_type_codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        def_codes=def_codes,
    )
    payload: dict[str, Any] = {
        "filters": filters,
        "limit": limit,
        "page": page,
        "order": order,
    }
    if sort:
        payload["sort"] = sort
    return await _post("/api/v2/search/spending_by_subaward_grouped/", payload)


# ---------------------------------------------------------------------------
# Recipient depth
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Search Recipients", "readOnlyHint": True, "destructiveHint": False})
async def search_recipients(
    keyword: str | None = None,
    award_type: Literal["all", "contracts", "grants", "loans", "direct_payments", "other"] = "all",
    sort: Literal["amount", "name", "duns", "uei"] = "amount",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search USASpending recipients (vendors and grantees) by keyword.

    Returns paginated recipients with their UEI, DUNS, name, and a recipient
    'id' that downstream tools use as the hash for get_recipient_profile and
    get_recipient_children.

    keyword can match recipient name, UEI, or DUNS. If omitted, returns the
    top recipients ranked by `sort`.
    """
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    keyword = _validate_no_control_chars(keyword, field="keyword")
    payload: dict[str, Any] = {
        "limit": limit,
        "page": page,
        "order": order,
        "sort": sort,
        "award_type": award_type,
    }
    if keyword and keyword.strip():
        payload["keyword"] = keyword.strip()
    return await _post("/api/v2/recipient/", payload)


_RECIPIENT_HASH_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-[CRP]$")


def _validate_recipient_hash(value: str, *, field: str = "recipient_hash") -> str:
    """USASpending recipient IDs look like '7fe0d08f-685f-...-R' (UUID + -C/-R/-P)."""
    if not value or not value.strip():
        raise ValueError(f"{field} cannot be empty.")
    s = value.strip()
    if not _RECIPIENT_HASH_RE.match(s):
        raise ValueError(
            f"{field}={value!r} is not a valid recipient hash. "
            f"Expected UUID format with -C/-R/-P suffix (e.g. "
            f"'7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-R'). Use search_recipients() "
            f"or autocomplete_recipient() to find the correct hash."
        )
    return s


@mcp.tool(annotations={"title": "Get Recipient Profile", "readOnlyHint": True, "destructiveHint": False})
async def get_recipient_profile(
    recipient_hash: str,
    year: str | None = None,
) -> dict[str, Any]:
    """Get full profile for a recipient by their USASpending hash.

    Returns recipient details: name, UEI, DUNS, business categories, location,
    parent (if any), and lifetime award totals. The hash is the 'id' field
    returned by search_recipients() or autocomplete_recipient().

    year: optional 'all' or a fiscal year like '2026'. Default is 'latest'.
    """
    recipient_hash = _validate_recipient_hash(recipient_hash)
    params = {}
    if year:
        params["year"] = year.strip()
    return await _get(f"/api/v2/recipient/{recipient_hash}/", params=params)


@mcp.tool(annotations={"title": "Get Recipient Children", "readOnlyHint": True, "destructiveHint": False})
async def get_recipient_children(
    recipient_hash: str,
    year: str | None = None,
) -> dict[str, Any]:
    """Get the child recipients (subsidiaries) of a parent recipient hash.

    Pass a recipient hash with -P (parent) suffix to retrieve subsidiary
    recipients. The endpoint returns a list of -C suffixed hashes representing
    children. For -R (regular, no parent) recipients this returns an empty
    list or 4xx.

    Useful for mapping corporate structures (e.g. Lockheed Martin -P -> all
    its subsidiaries -C).
    """
    recipient_hash = _validate_recipient_hash(recipient_hash)
    params = {}
    if year:
        params["year"] = year.strip()
    return await _get(f"/api/v2/recipient/children/{recipient_hash}/", params=params)


@mcp.tool(annotations={"title": "Autocomplete Recipient", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_recipient(
    search_text: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Find recipient hashes by partial name or UEI/DUNS.

    Returns matching recipients with their hash IDs and metadata. Use the hash
    from results in get_recipient_profile() or get_recipient_children().
    """
    limit = _clamp_limit(limit, cap=500)
    search_text = _validate_no_control_chars(search_text, field="search_text") or ""
    if not search_text.strip():
        raise ValueError("search_text cannot be empty.")
    payload = {"search_text": search_text.strip(), "limit": limit}
    return await _post("/api/v2/autocomplete/recipient/", payload)


@mcp.tool(annotations={"title": "List States", "readOnlyHint": True, "destructiveHint": False})
async def list_states() -> dict[str, Any]:
    """List all states with their FIPS codes and award totals.

    Returns the full list of US states/territories with FIPS codes you can
    pass to get_state_profile().

    The /recipient/state/ endpoint returns a JSON array (not an object). We
    wrap it in {"results": [...]} to keep the tool return type consistent
    with every other endpoint in this MCP.
    """
    try:
        r = await _get_client().get("/api/v2/recipient/state/")
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_http_error(e)) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling USASpending: {e}") from e
    if isinstance(data, list):
        return {"results": data, "total": len(data)}
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        f"USASpending /recipient/state/ returned an unexpected "
        f"{type(data).__name__} (expected list or dict)."
    )


# ---------------------------------------------------------------------------
# Agency depth
# ---------------------------------------------------------------------------

def _validate_toptier_code(code: str, *, field: str = "toptier_code") -> str:
    """Toptier agency codes are 3-4 numeric digits (e.g. '097' for DoD)."""
    if not code or not code.strip():
        raise ValueError(f"{field} cannot be empty.")
    s = code.strip()
    if not re.match(r"^\d{3,4}$", s):
        raise ValueError(
            f"{field}={code!r} must be a 3-4 digit numeric toptier agency code "
            f"(e.g. '097' for DoD, '075' for HHS). Use list_toptier_agencies() "
            f"to find the right code."
        )
    return s


def _validate_fy(fy: int | str | None, *, field: str = "fiscal_year") -> str | None:
    if fy is None:
        return None
    try:
        fy_int = int(str(fy).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an int year like 2026. Got {fy!r}.") from exc
    if fy_int < 2017 or fy_int > _current_fiscal_year() + 1:
        raise ValueError(
            f"{field}={fy_int} out of range. USASpending agency profile data "
            f"covers FY2017 through FY{_current_fiscal_year()}."
        )
    return str(fy_int)


@mcp.tool(annotations={"title": "Get Agency Budgetary Resources", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_budgetary_resources(toptier_code: str) -> dict[str, Any]:
    """Get an agency's budgetary resources by fiscal year.

    Returns total budgetary resources, obligations, outlays, and discretionary
    vs mandatory breakdown for each fiscal year on file.
    """
    toptier_code = _validate_toptier_code(toptier_code)
    return await _get(f"/api/v2/agency/{toptier_code}/budgetary_resources/")


@mcp.tool(annotations={"title": "Get Agency Sub-Agencies", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_sub_agencies(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "total_obligations", "total_outlays", "transaction_count", "new_award_count"] = "total_obligations",
) -> dict[str, Any]:
    """List the subordinate (subtier) organizations of a toptier agency.

    Returns each sub-agency with its obligations, outlays, transaction count,
    and new-award count for the given fiscal year. Useful for finding the
    canonical subtier name to pass into search_awards() awarding_subagency.
    """
    toptier_code = _validate_toptier_code(toptier_code)
    fy = _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {"page": str(page), "limit": str(limit), "order": order, "sort": sort}
    if fy:
        params["fiscal_year"] = fy
    return await _get(f"/api/v2/agency/{toptier_code}/sub_agency/", params=params)


@mcp.tool(annotations={"title": "Get Agency Federal Accounts", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_federal_accounts(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the Treasury Account Symbols (federal accounts) used by an agency.

    Returns each federal account with its obligated amount and gross outlay
    for the given fiscal year. Useful for understanding how an agency's
    money flows through Treasury.
    """
    toptier_code = _validate_toptier_code(toptier_code)
    fy = _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {"page": str(page), "limit": str(limit), "order": order, "sort": sort}
    if fy:
        params["fiscal_year"] = fy
    return await _get(f"/api/v2/agency/{toptier_code}/federal_account/", params=params)


@mcp.tool(annotations={"title": "Get Agency Object Classes", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_object_classes(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the object class breakdown (what an agency spends money on).

    Object classes are OMB categories: Personnel Compensation, Travel,
    Contractual Services, Equipment, Grants, etc. Useful for understanding
    what types of expenditures an agency makes.
    """
    toptier_code = _validate_toptier_code(toptier_code)
    fy = _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {"page": str(page), "limit": str(limit), "order": order, "sort": sort}
    if fy:
        params["fiscal_year"] = fy
    return await _get(f"/api/v2/agency/{toptier_code}/object_class/", params=params)


@mcp.tool(annotations={"title": "Get Agency Program Activities", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_program_activities(
    toptier_code: str,
    fiscal_year: int | str | None = None,
    page: int = 1,
    limit: int = 25,
    order: Literal["asc", "desc"] = "desc",
    sort: Literal["name", "obligated_amount", "gross_outlay_amount"] = "obligated_amount",
) -> dict[str, Any]:
    """List the program activities (specific programs) within an agency.

    Program activities are the specific named programs that obligate funds
    (e.g., 'Cybersecurity and Infrastructure Security Agency'). Useful for
    pinpointing which program funds a specific activity.
    """
    toptier_code = _validate_toptier_code(toptier_code)
    fy = _validate_fy(fiscal_year)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    params: dict[str, Any] = {"page": str(page), "limit": str(limit), "order": order, "sort": sort}
    if fy:
        params["fiscal_year"] = fy
    return await _get(f"/api/v2/agency/{toptier_code}/program_activity/", params=params)


@mcp.tool(annotations={"title": "Get Agency Obligations by Award Category", "readOnlyHint": True, "destructiveHint": False})
async def get_agency_obligations_by_award_category(
    toptier_code: str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """Get an agency's obligation breakdown by award category.

    Returns total obligated dollars split by category: contracts, IDVs, grants,
    loans, direct payments, other. Quick way to see what mix of award types
    an agency uses (heavy contractor agency vs grant-issuing agency vs mixed).
    """
    toptier_code = _validate_toptier_code(toptier_code)
    fy = _validate_fy(fiscal_year)
    params: dict[str, Any] = {}
    if fy:
        params["fiscal_year"] = fy
    return await _get(
        f"/api/v2/agency/{toptier_code}/obligations_by_award_category/", params=params,
    )


# ---------------------------------------------------------------------------
# Award depth
# ---------------------------------------------------------------------------

def _validate_generated_award_id(award_id: str, *, field: str = "award_id") -> str:
    """Generated award IDs look like 'CONT_AWD_W912QR25C0022_9700_...' or
    'CONT_IDV_GS00Q14OADU131_4732_...' or 'ASST_NON_FA86502125028_097'.
    """
    if not award_id or not award_id.strip():
        raise ValueError(f"{field} cannot be empty.")
    award_id = _validate_no_control_chars(award_id.strip(), field=field) or ""
    if not award_id.startswith(("CONT_AWD_", "CONT_IDV_", "ASST_NON_", "ASST_AGG_")):
        raise ValueError(
            f"{field}={award_id!r} is not a valid generated award id. "
            f"Expected prefix: CONT_AWD_, CONT_IDV_, ASST_NON_, or ASST_AGG_. "
            f"Find the right id from search_awards() results."
        )
    return award_id


@mcp.tool(annotations={"title": "Get Award Funding Rollup", "readOnlyHint": True, "destructiveHint": False})
async def get_award_funding_rollup(award_id: str) -> dict[str, Any]:
    """Get a rollup of an award's funding totals.

    Returns total transaction obligated amount, awarding agency count,
    funding agency count, and federal account count for a single award.
    Useful for a one-line summary of an award's funding picture.
    """
    award_id = _validate_generated_award_id(award_id)
    return await _post("/api/v2/awards/funding_rollup/", {"award_id": award_id})


@mcp.tool(annotations={"title": "Get Award Subaward Count", "readOnlyHint": True, "destructiveHint": False})
async def get_award_subaward_count(award_id: str) -> dict[str, Any]:
    """Count of subawards (FFATA subcontracts/subawards) reported on an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/subaward/{award_id}/")


@mcp.tool(annotations={"title": "Get Award Federal Account Count", "readOnlyHint": True, "destructiveHint": False})
async def get_award_federal_account_count(award_id: str) -> dict[str, Any]:
    """Count of distinct federal accounts (TAS) funding an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/federal_account/{award_id}/")


@mcp.tool(annotations={"title": "Get Award Transaction Count", "readOnlyHint": True, "destructiveHint": False})
async def get_award_transaction_count(award_id: str) -> dict[str, Any]:
    """Count of transactions (modifications) on an award."""
    award_id = _validate_generated_award_id(award_id)
    return await _get(f"/api/v2/awards/count/transaction/{award_id}/")


@mcp.tool(annotations={"title": "Awards Last Updated", "readOnlyHint": True, "destructiveHint": False})
async def awards_last_updated() -> dict[str, Any]:
    """Get the timestamp of the last USASpending award data refresh.

    Use this to determine data freshness when comparing to other sources
    (SAM.gov Contract Awards API for example).
    """
    return await _get("/api/v2/awards/last_updated/")


# ---------------------------------------------------------------------------
# Search depth (transactions, geography, timeline)
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Spending by Transaction", "readOnlyHint": True, "destructiveHint": False})
async def spending_by_transaction(
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other"] = "contracts",
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    recipient_uei: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
    set_aside_type_codes: list[str | int] | None = None,
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    award_amount_min: float | None = None,
    award_amount_max: float | None = None,
    sort: str = "Action Date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """Search at the transaction (modification) level.

    Unlike search_awards which returns one row per award, this returns one
    row per transaction (initial action plus every modification). Useful for
    tracking obligation events over time, ceiling adjustments, deobligations,
    and admin mods.

    Returns standard transaction fields: Action Date, Mod, Award ID,
    Action Type, Awarding Agency, Recipient Name.
    """
    codes = _resolve_award_type(award_type)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    filters = _build_filters(
        keywords=keywords,
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        recipient_uei=recipient_uei,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        set_aside_type_codes=set_aside_type_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
        award_amount_min=award_amount_min,
        award_amount_max=award_amount_max,
    )
    fields = [
        "Action Date", "Mod", "Award ID", "Action Type",
        "Awarding Agency", "Recipient Name", "Transaction Amount",
        "Transaction Description", "internal_id", "generated_internal_id",
    ]
    payload = {
        "filters": filters, "fields": fields,
        "sort": sort, "order": order, "limit": limit, "page": page,
    }
    return await _post("/api/v2/search/spending_by_transaction/", payload)


@mcp.tool(annotations={"title": "Spending by Geography", "readOnlyHint": True, "destructiveHint": False})
async def spending_by_geography(
    scope: Literal["recipient_location", "place_of_performance"] = "place_of_performance",
    geo_layer: Literal["state", "county", "district"] = "state",
    award_type: Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other", "all"] = "all",
    time_period_start: str | None = None,
    time_period_end: str | None = None,
    awarding_agency: str | None = None,
    funding_agency: str | None = None,
    naics_codes: list[str | int] | None = None,
    psc_codes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Geographic breakdown of spending.

    scope: 'recipient_location' (where the recipient is) or 'place_of_performance'
    (where the work happens).
    geo_layer: 'state', 'county', or 'district'.
    """
    codes = None if award_type == "all" else _resolve_award_type(award_type)
    filters = _build_filters(
        award_type_codes=codes,
        awarding_agency=awarding_agency,
        funding_agency=funding_agency,
        naics_codes=naics_codes,
        psc_codes=psc_codes,
        time_period_start=time_period_start,
        time_period_end=time_period_end,
    )
    payload = {"filters": filters, "scope": scope, "geo_layer": geo_layer}
    return await _post("/api/v2/search/spending_by_geography/", payload)


@mcp.tool(annotations={"title": "New Awards Over Time", "readOnlyHint": True, "destructiveHint": False})
async def new_awards_over_time(
    recipient_id: str,
    group: Literal["fiscal_year", "quarter", "month"] = "month",
    time_period_start: str | None = None,
    time_period_end: str | None = None,
) -> dict[str, Any]:
    """Pipeline trend of new awards to a recipient over time.

    REQUIRES recipient_id (the recipient hash with -P suffix for parent-level
    rollup, or -R for a single recipient). Returns counts of new awards
    grouped by month, quarter, or fiscal year.

    The endpoint will reject calls without recipient_id with HTTP 422.
    """
    recipient_id = _validate_recipient_hash(recipient_id, field="recipient_id")
    filters: dict[str, Any] = {"recipient_id": recipient_id}
    if time_period_start or time_period_end:
        start = _validate_date(time_period_start, "time_period_start") if time_period_start else _EARLIEST_SEARCH_DATE
        end = _validate_date(time_period_end, "time_period_end") if time_period_end else "2099-09-30"
        filters["time_period"] = [{"start_date": start, "end_date": end}]
    payload = {"group": group, "filters": filters}
    return await _post("/api/v2/search/new_awards_over_time/", payload)


# ---------------------------------------------------------------------------
# IDV depth
# ---------------------------------------------------------------------------

def _validate_idv_award_id(award_id: str, *, field: str = "award_id") -> str:
    """IDV-specific endpoints require CONT_IDV_ prefix."""
    award_id = _validate_generated_award_id(award_id, field=field)
    if not award_id.startswith("CONT_IDV_"):
        raise ValueError(
            f"{field}={award_id!r} is not an IDV award id (CONT_IDV_*). "
            f"This endpoint is IDV-only. For non-IDV contracts use the awards "
            f"endpoints instead."
        )
    return award_id


@mcp.tool(annotations={"title": "Get IDV Amounts", "readOnlyHint": True, "destructiveHint": False})
async def get_idv_amounts(award_id: str) -> dict[str, Any]:
    """Top-line amounts for an Indefinite Delivery Vehicle (IDV).

    Returns child IDV count, child award count, child award total obligation,
    and base/option values rolled up across all task/delivery orders under
    the IDV. Pass a CONT_IDV_* generated_internal_id.
    """
    award_id = _validate_idv_award_id(award_id)
    return await _get(f"/api/v2/idvs/amounts/{award_id}/")


@mcp.tool(annotations={"title": "Get IDV Funding", "readOnlyHint": True, "destructiveHint": False})
async def get_idv_funding(
    award_id: str,
    sort: Literal["reporting_fiscal_date", "transaction_obligated_amount", "piid"] = "reporting_fiscal_date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """List the funding records (File C) for an IDV's child orders."""
    award_id = _validate_idv_award_id(award_id)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload = {
        "award_id": award_id, "sort": sort, "order": order,
        "limit": limit, "page": page,
    }
    return await _post("/api/v2/idvs/funding/", payload)


@mcp.tool(annotations={"title": "Get IDV Funding Rollup", "readOnlyHint": True, "destructiveHint": False})
async def get_idv_funding_rollup(award_id: str) -> dict[str, Any]:
    """Funding rollup totals for an IDV (single dict, not paginated)."""
    award_id = _validate_idv_award_id(award_id)
    return await _post("/api/v2/idvs/funding_rollup/", {"award_id": award_id})


@mcp.tool(annotations={"title": "Get IDV Activity", "readOnlyHint": True, "destructiveHint": False})
async def get_idv_activity(
    award_id: str,
    sort: Literal["period_of_performance_start_date", "obligated_amount"] = "period_of_performance_start_date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    page: int = 1,
) -> dict[str, Any]:
    """List child task/delivery orders awarded under an IDV."""
    award_id = _validate_idv_award_id(award_id)
    limit = _clamp_limit(limit, cap=100)
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    payload = {
        "award_id": award_id, "sort": sort, "order": order,
        "limit": limit, "page": page,
    }
    return await _post("/api/v2/idvs/activity/", payload)


# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------

def _autocomplete_payload(search_text: str, limit: int) -> dict[str, Any]:
    search_text = _validate_no_control_chars(search_text, field="search_text") or ""
    if not search_text.strip():
        raise ValueError("search_text cannot be empty.")
    return {"search_text": search_text.strip(), "limit": _clamp_limit(limit, cap=500)}


@mcp.tool(annotations={"title": "Autocomplete Awarding Agency", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_awarding_agency(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find awarding agency names by partial match.

    USASpending search filters require the EXACT awarding agency name
    (slugs return zero). Use this to resolve a partial name to the canonical
    one before passing to search_awards() awarding_agency parameter.
    """
    return await _post("/api/v2/autocomplete/awarding_agency/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete Funding Agency", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_funding_agency(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find funding agency names by partial match (companion to awarding agency)."""
    return await _post("/api/v2/autocomplete/funding_agency/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete CFDA", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_cfda(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find CFDA (Catalog of Federal Domestic Assistance) program numbers
    by partial title or program number. CFDA codes are used in grants."""
    return await _post("/api/v2/autocomplete/cfda/", _autocomplete_payload(search_text, limit))


@mcp.tool(annotations={"title": "Autocomplete Glossary", "readOnlyHint": True, "destructiveHint": False})
async def autocomplete_glossary(search_text: str, limit: int = 10) -> dict[str, Any]:
    """Find glossary terms (acquisition + spending vocabulary) by partial match."""
    return await _post("/api/v2/autocomplete/glossary/", _autocomplete_payload(search_text, limit))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Award Types Reference", "readOnlyHint": True, "destructiveHint": False})
async def get_award_types_reference() -> dict[str, Any]:
    """Return the full mapping of award type codes to descriptions.

    Returns the canonical reference: contracts (A=BPA Call, B=Purchase Order,
    C=Delivery Order, D=Definitive Contract), IDVs, grants, loans, etc.
    Authoritative source if you're unsure what a code letter means.
    """
    return await _get("/api/v2/references/award_types/")


@mcp.tool(annotations={"title": "Get DEF Codes Reference", "readOnlyHint": True, "destructiveHint": False})
async def get_def_codes_reference() -> dict[str, Any]:
    """Return all Disaster Emergency Fund (DEFC) codes with public laws.

    DEFCs are used to filter awards funded by specific supplemental
    appropriations (COVID-19, IIJA, IRA, etc.).
    """
    return await _get("/api/v2/references/def_codes/")


@mcp.tool(annotations={"title": "Get Glossary", "readOnlyHint": True, "destructiveHint": False})
async def get_glossary(
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    """Get the full USASpending glossary of acquisition + spending terms."""
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=500)
    return await _get("/api/v2/references/glossary/", params={"page": str(page), "limit": str(limit)})


@mcp.tool(annotations={"title": "Get Submission Periods", "readOnlyHint": True, "destructiveHint": False})
async def get_submission_periods() -> dict[str, Any]:
    """Return the list of agency submission periods (when each agency last
    submitted data for each fiscal period). Useful for understanding which
    quarters of which fiscal years have full data coverage."""
    return await _get("/api/v2/references/submission_periods/")


# ---------------------------------------------------------------------------
# Federal accounts
# ---------------------------------------------------------------------------

_TAS_RE = re.compile(r"^[\w\-]+$")


def _validate_tas(tas: str, *, field: str = "account_code") -> str:
    if not tas or not tas.strip():
        raise ValueError(f"{field} cannot be empty.")
    s = tas.strip()
    if not _TAS_RE.match(s):
        raise ValueError(
            f"{field}={tas!r} contains invalid characters. Treasury account "
            f"symbols look like '097-0100' or similar alphanumeric/hyphen."
        )
    return s


@mcp.tool(annotations={"title": "List Federal Accounts", "readOnlyHint": True, "destructiveHint": False})
async def list_federal_accounts(
    keyword: str | None = None,
    fiscal_year: int | str | None = None,
    sort: dict[str, str] | None = None,
    page: int = 1,
    limit: int = 25,
) -> dict[str, Any]:
    """List Treasury federal accounts (TAS) with budgetary resources.

    keyword filters by account name or AID. fiscal_year defaults to current FY.
    sort is a dict like {'field':'budgetary_resources','direction':'desc'}.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1. Got {page}.")
    limit = _clamp_limit(limit, cap=100)
    keyword = _validate_no_control_chars(keyword, field="keyword")
    fy = _validate_fy(fiscal_year)
    payload: dict[str, Any] = {"page": page, "limit": limit}
    if keyword and keyword.strip():
        payload["keyword"] = keyword.strip()
    if fy:
        payload["filters"] = {"fy": fy}
    if sort:
        payload["sort"] = sort
    return await _post("/api/v2/federal_accounts/", payload)


@mcp.tool(annotations={"title": "Get Federal Account Detail", "readOnlyHint": True, "destructiveHint": False})
async def get_federal_account_detail(account_code: str) -> dict[str, Any]:
    """Get an individual federal account's metadata + budgetary resources."""
    account_code = _validate_tas(account_code)
    return await _get(f"/api/v2/federal_accounts/{account_code}/")


@mcp.tool(annotations={"title": "Get Federal Account Object Classes", "readOnlyHint": True, "destructiveHint": False})
async def get_federal_account_object_classes(account_code: str) -> dict[str, Any]:
    """Get the object class breakdown of obligations for a federal account.

    Note: this endpoint requires POST (not GET like the other federal account
    sub-endpoints). Live audit caught this; the body is empty.
    """
    account_code = _validate_tas(account_code)
    return await _post(f"/api/v2/federal_accounts/{account_code}/object_classes/total/", {})


@mcp.tool(annotations={"title": "Get Federal Account Program Activities", "readOnlyHint": True, "destructiveHint": False})
async def get_federal_account_program_activities(
    account_code: str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """Get the program activities funded under a federal account."""
    account_code = _validate_tas(account_code)
    fy = _validate_fy(fiscal_year)
    params: dict[str, Any] = {}
    if fy:
        params["fiscal_year"] = fy
    return await _get(
        f"/api/v2/federal_accounts/{account_code}/program_activities/", params=params,
    )


@mcp.tool(annotations={"title": "Get Federal Account Fiscal Year Snapshot", "readOnlyHint": True, "destructiveHint": False})
async def get_federal_account_fy_snapshot(
    account_id: int | str,
    fiscal_year: int | str | None = None,
) -> dict[str, Any]:
    """Get a single-fiscal-year snapshot of a federal account's resources.

    Important: this endpoint takes the numeric `account_id` (e.g. 4595), NOT
    the alphanumeric `account_number` (e.g. "027-5183") used by the other
    federal-account endpoints. The list_federal_accounts response includes
    both fields per record. Pass the integer account_id here.
    """
    aid = str(account_id).strip()
    if not aid:
        raise ValueError("account_id cannot be empty.")
    if not aid.lstrip("-").isdigit():
        raise ValueError(
            f"account_id={account_id!r} must be a numeric integer ID (e.g. 4595). "
            f"This endpoint differs from get_federal_account_detail which takes "
            f"the alphanumeric account_number. Pull both fields from "
            f"list_federal_accounts and pass the right one to each tool."
        )
    fy = _validate_fy(fiscal_year)
    if fy:
        return await _get(f"/api/v2/federal_accounts/{aid}/fiscal_year_snapshot/{fy}/")
    return await _get(f"/api/v2/federal_accounts/{aid}/fiscal_year_snapshot/")


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    FastMCP's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_awards(keyword='cyber') (real
    param is `search_text`) would succeed with the typo discarded and
    return unfiltered data. extra='forbid' raises "Extra inputs are not
    permitted" on typos before any HTTP call.
    """
    for tool in mcp._tool_manager.list_tools():
        am = tool.fn_metadata.arg_model
        am.model_config = {**am.model_config, "extra": "forbid"}
        am.model_rebuild(force=True)


_forbid_extra_params_on_all_tools()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
