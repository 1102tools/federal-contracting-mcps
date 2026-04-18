# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Federal Register MCP server.

Free, no-auth access to all Federal Register content since 1994: proposed
rules, final rules, notices, presidential documents, and corrections.

Complements eCFR (what the regulation currently says) by showing what is
changing, what has changed, and what comment periods are open.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_FIELDS,
    DEFAULT_TIMEOUT,
    FACET_NAMES,
    USER_AGENT,
)

mcp = FastMCP("federal-register")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EARLIEST_FR_DATE = "1994-01-01"


def _validate_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not _DATE_RE.match(value):
        raise ValueError(
            f"{field_name} must be in YYYY-MM-DD format (e.g. '2026-01-15'). "
            f"Got {value!r}. ISO 8601 datetimes and 'YYYY/MM/DD' are rejected."
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}={value!r} is not a valid calendar date: {exc}") from exc
    return value


def _clamp(value: int, *, field: str, lo: int, hi: int) -> int:
    if value < lo:
        raise ValueError(f"{field} must be >= {lo}. Got {value}.")
    if value > hi:
        raise ValueError(
            f"{field} exceeds maximum of {hi}. Got {value}. Paginate with 'page' instead."
        )
    return value


def _reject_empty_list(value: list[Any] | None, field: str) -> list[Any] | None:
    if value is None:
        return None
    if len(value) == 0:
        raise ValueError(
            f"{field}=[] is silently ignored by the API (matches everything). "
            f"Omit {field} entirely to search without it."
        )
    return value


def _check_date_range(gte: str | None, lte: str | None, field_pair: str) -> None:
    if gte and lte and gte > lte:
        raise ValueError(
            f"{field_pair}: gte ({gte}) is after lte ({lte}). "
            f"Check parameter order (gte = start / lte = end)."
        )


