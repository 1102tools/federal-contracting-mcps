# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""GSA CALC+ MCP server.

Provides access to awarded GSA MAS schedule ceiling rates for labor
categories. No authentication required.

These are NOT-TO-EXCEED hourly rates from GSA MAS contracts, not prices
paid or BLS wages. Use for IGCE development, price reasonableness
determinations, and market research.

Data refreshes nightly from GSA MAS contract price proposal tables.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from typing import Any, Literal, Union

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    EDUCATION_LEVELS,
    MAX_PAGE_SIZE,
    ORDERING_FIELDS,
    USER_AGENT,
    WORKSITE_VALUES,
)

mcp = FastMCP("gsa-calc")


# ---------------------------------------------------------------------------
# Defensive response parsing helpers
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, else empty dict. Tolerates None, list, str."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Return value as a list. XML-to-JSON collapse tolerant."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _safe_bucket_key(b: Any) -> tuple[Any, Any] | None:
    """Extract (key, doc_count) from a bucket item. Returns None if invalid."""
    if not isinstance(b, dict):
        return None
    key = b.get("key")
    count = b.get("doc_count")
    if key is None or count is None:
        return None
    return (key, count)


def _safe_number(value: Any) -> float | int | None:
    """Coerce to a real number, rejecting None, NaN, Inf. Used for stats values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


# ---------------------------------------------------------------------------
# Input validators
# ---------------------------------------------------------------------------

_ASCII_PRINTABLE_SAFE_RE = re.compile(r"^[A-Za-z0-9 \-_,.:/()&#+|*@$]*$")

# WAF triggers for GSA's firewall (observed empirically: quote, SQL, angle brackets,
# path traversal all return 403/503)
_WAF_PATTERNS = [
    (re.compile(r"\.\./"), "path traversal ('../')"),
    (re.compile(r"<[a-z/]", re.IGNORECASE), "HTML angle brackets"),
    (re.compile(r"\b(?:drop|select|union|insert|delete|truncate)\s+(?:table|from)\b",
                re.IGNORECASE), "SQL keywords"),
    (re.compile(r"--\s*$", re.MULTILINE), "SQL comment marker"),
    (re.compile(r"/\*|\*/"), "SQL block comment"),
    (re.compile(r"['`;]"), "single quote, backtick, or semicolon"),
    (re.compile(r"\x00"), "null byte"),
]


def _validate_waf_safe(value: str | None, *, field: str) -> str | None:
    """Reject strings containing characters that trigger GSA's WAF."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    for pattern, description in _WAF_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"{field}={value!r} contains characters that trigger GSA CALC+'s "
                f"web application firewall ({description}). Remove the offending "
                f"characters and try again (empirically: quotes, SQL keywords, "
                f"angle brackets, path traversal, semicolons all trigger 403/503)."
            )
    return value


def _strip_or_none(value: str | None) -> str | None:
    """Strip whitespace; return None if result is empty."""
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    return s or None


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(
            f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead."
        )
    return value


def _validate_ordering(value: str | None) -> str:
    """Validate against ORDERING_FIELDS whitelist. Returns default if None."""
    if value is None:
        return "current_price"
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return "current_price"
    if s not in ORDERING_FIELDS:
        raise ValueError(
            f"ordering={value!r} is not a valid field. "
            f"Valid: {', '.join(ORDERING_FIELDS)}."
        )
    return s


def _validate_sort(value: str) -> str:
    if value is None:
        return "asc"
    s = value.strip().lower() if isinstance(value, str) else str(value).strip().lower()
    if s not in ("asc", "desc"):
        raise ValueError(f"sort must be 'asc' or 'desc'. Got {value!r}.")
    return s


def _validate_education_level(value: str | None) -> str | None:
    """Validate an education level. Supports pipe-delimited OR (e.g. 'BA|MA')."""
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split("|")]
    for p in parts:
        if not p:
            raise ValueError(f"education_level {value!r} has an empty entry between pipes.")
        if p not in EDUCATION_LEVELS:
            valid = ", ".join(sorted(EDUCATION_LEVELS.keys()))
            raise ValueError(
                f"education_level entry {p!r} not valid. Valid codes: {valid}. "
                f"Pipe-delimit for OR (e.g. 'BA|MA')."
            )
    return "|".join(parts)


