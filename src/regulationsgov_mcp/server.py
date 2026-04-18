# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Regulations.gov MCP server.

Federal rulemaking dockets, documents, public comments, and comment period
tracking. Authentication via REGULATIONS_GOV_API_KEY environment variable.
Falls back to DEMO_KEY (40 req/hr) if not set.

Complements the Federal Register MCP (what was published) by providing the
rulemaking docket structure, public comments, and comment period status.
"""

from __future__ import annotations

import json as _json
import os
import re
import urllib.parse
from datetime import date as _date, datetime as _datetime
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    DOCKET_TYPES,
    DOCUMENT_TYPES,
    MAX_PAGE_SIZE,
    MIN_PAGE_SIZE,
    PROCUREMENT_AGENCIES,
    USER_AGENT,
)

mcp = FastMCP("regulationsgov")


# ---------------------------------------------------------------------------
# Defensive helpers (ported from sam-gov / ecfr / bls-oews hardening)
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(f"{field} exceeds maximum of {hi}. Got {value}. Paginate instead.")
    return value


def _clamp_str_len(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if len(value) > maximum:
        raise ValueError(
            f"{field} exceeds maximum length of {maximum} chars. Got {len(value)}."
        )
    return value


_HTML_MARK_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: Any) -> str:
    if text is None:
        return "(empty body)"
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            text = repr(text)
    if not isinstance(text, str):
        text = str(text)
    if not _HTML_MARK_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    title = _TITLE_RE.search(text)
    if title:
        pieces.append(re.sub(r"\s+", " ", title.group(1)).strip())
    h1 = _H1_RE.search(text)
    if h1:
        h1_text = re.sub(r"\s+", " ", h1.group(1)).strip()
        if h1_text and (not pieces or h1_text != pieces[0]):
            pieces.append(h1_text)
    return " - ".join(pieces) if pieces else "upstream returned HTML page"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SEARCH_TERM_MAX = 500
_ID_MAX_LEN = 128

_YYYYMMDD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YYYYMMDD_HMS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

# Valid sort fields per Regulations.gov API docs
_DOCUMENT_SORT_FIELDS = {
    "postedDate", "lastModifiedDate", "title", "documentId", "commentEndDate",
}
_COMMENT_SORT_FIELDS = {"postedDate", "lastModifiedDate", "documentId"}
_DOCKET_SORT_FIELDS = {"title", "docketId", "lastModifiedDate"}


def _validate_sort(value: Any, *, field: str, valid_fields: set[str]) -> str | None:
    """Validate a sort parameter: optional leading '-' plus a known field name."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string like '-postedDate'.")
    s = value.strip()
    if not s:
        return None
    bare = s[1:] if s.startswith("-") else s
    if bare not in valid_fields:
        sample = ", ".join(sorted(valid_fields))
        raise ValueError(
            f"{field}={value!r} is not a valid sort field. "
            f"Use one of: {sample} (prefix with '-' for descending)."
        )
    return s


def _validate_date_ymd(value: str | None, *, field: str) -> str | None:
    """YYYY-MM-DD with real calendar check. Regulations.gov rejects everything else."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string. Got {type(value).__name__}.")
    s = value.strip()
    if not s:
        return None
    if not _YYYYMMDD_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be YYYY-MM-DD (e.g. '2026-04-18'). "
            f"ISO 8601 with T/Z is rejected by the API."
        )
    try:
        parts = s.split("-")
        _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return s


def _validate_datetime_ymdhms(value: str | None, *, field: str) -> str | None:
    """'YYYY-MM-DD HH:MM:SS' (space-separated). This is a Regulations.gov quirk;
    the modified-date filters require this exact format, not ISO 8601."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a datetime string.")
    s = value.strip()
    if not s:
        return None
    if not _YYYYMMDD_HMS_RE.match(s):
        raise ValueError(
            f"{field}={value!r} must be 'YYYY-MM-DD HH:MM:SS' (space-separated, "
            f"24-hour time, no T or Z). Example: '2026-04-18 14:30:00'. "
            f"ISO 8601 is rejected by the API."
        )
    try:
        _datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"{field}={value!r} is not a valid datetime: {exc}") from exc
    return s


def _check_date_range(
    ge: str | None, le: str | None, *, field_pair: tuple[str, str]
) -> None:
    """Reject a range where the ge bound is after the le bound."""
    if ge and le and ge > le:
        raise ValueError(
            f"{field_pair[0]}={ge!r} is after {field_pair[1]}={le!r}. "
            f"The 'ge' (>=) bound must be <= the 'le' (<=) bound."
        )


