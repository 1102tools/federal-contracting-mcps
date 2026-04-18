# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
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
import re
from typing import Any, Literal, Union

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL_V1,
    BASE_URL_V2,
    COMMON_SOC_CODES,
    COUNT_DATATYPES,
    DATATYPE_LABELS,
    DEFAULT_TIMEOUT,
    FULL_DATATYPES,
    HOURLY_DATATYPES,
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
# Validators and normalizers
# ---------------------------------------------------------------------------

# ASCII-only digit regex (Python's .isdigit() accepts Unicode digits like fullwidth)
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_DATATYPE_RE = re.compile(r"^[0-9]{2}$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")

# OEWS data is available from 1997 onward (earliest published year).
OEWS_EARLIEST_YEAR = 1997
OEWS_LATEST_FUTURE_YEAR = 2100  # generous upper bound


def _as_list(value: Any) -> list[Any]:
    """Normalize XML-to-JSON single-item collapse. BLS (and any SOAP-backed API)
    sometimes returns a lone dict where a list is expected."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_str_digits(value: Any, *, field: str, length: int | None = None) -> str:
    """Coerce a numeric-looking value (int or str) to an ASCII-digit string.

    Rejects Unicode digits (fullwidth, etc), whitespace, dashes. If length is
    given, enforces exact length after stripping."""
    if value is None:
        raise ValueError(f"{field} cannot be None.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer or digit-string, not bool.")
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.strip()
    else:
        raise ValueError(f"{field} must be an integer or string. Got {type(value).__name__}.")
    if not s:
        raise ValueError(f"{field} cannot be empty.")
    if not _ASCII_DIGITS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must contain only ASCII digits 0-9 "
            f"(no dashes, letters, whitespace, or Unicode digit characters)."
        )
    if length is not None and len(s) != length:
        raise ValueError(
            f"{field}={value!r} must be exactly {length} digits. Got {len(s)}."
        )
    return s


def _validate_soc(value: Any, *, field: str = "occ_code") -> str:
    """Validate a SOC code: exactly 6 ASCII digits. No dash (use '151252' not '15-1252')."""
    return _coerce_str_digits(value, field=field, length=6)


def _validate_industry(value: Any, *, field: str = "industry") -> str:
    """Validate a 6-digit NAICS-like industry code."""
    return _coerce_str_digits(value, field=field, length=6)


def _validate_datatype(value: Any, *, field: str = "datatype") -> str:
    """Validate a 2-digit datatype code. Accepts int or str."""
    s = _coerce_str_digits(value, field=field, length=2)
    if s not in DATATYPE_LABELS:
        sample = ", ".join(sorted(DATATYPE_LABELS.keys()))
        raise ValueError(
            f"{field}={value!r} is not a known OEWS datatype. Valid: {sample}."
        )
    return s


def _validate_year(value: Any, *, field: str = "year") -> str:
    """Validate a 4-digit year in OEWS range. Accepts int or str (stripped)."""
    if value is None:
        return str(OEWS_CURRENT_YEAR)
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a year, not bool.")
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.strip()
    else:
        raise ValueError(f"{field} must be an integer or year-string. Got {type(value).__name__}.")
    if not s:
        return str(OEWS_CURRENT_YEAR)
    if not _YEAR_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be a 4-digit year (e.g. '2024' or 2024). "
            f"Decimals, whitespace, and leading zeros beyond 4 digits are rejected."
        )
    y = int(s)
    if y < OEWS_EARLIEST_YEAR or y > OEWS_LATEST_FUTURE_YEAR:
        raise ValueError(
            f"{field}={y} is out of OEWS range. "
            f"Valid years: {OEWS_EARLIEST_YEAR}..{OEWS_LATEST_FUTURE_YEAR}. "
            f"OEWS data currently lags ~2 years; default is {OEWS_CURRENT_YEAR}."
        )
    return s


def _normalize_whitespace_str(value: Any) -> str | None:
    """Strip and normalize an arbitrary str-like value, or return None."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return str(value).strip() or None


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML bodies from upstream error responses so error messages stay readable."""
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
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str | None:
    """Read BLS API key from environment. None = v1 (25/day).

    Whitespace-only values are treated as unset (silent downgrade to v1). Callers
    that need to know whether a key was intentionally provided should use
    _api_key_status() instead.
    """
    key = os.environ.get("BLS_API_KEY", "").strip()
    return key if key else None


def _api_key_status() -> dict[str, Any]:
    """Report whether API key was set, empty, whitespace-only, or absent."""
    raw = os.environ.get("BLS_API_KEY")
    if raw is None:
        return {"set": False, "mode": "v1", "note": "BLS_API_KEY not set (v1, 25/day)"}
    stripped = raw.strip()
    if not stripped:
        return {
            "set": True, "mode": "v1",
            "note": "BLS_API_KEY is set but empty/whitespace-only; using v1 (25/day).",
        }
    return {"set": True, "mode": "v2", "note": "v2 mode (500/day)"}


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
    cleaned = _clean_error_body(body)
    if status == 429:
        key = _get_api_key()
        limit = "500/day (v2)" if key else "25/day (v1)"
        return (
            f"HTTP 429: BLS rate limit exceeded ({limit}). "
            "Wait until tomorrow or register a free v2 key at "
            "https://data.bls.gov/registrationEngine/ for 500 queries/day."
        )
    if status == 400:
        return f"HTTP 400: Bad request. Check series ID format (must be exactly 25 chars). API response: {cleaned}"
    if status == 403:
        return (
            "HTTP 403: Forbidden. Your BLS API key may be invalid. "
            "Register a free key at https://data.bls.gov/registrationEngine/"
        )
    return f"HTTP {status}: {cleaned}"


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

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            body_preview = _clean_error_body(r.text or "(empty body)")
            raise RuntimeError(
                f"BLS returned non-JSON response on 200 OK. "
                f"This often happens during API maintenance or when an HTML "
                f"error page is served without an error status. "
                f"Body: {body_preview}"
            ) from e

        if not isinstance(data, dict):
            raise RuntimeError(
                f"BLS response was not a JSON object. Got {type(data).__name__}: {str(data)[:200]}"
            )

        status = data.get("status")
        if status == "REQUEST_NOT_PROCESSED":
            messages = data.get("message", [])
            raise RuntimeError(
                f"BLS API refused the request: {messages}. "
                "Common cause: rate limit exceeded or malformed series IDs."
            )
        if status == "REQUEST_PARTIALLY_PROCESSED":
            # Surface the warnings so caller knows some series failed.
            messages = data.get("message", [])
            data["_partial"] = True
            data["_warnings"] = messages
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


def _normalize_area(area_input: Any) -> str:
    """Convert 2-digit FIPS, 5-digit MSA, or 7-digit full code to 7-char format.

    Requires ASCII digits only; rejects letters, unicode digits, whitespace.
    """
    if area_input is None:
        raise ValueError("area_code cannot be None.")
    if isinstance(area_input, int):
        area = str(area_input)
    else:
        area = str(area_input).strip()
    if not area:
        raise ValueError("area_code cannot be empty.")
    if not _ASCII_DIGITS_RE.match(area):
        raise ValueError(
            f"area_code={area_input!r} must contain only ASCII digits 0-9. "
            f"Got characters other than digits."
        )
    if len(area) == 7:
        return area
    if len(area) == 5:
        return f"00{area}"
    if len(area) == 2:
        return f"{area}00000"
    raise ValueError(
        f"Unrecognized area code '{area}' (length {len(area)}). "
        "Expected: 2-digit state FIPS (e.g., '51'), 5-digit MSA (e.g., '47900'), "
        "or 7-digit full code (e.g., '0047900')."
    )


def _parse_value(value: Any, datatype: str, footnotes: list[str] | None = None) -> dict[str, Any]:
    """Parse a BLS data value, handling special codes and unusual types."""
    # Normalize: str-coerce non-strings, strip whitespace (BLS sometimes pads)
    if value is None:
        return {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}
    raw = value
    if isinstance(value, str):
        stripped = value.strip()
    else:
        stripped = str(value).strip()

    if stripped in SPECIAL_VALUES or stripped == "":
        msg = f"[Capped] {footnotes[0]}" if footnotes else f"[Suppressed: {stripped or '(empty)'}]"
        return {"raw": raw, "formatted": msg, "numeric": None, "suppressed": True}

    try:
        if datatype in COUNT_DATATYPES:
            n = int(float(stripped))
            return {"raw": raw, "formatted": f"{n:,}", "numeric": n, "suppressed": False}
        elif datatype in HOURLY_DATATYPES:
            n = float(stripped)
            return {"raw": raw, "formatted": f"${n:,.2f}/hr", "numeric": n, "suppressed": False}
        else:
            n = int(float(stripped))
            return {"raw": raw, "formatted": f"${n:,}", "numeric": n, "suppressed": False}
    except (ValueError, TypeError):
        return {"raw": raw, "formatted": f"[Unparseable: {stripped}]", "numeric": None, "suppressed": False}


def _extract_first_data_entry(series_item: Any) -> dict[str, Any] | None:
    """Safely pull the first data entry from a series response, tolerating
    XML-to-JSON collapse, None entries, and missing keys. Returns None if no
    valid entry exists.
    """
    if not isinstance(series_item, dict):
        return None
    data = _as_list(series_item.get("data"))
    for entry in data:
        if isinstance(entry, dict):
            return entry
    return None


def _safe_footnotes(entry: dict[str, Any]) -> list[str]:
    """Extract footnote text strings, tolerating dict/str/None footnotes fields."""
    raw = entry.get("footnotes")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    items = _as_list(raw)
    out: list[str] = []
    for f in items:
        if isinstance(f, dict):
            text = f.get("text")
            if text:
                out.append(text)
        elif isinstance(f, str) and f.strip():
            out.append(f)
    return out


def _series_id_from(series_item: Any, fallback: str = "") -> str:
    """Extract seriesID from a series response item, tolerating int/missing."""
    if not isinstance(series_item, dict):
        return fallback
    sid = series_item.get("seriesID")
    if sid is None:
        return fallback
    return str(sid)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_wage_data(
    occ_code: Union[str, int],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    industry: Union[str, int] = "000000",
    datatypes: list[str] | None = None,
    year: Union[str, int, None] = None,
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
    occ_code = _validate_soc(occ_code)
    industry = _validate_industry(industry)
    year = _validate_year(year)

    if datatypes is None:
        datatypes = list(IGCE_DATATYPES)
    if not datatypes:
        raise ValueError(
            "datatypes cannot be empty. Pass None for defaults or specify at least one code."
        )
    validated_datatypes = [_validate_datatype(dt, field="datatypes[i]") for dt in datatypes]
    # Dedup while preserving order
    seen: set[str] = set()
    validated_datatypes = [x for x in validated_datatypes if not (x in seen or seen.add(x))]

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        if area_code is not None:
            # area_code is ignored at national scope; keep quiet but flag in response
            pass
        area = "0000000"
    else:
        if area_code is None or (isinstance(area_code, str) and not area_code.strip()):
            raise ValueError(f"area_code is required for scope='{scope}'.")
        area = _normalize_area(area_code)

    if industry != "000000" and scope != "national":
        raise ValueError(
            "Industry-specific estimates are only available at the national level "
            "(scope='national'). Cannot combine state/metro scope with industry filter."
        )

    series_ids = [_build_series_id(prefix, area, industry, occ_code, dt) for dt in validated_datatypes]
    data = await _query_bls(series_ids, start_year=year)

    results: dict[str, Any] = {}
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        dt = sid[-2:] if sid else ""
        label = DATATYPE_LABELS.get(dt, dt or "unknown")
        entry = _extract_first_data_entry(series)
        if entry:
            footnotes = _safe_footnotes(entry)
            results[label] = _parse_value(entry.get("value"), dt, footnotes)
            year_val = entry.get("year")
            period_val = entry.get("periodName")
            if year_val is not None:
                results["_data_year"] = str(year_val)
            if period_val is not None:
                results["_period"] = str(period_val)
        else:
            results[label] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    response: dict[str, Any] = {
        "occ_code": occ_code,
        "scope": scope,
        "area_code": area_code if scope != "national" else None,
        "industry": industry,
        "wages": results,
    }
    if scope == "national" and area_code is not None:
        response["_note"] = (
            f"area_code={area_code!r} was ignored because scope='national'. "
            "Use scope='state' or scope='metro' for geographic breakdowns."
        )
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    return response


@mcp.tool()
async def compare_metros(
    occ_code: Union[str, int],
    metro_codes: list[Union[str, int]],
    datatype: Union[str, int] = "04",
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Compare wages for one occupation across multiple metro areas.

    Pass a list of 5-digit MSA codes (e.g., ['47900', '42660', '12580']
    for DC, Seattle, Baltimore). Returns the specified wage measure for
    each metro. Use list_common_metros() to find codes.

    datatype: '04' (Annual Mean, default), '13' (Median), '03' (Hourly Mean).

    Max ~12 metros per call (each metro = 1 series, 50 series limit on v2).
    """
    occ_code = _validate_soc(occ_code)
    datatype = _validate_datatype(datatype)
    year = _validate_year(year)
    if not metro_codes:
        raise ValueError("metro_codes list cannot be empty.")

    # Dedup metros while preserving order (first occurrence wins)
    deduped: list[Any] = []
    seen: set[str] = set()
    for code in metro_codes:
        key = str(code).strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(code)

    series_ids: list[str] = []
    metro_labels: dict[str, str] = {}
    for code in deduped:
        area = _normalize_area(code)
        sid = _build_series_id("OEUM", area, "000000", occ_code, datatype)
        series_ids.append(sid)
        metro_labels[sid] = str(code).strip()

    data = await _query_bls(series_ids, start_year=year)

    metros: dict[str, Any] = {}
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        code = metro_labels.get(sid, sid or "unknown")
        entry = _extract_first_data_entry(series)
        if entry:
            metros[code] = _parse_value(entry.get("value"), datatype, _safe_footnotes(entry))
        else:
            metros[code] = {"raw": None, "formatted": "No data", "numeric": None, "suppressed": True}

    response: dict[str, Any] = {
        "occ_code": occ_code,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "metros": metros,
    }
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    return response


