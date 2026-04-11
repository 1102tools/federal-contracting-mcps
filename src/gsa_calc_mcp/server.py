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

import urllib.parse
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_PAGE_SIZE,
    USER_AGENT,
)

mcp = FastMCP("gsa-calc")


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
            "name is invalid. Valid ordering: current_price, labor_category, "
            "vendor_name, education_level, min_years_experience. "
            f"API response: {body[:300]}"
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
        return f"HTTP 400: Bad request. Check filter format (field:value) and page_size (max 500). API response: {body[:300]}"
    return f"HTTP {status}: {body[:400]}"


async def _get(params_str: str) -> dict[str, Any]:
    """GET helper. Builds full URL from query string."""
    url = f"{BASE_URL}?{params_str}"
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        return r.json()
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
    """Build filter strings for the CALC+ API."""
    filters = []
    if education_level:
        filters.append(f"education_level:{education_level}")
    if experience_min is not None and experience_max is not None:
        filters.append(f"experience_range:{experience_min},{experience_max}")
    elif experience_min is not None:
        filters.append(f"min_years_experience:{experience_min}")
    if price_min is not None and price_max is not None:
        filters.append(f"price_range:{price_min},{price_max}")
    elif price_min is not None:
        filters.append(f"price_range:{price_min},99999")
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
    """Build the full query parameter string."""
    parts: list[str] = []

    if keyword is not None:
        parts.append(f"keyword={urllib.parse.quote_plus(keyword)}")
    elif search_field and search_value:
        parts.append(f"search={search_field}:{urllib.parse.quote_plus(search_value)}")
    elif suggest_field and suggest_term:
        parts.append(f"suggest-contains={suggest_field}:{urllib.parse.quote_plus(suggest_term)}")

    if filters:
        for f in filters:
            parts.append(f"filter={f}")

    parts.append(f"page={page}")
    parts.append(f"page_size={min(page_size, MAX_PAGE_SIZE)}")
    parts.append(f"ordering={ordering}")
    parts.append(f"sort={sort}")

    if exclude:
        parts.append(f"exclude={exclude}")

    return "&".join(parts)