def _validate_search_term(value: str | None, *, field: str = "search_term") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    # Check raw value for control chars BEFORE strip() eats \n/\r/\t.
    if _CONTROL_CHARS_RE.search(value) or any(c in value for c in ("\n", "\r", "\t")):
        raise ValueError(
            f"{field}={value!r} contains control characters. Remove them and retry."
        )
    s = value.strip()
    if not s:
        return None
    if len(s) > _SEARCH_TERM_MAX:
        raise ValueError(
            f"{field} exceeds {_SEARCH_TERM_MAX} chars. Regulations.gov silently "
            f"truncates long searches -- narrow your query first."
        )
    return s


_AGENCY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,19}$")


def _validate_agency_id(value: str | None, *, field: str = "agency_id") -> str | None:
    """Agency IDs are short letter-prefixed codes (FAR, DARS, GSA, DoD, etc).

    Empty string is explicitly rejected so that callers do not accidentally
    issue an unfiltered query that returns every document in Regulations.gov
    (verified live: empty string returns ~1.95M records).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    s = value.strip()
    if not s:
        raise ValueError(
            f"{field} cannot be empty. An empty agency_id returns ALL "
            f"documents in Regulations.gov (~1.95M). Pass None to skip the "
            f"filter or a valid agency code like 'FAR', 'DARS', 'GSA'."
        )
    if not _AGENCY_ID_RE.match(s):
        raise ValueError(
            f"{field}={value!r} is not a valid agency code. Agency codes are "
            f"short letter-prefixed strings like 'FAR', 'DARS', 'GSA', 'DoD'."
        )
    return s


_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,%d}$" % (_ID_MAX_LEN - 1))


def _validate_id(value: Any, *, field: str) -> str:
    """Validate a Regulations.gov ID (document_id, docket_id, comment_id).

    IDs look like 'FAR-2023-0008', 'FAR-2023-0008-0023'. Slashes, control
    chars, and path traversal sequences all fail the API differently
    (500/301); pre-reject them so callers get a clear error.
    """
    if value is None:
        raise ValueError(f"{field} is required.")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    # Check raw value for control chars BEFORE strip() eats them.
    if _CONTROL_CHARS_RE.search(value) or any(c in value for c in ("\n", "\r", "\t")):
        raise ValueError(f"{field}={value!r} contains control characters.")
    s = value.strip()
    if not s:
        raise ValueError(f"{field} cannot be empty.")
    if not _ID_SAFE_RE.match(s):
        raise ValueError(
            f"{field}={value!r} contains characters outside [A-Za-z0-9_.-] "
            f"or starts with a non-alphanumeric. Example valid IDs: "
            f"'FAR-2023-0008', 'FAR-2023-0008-0023'."
        )
    return s


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("REGULATIONS_GOV_API_KEY", "").strip() or "DEMO_KEY"


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or getattr(_client, "is_closed", False):
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: Any) -> str:
    cleaned = _clean_error_body(body)
    low = cleaned.lower() if isinstance(cleaned, str) else ""
    if status == 403:
        # 403 from api.data.gov means key rejected. 403 from regulations.gov
        # itself often means the WAF blocked angle brackets / other patterns.
        if "rate" in low or "key" in low or "unauthorized" in low:
            return (
                "HTTP 403: API key rejected or missing. "
                "Set REGULATIONS_GOV_API_KEY env var. "
                "Register free at https://open.gsa.gov/api/regulationsgov/#getting-started"
            )
        return (
            f"HTTP 403: Request blocked. Common cause: Regulations.gov's WAF "
            f"rejects angle brackets and a handful of other patterns. Remove "
            f"special characters from search terms. API response: {cleaned}"
        )
    if status == 429:
        key = _get_api_key()
        limit = "1,000/hr (registered)" if key != "DEMO_KEY" else "40/hr (DEMO_KEY)"
        return (
            f"HTTP 429: Rate limited ({limit}). "
            "Register a free key for 1,000/hr at "
            "https://open.gsa.gov/api/regulationsgov/#getting-started"
        )
    if status == 400:
        if "page" in low and "size" in low:
            return (
                f"HTTP 400: page_size must be {MIN_PAGE_SIZE}-{MAX_PAGE_SIZE}. "
                f"API response: {cleaned}"
            )
        if "page number" in low:
            return (
                f"HTTP 400: page_number out of range. The API caps total "
                f"results around 5,000 (20 pages at page_size=250). For "
                f"larger sets, partition with date ranges. API: {cleaned}"
            )
        if "date" in low:
            return (
                f"HTTP 400: Date format error. postedDate and commentEndDate "
                f"use YYYY-MM-DD. lastModifiedDate requires "
                f"'YYYY-MM-DD HH:MM:SS' (space-separated, no T or Z). "
                f"API response: {cleaned}"
            )
        if "filter" in low:
            return (
                f"HTTP 400: Invalid filter. Values are CASE-SENSITIVE: "
                f"'Proposed Rule' not 'proposed rule', 'Rulemaking' not "
                f"'rulemaking'. API response: {cleaned}"
            )
        if "sort" in low:
            return (
                f"HTTP 400: Invalid sort field. Use one of "
                f"postedDate, lastModifiedDate, title, documentId, "
                f"commentEndDate (prefix with '-' for descending). "
                f"API response: {cleaned}"
            )
        return f"HTTP 400: {cleaned}"
    if status == 404:
        return (
            f"HTTP 404: Resource not found. Verify the ID (e.g. "
            f"'FAR-2023-0008-0001' is documentId; 'FAR-2023-0008' is docketId). "
            f"API response: {cleaned}"
        )
    if status == 503:
        return (
            "HTTP 503: Regulations.gov upstream service unavailable. "
            "This often happens when the request contains characters that "
            "trigger their firewall (SQL keywords, angle brackets). Remove "
            "special characters and retry."
        )
    return f"HTTP {status}: {cleaned}"


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET helper. Returns parsed JSON; empty/null bodies become {}."""
    key = _get_api_key()
    query = dict(params or {})
    query["api_key"] = key
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(query)}"
    try:
        r = await _get_client().get(url)
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling Regulations.gov: {e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text))
    try:
        data = r.json()
    except (ValueError, _json.JSONDecodeError) as e:
        preview = _clean_error_body(r.text or "(empty body)")[:200]
        ct = r.headers.get("content-type", "?")
        raise RuntimeError(
            f"Regulations.gov returned a non-JSON response (status {r.status_code}, "
            f"content-type={ct!r}): {preview}"
        ) from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Regulations.gov returned unexpected JSON type {type(data).__name__}: "
            f"{str(data)[:200]}"
        )
    return data