@mcp.tool()
async def compare_occupations(
    occ_codes: list[Union[str, int]],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    datatype: Union[str, int] = "04",
    year: Union[str, int, None] = None,
) -> dict[str, Any]:
    """Compare wages across multiple occupations in one location.

    Pass a list of 6-digit SOC codes. Returns the specified wage measure
    for each occupation. Use list_common_soc_codes() to find codes.

    Max ~12 occupations per call.
    """
    if not occ_codes:
        raise ValueError("occ_codes list cannot be empty.")

    datatype = _validate_datatype(datatype)
    year = _validate_year(year)

    prefix_map = {"national": "OEUN", "state": "OEUS", "metro": "OEUM"}
    prefix = prefix_map[scope]

    if scope == "national":
        area = "0000000"
    else:
        if area_code is None or (isinstance(area_code, str) and not area_code.strip()):
            raise ValueError(f"area_code required for scope='{scope}'.")
        area = _normalize_area(area_code)

    # Dedup while preserving order
    seen: set[str] = set()
    deduped: list[Any] = []
    for code in occ_codes:
        key = str(code).strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(code)

    series_ids: list[str] = []
    occ_labels: dict[str, str] = {}
    for code in deduped:
        validated = _validate_soc(code)
        sid = _build_series_id(prefix, area, "000000", validated, datatype)
        series_ids.append(sid)
        occ_labels[sid] = validated

    data = await _query_bls(series_ids, start_year=year)

    occupations: dict[str, Any] = {}
    series_list = _as_list(data.get("Results", {}).get("series"))
    for series in series_list:
        if not isinstance(series, dict):
            continue
        sid = _series_id_from(series)
        code = occ_labels.get(sid, sid or "unknown")
        label = COMMON_SOC_CODES.get(code, code)
        entry = _extract_first_data_entry(series)
        if entry:
            occupations[f"{code} ({label})"] = _parse_value(
                entry.get("value"), datatype, _safe_footnotes(entry)
            )
        else:
            occupations[f"{code} ({label})"] = {
                "raw": None, "formatted": "No data", "numeric": None, "suppressed": True,
            }

    response: dict[str, Any] = {
        "scope": scope,
        "area_code": area_code if scope != "national" else None,
        "datatype": DATATYPE_LABELS.get(datatype, datatype),
        "occupations": occupations,
    }
    if data.get("_partial"):
        response["_partial"] = True
        response["_warnings"] = data.get("_warnings", [])
    return response