def _validate_worksite(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else str(value).strip()
    if not s:
        return None
    # Case-normalize to match GSA's expected capitalization
    match = next((v for v in WORKSITE_VALUES if v.lower() == s.lower()), None)
    if match is None:
        raise ValueError(
            f"worksite={value!r} not valid. Valid: {', '.join(sorted(WORKSITE_VALUES))}."
        )
    return match


def _validate_sin(value: Any) -> str | None:
    """SIN codes are alphanumeric (e.g., '54151S', '541330ENG'). No special chars."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not re.match(r"^[A-Za-z0-9]+$", s):
        raise ValueError(
            f"sin={value!r} must be alphanumeric (e.g. '54151S', '541330ENG'). "
            f"No spaces or special characters."
        )
    return s


def _validate_experience_range(emin: int | None, emax: int | None) -> tuple[int | None, int | None]:
    if emin is not None and emin < 0:
        raise ValueError(f"experience_min must be >= 0. Got {emin}.")
    if emax is not None and emax < 0:
        raise ValueError(f"experience_max must be >= 0. Got {emax}.")
    if emin is not None and emax is not None and emin > emax:
        raise ValueError(
            f"experience_min ({emin}) must be <= experience_max ({emax})."
        )
    return emin, emax


def _validate_price_range(pmin: float | None, pmax: float | None) -> tuple[float | None, float | None]:
    if pmin is not None and pmin < 0:
        raise ValueError(f"price_min must be >= 0. Got {pmin}.")
    if pmax is not None and pmax < 0:
        raise ValueError(f"price_max must be >= 0. Got {pmax}.")
    if pmin is not None and pmax is not None and pmin > pmax:
        raise ValueError(
            f"price_min (${pmin}) must be <= price_max (${pmax})."
        )
    return pmin, pmax


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML bodies from upstream error responses for clean messages."""
    if not text:
        return ""
    if not _HTML_ERROR_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    t = _TITLE_RE.search(text)
    if t:
        pieces.append(t.group(1).strip())
    h = _H1_RE.search(text)
    if h and (not t or h.group(1).strip() != t.group(1).strip()):
        pieces.append(h.group(1).strip())
    return " - ".join(pieces) if pieces else "upstream returned HTML error page"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: str) -> str:
    cleaned = _clean_error_body(body)
    if status == 403:
        return (
            "HTTP 403: Forbidden. GSA's web application firewall blocked this request. "
            "This typically happens when the query contains characters that look like "
            "injection attempts (single quotes, angle brackets, path traversal sequences). "
            "Remove special characters from your search terms and try again."
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. Common causes: (1) keyword or query string "
            "is too long; (2) page number is out of valid range; (3) ordering field "
            "name is invalid. Valid ordering: "
            f"{', '.join(ORDERING_FIELDS)}. "
            f"API response: {cleaned}"
        )
    if status == 429:
        return (
            "HTTP 429: Rate limited. GSA CALC+ allows 1,000 requests/hour. "
            "Add delays between batch requests and reduce page_size."
        )
    if status == 503:
        return (
            "HTTP 503: GSA upstream service unavailable. This often happens when "
            "the request URL contains characters that trigger their firewall. "
            "Remove special characters (quotes, angle brackets, SQL keywords) and retry."
        )
    if status == 400:
        return f"HTTP 400: Bad request. Check filter format (field:value) and page_size (max 500). API response: {cleaned}"
    return f"HTTP {status}: {cleaned}"


async def _get(params_str: str) -> dict[str, Any]:
    """GET helper. Builds full URL from query string."""
    url = f"{BASE_URL}?{params_str}"
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            body_preview = _clean_error_body(r.text or "(empty body)")
            raise RuntimeError(
                f"GSA CALC+ returned non-JSON response on 200 OK. "
                f"This often happens during API maintenance or when an HTML "
                f"error page is served without an error status. "
                f"Body: {body_preview}"
            ) from e
        if not isinstance(data, dict):
            raise RuntimeError(
                f"GSA CALC+ response was not a JSON object. "
                f"Got {type(data).__name__}: {str(data)[:200]}"
            )
        return data
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling GSA CALC+: {e}") from e


