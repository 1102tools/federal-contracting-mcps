# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""eCFR MCP server.

Provides access to the full text, structure, version history, and search
of the Code of Federal Regulations via the eCFR API (ecfr.gov).

No authentication required. All endpoints are public and free.

The server parses XML content responses into clean text so the calling LLM
never needs to process raw XML. Structure and metadata endpoints return JSON.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    DEFAULT_TIMEOUT_CONTENT,
    DEFAULT_TIMEOUT_JSON,
    DEFAULT_TIMEOUT_STRUCTURE,
    SEARCH_MAX_PER_PAGE,
    USER_AGENT,
)

mcp = FastMCP("ecfr")


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: str) -> str:
    """Translate common eCFR errors into actionable messages."""
    if status == 404:
        return (
            "HTTP 404: Resource not found. Common causes: (1) the date exceeds "
            "the title's up_to_date_as_of value -- use get_latest_date() first; "
            "(2) the section/part does not exist at the requested date; "
            "(3) 'current' is not a valid date keyword -- use a specific YYYY-MM-DD date. "
            f"API response: {body[:300]}"
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. The eCFR content endpoint only returns XML. "
            "This server handles the XML parsing automatically -- if you see this "
            "error, the request path may be malformed."
        )
    if status == 400:
        lower = body.lower()
        if "section" in lower and ("filter" in lower or "not supported" in lower):
            return (
                "HTTP 400: The structure endpoint does not support section-level "
                "filtering. Use part or subpart filters instead, then walk the "
                "children to find sections."
            )
        if "per_page" in lower or "9999" in lower:
            return (
                f"HTTP 400: per_page value too high (max {SEARCH_MAX_PER_PAGE}). "
                f"API response: {body[:300]}"
            )
        return f"HTTP 400: {body[:400]}"
    return f"HTTP {status}: {body[:400]}"


async def _get_json(path: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT_JSON) -> dict[str, Any]:
    """GET helper for JSON endpoints."""
    try:
        r = await _get_client().get(path, params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e


async def _get_xml(path: str, params: dict[str, Any] | None = None) -> str:
    """GET helper for XML content endpoints. Returns raw XML string."""
    try:
        r = await _get_client().get(path, params=params or {}, timeout=DEFAULT_TIMEOUT_CONTENT)
        r.raise_for_status()
        return r.text
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_format_error(e.response.status_code, e.response.text[:500])) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e


# ---------------------------------------------------------------------------
# XML parsing helpers (server-side so Claude never sees raw XML)
# ---------------------------------------------------------------------------

def _parse_xml_to_text(xml_content: str) -> dict[str, Any]:
    """Extract clean text from eCFR XML content response.

    Returns structured data with heading, paragraphs, and citations.
    Handles <I>, <E> (emphasis), <EXTRACT>, <P>, <HEAD>, and <CITA> tags.
    """
    text = re.sub(r'<\?xml[^>]+\?>', '', xml_content)

    # Extract heading
    head_match = re.search(r'<HEAD>(.*?)</HEAD>', text)
    heading = head_match.group(1) if head_match else ""
    heading = re.sub(r'<[^>]+>', '', heading).strip()

    # Extract citations (FR references)
    cita_matches = re.findall(r'<CITA[^>]*>(.*?)</CITA>', text, re.DOTALL)
    citations = [re.sub(r'<[^>]+>', '', c).strip() for c in cita_matches]

    # Extract paragraphs with formatting preserved as markdown
    paragraphs = re.findall(r'<P>(.*?)</P>', text, re.DOTALL)
    clean_paragraphs = []
    for p in paragraphs:
        p = re.sub(r'<I>(.*?)</I>', r'*\1*', p)
        p = re.sub(r'<E[^>]*>(.*?)</E>', r'*\1*', p)
        p = re.sub(r'<[^>]+>', '', p)
        p = html.unescape(p).strip()
        if p:
            clean_paragraphs.append(p)

    # Extract any EXTRACT blocks (clause text blocks)
    extracts = re.findall(r'<EXTRACT>(.*?)</EXTRACT>', text, re.DOTALL)
    extract_texts = []
    for ex in extracts:
        ex_clean = re.sub(r'<[^>]+>', '', ex)
        ex_clean = html.unescape(ex_clean).strip()
        if ex_clean:
            extract_texts.append(ex_clean)

    # Try to extract hierarchy metadata
    meta_matches = re.findall(r'hierarchy_metadata="([^"]+)"', xml_content)
    metadata = []
    for m in meta_matches:
        cleaned = m.replace('&quot;', '"').replace('&amp;quot;', '"')
        try:
            import json
            metadata.append(json.loads(cleaned))
        except Exception:
            pass

    result: dict[str, Any] = {
        "heading": heading,
        "paragraphs": clean_paragraphs,
        "citations": citations,
    }
    if extract_texts:
        result["extracts"] = extract_texts
    if metadata:
        result["hierarchy_metadata"] = metadata

    return result


