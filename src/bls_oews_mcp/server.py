# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""BLS OEWS MCP server.

Provides access to Bureau of Labor Statistics Occupational Employment and
Wage Statistics (OEWS) data. Authentication via BLS_API_KEY environment
variable (optional but recommended for higher rate limits).

Without a key (v1): 25 queries/day, 25 series/query.
With a key (v2): 500 queries/day, 50 series/query.

OEWS data lags ~2 years. The server defaults to the correct data year
(currently 2024 = May 2024 estimates). Do NOT query the current calendar year.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL_V1,
    BASE_URL_V2,
    COMMON_SOC_CODES,
    DATATYPE_LABELS,
    DEFAULT_TIMEOUT,
    FULL_DATATYPES,
    IGCE_DATATYPES,
    MAX_SERIES_V1,
    MAX_SERIES_V2,
    OEWS_CURRENT_YEAR,
    SERIES_ID_LENGTH,
    SPECIAL_VALUES,
    USER_AGENT,
)

mcp = FastMCP("bls-oews")


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str | None:
    """Read BLS API key from environment. None = v1 (25/day)."""
    key = os.environ.get("BLS_API_KEY", "").strip()
    return key if key else None


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        )
    return _client


def _format_error(status: int, body: str) -> str:
    if status == 429:
        key = _get_api_key()
        limit = "500/day (v2)" if key else "25/day (v1)"
        return (
            f"HTTP 429: BLS rate limit exceeded ({limit}). "
            "Wait until tomorrow or register a free v2 key at "
            "https://data.bls.gov/registrationEngine/ for 500 queries/day."
        )
    if status == 400:
        return f"HTTP 400: Bad request. Check series ID format (must be exactly 25 chars). API response: {body[:300]}"
    if status == 403:
        return (
            "HTTP 403: Forbidden. Your BLS API key may be invalid. "
            "Register a free key at https://data.bls.gov/registrationEngine/"
        )
    return f"HTTP {status}: {body[:400]}"


async def _query_bls(
    series_ids: list[str],
    start_year: str | None = None,
    end_year: str | None = None,
) -> dict[str, Any]:
    """POST to BLS timeseries API."""
    api_key = _get_api_key()
    base_url = BASE_URL_V2 if api_key else BASE_URL_V1
    max_series = MAX_SERIES_V2 if api_key else MAX_SERIES_V1

    if len(series_ids) > max_series:
        raise ValueError(
            f"Too many series ({len(series_ids)}). "
            f"Max {max_series} per request ({'v2' if api_key else 'v1'}). "
            "Split into multiple calls."
        )

    year = start_year or OEWS_CURRENT_YEAR
    payload: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": year,
        "endyear": end_year or year,
    }
    if api_key:
        payload["registrationkey"] = api_key

    try:
        r = await _get_client().post(base_url, content=json.dumps(payload))
        r.raise_for_status()
        data = r.json()

        status = data.get("status")
        if status == "REQUEST_NOT_PROCESSED":
            messages = data.get("message", [])
            raise RuntimeError(
                f"BLS API refused the request: {messages}. "
                "Common cause: rate limit exceeded or malformed series IDs."
            )
        return data

    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling BLS: {e}") from e


# ---------------------------------------------------------------------------
# Series ID helpers
# ---------------------------------------------------------------------------

def _build_series_id(
    prefix: str = "OEUN",
    area: str = "0000000",
    industry: str = "000000",
    occ_code: str = "000000",
    datatype: str = "04",
) -> str:
    """Build a 25-character OEWS series ID."""
    sid = f"{prefix}{area}{industry}{occ_code}{datatype}"
    if len(sid) != SERIES_ID_LENGTH:
        raise ValueError(
            f"Series ID must be {SERIES_ID_LENGTH} chars, got {len(sid)}: {sid}. "
            f"Components: prefix={prefix}({len(prefix)}), area={area}({len(area)}), "
            f"industry={industry}({len(industry)}), occ={occ_code}({len(occ_code)}), "
            f"datatype={datatype}({len(datatype)})"
        )
    return sid


