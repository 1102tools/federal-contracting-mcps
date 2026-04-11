# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""GSA Per Diem Rates MCP server.

Federal travel lodging and M&IE rates for CONUS locations. Rates are set
annually per fiscal year (Oct 1 - Sep 30).

Authentication via PERDIEM_API_KEY environment variable. Falls back to
DEMO_KEY (~10 req/hr) if not set. Register free at api.data.gov/signup
for 1,000 req/hr.

These are maximum reimbursement ceilings, not actual hotel prices.
CONUS only; OCONUS rates are from the State Department.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import BASE_URL, DEFAULT_FISCAL_YEAR, DEFAULT_TIMEOUT, USER_AGENT

mcp = FastMCP("gsa-perdiem")


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("PERDIEM_API_KEY", "").strip() or "DEMO_KEY"


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
            "HTTP 403: API key rejected or missing. "
            "Set PERDIEM_API_KEY env var, or the server will use DEMO_KEY "
            "(~10 req/hr). Register free at https://api.data.gov/signup/ "
            "for 1,000 req/hr."
        )
    if status == 429:
        return (
            "HTTP 429: Rate limited. DEMO_KEY allows ~10 req/hr. "
            "Register a free key at https://api.data.gov/signup/ for 1,000 req/hr."
        )
    if status == 500:
        return (
            "HTTP 500: GSA Per Diem API server error. This can happen with "
            "non-ASCII characters in city names (emoji, CJK, Arabic). "
            "Use standard English city names."
        )
    return f"HTTP {status}: {body[:400]}"


async def _get(path: str) -> Any:
    """GET helper with API key injection."""
    key = _get_api_key()
    sep = "&" if "?" in path else "?"
    url = f"{BASE_URL}/{path}{sep}api_key={key}"
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling GSA Per Diem API: {e}") from e


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _parse_rate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Parse one rate entry from the API response."""
    months_raw = entry.get("months", {}).get("month", [])
    months = {}
    for m in months_raw:
        short = m.get("short", "")
        val = m.get("value", 0)
        if isinstance(val, str):
            try:
                val = int(val)
            except ValueError:
                val = 0
        months[short] = val

    is_standard = entry.get("city", "") == "Standard Rate"
    lodging_values = list(months.values()) if months else [0]

    return {
        "city": entry.get("city"),
        "county": entry.get("county") or "N/A",
        "meals": entry.get("meals", 0),
        "is_standard_rate": is_standard,
        "lodging_by_month": months,
        "lodging_min": min(lodging_values),
        "lodging_max": max(lodging_values),
        "has_seasonal_variation": min(lodging_values) != max(lodging_values),
    }


def _select_best_rate(
    response: Any,
    query_city: str | None = None,
) -> dict[str, Any] | None:
    """Select the best matching rate from an API response.

    Priority: exact city match > composite name match > first NSA > standard rate.
    """
    rates = response.get("rates", [])
    if not rates or not rates[0].get("rate"):
        return None

    parsed = [_parse_rate_entry(e) for e in rates[0]["rate"]]

    if query_city:
        q = query_city.lower()
        # Exact match
        exact = [p for p in parsed if p["city"] and p["city"].lower() == q]
        if exact:
            return exact[0]
        # Composite name match (e.g., "Boston / Cambridge")
        composite = [
            p for p in parsed
            if p["city"] and q in p["city"].lower() and not p["is_standard_rate"]
        ]
        if composite:
            return composite[0]

    # First non-standard entry
    nsa = [p for p in parsed if not p["is_standard_rate"]]
    return nsa[0] if nsa else (parsed[0] if parsed else None)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_city_perdiem(
    city: str,
    state: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Look up federal per diem rates for a city and state.

    Returns lodging rates (monthly breakdown for seasonal locations) and
    M&IE (meals and incidental expenses) for the specified fiscal year.

    state: 2-letter USPS code (e.g., 'DC', 'VA', 'MD', 'CA').
    fiscal_year: defaults to current FY (2026). FY runs Oct 1 - Sep 30.

    The API uses prefix matching on city names, which can return multiple
    entries. This tool auto-selects the best match:
    1. Exact city name match
    2. Composite NSA name containing the city (e.g., 'Boston' matches 'Boston / Cambridge')
    3. First non-standard rate entry
    4. Standard rate as fallback

    Special character handling: apostrophes and hyphens in city names are
    auto-replaced with spaces. Keep periods for 'St.' prefix cities
    (St. Louis, St. Petersburg).

    For DC: query city='Washington', state='DC'. Returns 'District of Columbia'.
    """
    if not city or not city.strip():
        raise ValueError("city cannot be empty.")
    if not state or len(state.strip()) != 2 or not state.strip().isalpha():
        raise ValueError(f"state must be a 2-letter USPS code (e.g., 'DC', 'VA'). Got {state!r}.")

    year = fiscal_year or DEFAULT_FISCAL_YEAR
    city_clean = city.strip().replace("'", " ").replace("-", " ")
    city_encoded = urllib.parse.quote(city_clean)
    state_upper = state.strip().upper()

    response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
    best = _select_best_rate(response, query_city=city.strip())

    if not best:
        return {
            "query": {"city": city, "state": state_upper, "fiscal_year": year},
            "error": f"No rates found for {city}, {state_upper} in FY{year}.",
        }

    return {
        "query": {"city": city, "state": state_upper, "fiscal_year": year},
        "matched_city": best["city"],
        "county": best["county"],
        "is_standard_rate": best["is_standard_rate"],
        "lodging_by_month": best["lodging_by_month"],
        "lodging_range": (
            f"${best['lodging_min']}-${best['lodging_max']}/night"
            if best["has_seasonal_variation"]
            else f"${best['lodging_min']}/night"
        ),
        "mie_daily": best["meals"],
        "mie_first_last_day": round(best["meals"] * 0.75, 2),
        "max_daily_total": best["lodging_max"] + best["meals"],
    }