def _walk_structure(node: dict[str, Any], target_type: str = "section") -> list[dict[str, Any]]:
    """Recursively walk a structure tree and collect nodes of a given type."""
    collected = []
    if node.get("type") == target_type:
        collected.append({
            "identifier": node.get("identifier"),
            "label": node.get("label"),
            "label_description": node.get("label_description"),
            "size": node.get("size"),
            "received_on": node.get("received_on"),
        })
    for child in node.get("children", []):
        collected.extend(_walk_structure(child, target_type))
    return collected


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_date(title_number: int) -> str:
    """Resolve the latest available date for a CFR title.

    MUST be called before any versioner endpoint. Using today's date
    often returns 404 because eCFR lags 1-2 business days.
    """
    data = await _get_json("/api/versioner/v1/titles.json")
    for title in data.get("titles", []):
        if title["number"] == title_number:
            return title["up_to_date_as_of"]
    raise ValueError(f"Title {title_number} not found in eCFR titles list.")


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_latest_date(title_number: int = 48) -> dict[str, Any]:
    """Get the most recent available date for a CFR title.

    CRITICAL: eCFR lags 1-2 business days behind the Federal Register.
    Using today's date on versioner endpoints causes 404 errors. Call this
    first to get the safe date, then pass it to other tools.

    Default title 48 = Federal Acquisition Regulations System (FAR, DFARS,
    and all agency supplements). Other common titles: 2 (Grants/Agreements),
    5 (Administrative Personnel), 29 (Labor), 41 (Public Contracts).
    """
    data = await _get_json("/api/versioner/v1/titles.json")
    for title in data.get("titles", []):
        if title["number"] == title_number:
            return {
                "title": title_number,
                "name": title.get("name"),
                "up_to_date_as_of": title["up_to_date_as_of"],
                "latest_amended_on": title.get("latest_amended_on"),
                "latest_issue_date": title.get("latest_issue_date"),
            }
    raise ValueError(f"Title {title_number} not found.")


@mcp.tool()
async def get_cfr_content(
    title_number: int = 48,
    date: str | None = None,
    part: str | None = None,
    subpart: str | None = None,
    section: str | None = None,
    chapter: str | None = None,
    raw_xml: bool = False,
) -> dict[str, Any]:
    """Get the full text of a CFR section, subpart, or part.

    This is the primary workhorse for reading regulatory text. Returns
    parsed clean text by default (heading, paragraphs, citations). Set
    raw_xml=True to get the original XML instead.

    Specify the narrowest scope possible to keep responses manageable:
    - section='15.305' for a single FAR section
    - subpart='15.3' for a subpart
    - part='15' for an entire part (can be large)

    Date auto-resolves to the latest available if not provided. Do NOT use
    today's date directly -- eCFR lags 1-2 business days and today often 404s.

    Title 48 = FAR/DFARS. Chapter 1 = FAR (Parts 1-99), Chapter 2 = DFARS
    (Parts 200-299). Other chapters = agency FAR supplements (GSAR, VAAR, etc.).

    For DFARS clauses, use chapter='2' (e.g., section='252.227-7014').
    """
    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/full/{date}/title-{title_number}.xml"
    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter
    if part:
        params["part"] = part
    if subpart:
        params["subpart"] = subpart
    if section:
        params["section"] = section

    xml_content = await _get_xml(path, params)

    if raw_xml:
        return {"date": date, "title": title_number, "xml": xml_content}

    parsed = _parse_xml_to_text(xml_content)
    parsed["date"] = date
    parsed["title"] = title_number
    if section:
        parsed["section"] = section
    if part:
        parsed["part"] = part
    return parsed


@mcp.tool()
async def get_cfr_structure(
    title_number: int = 48,
    date: str | None = None,
    chapter: str | None = None,
    subchapter: str | None = None,
    part: str | None = None,
    subpart: str | None = None,
) -> dict[str, Any]:
    """Get the hierarchical table of contents for a CFR title or subset.

    Returns a nested tree of titles, chapters, parts, subparts, and sections
    with identifiers, descriptions, and byte sizes.

    IMPORTANT: Does NOT support section-level filtering (returns 400).
    Use part or subpart, then walk the children to find sections.

    Common patterns:
    - chapter='1' for all FAR parts
    - chapter='2' for all DFARS parts
    - part='15' for FAR Part 15 structure
    - subpart='15.3' for just that subpart's sections
    """
    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/structure/{date}/title-{title_number}.json"
    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter
    if subchapter:
        params["subchapter"] = subchapter
    if part:
        params["part"] = part
    if subpart:
        params["subpart"] = subpart

    return await _get_json(path, params, timeout=DEFAULT_TIMEOUT_STRUCTURE)