def _strip_or_none(value: str | None) -> str | None:
    """Normalize whitespace-only strings to None. Trim leading/trailing space."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _require_min_length(value: str, *, field: str, minimum: int) -> str:
    stripped = value.strip()
    if len(stripped) < minimum:
        raise ValueError(
            f"{field} must be at least {minimum} characters after trimming whitespace. "
            f"Got {value!r} ({len(stripped)} chars). Short queries match too broadly "
            f"and return unrelated results."
        )
    return stripped


def _clamp_str_len(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if len(value) > maximum:
        raise ValueError(
            f"{field} exceeds maximum length of {maximum} chars. "
            f"Got {len(value)}. Very long query strings cause HTTP 414 errors."
        )
    return value


_DOC_NUMBER_RE = re.compile(r"^(?:C\d-)?\d{4}-\d{5}$")


def _validate_doc_number(value: str, *, field: str = "document_number") -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} cannot be empty.")
    if not _DOC_NUMBER_RE.match(stripped):
        raise ValueError(
            f"{field}={value!r} has invalid format. "
            f"Expected 'YYYY-NNNNN' (e.g. '2026-07731') or 'CN-YYYY-NNNNN' for corrections."
        )
    return stripped


def _warn_pre_fr_date(value: str | None, field: str) -> str | None:
    """Dates before 1994 return nothing useful; reject with actionable message."""
    if value is None:
        return None
    if value < _EARLIEST_FR_DATE:
        raise ValueError(
            f"{field}={value!r} predates the Federal Register API (earliest date: "
            f"{_EARLIEST_FR_DATE}). The API will return empty results for pre-1994 dates."
        )
    return value


_HTML_ERROR_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: str) -> str:
    """Strip HTML from upstream error bodies so error messages stay readable."""
    if not _HTML_ERROR_RE.search(text):
        return text[:400]
    pieces: list[str] = []
    title = _TITLE_RE.search(text)
    if title:
        pieces.append(title.group(1).strip())
    h1 = _H1_RE.search(text)
    if h1 and (not title or h1.group(1).strip() != title.group(1).strip()):
        pieces.append(h1.group(1).strip())
    return " - ".join(pieces) if pieces else "upstream returned HTML error page"


# ---------------------------------------------------------------------------
# HTTP
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
    if status == 404:
        return (
            f"HTTP 404: Resource not found. For get_document/get_documents_batch, "
            f"verify the document_number. For other endpoints the path may be invalid. "
            f"API response: {cleaned}"
        )
    if status == 414:
        return (
            f"HTTP 414: Request URI too long. "
            f"Shorten long query strings (term, docket_id, regulation_id_number)."
        )
    if status == 422:
        return (
            f"HTTP 422: Invalid parameters. Check agency slugs, document type codes "
            f"(PRORULE, RULE, NOTICE, PRESDOCU), date formats (YYYY-MM-DD), "
            f"and field names. API response: {cleaned}"
        )
    if status == 429:
        return "HTTP 429: Rate limited. Add delays between requests."
    return f"HTTP {status}: {cleaned}"


async def _get(url: str) -> Any:
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling Federal Register: {e}") from e


def _build_search_params(
    *,
    agencies: list[str] | None = None,
    doc_types: list[str] | None = None,
    term: str | None = None,
    docket_id: str | None = None,
    regulation_id_number: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
    comment_date_gte: str | None = None,
    comment_date_lte: str | None = None,
    effective_date_gte: str | None = None,
    effective_date_lte: str | None = None,
    correction: bool | None = None,
    significant: bool | None = None,
    fields: list[str] | None = None,
    per_page: int = 20,
    page: int = 1,
    order: str = "newest",
) -> str:
    params: list[tuple[str, str]] = []

    if agencies:
        for a in agencies:
            params.append(("conditions[agencies][]", a))
    if doc_types:
        for t in doc_types:
            params.append(("conditions[type][]", t))
    if term:
        params.append(("conditions[term]", term))
    if docket_id:
        params.append(("conditions[docket_id]", docket_id))
    if regulation_id_number:
        params.append(("conditions[regulation_id_number]", regulation_id_number))
    if pub_date_gte:
        params.append(("conditions[publication_date][gte]", pub_date_gte))
    if pub_date_lte:
        params.append(("conditions[publication_date][lte]", pub_date_lte))
    if comment_date_gte:
        params.append(("conditions[comment_date][gte]", comment_date_gte))
    if comment_date_lte:
        params.append(("conditions[comment_date][lte]", comment_date_lte))
    if effective_date_gte:
        params.append(("conditions[effective_date][gte]", effective_date_gte))
    if effective_date_lte:
        params.append(("conditions[effective_date][lte]", effective_date_lte))
    if correction is not None:
        params.append(("conditions[correction]", "1" if correction else "0"))
    if significant is not None:
        params.append(("conditions[significant]", "1" if significant else "0"))

    for f in (fields or DEFAULT_FIELDS):
        params.append(("fields[]", f))

    params.append(("per_page", str(per_page)))
    params.append(("page", str(page)))
    params.append(("order", order))

    return urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_documents(
    agencies: list[str] | None = None,
    doc_types: list[Literal["PRORULE", "RULE", "NOTICE", "PRESDOCU"]] | None = None,
    term: str | None = None,
    docket_id: str | None = None,
    regulation_id_number: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
    comment_date_gte: str | None = None,
    comment_date_lte: str | None = None,
    effective_date_gte: str | None = None,
    effective_date_lte: str | None = None,
    correction: bool | None = None,
    significant: bool | None = None,
    per_page: int = 20,
    page: int = 1,
    order: Literal["newest", "oldest", "relevance", "executive_order_number"] = "newest",
) -> dict[str, Any]:
    """Search Federal Register documents.

    The primary tool for finding proposed rules, final rules, notices,
    and presidential documents published in the Federal Register since 1994.

    Key parameters:
    - agencies: list of agency URL slugs (OR logic). Use list_agencies() to find slugs.
      Common: 'defense-department', 'general-services-administration',
      'federal-procurement-policy-office', 'small-business-administration'
    - doc_types: PRORULE (proposed rule), RULE (final rule), NOTICE, PRESDOCU
    - term: full-text keyword search (strips stop words)
    - docket_id: docket identifier (substring match). 'FAR Case 2023-008' = exact,
      'FAR Case 2023' = all 2023 cases
    - regulation_id_number: RIN (precise match, e.g., '9000-AO56')
    - pub_date_gte/lte: publication date range (YYYY-MM-DD)
    - comment_date_gte/lte: comment close date range
    - effective_date_gte/lte: effective date range
    - correction: True for modern corrections (C1- prefix documents)
    - significant: True for EO 12866 significant rules only

    Count caps at 10,000 for broad queries. Use date ranges for accurate counts.
    per_page capped at 100 to stay within MCP response size limits.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    doc_types = _reject_empty_list(doc_types, "doc_types")
    per_page = _clamp(per_page, field="per_page", lo=1, hi=100)
    page = _clamp(page, field="page", lo=1, hi=10_000)
    term = _clamp_str_len(_strip_or_none(term), field="term", maximum=500)
    docket_id = _clamp_str_len(_strip_or_none(docket_id), field="docket_id", maximum=200)
    regulation_id_number = _clamp_str_len(
        _strip_or_none(regulation_id_number), field="regulation_id_number", maximum=50
    )
    pub_date_gte = _warn_pre_fr_date(_validate_date(pub_date_gte, "pub_date_gte"), "pub_date_gte")
    pub_date_lte = _validate_date(pub_date_lte, "pub_date_lte")
    comment_date_gte = _validate_date(comment_date_gte, "comment_date_gte")
    comment_date_lte = _validate_date(comment_date_lte, "comment_date_lte")
    effective_date_gte = _validate_date(effective_date_gte, "effective_date_gte")
    effective_date_lte = _validate_date(effective_date_lte, "effective_date_lte")
    _check_date_range(pub_date_gte, pub_date_lte, "publication_date")
    _check_date_range(comment_date_gte, comment_date_lte, "comment_date")
    _check_date_range(effective_date_gte, effective_date_lte, "effective_date")

    qs = _build_search_params(
        agencies=agencies, doc_types=doc_types, term=term,
        docket_id=docket_id, regulation_id_number=regulation_id_number,
        pub_date_gte=pub_date_gte, pub_date_lte=pub_date_lte,
        comment_date_gte=comment_date_gte, comment_date_lte=comment_date_lte,
        effective_date_gte=effective_date_gte, effective_date_lte=effective_date_lte,
        correction=correction, significant=significant,
        per_page=per_page, page=page, order=order,
    )
    return await _get(f"{BASE_URL}/documents.json?{qs}")