def _normalize_area(area_input: str) -> str:
    """Convert 2-digit FIPS, 5-digit MSA, or 7-char code to 7-char format."""
    area = str(area_input).strip()
    if len(area) == 7:
        return area
    if len(area) == 5:
        return f"00{area}"
    if len(area) == 2:
        return f"{area}00000"
    raise ValueError(
        f"Unrecognized area code '{area}' (length {len(area)}). "
        "Expected: 2-digit state FIPS (e.g., '51'), 5-digit MSA (e.g., '47900'), "
        "or 7-char full code (e.g., '0047900')."
    )


def _parse_value(value: str, datatype: str, footnotes: list[str] | None = None) -> dict[str, Any]:
    """Parse a BLS data value, handling special codes."""
    if value in SPECIAL_VALUES:
        msg = f"[Capped] {footnotes[0]}" if footnotes else f"[Suppressed: {value}]"
        return {"raw": value, "formatted": msg, "numeric": None, "suppressed": True}

    try:
        if datatype == "01":
            n = int(float(value))
            return {"raw": value, "formatted": f"{n:,}", "numeric": n, "suppressed": False}
        elif datatype in ("03", "06", "07", "08", "09", "10"):
            n = float(value)
            return {"raw": value, "formatted": f"${n:,.2f}/hr", "numeric": n, "suppressed": False}
        else:
            n = int(float(value))
            return {"raw": value, "formatted": f"${n:,}", "numeric": n, "suppressed": False}
    except (ValueError, TypeError):
        return {"raw": value, "formatted": f"[Unparseable: {value}]", "numeric": None, "suppressed": False}


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_wage_data(
    occ_code: str,
    scope: Literal["national", "state", "metro"] = "national",
    area_code: str | None = None,
    industry: str = "000000",
    datatypes: list[str] | None = None,
    year: str | None = None,
) -> dict[str, Any]:
    """Get wage data for an occupation by SOC code.

    This is the primary tool for querying BLS OEWS wage statistics.

    occ_code: 6-digit SOC code without dash (e.g., '151252' for Software
    Developers, '131082' for Project Management Specialists). See
    list_common_soc_codes() for common mappings.

    scope + area_code:
    - 'national': no area_code needed (all US)
    - 'state': area_code = 2-digit state FIPS (e.g., '51' for VA, '11' for DC)
    - 'metro': area_code = 5-digit MSA code (e.g., '47900' for DC metro,
      '42660' for Seattle). See list_common_metros() for codes.

    industry: 6-digit industry code for national-only breakdowns.
    '000000' = all industries (default). Common: '541000' (Professional Services),
    '541500' (Computer Systems), '999100' (Federal Government). Industry
    breakdowns only work with scope='national'.

    datatypes: list of 2-digit codes. Default uses IGCE set:
    - '04' = Annual Mean Wage
    - '13' = Annual Median
    - '11' = Annual 10th Percentile
    - '15' = Annual 90th Percentile
    Other: '01' (Employment), '03' (Hourly Mean), '08' (Hourly Median),
    '12' (25th Percentile), '14' (75th Percentile).

    CRITICAL: Data year defaults to 2024 (May 2024 estimates). Do NOT pass
    2025 or 2026. OEWS data lags ~2 years. Querying the current year returns
    nothing.

    Values of '-' mean wage >= $239,200/yr (capped). '*' means sample too small.
    """
    if not occ_code or not occ_code.strip().isdigit() or len(occ_code.strip()) != 6:
        raise ValueError(
            f"occ_code must be a 6-digit SOC code (e.g., '151252'). Got {occ_code!r}."
        )

    occ_code = occ_code.strip()
    if datatypes is None:
        datatypes = list(IGCE_DATATYPES)

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        area = "0000000"
    else:
        if not area_code:
            raise ValueError(f"area_code is required for scope='{scope}'.")
        area = _normalize_area(area_code)

    if industry != "000000" and scope != "national":
        raise ValueError(
            "Industry-specific estimates are only available at the national level "
            "(scope='national'). Cannot combine state/metro scope with industry filter."
        )

    series_ids = [_build_series_id(prefix, area, industry, occ_code, dt) for dt in datatypes]
    data = await _query_bls(series_ids, start_year=year)

    results: dict[str, Any] = {}
    for series in data.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        dt = sid[-2:]
        label = DATATYPE_LABELS.get(dt, dt)
        if series["data"]:
            entry = series["data"][0]
            footnotes = [f.get("text", "") for f in entry.get("footnotes", []) if f.get("text")]
            results[label] = _parse_value(entry["value"], dt, footnotes)
            results["_data_year"] = entry["year"]
            results["_period"] = entry["periodName"]
        else:
            results[label] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    return {
        "occ_code": occ_code,
        "scope": scope,
        "area_code": area_code,
        "industry": industry,
        "wages": results,
    }


