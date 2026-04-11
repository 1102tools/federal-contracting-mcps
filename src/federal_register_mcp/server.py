# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""Federal Register MCP server.

Free, no-auth access to all Federal Register content since 1994: proposed
rules, final rules, notices, presidential documents, and corrections.

Complements eCFR (what the regulation currently says) by showing what is
changing, what has changed, and what comment periods are open.
"""

from __future__ import annotations

import urllib.parse
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
    if status == 404:
        return (
            f"HTTP 404: Document not found. Verify the document_number is correct. "
            f"API response: {body[:300]}"
        )
    if status == 422:
        return (
            f"HTTP 422: Invalid parameters. Check agency slugs, document type codes "
            f"(PRORULE, RULE, NOTICE, PRESDOCU), date formats (YYYY-MM-DD), "
            f"and field names. API response: {body[:300]}"
        )
    if status == 429:
        return "HTTP 429: Rate limited. Add delays between requests."
    return f"HTTP {status}: {body[:400]}"


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
    """
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
    if not document_number or not document_number.strip():
        raise ValueError("document_number cannot be empty.")
    dn = document_number.strip()
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

    nums = ",".join(d.strip() for d in document_numbers)
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
    """
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
) -> dict[str, Any]:
    """Get current public inspection documents (pre-publication).

    Public inspection documents are FR documents filed for publication but
    not yet published. Updated business days only.

    The PI endpoint does NOT support server-side filtering. This tool
    fetches all current PI documents and filters client-side by agency
    slug and/or keyword in the title.

    Useful for getting early notice of upcoming regulatory actions.
    """
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

    return {
        "total_pi_documents": data.get("count", 0),
        "filtered_count": len(results),
        "filters_applied": {
            "agency": agency_filter,
            "keyword": keyword_filter,
        },
        "documents": results,
    }


@mcp.tool()
async def list_agencies() -> dict[str, Any]:
    """List all ~470 agencies with their IDs, names, slugs, and parent agencies.

    Use the 'slug' values with search_documents() and other tools.
    Common procurement slugs:
    - federal-procurement-policy-office (OFPP)
    - defense-department (DoD)
    - general-services-administration (GSA)
    - defense-acquisition-regulations-system (DARS/DFARS)
    - small-business-administration (SBA)
    - national-aeronautics-and-space-administration (NASA)
    - veterans-affairs-department (VA)
    """
    return await _get(f"{BASE_URL}/agencies.json")


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def open_comment_periods(
    agencies: list[str] | None = None,
    term: str | None = None,
) -> dict[str, Any]:
    """Find proposed rules and notices with currently open comment periods.

    Filters for documents where the comment close date is today or later.
    Results sorted by soonest closing deadline first.

    Default: searches all agencies. Pass agency slugs to narrow scope.
    Common for procurement: ['federal-procurement-policy-office',
    'defense-department', 'general-services-administration']
    """
    from datetime import date
    today = date.today().isoformat()

    data = await search_documents(
        agencies=agencies,
        doc_types=["PRORULE", "NOTICE"],
        term=term,
        comment_date_gte=today,
        per_page=100,
        order="newest",
    )

    results = data.get("results", [])
    results.sort(key=lambda x: x.get("comments_close_on") or "9999-99-99")

    return {
        "as_of": today,
        "total_open": len(results),
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
    """
    if not docket_id or not docket_id.strip():
        raise ValueError("docket_id cannot be empty.")

    data = await search_documents(
        docket_id=docket_id.strip(),
        per_page=100,
        order="oldest",
    )

    if data.get("count", 0) == 0:
        data = await search_documents(
            term=f'"{docket_id.strip()}"',
            per_page=100,
            order="oldest",
        )

    return {
        "docket_id": docket_id,
        "total_documents": data.get("count", 0),
        "documents": data.get("results", []),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