def _validate_page_size(page_size: Any) -> int:
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        raise ValueError(f"page_size must be an int {MIN_PAGE_SIZE}-{MAX_PAGE_SIZE}.")
    return _clamp(page_size, field="page_size", lo=MIN_PAGE_SIZE, hi=MAX_PAGE_SIZE)


def _validate_page_number(page_number: Any) -> int:
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise ValueError("page_number must be a positive int.")
    # API caps at 20 pages (~5,000 records). Reject up front.
    return _clamp(page_number, field="page_number", lo=1, hi=20)


def _flag_no_data(
    response: dict[str, Any], *, context: str, page_size: int = 25, page_number: int = 1
) -> dict[str, Any]:
    """Add a no_data hint when an agency/id filter silently returns zero,
    OR a paged_past_end hint when the caller walked past the last page."""
    data_items = _as_list(response.get("data"))
    meta = _safe_dict(response.get("meta"))
    total = meta.get("totalElements") if isinstance(meta, dict) else None
    if data_items:
        return response
    response = dict(response)
    if total in (0, None):
        response["no_data"] = True
        response["no_data_reason"] = (
            f"No results for this query ({context}). If you expected results, "
            f"verify: (1) agency_id is the exact code (FAR, DARS, GSA, DoD), "
            f"(2) document_type casing exact ('Proposed Rule' not lowercase), "
            f"(3) date ranges are not inverted. Agency codes are case-insensitive "
            f"at the API; unknown codes silently return zero with no error."
        )
    elif isinstance(total, int) and page_number * page_size > total:
        response["paged_past_end"] = True
        response["paged_past_end_reason"] = (
            f"No data on page {page_number} (page_size={page_size}), but total "
            f"matching records = {total}. You paged past the end. Last page "
            f"with data is page {max(1, (total + page_size - 1) // page_size)}."
        )
    return response


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_documents(
    search_term: str | None = None,
    agency_id: str | None = None,
    document_type: Literal["Proposed Rule", "Rule", "Notice", "Supporting & Related Material", "Other"] | None = None,
    docket_id: str | None = None,
    within_comment_period: bool | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    comment_end_date_ge: str | None = None,
    comment_end_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov documents (proposed rules, final rules, notices).

    Filter values are CASE-SENSITIVE. Use exact casing:
    - document_type: 'Proposed Rule', 'Rule', 'Notice', 'Supporting & Related Material', 'Other'
    - Lowercase values silently return 0 results (no error)

    Key parameters:
    - agency_id: FAR, DARS, GSA, SBA, OFPP, DOD, NASA, VA, etc.
      Empty string is REJECTED (previously returned all 1.95M records).
    - docket_id: e.g., 'FAR-2023-0008' for a specific FAR case
    - within_comment_period: True to find documents currently accepting comments
    - posted_date_ge/le: YYYY-MM-DD format (calendar-checked)
    - comment_end_date_ge/le: YYYY-MM-DD format

    Response includes meta.aggregations with counts by document type, agency,
    and comment period status.

    Page size: 5-250. page_number: 1-20 (API caps total results at ~5,000).
    For larger sets, use date ranges to partition.

    sort: '-postedDate' (newest first, default), 'postedDate', '-commentEndDate',
    'lastModifiedDate', 'title', 'documentId'.
    """
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    if docket_id is not None and docket_id != "":
        docket_id = _validate_id(docket_id, field="docket_id")
    elif docket_id == "":
        docket_id = None
    posted_date_ge = _validate_date_ymd(posted_date_ge, field="posted_date_ge")
    posted_date_le = _validate_date_ymd(posted_date_le, field="posted_date_le")
    comment_end_date_ge = _validate_date_ymd(comment_end_date_ge, field="comment_end_date_ge")
    comment_end_date_le = _validate_date_ymd(comment_end_date_le, field="comment_end_date_le")
    _check_date_range(posted_date_ge, posted_date_le,
                      field_pair=("posted_date_ge", "posted_date_le"))
    _check_date_range(comment_end_date_ge, comment_end_date_le,
                      field_pair=("comment_end_date_ge", "comment_end_date_le"))
    sort = _validate_sort(sort, field="sort", valid_fields=_DOCUMENT_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if document_type:
        params["filter[documentType]"] = document_type
    if docket_id:
        params["filter[docketId]"] = docket_id
    if within_comment_period is not None:
        params["filter[withinCommentPeriod]"] = str(within_comment_period).lower()
    if posted_date_ge:
        params["filter[postedDate][ge]"] = posted_date_ge
    if posted_date_le:
        params["filter[postedDate][le]"] = posted_date_le
    if comment_end_date_ge:
        params["filter[commentEndDate][ge]"] = comment_end_date_ge
    if comment_end_date_le:
        params["filter[commentEndDate][le]"] = comment_end_date_le

    result = await _get("documents", params)
    ctx = f"agency_id={agency_id!r}, document_type={document_type!r}"
    return _flag_no_data(result, context=ctx, page_size=page_size, page_number=page_number)


@mcp.tool()
async def get_document_detail(
    document_id: str,
    include_attachments: bool = False,
) -> dict[str, Any]:
    """Get full details for a single Regulations.gov document.

    Returns fileFormats (download URLs), cfrPart, displayProperties, and
    other detail fields not available in search results.

    Set include_attachments=True to get attachment objects with download URLs.

    document_id format: FAR-2023-0008-0023
    """
    document_id = _validate_id(document_id, field="document_id")
    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"
    return await _get(f"documents/{document_id}", params)


@mcp.tool()
async def search_comments(
    search_term: str | None = None,
    agency_id: str | None = None,
    comment_on_id: str | None = None,
    docket_id: str | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search public comments on Regulations.gov.

    To find comments on a specific document, use comment_on_id with the
    hex objectId from document search results (NOT the human-readable
    documentId).

    docket_id can also filter comments to all documents in a docket.

    Page size: 5-250. Comments sorted by '-postedDate' by default.
    """
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    if comment_on_id is not None and comment_on_id != "":
        comment_on_id = _validate_id(comment_on_id, field="comment_on_id")
    elif comment_on_id == "":
        comment_on_id = None
    if docket_id is not None and docket_id != "":
        docket_id = _validate_id(docket_id, field="docket_id")
    elif docket_id == "":
        docket_id = None
    posted_date_ge = _validate_date_ymd(posted_date_ge, field="posted_date_ge")
    posted_date_le = _validate_date_ymd(posted_date_le, field="posted_date_le")
    _check_date_range(posted_date_ge, posted_date_le,
                      field_pair=("posted_date_ge", "posted_date_le"))
    sort = _validate_sort(sort, field="sort", valid_fields=_COMMENT_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if comment_on_id:
        params["filter[commentOnId]"] = comment_on_id
    if docket_id:
        params["filter[docketId]"] = docket_id
    if posted_date_ge:
        params["filter[postedDate][ge]"] = posted_date_ge
    if posted_date_le:
        params["filter[postedDate][le]"] = posted_date_le

    result = await _get("comments", params)
    ctx = f"agency_id={agency_id!r}, docket_id={docket_id!r}"
    return _flag_no_data(result, context=ctx, page_size=page_size, page_number=page_number)


@mcp.tool()
async def get_comment_detail(
    comment_id: str,
    include_attachments: bool = False,
) -> dict[str, Any]:
    """Get full details for a single comment.

    Returns the full comment text, organization, submitter info (if public),
    tracking number, and duplicate comment count.

    Some fields (firstName, lastName, organization) are agency-configurable
    and may be hidden.
    """
    comment_id = _validate_id(comment_id, field="comment_id")
    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"
    return await _get(f"comments/{comment_id}", params)


@mcp.tool()
async def search_dockets(
    search_term: str | None = None,
    agency_id: str | None = None,
    docket_type: Literal["Rulemaking", "Nonrulemaking"] | None = None,
    last_modified_date_ge: str | None = None,
    last_modified_date_le: str | None = None,
    sort: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov dockets.

    Dockets are containers for related regulatory documents (proposed rules,
    comments, supporting materials). FAR cases, DFARS cases, and agency
    rulemaking actions each have a docket.

    docket_type is CASE-SENSITIVE: 'Rulemaking' or 'Nonrulemaking'.

    lastModifiedDate format: 'YYYY-MM-DD HH:MM:SS' (space-separated, NOT ISO).
    This is a Regulations.gov quirk; ISO 8601 is rejected.

    Limited filters: only searchTerm, agencyId, docketType, lastModifiedDate.
    """
    page_size = _validate_page_size(page_size)
    page_number = _validate_page_number(page_number)
    search_term = _validate_search_term(search_term, field="search_term")
    agency_id = _validate_agency_id(agency_id, field="agency_id")
    last_modified_date_ge = _validate_datetime_ymdhms(
        last_modified_date_ge, field="last_modified_date_ge"
    )
    last_modified_date_le = _validate_datetime_ymdhms(
        last_modified_date_le, field="last_modified_date_le"
    )
    _check_date_range(
        last_modified_date_ge, last_modified_date_le,
        field_pair=("last_modified_date_ge", "last_modified_date_le"),
    )
    sort = _validate_sort(sort, field="sort", valid_fields=_DOCKET_SORT_FIELDS)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
    }
    if sort:
        params["sort"] = sort
    if search_term:
        params["filter[searchTerm]"] = search_term
    if agency_id:
        params["filter[agencyId]"] = agency_id
    if docket_type:
        params["filter[docketType]"] = docket_type
    if last_modified_date_ge:
        params["filter[lastModifiedDate][ge]"] = last_modified_date_ge
    if last_modified_date_le:
        params["filter[lastModifiedDate][le]"] = last_modified_date_le

    result = await _get("dockets", params)
    ctx = f"agency_id={agency_id!r}, docket_type={docket_type!r}"
    return _flag_no_data(result, context=ctx, page_size=page_size, page_number=page_number)


@mcp.tool()
async def get_docket_detail(docket_id: str) -> dict[str, Any]:
    """Get full details for a single docket.

    Returns title, abstract, RIN (links to Unified Agenda), agency,
    keywords, and modification date.

    docket_id format: FAR-2023-0008, DARS-2025-0071, SBA-2024-0002
    """
    docket_id = _validate_id(docket_id, field="docket_id")
    return await _get(f"dockets/{docket_id}")


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def open_comment_periods(
    agency_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Find documents with currently open comment periods.

    Searches for documents where withinCommentPeriod=true, sorted by
    soonest closing deadline. Returns document IDs, titles, agencies,
    comment end dates, and docket IDs.

    Default searches FAR, DARS, GSA, SBA, OFPP, DOD, NASA, VA.
    Pass agency_ids to narrow or expand the scope. An empty list is
    rejected; pass None to use the defaults.
    """
    import asyncio

    if agency_ids is not None:
        if not isinstance(agency_ids, list):
            raise ValueError("agency_ids must be a list of agency codes.")
        if len(agency_ids) == 0:
            raise ValueError(
                "agency_ids cannot be empty. Pass None to use the default "
                "procurement-agency list, or a non-empty list of codes like "
                "['FAR', 'DARS']."
            )
        if len(agency_ids) > 20:
            raise ValueError(
                f"agency_ids capped at 20 entries (got {len(agency_ids)}). "
                f"Each entry costs a round-trip."
            )
        validated = []
        for i, a in enumerate(agency_ids):
            validated.append(_validate_agency_id(a, field=f"agency_ids[{i}]"))
        agencies = validated
    else:
        agencies = list(PROCUREMENT_AGENCIES)

    all_docs: list[dict[str, Any]] = []
    errors_by_agency: dict[str, str] = {}

    for agency in agencies:
        try:
            result = await search_documents(
                agency_id=agency,
                within_comment_period=True,
                sort="-commentEndDate",
                page_size=50,
            )
            for item in _as_list(result.get("data")):
                item = _safe_dict(item)
                attrs = _safe_dict(item.get("attributes"))
                all_docs.append({
                    "document_id": item.get("id"),
                    "agency": attrs.get("agencyId"),
                    "title": attrs.get("title"),
                    "document_type": attrs.get("documentType"),
                    "comment_end_date": attrs.get("commentEndDate"),
                    "docket_id": attrs.get("docketId"),
                    "url": f"https://www.regulations.gov/document/{item.get('id')}",
                })
        except Exception as e:
            errors_by_agency[agency] = str(e)[:200]
        await asyncio.sleep(0.5)

    valid = [d for d in all_docs if d.get("comment_end_date")]
    valid.sort(key=lambda x: x["comment_end_date"] or "")

    response: dict[str, Any] = {
        "agencies_searched": agencies,
        "total_open": len(valid),
        "documents": valid,
    }
    if errors_by_agency:
        response["errors_by_agency"] = errors_by_agency
    return response


@mcp.tool()
async def far_case_history(docket_id: str) -> dict[str, Any]:
    """Get the full lifecycle of a FAR/DFARS rulemaking case.

    Fetches the docket metadata (title, abstract, RIN) plus all documents
    filed under the docket, sorted by most recent first.

    docket_id examples: FAR-2023-0008, DARS-2025-0071

    Returns the docket abstract, RIN (links to Unified Agenda), and all
    documents with their types, dates, and URLs.
    """
    docket_id = _validate_id(docket_id, field="docket_id")

    import asyncio
    docket = await get_docket_detail(docket_id)
    docket_attrs = _safe_dict(_safe_dict(docket.get("data")).get("attributes"))

    await asyncio.sleep(0.5)

    docs_result = await search_documents(
        docket_id=docket_id,
        sort="-postedDate",
        page_size=250,
    )

    documents = []
    for item in _as_list(docs_result.get("data")):
        item = _safe_dict(item)
        attrs = _safe_dict(item.get("attributes"))
        documents.append({
            "document_id": item.get("id"),
            "document_type": attrs.get("documentType"),
            "title": attrs.get("title"),
            "posted_date": attrs.get("postedDate"),
            "comment_end_date": attrs.get("commentEndDate"),
            "within_comment_period": attrs.get("withinCommentPeriod"),
            "url": f"https://www.regulations.gov/document/{item.get('id')}",
        })

    return {
        "docket_id": docket_id,
        "title": docket_attrs.get("title"),
        "abstract": docket_attrs.get("dkAbstract"),
        "rin": docket_attrs.get("rin"),
        "agency": docket_attrs.get("agencyId"),
        "total_documents": _safe_dict(docs_result.get("meta")).get(
            "totalElements", len(documents)
        ),
        "documents": documents,
        "url": f"https://www.regulations.gov/docket/{docket_id}",
    }


# ---------------------------------------------------------------------------
# Strict parameter validation (cross-fix from sam-gov-mcp 0.3.1)
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    FastMCP's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_documents(keyword='audit') (real
    param is `search_term`) succeeded with the typo silently discarded,
    returning unfiltered data. extra='forbid' raises "Extra inputs are
    not permitted" on typos before any HTTP call.
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
    mcp.run()


if __name__ == "__main__":
    main()