def _extract_stats(data: dict[str, Any]) -> dict[str, Any]:
    """Extract key statistics from the aggregations in a response."""
    aggs = data.get("aggregations", {})
    wage_stats = aggs.get("wage_stats", {})
    percentiles = aggs.get("histogram_percentiles", {}).get("values", {})
    ed_counts = aggs.get("education_level_counts", {}).get("buckets", [])
    biz_size = aggs.get("business_size", {}).get("buckets", [])

    hits_total = data.get("hits", {}).get("total", {})
    true_count = wage_stats.get("count", hits_total.get("value", 0))

    return {
        "total_rates": true_count,
        "hits_capped": hits_total.get("relation") == "gte",
        "min_rate": wage_stats.get("min"),
        "max_rate": wage_stats.get("max"),
        "avg_rate": round(wage_stats.get("avg", 0), 2) if wage_stats.get("avg") else None,
        "std_deviation": round(wage_stats.get("std_deviation", 0), 2) if wage_stats.get("std_deviation") else None,
        "percentiles": {
            "p10": percentiles.get("10.0"),
            "p25": percentiles.get("25.0"),
            "p50_median": percentiles.get("50.0"),
            "p75": percentiles.get("75.0"),
            "p90": percentiles.get("90.0"),
        },
        "outlier_bounds_2sigma": {
            "lower": wage_stats.get("std_deviation_bounds", {}).get("lower"),
            "upper": wage_stats.get("std_deviation_bounds", {}).get("upper"),
        },
        "education_breakdown": {b["key"]: b["doc_count"] for b in ed_counts},
        "business_size_breakdown": {b["key"]: b["doc_count"] for b in biz_size},
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
    sin: str | None = None,
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
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size max is {MAX_PAGE_SIZE}. Got {page_size}.")
    if page_size < 1:
        raise ValueError(f"page_size must be at least 1. Got {page_size}.")

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
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size max is {MAX_PAGE_SIZE}. Got {page_size}.")
    if not value or not value.strip():
        raise ValueError("value cannot be empty. Use suggest_contains() to discover valid values.")

    filters = _build_filters(
        education_level=education_level, experience_min=experience_min,
        experience_max=experience_max, price_min=price_min, price_max=price_max,
        business_size=business_size,
    )
    qs = _build_query_string(
        search_field=field, search_value=value.strip(), filters=filters,
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
    if not term or len(term.strip()) < 2:
        raise ValueError(
            "suggest_contains requires at least 2 characters. "
            f"Got {term!r}."
        )
    qs = _build_query_string(suggest_field=field, suggest_term=term.strip())
    data = await _get(qs)

    buckets = data.get("aggregations", {}).get(field, {}).get("buckets", [])
    return {
        "field": field,
        "search_term": term,
        "suggestions": [{"value": b["key"], "count": b["doc_count"]} for b in buckets],
        "total_matching_records": data.get("hits", {}).get("total", {}).get("value", 0),
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
    sin: str | None = None,
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
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size max is {MAX_PAGE_SIZE}. Got {page_size}.")

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
    sin: str | None = None,
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
    benchmark = await igce_benchmark(
        labor_category, education_level=education_level,
        experience_min=experience_min, experience_max=experience_max,
        business_size=business_size,
    )

    if benchmark["total_rates"] == 0:
        return {
            "status": "NO_DATA",
            "proposed_rate": proposed_rate,
            "message": f"No comparable ceiling rates found for '{labor_category}' with the given filters.",
        }

    avg = benchmark["avg_rate"] or 0
    std = benchmark["std_deviation"] or 0
    median = benchmark["percentiles"]["p50_median"]
    p25 = benchmark["percentiles"]["p25"]
    p75 = benchmark["percentiles"]["p75"]

    z_score = round((proposed_rate - avg) / std, 2) if std > 0 else 0

    iqr_position = None
    if p25 is not None and p75 is not None:
        if proposed_rate < p25:
            iqr_position = "below P25 (low)"
        elif proposed_rate <= p75:
            iqr_position = "within IQR P25-P75 (typical)"
        else:
            iqr_position = "above P75 (high)"

    return {
        **benchmark,
        "proposed_rate": proposed_rate,
        "analysis": {
            "z_score": z_score,
            "vs_median": "below" if median and proposed_rate < median else "above",
            "iqr_position": iqr_position,
            "delta_from_avg": round(proposed_rate - avg, 2),
            "delta_from_avg_pct": round(((proposed_rate - avg) / avg) * 100, 1) if avg > 0 else None,
        },
    }


@mcp.tool()
async def vendor_rate_card(
    vendor_name: str,
    page_size: int = 500,
) -> dict[str, Any]:
    """Get all ceiling rates for a specific vendor.

    Auto-discovers the exact vendor name via suggest-contains, then pulls
    all their rate records. Returns labor categories, rates, education
    levels, experience requirements, SINs, and contract numbers.

    Pass a partial name (e.g., 'booz' for Booz Allen Hamilton). The tool
    finds the exact registered name automatically.
    """
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size max is {MAX_PAGE_SIZE}. Got {page_size}.")
    if not vendor_name or len(vendor_name.strip()) < 2:
        raise ValueError("vendor_name must be at least 2 characters.")

    # Step 1: discover exact name
    discovery = await suggest_contains("vendor_name", vendor_name)
    if not discovery["suggestions"]:
        return {
            "vendor_search": vendor_name,
            "error": f"No vendor found matching '{vendor_name}'. Try a shorter or different term.",
        }

    exact_name = discovery["suggestions"][0]["value"]

    # Step 2: pull all rates for that vendor
    qs = _build_query_string(
        search_field="vendor_name", search_value=exact_name,
        page=1, page_size=page_size, ordering="labor_category", sort="asc",
    )
    data = await _get(qs)

    hits = data.get("hits", {}).get("hits", [])
    rates = []
    for h in hits:
        src = h.get("_source", {})
        rates.append({
            "labor_category": src.get("labor_category"),
            "current_price": src.get("current_price"),
            "next_year_price": src.get("next_year_price"),
            "education_level": src.get("education_level"),
            "min_years_experience": src.get("min_years_experience"),
            "sin": src.get("sin"),
            "idv_piid": src.get("idv_piid"),
            "business_size": src.get("business_size"),
        })

    total = data.get("hits", {}).get("total", {}).get("value", 0)
    return {
        "vendor": exact_name,
        "total_categories": total,
        "returned": len(rates),
        "rates": rates,
        "_stats": _extract_stats(data),
    }


@mcp.tool()
async def sin_analysis(
    sin_code: str,
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
    if not sin_code or not sin_code.strip():
        raise ValueError("sin_code cannot be empty.")

    filters = [f"sin:{sin_code.strip()}"]
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