@mcp.tool()
async def get_document(
    document_number: str,
) -> dict[str, Any]:
    """Get full details for a single Federal Register document by number.

    Returns all available fields including full text URLs, docket info,
    RIN details, page views, topics, corrections, and CFR references.

    Document numbers look like '2026-03065' or 'C1-2026-01234' (corrections).
    """
    dn = _validate_doc_number(document_number)
    return await _get(f"{BASE_URL}/documents/{dn}.json")


@mcp.tool()
async def get_documents_batch(
    document_numbers: list[str],
) -> dict[str, Any]:
    """Fetch multiple documents in one call (up to ~20).

    Pass a list of document numbers. More efficient than individual calls.
    """
    if not document_numbers:
        raise ValueError("document_numbers list cannot be empty.")
    if len(document_numbers) > 20:
        raise ValueError(f"Max 20 documents per batch. Got {len(document_numbers)}.")

    validated = [_validate_doc_number(d, field=f"document_numbers[{i}]")
                 for i, d in enumerate(document_numbers)]
    nums = ",".join(validated)
    return await _get(f"{BASE_URL}/documents/{nums}.json")


@mcp.tool()
async def get_facet_counts(
    facet: Literal["type", "agency", "topic"],
    agencies: list[str] | None = None,
    doc_types: list[str] | None = None,
    term: str | None = None,
    pub_date_gte: str | None = None,
    pub_date_lte: str | None = None,
) -> dict[str, Any]:
    """Get document counts grouped by type, agency, or topic.

    Accepts the same filter conditions as search_documents. Returns
    aggregated counts without individual document results.

    Useful for understanding the volume of rulemaking by agency or type
    within a date range before drilling into specific documents.

    At least one filter (agencies, doc_types, term, or pub_date_gte/lte) is
    required. An unfiltered facet query returns the entire all-time aggregate.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    doc_types = _reject_empty_list(doc_types, "doc_types")
    term = _clamp_str_len(_strip_or_none(term), field="term", maximum=500)
    pub_date_gte = _warn_pre_fr_date(
        _validate_date(pub_date_gte, "pub_date_gte"), "pub_date_gte"
    )
    pub_date_lte = _validate_date(pub_date_lte, "pub_date_lte")
    _check_date_range(pub_date_gte, pub_date_lte, "publication_date")

    if not any([agencies, doc_types, term, pub_date_gte, pub_date_lte]):
        raise ValueError(
            "get_facet_counts requires at least one filter "
            "(agencies, doc_types, term, or pub_date_gte/lte). "
            "An unfiltered query returns all-time aggregates and is rarely useful."
        )

    params: list[tuple[str, str]] = []
    if agencies:
        for a in agencies:
            params.append(("conditions[agencies][]", a))
    if doc_types:
        for t in doc_types:
            params.append(("conditions[type][]", t))
    if term:
        params.append(("conditions[term]", term))
    if pub_date_gte:
        params.append(("conditions[publication_date][gte]", pub_date_gte))
    if pub_date_lte:
        params.append(("conditions[publication_date][lte]", pub_date_lte))

    qs = urllib.parse.urlencode(params) if params else ""
    url = f"{BASE_URL}/documents/facets/{facet}"
    if qs:
        url += f"?{qs}"
    return await _get(url)


@mcp.tool()
async def get_public_inspection(
    agency_filter: str | None = None,
    keyword_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Get current public inspection documents (pre-publication).

    Public inspection documents are FR documents filed for publication but
    not yet published. Updated business days only.

    The PI endpoint does NOT support server-side filtering. This tool
    fetches all current PI documents and filters client-side by agency
    slug and/or keyword in the title.

    Useful for getting early notice of upcoming regulatory actions.

    Parameters:
    - agency_filter: substring match against each document's agency slugs
    - keyword_filter: substring match against document titles
    - limit: max documents returned after filtering (default 50, max 500).
      Unfiltered dumps can exceed 170KB; narrow with filters or raise the cap.
    """
    limit = _clamp(limit, field="limit", lo=1, hi=500)
    agency_filter = _strip_or_none(agency_filter)
    keyword_filter = _strip_or_none(keyword_filter)

    data = await _get(f"{BASE_URL}/public-inspection-documents/current.json")

    results = data.get("results", [])

    if agency_filter:
        agency_lower = agency_filter.lower()
        results = [
            d for d in results
            if any(agency_lower in (a.get("slug") or "").lower()
                   for a in d.get("agencies", []))
        ]

    if keyword_filter:
        kw_lower = keyword_filter.lower()
        results = [
            d for d in results
            if kw_lower in (d.get("title") or "").lower()
        ]

    total_matched = len(results)
    truncated = total_matched > limit
    results = results[:limit]

    return {
        "total_pi_documents": data.get("count", 0),
        "filtered_count": total_matched,
        "returned": len(results),
        "truncated": truncated,
        "filters_applied": {
            "agency": agency_filter,
            "keyword": keyword_filter,
            "limit": limit,
        },
        "documents": results,
    }