# ---------------------------------------------------------------------------
# Filter/param helpers
# ---------------------------------------------------------------------------

def _build_filters(
    *,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: str | None = None,
    worksite: str | None = None,
) -> list[str]:
    """Build filter strings for the CALC+ API.

    Values are URL-encoded at the call site of _build_query_string. This helper
    only composes the `field:value` pieces.
    """
    filters: list[str] = []
    if education_level:
        filters.append(f"education_level:{education_level}")
    # Experience: support either both, min-only, or max-only
    if experience_min is not None and experience_max is not None:
        filters.append(f"experience_range:{experience_min},{experience_max}")
    elif experience_min is not None:
        filters.append(f"min_years_experience:{experience_min}")
    elif experience_max is not None:
        filters.append(f"experience_range:0,{experience_max}")
    # Price: support either both, min-only, or max-only
    if price_min is not None and price_max is not None:
        filters.append(f"price_range:{price_min},{price_max}")
    elif price_min is not None:
        # No hardcoded upper bound — use an explicit sentinel that won't truncate real data
        filters.append(f"price_range:{price_min},999999")
    elif price_max is not None:
        filters.append(f"price_range:0,{price_max}")
    if business_size:
        filters.append(f"business_size:{business_size}")
    if security_clearance:
        filters.append(f"security_clearance:{security_clearance}")
    if sin:
        filters.append(f"sin:{sin}")
    if worksite:
        filters.append(f"worksite:{worksite}")
    return filters


def _build_query_string(
    *,
    keyword: str | None = None,
    search_field: str | None = None,
    search_value: str | None = None,
    suggest_field: str | None = None,
    suggest_term: str | None = None,
    filters: list[str] | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: str = "asc",
    exclude: str | None = None,
) -> str:
    """Build the full query parameter string. All values URL-encoded."""
    # Filters param must be a list; protect against accidental string passage.
    if filters is not None and not isinstance(filters, list):
        raise ValueError(
            f"filters must be a list of 'field:value' strings. "
            f"Got {type(filters).__name__}."
        )

    parts: list[str] = []

    # Precedence: keyword > search > suggest. Reject combinations to prevent
    # silent dropping of the non-selected search mode.
    search_modes = sum([
        keyword is not None,
        bool(search_field and search_value),
        bool(suggest_field and suggest_term),
    ])
    if search_modes > 1:
        raise ValueError(
            "Only one search mode allowed per query: keyword, search (field+value), "
            "or suggest (field+term). Combining silently drops the lower-priority modes."
        )

    if keyword is not None:
        parts.append(f"keyword={urllib.parse.quote_plus(keyword)}")
    elif search_field and search_value:
        parts.append(
            f"search={search_field}:{urllib.parse.quote_plus(search_value)}"
        )
    elif suggest_field and suggest_term:
        parts.append(
            f"suggest-contains={suggest_field}:{urllib.parse.quote_plus(suggest_term)}"
        )

    # URL-encode each filter's value portion. Filters are "field:value" strings;
    # split once, encode value, rejoin.
    if filters:
        for f in filters:
            if not isinstance(f, str) or not f:
                continue
            if ":" in f:
                field, value = f.split(":", 1)
                parts.append(f"filter={field}:{urllib.parse.quote_plus(value)}")
            else:
                parts.append(f"filter={urllib.parse.quote_plus(f)}")

    parts.append(f"page={page}")
    parts.append(f"page_size={min(page_size, MAX_PAGE_SIZE)}")
    parts.append(f"ordering={urllib.parse.quote_plus(ordering)}")
    parts.append(f"sort={urllib.parse.quote_plus(sort)}")

    if exclude:
        parts.append(f"exclude={urllib.parse.quote_plus(exclude)}")

    return "&".join(parts)