@mcp.tool()
async def compare_metros(
    occ_code: str,
    metro_codes: list[str],
    datatype: str = "04",
    year: str | None = None,
) -> dict[str, Any]:
    """Compare wages for one occupation across multiple metro areas.

    Pass a list of 5-digit MSA codes (e.g., ['47900', '42660', '12580']
    for DC, Seattle, Baltimore). Returns the specified wage measure for
    each metro. Use list_common_metros() to find codes.

    datatype: '04' (Annual Mean, default), '13' (Median), '03' (Hourly Mean).

    Max ~12 metros per call (each metro = 1 series, 50 series limit on v2).
    """
    if not occ_code or len(occ_code.strip()) != 6:
        raise ValueError(f"occ_code must be 6-digit SOC. Got {occ_code!r}.")
    if not metro_codes:
        raise ValueError("metro_codes list cannot be empty.")

    occ_code = occ_code.strip()
    series_ids = []
    metro_labels = {}
    for code in metro_codes:
        area = _normalize_area(code.strip())
        sid = _build_series_id("OEUM", area, "000000", occ_code, datatype)
        series_ids.append(sid)
        metro_labels[sid] = code.strip()

    data = await _query_bls(series_ids, start_year=year)

    metros: dict[str, Any] = {}
    for series in data.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        code = metro_labels.get(sid, sid)
        if series["data"]:
            entry = series["data"][0]
            footnotes = [f.get("text", "") for f in entry.get("footnotes", []) if f.get("text")]
            metros[code] = _parse_value(entry["value"], datatype, footnotes)
        else:
            metros[code] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    return {
        "occ_code": occ_code,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "metros": metros,
    }


@mcp.tool()
async def compare_occupations(
    occ_codes: list[str],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: str | None = None,
    datatype: str = "04",
    year: str | None = None,
) -> dict[str, Any]:
    """Compare wages across multiple occupations in one location.

    Pass a list of 6-digit SOC codes. Returns the specified wage measure
    for each occupation. Use list_common_soc_codes() to find codes.

    Max ~12 occupations per call.
    """
    if not occ_codes:
        raise ValueError("occ_codes list cannot be empty.")

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        area = "0000000"
    else:
        if not area_code:
            raise ValueError(f"area_code required for scope='{scope}'.")
        area = _normalize_area(area_code)

    series_ids = []
    occ_labels = {}
    for code in occ_codes:
        code = code.strip()
        if len(code) != 6:
            raise ValueError(f"Each occ_code must be 6 digits. Got {code!r}.")
        sid = _build_series_id(prefix, area, "000000", code, datatype)
        series_ids.append(sid)
        occ_labels[sid] = code

    data = await _query_bls(series_ids, start_year=year)

    occupations: dict[str, Any] = {}
    for series in data.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        code = occ_labels.get(sid, sid)
        label = COMMON_SOC_CODES.get(code, code)
        if series["data"]:
            entry = series["data"][0]
            footnotes = [f.get("text", "") for f in entry.get("footnotes", []) if f.get("text")]
            occupations[f"{code} ({label})"] = _parse_value(entry["value"], datatype, footnotes)
        else:
            occupations[f"{code} ({label})"] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    return {
        "scope": scope,
        "area_code": area_code,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "occupations": occupations,
    }