@mcp.tool()
async def get_version_history(
    title_number: int = 48,
    part: str | None = None,
    section: str | None = None,
    subpart: str | None = None,
) -> dict[str, Any]:
    """Get the version history of a CFR section, subpart, or part.

    Returns a list of content versions with dates, amendment info, and
    whether each version was a substantive text change vs editorial.

    The 'substantive' field is key: True = the regulatory text actually
    changed. False = only editorial/formatting change.

    History goes back to January 2017 only. Pre-2017 changes are not tracked.
    """
    path = f"/api/versioner/v1/versions/title-{title_number}"
    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section
    if subpart:
        params["subpart"] = subpart

    return await _get_json(path, params)


@mcp.tool()
async def get_ancestry(
    title_number: int = 48,
    date: str | None = None,
    part: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Get the breadcrumb hierarchy path for a section or part.

    Returns ancestors from title down to the target node: title > chapter >
    subchapter > part > subpart > section. Useful for understanding where
    a section sits in the CFR hierarchy and what regulation it belongs to.
    """
    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/ancestry/{date}/title-{title_number}.json"
    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section

    return await _get_json(path, params)


@mcp.tool()
async def search_cfr(
    query: str,
    title: int | None = None,
    chapter: str | None = None,
    part: str | None = None,
    subpart: str | None = None,
    section: str | None = None,
    current_only: bool = True,
    last_modified_after: str | None = None,
    last_modified_before: str | None = None,
    per_page: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """Full-text search across the Code of Federal Regulations.

    Returns matching sections with excerpts, headings, scores, and hierarchy.

    CRITICAL: Set current_only=True (default) to search only in-effect text.
    Without it, search returns ALL historical versions including superseded,
    so a section amended 5 times appears 5 times.

    Search caps at 10,000 total results. Use hierarchy filters (title,
    chapter, part) to narrow if you hit the cap.

    Only 'relevance' ordering is supported. No date or newest sorting.

    last_modified_after/before use YYYY-MM-DD format and filter by the
    date sections were last amended. Useful for finding recent regulatory changes.
    """
    if per_page > SEARCH_MAX_PER_PAGE:
        raise ValueError(
            f"per_page max is {SEARCH_MAX_PER_PAGE}. Got {per_page}."
        )

    params: list[tuple[str, str]] = [("query", query)]
    if title is not None:
        params.append(("hierarchy[title]", str(title)))
    if chapter:
        params.append(("hierarchy[chapter]", chapter))
    if part:
        params.append(("hierarchy[part]", part))
    if subpart:
        params.append(("hierarchy[subpart]", subpart))
    if section:
        params.append(("hierarchy[section]", section))
    if current_only:
        params.append(("date", "current"))
    if last_modified_after:
        params.append(("last_modified_on_or_after", last_modified_after))
    if last_modified_before:
        params.append(("last_modified_on_or_before", last_modified_before))
    params.append(("per_page", str(per_page)))
    params.append(("page", str(page)))

    query_str = urllib.parse.urlencode(params)
    return await _get_json(f"/api/search/v1/results?{query_str}")


@mcp.tool()
async def list_agencies() -> dict[str, Any]:
    """List all agencies with their CFR title and chapter references.

    Returns agency names, slugs, and which CFR titles/chapters they own.
    Useful for finding which chapter corresponds to an agency's FAR supplement.
    """
    return await _get_json("/api/admin/v1/agencies.json")


@mcp.tool()
async def get_corrections(title_number: int = 48) -> dict[str, Any]:
    """Get editorial corrections for a CFR title.

    Returns a list of corrections with CFR references, corrective actions,
    error dates, and FR citations. Useful for checking whether a section's
    current text has been corrected since its last amendment.
    """
    return await _get_json(
        "/api/admin/v1/corrections.json",
        {"title": str(title_number)},
    )


# ---------------------------------------------------------------------------
# Workflow / convenience tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_far_clause(
    section_id: str,
    chapter: str = "1",
    date: str | None = None,
) -> dict[str, Any]:
    """Convenience tool: look up the current text of a FAR or DFARS clause.

    Pass a section identifier like '15.305', '52.212-4', '2.101', etc.
    Default chapter='1' (FAR). Use chapter='2' for DFARS (e.g., '252.227-7014').

    Auto-resolves the latest available date. Returns parsed clean text
    with heading, paragraphs, and citations.

    Common FAR sections: 2.101 (Definitions), 9.104-1 (Responsibility),
    15.305 (Proposal Evaluation), 19.502-2 (Small Business Set-Asides),
    52.212-4 (Commercial Terms), 52.212-5 (Required Commercial Terms).
    """
    if date is None:
        date = await _resolve_date(48)
    return await get_cfr_content(
        title_number=48,
        date=date,
        chapter=chapter,
        section=section_id,
    )


@mcp.tool()
async def compare_versions(
    section_id: str,
    date_before: str,
    date_after: str,
    title_number: int = 48,
    chapter: str | None = None,
) -> dict[str, Any]:
    """Compare the text of a CFR section at two different dates.

    Useful for understanding what changed in a regulatory amendment. Returns
    the parsed text at both dates side by side. You can then diff the
    paragraphs to identify specific changes.

    Dates must be in YYYY-MM-DD format and within the eCFR's tracking range
    (January 2017 to present). Both dates must not exceed the title's
    up_to_date_as_of value.
    """
    if date_before > date_after:
        raise ValueError(
            f"date_before ({date_before}) must be earlier than date_after ({date_after})."
        )
    params: dict[str, str] = {}
    if chapter:
        params["chapter"] = chapter

    old_xml = await _get_xml(
        f"/api/versioner/v1/full/{date_before}/title-{title_number}.xml",
        {**params, "section": section_id},
    )
    new_xml = await _get_xml(
        f"/api/versioner/v1/full/{date_after}/title-{title_number}.xml",
        {**params, "section": section_id},
    )

    return {
        "section": section_id,
        "title": title_number,
        "before": {"date": date_before, **_parse_xml_to_text(old_xml)},
        "after": {"date": date_after, **_parse_xml_to_text(new_xml)},
    }


@mcp.tool()
async def list_sections_in_part(
    part_number: str,
    chapter: str = "1",
    title_number: int = 48,
    date: str | None = None,
) -> dict[str, Any]:
    """List all sections in a FAR/DFARS part with their headings.

    Returns a flat list of sections extracted from the structure tree.
    Useful for understanding the scope of a FAR part before drilling into
    specific sections.

    Default chapter='1' (FAR). Use chapter='2' for DFARS.
    """
    if date is None:
        date = await _resolve_date(title_number)

    structure = await _get_json(
        f"/api/versioner/v1/structure/{date}/title-{title_number}.json",
        {"chapter": chapter, "part": part_number},
        timeout=DEFAULT_TIMEOUT_STRUCTURE,
    )

    sections = _walk_structure(structure, "section")
    return {
        "title": title_number,
        "chapter": chapter,
        "part": part_number,
        "date": date,
        "section_count": len(sections),
        "sections": sections,
    }


@mcp.tool()
async def find_far_definition(term: str, date: str | None = None) -> dict[str, Any]:
    """Search for a term's definition in FAR 2.101 (master definition section).

    FAR 2.101 contains definitions used throughout the Federal Acquisition
    Regulation. This tool fetches the full section and searches for paragraphs
    containing the term, returning matching paragraphs with surrounding context.

    Note: FAR 2.101 is large (~109KB XML). This tool parses the full section
    server-side and returns only matching paragraphs.
    """
    if date is None:
        date = await _resolve_date(48)

    xml = await _get_xml(
        f"/api/versioner/v1/full/{date}/title-48.xml",
        {"section": "2.101"},
    )
    parsed = _parse_xml_to_text(xml)

    term_lower = term.lower()
    matches = []
    paragraphs = parsed["paragraphs"]
    for i, para in enumerate(paragraphs):
        if term_lower in para.lower():
            start = max(0, i - 1)
            end = min(len(paragraphs), i + 3)
            matches.append({
                "paragraph_index": i,
                "context": paragraphs[start:end],
            })

    return {
        "section": "2.101",
        "date": date,
        "search_term": term,
        "match_count": len(matches),
        "matches": matches,
        "total_paragraphs": len(paragraphs),
    }


@mcp.tool()
async def find_recent_changes(
    since_date: str,
    title: int = 48,
    chapter: str | None = None,
    part: str | None = None,
    per_page: int = 100,
) -> dict[str, Any]:
    """Find CFR sections that have been modified since a given date.

    Uses the search API with last_modified_on_or_after filter to find
    sections amended after the specified date. Returns section identifiers,
    headings, and excerpts.

    since_date must be in YYYY-MM-DD format. Results are capped at 10,000
    by the API. Use title/chapter/part filters to narrow if needed.

    Common pattern: find FAR changes since a specific date to check for
    regulatory updates that might affect ongoing acquisitions.
    """
    return await search_cfr(
        query="*",
        title=title,
        chapter=chapter,
        part=part,
        current_only=True,
        last_modified_after=since_date,
        per_page=per_page,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