def _extract_stats(data: Any) -> dict[str, Any]:
    """Extract key statistics from the aggregations in a response.

    Fully defensive — tolerates every GSA CALC+ / ES response shape observed
    in testing: aggregations as null / list / str, wage_stats as null, percentile
    values as null, std_deviation_bounds as null, bucket items with None entries
    or missing key/doc_count, hits.total as int or None, wage_stats.avg/std as
    NaN/Inf. Never raises; returns a structured response with Nones for missing
    values.
    """
    data = _safe_dict(data)
    aggs = _safe_dict(data.get("aggregations"))
    wage_stats = _safe_dict(aggs.get("wage_stats"))
    percentiles = _safe_dict(_safe_dict(aggs.get("histogram_percentiles")).get("values"))
    ed_counts = _as_list(_safe_dict(aggs.get("education_level_counts")).get("buckets"))
    biz_size = _as_list(_safe_dict(aggs.get("business_size")).get("buckets"))
    std_bounds = _safe_dict(wage_stats.get("std_deviation_bounds"))

    hits = _safe_dict(data.get("hits"))
    hits_total = hits.get("total")
    if isinstance(hits_total, dict):
        total_value = hits_total.get("value", 0)
        capped = hits_total.get("relation") == "gte"
    elif isinstance(hits_total, int):
        # ES 6 legacy format: total is just an int
        total_value = hits_total
        capped = False
    else:
        total_value = 0
        capped = False

    wage_count = wage_stats.get("count")
    true_count = wage_count if isinstance(wage_count, int) else total_value

    def _round_or_none(v: Any) -> float | None:
        n = _safe_number(v)
        return round(n, 2) if n is not None else None

    def _bucket_dict(buckets: list[Any]) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for b in buckets:
            pair = _safe_bucket_key(b)
            if pair is not None:
                out[pair[0]] = pair[1]
        return out

    # Percentile keys might be "10.0" string or 10 int or even 10.0 float
    def _pct(key: float) -> Any:
        for k in (f"{key}", f"{key:.1f}", key, int(key)):
            if k in percentiles:
                return _safe_number(percentiles[k])
        return None

    return {
        "total_rates": true_count if true_count is not None else 0,
        "hits_capped": capped,
        "min_rate": _safe_number(wage_stats.get("min")),
        "max_rate": _safe_number(wage_stats.get("max")),
        "avg_rate": _round_or_none(wage_stats.get("avg")),
        "std_deviation": _round_or_none(wage_stats.get("std_deviation")),
        "percentiles": {
            "p10": _pct(10.0),
            "p25": _pct(25.0),
            "p50_median": _pct(50.0),
            "p75": _pct(75.0),
            "p90": _pct(90.0),
        },
        "outlier_bounds_2sigma": {
            "lower": _safe_number(std_bounds.get("lower")),
            "upper": _safe_number(std_bounds.get("upper")),
        },
        "education_breakdown": _bucket_dict(ed_counts),
        "business_size_breakdown": _bucket_dict(biz_size),
    }


# ---------------------------------------------------------------------------
# Core search tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def keyword_search(
    keyword: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: Union[str, int, None] = None,
    worksite: str | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
    exclude: str | None = None,
) -> dict[str, Any]:
    """Search GSA CALC+ ceiling rates by keyword.

    Performs wildcard matching across labor_category, vendor_name, and
    idv_piid fields. This is the primary search tool for finding rates.

    Returns matching rate records plus aggregation statistics (wage_stats,
    percentiles, education breakdown, business size) covering the FULL
    result set even when individual hits are capped at 10,000.

    Important notes:
    - These are NTE (not-to-exceed) ceiling rates, not prices paid
    - Rates are fully burdened hourly rates from GSA MAS contracts
    - Data refreshes nightly from vendor price proposal tables
    - Use P50 from percentiles for median (more accurate than median_price)

    Filter parameters:
    - education_level: AA, BA, HS, MA, PHD, TEC (pipe-delimited for OR: 'BA|MA')
    - experience_min/max: years of experience range
    - price_min/max: hourly rate range in USD
    - business_size: 'S' (small) or 'O' (other/large)
    - security_clearance: 'yes' or 'no'
    - sin: Special Item Number (e.g., '54151S' for IT Professional Services)
    - worksite: 'Customer', 'Contractor', or 'Both'

    ordering: current_price, labor_category, vendor_name, education_level,
    min_years_experience. sort: 'asc' or 'desc'.

    exclude: pipe-delimited hit _id values to exclude from results and stats.
    """
    keyword = _strip_or_none(keyword)
    if keyword is None:
        raise ValueError(
            "keyword cannot be empty. For unfiltered browsing use filtered_browse() instead."
        )
    keyword = _validate_waf_safe(keyword, field="keyword")
    if len(keyword) > 500:
        raise ValueError(
            f"keyword exceeds 500 chars ({len(keyword)}). Very long keywords trigger "
            f"HTTP 406 URI-too-long errors."
        )
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    worksite = _validate_worksite(worksite)
    sin = _validate_sin(sin)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)
    exclude = _strip_or_none(exclude)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size, security_clearance=security_clearance,
        sin=sin, worksite=worksite,
    )
    qs = _build_query_string(
        keyword=keyword, filters=filters, page=page, page_size=page_size,
        ordering=ordering, sort=sort, exclude=exclude,
    )
    data = await _get(qs)
    return {**data, "_stats": _extract_stats(data)}