@mcp.tool()
async def igce_wage_benchmark(
    occ_code: Union[str, int],
    scope: Literal["national", "state", "metro"] = "national",
    area_code: Union[str, int, None] = None,
    burden_low: float = 1.8,
    burden_high: float = 2.2,
    year: Union[str, int, None] = None,
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

    Burden multipliers must be positive and burden_low <= burden_high.
    Reasonable range: 1.3 (lean) to 4.0 (high-overhead/clearance).
    """
    if not isinstance(burden_low, (int, float)) or not isinstance(burden_high, (int, float)):
        raise ValueError("burden_low and burden_high must be numeric.")
    if burden_low <= 0 or burden_high <= 0:
        raise ValueError(
            f"Burden multipliers must be positive. Got low={burden_low}, high={burden_high}."
        )
    if burden_low > burden_high:
        raise ValueError(
            f"burden_low ({burden_low}) must be <= burden_high ({burden_high})."
        )
    if burden_high > 10.0:
        raise ValueError(
            f"burden_high={burden_high} is implausibly large. "
            f"Reasonable max ~4.0x for high-overhead (SCIF/deployed) work."
        )

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
        series_list = _as_list(data.get("Results", {}).get("series"))
        for s in series_list:
            entry = _extract_first_data_entry(s)
            if entry and str(entry.get("value", "")).strip() not in SPECIAL_VALUES:
                return {
                    "latest_year": candidate,
                    "default_year": current,
                    "newer_data_available": True,
                    "message": f"OEWS {candidate} data is available. Use year='{candidate}' for the latest estimates.",
                }
    except Exception as e:
        # Don't silently eat the error: surface it so user knows probing failed
        return {
            "latest_year": current,
            "default_year": current,
            "newer_data_available": False,
            "probe_error": str(e),
            "message": (
                f"Could not probe for newer data (reason: {type(e).__name__}). "
                f"Defaulting to OEWS {current}. Rate limit, key issue, or BLS downtime "
                f"can all cause this. Call again later to check."
            ),
        }

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
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    FastMCP's default is extra='ignore', which silently drops unknown
    parameter names. A typo like get_wage_data(ocupation_code='15-1252')
    (with the real parameter soc_code) would succeed with the typo
    silently discarded, returning default-filter data with no indication
    of the problem. extra='forbid' surfaces typos immediately with
    "Extra inputs are not permitted".
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