@mcp.tool()
async def igce_wage_benchmark(
    occ_code: str,
    scope: Literal["national", "state", "metro"] = "national",
    area_code: str | None = None,
    burden_low: float = 1.8,
    burden_high: float = 2.2,
    year: str | None = None,
) -> dict[str, Any]:
    """Get wage benchmarks formatted for IGCE development.

    Returns annual and hourly wages at mean, median, 10th, and 90th
    percentiles, plus estimated burdened hourly rates using the specified
    burden multiplier range.

    BLS wages are BASE wages (no fringe, overhead, G&A, or profit).
    Multiply by a burden factor to estimate fully-loaded rates:
    - 1.5x-1.7x: lean contractor
    - 1.8x-2.2x: mid-range professional services (default)
    - 2.0x-2.5x: large contractor with clearance overhead
    - 2.5x-3.0x: high-overhead (SCIF, deployed)

    The burdened range should roughly align with GSA CALC+ ceiling rates
    for comparable labor categories. If CALC+ >> burdened BLS, the role
    may require specialized skills or clearance overhead. Document the gap.
    """
    wage_data = await get_wage_data(
        occ_code=occ_code, scope=scope, area_code=area_code,
        datatypes=["04", "11", "13", "15"], year=year,
    )

    wages = wage_data.get("wages", {})
    benchmarks: dict[str, Any] = {}

    for label in ["Annual Mean Wage", "Annual 10th Percentile", "Annual Median", "Annual 90th Percentile"]:
        entry = wages.get(label, {})
        annual = entry.get("numeric")
        if annual and not entry.get("suppressed"):
            hourly = round(annual / 2080, 2)
            benchmarks[label] = {
                "annual": f"${annual:,}",
                "hourly_base": f"${hourly:.2f}",
                "hourly_burdened_low": f"${round(hourly * burden_low, 2):.2f}",
                "hourly_burdened_high": f"${round(hourly * burden_high, 2):.2f}",
                "numeric_annual": annual,
                "numeric_hourly": hourly,
            }
        else:
            benchmarks[label] = {"annual": entry.get("formatted", "No data"), "suppressed": True}

    return {
        "occ_code": occ_code,
        "occ_title": COMMON_SOC_CODES.get(occ_code, occ_code),
        "scope": scope,
        "area_code": area_code,
        "data_year": wages.get("_data_year", OEWS_CURRENT_YEAR),
        "burden_range": f"{burden_low}x - {burden_high}x",
        "benchmarks": benchmarks,
        "_note": "BLS wages are base wages only (no fringe/overhead/G&A/profit). Burdened rates are estimates.",
    }


@mcp.tool()
async def detect_latest_year() -> dict[str, Any]:
    """Probe the BLS API to check if a newer OEWS data year is available.

    OEWS data releases annually around April/May. The server defaults to
    2024 (May 2024 estimates). This tool checks if 2025 data has been
    published yet by querying a known-good national series.

    Call this once at the start of an IGCE build to ensure you're using
    the latest available data.
    """
    probe_series = "OEUN000000000000000000004"  # National all-occupation annual mean
    current = OEWS_CURRENT_YEAR
    candidate = str(int(current) + 1)

    try:
        data = await _query_bls([probe_series], start_year=candidate, end_year=candidate)
        for s in data.get("Results", {}).get("series", []):
            if s.get("data") and s["data"][0].get("value") not in SPECIAL_VALUES:
                return {
                    "latest_year": candidate,
                    "default_year": current,
                    "newer_data_available": True,
                    "message": f"OEWS {candidate} data is available. Use year='{candidate}' for the latest estimates.",
                }
    except Exception:
        pass

    return {
        "latest_year": current,
        "default_year": current,
        "newer_data_available": False,
        "message": f"OEWS {current} is the latest available. Next release expected ~April {int(current) + 2}.",
    }


@mcp.tool()
async def list_common_soc_codes() -> dict[str, Any]:
    """List common SOC code mappings for federal IT and professional services.

    Use these codes with get_wage_data() and other tools. SOC codes are
    6 digits without a dash (e.g., '151252' not '15-1252').

    For the full SOC list: https://www.bls.gov/oes/current/oes_stru.htm
    """
    return {"soc_codes": COMMON_SOC_CODES}


@mcp.tool()
async def list_common_metros() -> dict[str, Any]:
    """List common metro area MSA codes for wage lookups.

    Use these codes with get_wage_data(scope='metro', area_code=...).
    Pass the 5-digit MSA code (the tool auto-pads to 7 characters).

    For the full MSA list: https://www.bls.gov/oes/current/msa_def.htm
    """
    from .constants import COMMON_METROS
    return {"metros": COMMON_METROS}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