@mcp.tool()
async def list_agencies(
    query: str | None = None,
    include_detail: bool = False,
) -> dict[str, Any]:
    """List agencies with their IDs, names, slugs, and parent agencies.

    Use the 'slug' values with search_documents() and other tools.
    Common procurement slugs:
    - federal-procurement-policy-office (OFPP)
    - defense-department (DoD)
    - general-services-administration (GSA)
    - defense-acquisition-regulations-system (DARS/DFARS)
    - small-business-administration (SBA)
    - national-aeronautics-and-space-administration (NASA)
    - veterans-affairs-department (VA)

    Parameters:
    - query: optional case-insensitive substring match against name, short_name,
      and slug. Recommended: narrow results before pulling full detail.
    - include_detail: if False (default), returns only id/name/short_name/slug/parent_id.
      If True, returns all fields (description, urls, etc.). The full dump is ~700KB.
    """
    query = _strip_or_none(query)
    data = await _get(f"{BASE_URL}/agencies.json")

    if not isinstance(data, list):
        raise RuntimeError(
            f"Unexpected response shape from /agencies.json: {type(data).__name__}"
        )

    results = data
    if query:
        q = query.lower()
        results = [
            a for a in results
            if q in (a.get("name") or "").lower()
            or q in (a.get("short_name") or "").lower()
            or q in (a.get("slug") or "").lower()
        ]

    if not include_detail:
        slim_fields = ("id", "name", "short_name", "slug", "parent_id")
        results = [{k: a.get(k) for k in slim_fields} for a in results]

    return {
        "total_agencies": len(data),
        "returned": len(results),
        "query": query,
        "include_detail": include_detail,
        "agencies": results,
    }


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def open_comment_periods(
    agencies: list[str] | None = None,
    term: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find proposed rules and notices with currently open comment periods.

    Filters for documents where the comment close date is today or later.
    Results sorted by soonest closing deadline first.

    Default: searches all agencies. Pass agency slugs to narrow scope.
    Common for procurement: ['federal-procurement-policy-office',
    'defense-department', 'general-services-administration']

    Parameters:
    - limit: max documents returned (default 50, max 100).
      Unfiltered dumps across all agencies can approach 200KB.
    """
    agencies = _reject_empty_list(agencies, "agencies")
    limit = _clamp(limit, field="limit", lo=1, hi=100)

    today = date.today().isoformat()

    data = await search_documents(
        agencies=agencies,
        doc_types=["PRORULE", "NOTICE"],
        term=term,
        comment_date_gte=today,
        per_page=limit,
        order="newest",
    )

    results = data.get("results", [])
    results.sort(key=lambda x: x.get("comments_close_on") or "9999-99-99")

    return {
        "as_of": today,
        "total_open": len(results),
        "limit": limit,
        "documents": results,
    }


@mcp.tool()
async def far_case_history(docket_id: str) -> dict[str, Any]:
    """Get all Federal Register documents for a FAR/DFARS case.

    Pass a docket ID like 'FAR Case 2023-008'. Returns all related
    documents sorted chronologically (oldest first) to show the full
    rulemaking progression: ANPRM -> proposed rule -> comments -> final rule.

    Docket IDs use substring matching, so 'FAR Case 2023' returns all
    2023 FAR cases. Be specific to avoid false positives.

    If the docket_id filter returns 0 results, the tool automatically
    retries with a term search (quoted phrase) as fallback.

    Minimum docket_id length is 3 characters to prevent substring matches that
    return unrelated documents (e.g. 'x' matched 65 random dockets in 0.1.x).
    """
    docket_id = _require_min_length(docket_id, field="docket_id", minimum=3)
    docket_id = _clamp_str_len(docket_id, field="docket_id", maximum=200)

    data = await search_documents(
        docket_id=docket_id,
        per_page=100,
        order="oldest",
    )

    if data.get("count", 0) == 0:
        data = await search_documents(
            term=f'"{docket_id}"',
            per_page=100,
            order="oldest",
        )

    return {
        "docket_id": docket_id,
        "total_documents": data.get("count", 0),
        "documents": data.get("results", []),
    }


# ---------------------------------------------------------------------------
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    FastMCP's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_documents(keyword='acquisition')
    (real param is `term`) would succeed with the typo silently discarded,
    leaving the tool to hit the API with no filter. extra='forbid' raises
    "Extra inputs are not permitted" on typos before any HTTP call.
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
