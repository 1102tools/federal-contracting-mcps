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

import os
import urllib.parse
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    MAX_PAGE_SIZE,
    MIN_PAGE_SIZE,
    USER_AGENT,
)

mcp = FastMCP("regulationsgov")


# ---------------------------------------------------------------------------
# Auth and HTTP
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("REGULATIONS_GOV_API_KEY", "").strip() or "DEMO_KEY"


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
            "Set REGULATIONS_GOV_API_KEY env var. "
            "Register free at https://open.gsa.gov/api/regulationsgov/#getting-started"
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
        lower = body.lower()
        if "page" in lower and "size" in lower:
            return f"HTTP 400: Page size must be 5-250. API response: {body[:300]}"
        if "date" in lower:
            return (
                f"HTTP 400: Date format error. postedDate and commentEndDate use "
                f"YYYY-MM-DD. lastModifiedDate requires 'YYYY-MM-DD HH:MM:SS' "
                f"(space-separated, no T or Z). API response: {body[:300]}"
            )
        if "filter" in lower:
            return (
                f"HTTP 400: Invalid filter. Values are CASE-SENSITIVE: "
                f"'Proposed Rule' not 'proposed rule', 'Rulemaking' not 'rulemaking'. "
                f"API response: {body[:300]}"
            )
        return f"HTTP 400: {body[:400]}"
    if status == 404:
        return f"HTTP 404: Resource not found. Verify the ID is correct. API response: {body[:300]}"
    if status == 503:
        return (
            "HTTP 503: Regulations.gov upstream service unavailable. "
            "This often happens when the request contains characters that trigger "
            "their firewall (SQL keywords, angle brackets). Remove special characters and retry."
        )
    return f"HTTP {status}: {body[:400]}"


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    key = _get_api_key()
    query = dict(params or {})
    query["api_key"] = key
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(query)}"
    try:
        r = await _get_client().get(url)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling Regulations.gov: {e}") from e


def _validate_page_size(page_size: int) -> None:
    if page_size < MIN_PAGE_SIZE or page_size > MAX_PAGE_SIZE:
        raise ValueError(
            f"page_size must be {MIN_PAGE_SIZE}-{MAX_PAGE_SIZE}. Got {page_size}."
        )


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
    page_size: int = 25,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov documents (proposed rules, final rules, notices).

    Filter values are CASE-SENSITIVE. Use exact casing:
    - document_type: 'Proposed Rule', 'Rule', 'Notice', 'Supporting & Related Material', 'Other'
    - Lowercase values silently return 0 results (no error)

    Key parameters:
    - agency_id: FAR, DARS, GSA, SBA, OFPP, DOD, NASA, VA, etc.
    - docket_id: e.g., 'FAR-2023-0008' for a specific FAR case
    - within_comment_period: True to find documents currently accepting comments
    - posted_date_ge/le: YYYY-MM-DD format
    - comment_end_date_ge/le: YYYY-MM-DD format

    Response includes meta.aggregations with counts by document type, agency,
    and comment period status. Use aggregations for quick counts without paging.

    Page size: 5-250. Pagination ceiling ~5,000 records (20 pages at 250).
    For larger sets, use date ranges to partition.

    sort: '-postedDate' (newest first, default), 'postedDate', '-commentEndDate',
    'lastModifiedDate', 'title', 'documentId'.
    """
    _validate_page_size(page_size)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
        "sort": sort,
    }
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

    return await _get("documents", params)


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
    if not document_id or not document_id.strip():
        raise ValueError("document_id cannot be empty.")

    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"

    return await _get(f"documents/{document_id.strip()}", params)


@mcp.tool()
async def search_comments(
    search_term: str | None = None,
    agency_id: str | None = None,
    comment_on_id: str | None = None,
    docket_id: str | None = None,
    posted_date_ge: str | None = None,
    posted_date_le: str | None = None,
    sort: str = "-postedDate",
    page_size: int = 25,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search public comments on Regulations.gov.

    To find comments on a specific document, use comment_on_id with the
    hex objectId from document search results (NOT the human-readable
    documentId). Get the objectId from search_documents attributes.

    docket_id can also filter comments to all documents in a docket.

    Page size: 5-250. Comments sorted by '-postedDate' by default.
    """
    _validate_page_size(page_size)

    params: dict[str, Any] = {
        "page[size]": page_size,
        "page[number]": page_number,
        "sort": sort,
    }
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

    return await _get("comments", params)


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
    if not comment_id or not comment_id.strip():
        raise ValueError("comment_id cannot be empty.")

    params: dict[str, Any] = {}
    if include_attachments:
        params["include"] = "attachments"

    return await _get(f"comments/{comment_id.strip()}", params)