@mcp.tool()
async def exact_search(
    field: Literal["labor_category", "vendor_name", "idv_piid"],
    value: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Exact match search on a specific field.

    Use suggest_contains() first to discover the exact field value, then
    pass it here. The API requires exact string matching -- partial matches
    return 0 results.

    Fields: labor_category, vendor_name, idv_piid (GSA MAS contract number).
    """
    value = _strip_or_none(value)
    if value is None:
        raise ValueError("value cannot be empty. Use suggest_contains() to discover valid values.")
    value = _validate_waf_safe(value, field="value")
    if len(value) > 500:
        raise ValueError(f"value exceeds 500 chars. Got {len(value)}.")
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size,
    )
    qs = _build_query_string(
        search_field=field, search_value=value, filters=filters,
        page=page, page_size=page_size, ordering=ordering, sort=sort,
    )
    data = await _get(qs)
    return {**data, "_stats": _extract_stats(data)}


@mcp.tool()
async def suggest_contains(
    field: Literal["labor_category", "vendor_name", "idv_piid"],
    term: str,
) -> dict[str, Any]:
    """Discover exact field values via autocomplete/contains matching.

    Returns aggregation buckets showing matching values and their record
    counts. Use this BEFORE exact_search() to find the right value string.

    Minimum 2 characters required for the search term.

    Example workflow:
    1. suggest_contains('vendor_name', 'booz') -> finds 'Booz Allen Hamilton Inc.'
    2. exact_search('vendor_name', 'Booz Allen Hamilton Inc.') -> all their rates
    """
    term = _strip_or_none(term)
    if term is None or len(term) < 2:
        raise ValueError(
            "suggest_contains requires at least 2 non-whitespace characters."
        )
    term = _validate_waf_safe(term, field="term")

    qs = _build_query_string(suggest_field=field, suggest_term=term)
    data = await _get(qs)

    buckets = _as_list(
        _safe_dict(_safe_dict(data.get("aggregations")).get(field)).get("buckets")
    )
    suggestions: list[dict[str, Any]] = []
    for b in buckets:
        pair = _safe_bucket_key(b)
        if pair is not None:
            suggestions.append({"value": pair[0], "count": pair[1]})

    hits = _safe_dict(data.get("hits"))
    total_obj = hits.get("total")
    if isinstance(total_obj, dict):
        total = total_obj.get("value", 0)
    elif isinstance(total_obj, int):
        total = total_obj
    else:
        total = 0

    return {
        "field": field,
        "search_term": term,
        "suggestions": suggestions,
        "total_matching_records": total,
    }


@mcp.tool()
async def filtered_browse(
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    business_size: Literal["S", "O"] | None = None,
    security_clearance: Literal["yes", "no"] | None = None,
    sin: Union[str, int, None] = None,
    worksite: str | None = None,
    page: int = 1,
    page_size: int = 100,
    ordering: str = "current_price",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Browse rates with filters only (no search keyword).

    Useful for market segment statistics: "what do all BA-level rates with
    5-15 years experience look like across all of GSA MAS?" Returns rate
    records plus full aggregation statistics.
    """
    page = _clamp(page, field="page", lo=1, hi=100_000)
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    price_min, price_max = _validate_price_range(price_min, price_max)
    education_level = _validate_education_level(education_level)
    worksite = _validate_worksite(worksite)
    sin = _validate_sin(sin)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size, security_clearance=security_clearance,
        sin=sin, worksite=worksite,
    )
    qs = _build_query_string(
        filters=filters, page=page, page_size=page_size,
        ordering=ordering, sort=sort,
    )
    data = await _get(qs)
    return {**data, "_stats": _extract_stats(data)}


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def igce_benchmark(
    labor_category: str,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    business_size: Literal["S", "O"] | None = None,
    sin: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Get ceiling rate benchmarks for IGCE development.

    Returns statistical summary for a labor category: count, min, max, avg,
    median, standard deviation, percentile distribution (P10-P90), education
    breakdown, and outlier bounds.

    This is the primary tool for building Independent Government Cost
    Estimates. The returned statistics represent the market distribution
    of GSA MAS ceiling rates for comparable labor categories.

    Reminder: these are ceiling rates (max a contractor can charge), not
    prices paid. Actual task order rates should be lower per FAR 8.405-2(d).
    """
    labor_category = _strip_or_none(labor_category)
    if labor_category is None:
        raise ValueError("labor_category cannot be empty.")
    labor_category = _validate_waf_safe(labor_category, field="labor_category")
    experience_min, experience_max = _validate_experience_range(experience_min, experience_max)
    education_level = _validate_education_level(education_level)
    sin = _validate_sin(sin)

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, business_size=business_size, sin=sin,
    )
    qs = _build_query_string(
        keyword=labor_category, filters=filters, page=1, page_size=10,
    )
    data = await _get(qs)
    stats = _extract_stats(data)

    return {
        "labor_category": labor_category,
        "filters_applied": filters,
        **stats,
        "_note": "Ceiling rates (NTE), not prices paid. Sample size matters for IGCE reliability.",
    }


@mcp.tool()
async def price_reasonableness_check(
    labor_category: str,
    proposed_rate: float,
    education_level: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    business_size: Literal["S", "O"] | None = None,
) -> dict[str, Any]:
    """Evaluate a proposed hourly rate against GSA ceiling rate distribution.

    Returns the benchmark statistics plus a positioning analysis: z-score,
    comparison to median, IQR position, and delta from average.

    Use this for FAR 15.404-1 price analysis: is the proposed rate within
    the expected range for comparable labor categories on GSA MAS?

    A rate above P75 may be high; above P90 warrants scrutiny. A rate below
    P25 may indicate an unrealistically low offer (potential performance risk).
    """
    if not isinstance(proposed_rate, (int, float)) or isinstance(proposed_rate, bool):
        raise ValueError("proposed_rate must be a positive number.")
    if proposed_rate <= 0:
        raise ValueError(f"proposed_rate must be > 0. Got {proposed_rate}.")

    benchmark = await igce_benchmark(
        labor_category, education_level=education_level,
        experience_min=experience_min, experience_max=experience_max,
        business_size=business_size,
    )

    if benchmark.get("total_rates", 0) == 0:
        return {
            "status": "NO_DATA",
            "proposed_rate": proposed_rate,
            "message": f"No comparable ceiling rates found for '{labor_category}' with the given filters.",
        }

    avg = benchmark.get("avg_rate") or 0
    std = benchmark.get("std_deviation") or 0
    median = benchmark.get("percentiles", {}).get("p50_median")
    p25 = benchmark.get("percentiles", {}).get("p25")
    p75 = benchmark.get("percentiles", {}).get("p75")

    z_score = round((proposed_rate - avg) / std, 2) if std and std > 0 else 0

    iqr_position = None
    if p25 is not None and p75 is not None:
        if proposed_rate < p25:
            iqr_position = "below P25 (low)"
        elif proposed_rate <= p75:
            iqr_position = "within IQR P25-P75 (typical)"
        else:
            iqr_position = "above P75 (high)"

    # Don't force "above" when median is missing; say "unknown"
    if median is None:
        vs_median = "unknown (median unavailable)"
    elif proposed_rate < median:
        vs_median = "below"
    elif proposed_rate > median:
        vs_median = "above"
    else:
        vs_median = "equal"

    return {
        **benchmark,
        "proposed_rate": proposed_rate,
        "analysis": {
            "z_score": z_score,
            "vs_median": vs_median,
            "iqr_position": iqr_position,
            "delta_from_avg": round(proposed_rate - avg, 2),
            "delta_from_avg_pct": round(((proposed_rate - avg) / avg) * 100, 1) if avg and avg > 0 else None,
        },
    }


@mcp.tool()
async def vendor_rate_card(
    vendor_name: str,
    page_size: int = 500,
    ordering: str = "labor_category",
    sort: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Get all ceiling rates for a specific vendor.

    Auto-discovers the exact vendor name via suggest-contains, then pulls
    all their rate records. Returns labor categories, rates, education
    levels, experience requirements, SINs, and contract numbers.

    Pass a partial name (e.g., 'booz' for Booz Allen Hamilton). The tool
    finds the exact registered name automatically.

    If the discovery term matches multiple vendors, this tool picks the one
    with the most rate records and returns a _candidates list so the caller
    can re-query with a more specific term if needed.
    """
    vendor_name = _strip_or_none(vendor_name)
    if vendor_name is None or len(vendor_name) < 2:
        raise ValueError("vendor_name must be at least 2 non-whitespace characters.")
    vendor_name = _validate_waf_safe(vendor_name, field="vendor_name")
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)
    ordering = _validate_ordering(ordering)
    sort = _validate_sort(sort)

    # Step 1: discover exact name
    discovery = await suggest_contains("vendor_name", vendor_name)
    suggestions = discovery.get("suggestions", [])
    if not suggestions:
        return {
            "vendor_search": vendor_name,
            "error": f"No vendor found matching '{vendor_name}'. Try a shorter or different term.",
        }

    exact_name = suggestions[0]["value"]
    multi_match_note = None
    if len(suggestions) > 1:
        multi_match_note = (
            f"{len(suggestions)} vendors matched '{vendor_name}'. Picked the one "
            f"with the most rate records ({suggestions[0].get('count')}). If this "
            f"isn't the intended vendor, pass a more specific term."
        )

    # Step 2: pull all rates for that vendor
    qs = _build_query_string(
        search_field="vendor_name", search_value=exact_name,
        page=1, page_size=page_size, ordering=ordering, sort=sort,
    )
    data = await _get(qs)

    hits_list = _as_list(_safe_dict(data.get("hits")).get("hits"))
    rates: list[dict[str, Any]] = []
    for h in hits_list:
        if not isinstance(h, dict):
            continue
        src = _safe_dict(h.get("_source"))
        rates.append({
            "labor_category": src.get("labor_category"),
            "current_price": _safe_number(src.get("current_price")),
            "next_year_price": _safe_number(src.get("next_year_price")),
            "education_level": src.get("education_level"),
            "min_years_experience": src.get("min_years_experience"),
            "sin": src.get("sin"),
            "idv_piid": src.get("idv_piid"),
            "business_size": src.get("business_size"),
        })

    hits_total = _safe_dict(data.get("hits")).get("total")
    if isinstance(hits_total, dict):
        total = hits_total.get("value", 0)
    elif isinstance(hits_total, int):
        total = hits_total
    else:
        total = 0

    response: dict[str, Any] = {
        "vendor": exact_name,
        "total_categories": total,
        "returned": len(rates),
        "rates": rates,
        "_stats": _extract_stats(data),
    }
    if multi_match_note:
        response["_note"] = multi_match_note
        response["_candidates"] = [
            {"value": s.get("value"), "count": s.get("count")}
            for s in suggestions[:10]
        ]
    return response


@mcp.tool()
async def sin_analysis(
    sin_code: Union[str, int],
    page_size: int = 100,
) -> dict[str, Any]:
    """Get rate distribution and statistics for a specific SIN.

    Returns rate statistics, education breakdown, business size breakdown,
    and sample records for a GSA MAS Special Item Number.

    Common SINs for professional services:
    - 54151S: IT Professional Services
    - 541611: Management and Financial Consulting
    - 541715: Engineering R&D
    - 541330ENG: Engineering Services
    - 541512: Computer Systems Design
    - 611430: Training
    """
    sin_code = _validate_sin(sin_code)
    if sin_code is None:
        raise ValueError("sin_code cannot be empty.")
    page_size = _clamp(page_size, field="page_size", lo=1, hi=MAX_PAGE_SIZE)

    filters = [f"sin:{sin_code}"]
    qs = _build_query_string(
        filters=filters, page=1, page_size=page_size,
        ordering="current_price", sort="asc",
    )
    data = await _get(qs)
    stats = _extract_stats(data)

    return {
        "sin": sin_code,
        **stats,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