@mcp.tool()
async def lookup_zip_perdiem(
    zip_code: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Look up federal per diem rates by ZIP code.

    May return multiple entries (NSA + standard rate). This tool auto-selects
    the NSA rate over the standard rate.

    Useful when the exact city name is uncertain but the ZIP is known.
    """
    if not zip_code or not zip_code.strip().isdigit() or len(zip_code.strip()) != 5:
        raise ValueError(f"zip_code must be a 5-digit ZIP. Got {zip_code!r}.")

    year = fiscal_year or DEFAULT_FISCAL_YEAR
    response = await _get(f"zip/{zip_code.strip()}/year/{year}")
    best = _select_best_rate(response)

    if not best:
        return {"zip_code": zip_code, "fiscal_year": year, "error": "No rates found."}

    return {
        "zip_code": zip_code,
        "fiscal_year": year,
        "matched_city": best["city"],
        "county": best["county"],
        "is_standard_rate": best["is_standard_rate"],
        "lodging_range": (
            f"${best['lodging_min']}-${best['lodging_max']}/night"
            if best["has_seasonal_variation"]
            else f"${best['lodging_min']}/night"
        ),
        "mie_daily": best["meals"],
    }


@mcp.tool()
async def lookup_state_rates(
    state: str,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Get all Non-Standard Area (NSA) per diem rates for a state.

    Returns every city/county with rates above the standard rate in that
    state. Useful for comparing rates across cities within a state or for
    building a travel IGCE with multiple destinations.
    """
    if not state or len(state.strip()) != 2 or not state.strip().isalpha():
        raise ValueError(f"state must be a 2-letter USPS code (e.g., 'VA', 'CA'). Got {state!r}.")

    year = fiscal_year or DEFAULT_FISCAL_YEAR
    state_upper = state.strip().upper()
    response = await _get(f"state/{state_upper}/year/{year}")

    rates = response.get("rates", [])
    if not rates or not rates[0].get("rate"):
        return {"state": state_upper, "fiscal_year": year, "nsa_count": 0, "rates": []}

    parsed = [_parse_rate_entry(e) for e in rates[0]["rate"]]
    nsa_only = [p for p in parsed if not p["is_standard_rate"]]

    return {
        "state": state_upper,
        "fiscal_year": year,
        "nsa_count": len(nsa_only),
        "rates": [
            {
                "city": r["city"],
                "county": r["county"],
                "lodging_max": r["lodging_max"],
                "lodging_min": r["lodging_min"],
                "mie": r["meals"],
                "max_daily": r["lodging_max"] + r["meals"],
                "seasonal": r["has_seasonal_variation"],
            }
            for r in nsa_only
        ],
    }


@mcp.tool()
async def get_mie_breakdown(fiscal_year: int | None = None) -> dict[str, Any]:
    """Get the M&IE (meals and incidental expenses) tier breakdown table.

    Returns all M&IE tiers with breakfast, lunch, dinner, incidental, and
    first/last day (75%) amounts. Use this to show the meal component
    breakdown when presenting per diem estimates.

    M&IE does NOT vary seasonally (unlike lodging). The tier is set per
    location and applies year-round.
    """
    year = fiscal_year or DEFAULT_FISCAL_YEAR
    data = await _get(f"conus/mie/{year}")

    if isinstance(data, list):
        tiers = data
    else:
        tiers = data.get("mieData", data.get("rates", []))

    return {
        "fiscal_year": year,
        "tiers": [
            {
                "total": t.get("total"),
                "breakfast": t.get("breakfast"),
                "lunch": t.get("lunch"),
                "dinner": t.get("dinner"),
                "incidental": t.get("incidental"),
                "first_last_day_75pct": t.get("FirstLastDay") or round(t.get("total", 0) * 0.75, 2),
            }
            for t in tiers
        ],
    }


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def estimate_travel_cost(
    city: str,
    state: str,
    num_nights: int,
    travel_month: str | None = None,
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Estimate total per diem cost for a trip.

    Calculates lodging + M&IE for the specified number of nights.
    First and last travel days use 75% M&IE per 41 CFR 301-11.101.

    travel_month: 3-letter abbreviation (Jan, Feb, ..., Dec). If omitted,
    uses the max monthly lodging rate (conservative estimate for IGCE).

    Does NOT include airfare or ground transportation. Add those separately.

    Formula:
    - Lodging = nightly_rate x num_nights
    - M&IE = full_day_rate x (travel_days - 2) + first/last_day_rate x 2
    - Travel days = num_nights + 1
    """
    if num_nights < 1:
        raise ValueError(f"num_nights must be at least 1. Got {num_nights}.")

    year = fiscal_year or DEFAULT_FISCAL_YEAR
    city_clean = city.strip().replace("'", " ").replace("-", " ")
    city_encoded = urllib.parse.quote(city_clean)
    state_upper = state.strip().upper()

    response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
    best = _select_best_rate(response, query_city=city.strip())

    if not best:
        return {"error": f"No rates found for {city}, {state_upper} in FY{year}."}

    if travel_month and travel_month in best["lodging_by_month"]:
        nightly = best["lodging_by_month"][travel_month]
    else:
        nightly = best["lodging_max"]

    lodging_total = nightly * num_nights
    travel_days = num_nights + 1
    daily_mie = best["meals"]
    first_last_mie = round(daily_mie * 0.75, 2)

    if travel_days <= 1:
        mie_total = first_last_mie
    elif travel_days == 2:
        mie_total = first_last_mie * 2
    else:
        mie_total = (daily_mie * (travel_days - 2)) + (first_last_mie * 2)

    return {
        "destination": best["city"],
        "state": state_upper,
        "fiscal_year": year,
        "num_nights": num_nights,
        "travel_days": travel_days,
        "nightly_lodging": nightly,
        "lodging_total": lodging_total,
        "daily_mie": daily_mie,
        "first_last_day_mie": first_last_mie,
        "mie_total": round(mie_total, 2),
        "grand_total": round(lodging_total + mie_total, 2),
        "rate_month": travel_month or "MAX",
        "_note": "Per diem only (lodging + M&IE). Airfare and ground transport not included.",
    }


@mcp.tool()
async def compare_locations(
    locations: list[dict[str, str]],
    fiscal_year: int | None = None,
) -> dict[str, Any]:
    """Compare per diem rates across multiple locations.

    locations: list of {"city": "...", "state": "XX"} dicts.
    Returns rates sorted by max daily total (highest first).

    Useful for travel IGCE development when comparing destination costs.
    """
    if not locations:
        raise ValueError("locations list cannot be empty.")

    import asyncio
    year = fiscal_year or DEFAULT_FISCAL_YEAR
    results = []

    for loc in locations:
        city = loc.get("city", "")
        state = loc.get("state", "")
        if not city or not state:
            results.append({"location": f"{city}, {state}", "error": "missing city or state"})
            continue

        try:
            city_clean = city.strip().replace("'", " ").replace("-", " ")
            city_encoded = urllib.parse.quote(city_clean)
            state_upper = state.strip().upper()
            response = await _get(f"city/{city_encoded}/state/{state_upper}/year/{year}")
            best = _select_best_rate(response, query_city=city.strip())
            if best:
                results.append({
                    "location": f"{best['city']}, {state_upper}",
                    "lodging_max": best["lodging_max"],
                    "lodging_min": best["lodging_min"],
                    "mie": best["meals"],
                    "max_daily_total": best["lodging_max"] + best["meals"],
                    "seasonal": best["has_seasonal_variation"],
                })
            else:
                results.append({"location": f"{city}, {state_upper}", "error": "no rates found"})
        except Exception as e:
            results.append({"location": f"{city}, {state}", "error": str(e)[:100]})

        await asyncio.sleep(0.3)

    results.sort(key=lambda x: x.get("max_daily_total", 0), reverse=True)
    return {"fiscal_year": year, "locations": results}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