@mcp.tool()
async def search_dockets(
    search_term: str | None = None,
    agency_id: str | None = None,
    docket_type: Literal["Rulemaking", "Nonrulemaking"] | None = None,
    last_modified_date_ge: str | None = None,
    last_modified_date_le: str | None = None,
    sort: str | None = None,
    page_size: int = 25,
    page_number: int = 1,
) -> dict[str, Any]:
    """Search Regulations.gov dockets.

    Dockets are containers for related regulatory documents (proposed rules,
    comments, supporting materials). FAR cases, DFARS cases, and agency
    rulemaking actions each have a docket.

    docket_type is CASE-SENSITIVE: 'Rulemaking' or 'Nonrulemaking'.

    Docket aggregations include ruleStage (pre-rule, proposed, final, completed),
    useful for understanding where a rulemaking stands.

    lastModifiedDate format: 'YYYY-MM-DD HH:MM:SS' (space-separated, NOT ISO).

    Limited filters: only searchTerm, agencyId, docketType, lastModifiedDate.
    """
    _validate_page_size(page_size)

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

    return await _get("dockets", params)


@mcp.tool()
async def get_docket_detail(docket_id: str) -> dict[str, Any]:
    """Get full details for a single docket.

    Returns title, abstract, RIN (links to Unified Agenda), agency,
    keywords, and modification date.

    docket_id format: FAR-2023-0008, DARS-2025-0071, SBA-2024-0002
    """
    if not docket_id or not docket_id.strip():
        raise ValueError("docket_id cannot be empty.")
    return await _get(f"dockets/{docket_id.strip()}")


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
    Pass agency_ids to narrow or expand the scope.
    """
    import asyncio
    from .constants import PROCUREMENT_AGENCIES

    agencies = agency_ids or PROCUREMENT_AGENCIES
    all_docs: list[dict[str, Any]] = []

    for agency in agencies:
        try:
            result = await search_documents(
                agency_id=agency,
                within_comment_period=True,
                sort="-commentEndDate",
                page_size=50,
            )
            for item in result.get("data", []):
                attrs = item.get("attributes", {})
                all_docs.append({
                    "document_id": item["id"],
                    "agency": attrs.get("agencyId"),
                    "title": attrs.get("title"),
                    "document_type": attrs.get("documentType"),
                    "comment_end_date": attrs.get("commentEndDate"),
                    "docket_id": attrs.get("docketId"),
                    "url": f"https://www.regulations.gov/document/{item['id']}",
                })
        except Exception:
            pass
        await asyncio.sleep(0.5)

    valid = [d for d in all_docs if d.get("comment_end_date")]
    valid.sort(key=lambda x: x["comment_end_date"])

    return {
        "agencies_searched": agencies,
        "total_open": len(valid),
        "documents": valid,
    }


@mcp.tool()
async def far_case_history(docket_id: str) -> dict[str, Any]:
    """Get the full lifecycle of a FAR/DFARS rulemaking case.

    Fetches the docket metadata (title, abstract, RIN) plus all documents
    filed under the docket, sorted by most recent first.

    docket_id examples: FAR-2023-0008, DARS-2025-0071

    Returns the docket abstract, RIN (links to Unified Agenda), and all
    documents with their types, dates, and URLs.
    """
    if not docket_id or not docket_id.strip():
        raise ValueError("docket_id cannot be empty.")

    import asyncio
    docket_id = docket_id.strip()

    docket = await get_docket_detail(docket_id)
    docket_attrs = docket.get("data", {}).get("attributes", {})

    await asyncio.sleep(0.5)

    docs_result = await search_documents(
        docket_id=docket_id,
        sort="-postedDate",
        page_size=250,
    )

    documents = []
    for item in docs_result.get("data", []):
        attrs = item.get("attributes", {})
        documents.append({
            "document_id": item["id"],
            "document_type": attrs.get("documentType"),
            "title": attrs.get("title"),
            "posted_date": attrs.get("postedDate"),
            "comment_end_date": attrs.get("commentEndDate"),
            "within_comment_period": attrs.get("withinCommentPeriod"),
            "url": f"https://www.regulations.gov/document/{item['id']}",
        })

    return {
        "docket_id": docket_id,
        "title": docket_attrs.get("title"),
        "abstract": docket_attrs.get("dkAbstract"),
        "rin": docket_attrs.get("rin"),
        "agency": docket_attrs.get("agencyId"),
        "total_documents": docs_result.get("meta", {}).get("totalElements", len(documents)),
        "documents": documents,
        "url": f"https://www.regulations.gov/docket/{docket_id}",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
