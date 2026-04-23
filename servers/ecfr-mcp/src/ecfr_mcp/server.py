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
import json as _json
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .constants import (
    BASE_URL,
    COMMON_FAR_SECTIONS,
    DEFAULT_TIMEOUT_CONTENT,
    DEFAULT_TIMEOUT_JSON,
    DEFAULT_TIMEOUT_STRUCTURE,
    SEARCH_MAX_PER_PAGE,
    SEARCH_MAX_TOTAL,
    TITLE_48_CHAPTERS,
    USER_AGENT,
)

mcp = FastMCP("ecfr")


# ---------------------------------------------------------------------------
# Defensive helpers (response shape + input validation)
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, else {}."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Coerce value to list. Empty if None; single-item wrap if dict."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]


def _safe_int(value: Any, default: int | None = None) -> int | None:
    """Coerce value to int. Returns default for None/""/'null'/non-parseable.

    Round 6 punishment-suite fix: also catches OverflowError from inf/nan
    floats. Without it, _safe_int(float('inf')) crashed instead of returning
    the default.
    """
    if value in (None, "", "null", "None"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _strip_or_none(value: Any) -> str | None:
    """Strip a string; return None for None/empty/whitespace-only."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None


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
        raise ValueError(f"{field} exceeds maximum length of {maximum}. Got {len(value)}.")
    return value


_HTML_MARK_RE = re.compile(r"<(?:!doctype|html)", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _clean_error_body(text: Any) -> str:
    """Strip HTML to extract just the useful error message. Safe for bytes/None."""
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


# Input validation


_YYYYMMDD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_ymd(value: str | None, *, field: str) -> str | None:
    """eCFR uses YYYY-MM-DD. Reject every other format."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string. Got {type(value).__name__}.")
    s = value.strip()
    if not s:
        raise ValueError(
            f"{field} cannot be empty or whitespace. Use YYYY-MM-DD (e.g. '2026-04-16'), "
            f"or omit to auto-resolve the latest available date."
        )
    if s.lower() == "current":
        raise ValueError(
            f"{field}='current' is not accepted. Use a specific YYYY-MM-DD date, "
            f"or omit {field} to auto-resolve to the latest available."
        )
    if not _YYYYMMDD_RE.match(s):
        raise ValueError(
            f"{field} must be YYYY-MM-DD (e.g. '2026-04-16'). Got {value!r}."
        )
    try:
        from datetime import date as _date
        parts = s.split("-")
        _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{field}={value!r} is not a valid calendar date: {exc}") from exc
    return s


def _validate_title_number(value: Any, *, field: str = "title_number") -> int:
    """CFR titles are 1-50."""
    if value is None:
        raise ValueError(f"{field} is required.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an int 1-50, not bool.")
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        # OverflowError catches inf/nan float coercion. Round 6 fix.
        raise ValueError(f"{field} must be an int 1-50. Got {value!r}.") from exc
    if n < 1 or n > 50:
        raise ValueError(f"{field} must be between 1 and 50. Got {n}.")
    return n


# Section/part/subpart/chapter normalization. LLMs often pass ints or
# include human-friendly prefixes.

_SECTION_PREFIX_RE = re.compile(r"^\s*(?:FAR|DFARS|GSAR|48\s*CFR|CFR)\s+", re.IGNORECASE)


def _coerce_cfr_str(
    value: Any,
    *,
    field: str,
    strip_prefixes: bool = False,
    maxlen: int = 120,
) -> str | None:
    """Accept int or str for CFR identifiers (part/subpart/section/chapter).

    LLMs often pass ints (part=15). We coerce to str, strip whitespace, and
    optionally strip common user-added prefixes like 'FAR ' or '48 CFR '.
    Returns None for None/empty/whitespace-only. Raises on other types.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a string or integer, not bool.")
    if not isinstance(value, (str, int)):
        raise ValueError(
            f"{field} must be a string or integer. Got {type(value).__name__}."
        )
    raw = str(value)
    if "\x00" in raw:
        raise ValueError(f"{field}={value!r} contains a null byte.")
    if any(c in raw for c in ("\n", "\r", "\t")):
        raise ValueError(f"{field}={value!r} must not contain newline/tab characters.")
    s = raw.strip()
    if not s:
        return None
    if strip_prefixes:
        s = _SECTION_PREFIX_RE.sub("", s).strip()
        if not s:
            return None
    if len(s) > maxlen:
        raise ValueError(
            f"{field} exceeds maximum length of {maxlen} chars. Got {len(s)}."
        )
    return s


def _validate_chapter(value: Any, *, title_number: int | None = None) -> str | None:
    """Chapter is a string or int. If title=48, validate against TITLE_48_CHAPTERS."""
    s = _coerce_cfr_str(value, field="chapter", maxlen=8)
    if s is None:
        return None
    # For title 48 we know every legitimate chapter.
    if title_number == 48 and s not in TITLE_48_CHAPTERS:
        sample = ", ".join(list(TITLE_48_CHAPTERS.keys())[:10])
        raise ValueError(
            f"chapter={value!r} is not a valid Title 48 chapter. "
            f"Valid chapters: {sample} (see TITLE_48_CHAPTERS for full list). "
            f"Chapter 1=FAR, 2=DFARS."
        )
    return s


# Free-text guard for search queries
_INJECT_PATTERNS = [
    (re.compile(r"\x00"), "null byte"),
]


def _validate_query_safe(value: str, *, field: str) -> str:
    """Pre-reject strings that break our URL construction."""
    for pattern, desc in _INJECT_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field} contains {desc}.")
    return value


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
        )
    return _client


def _format_error(status: int, body: Any) -> str:
    """Translate common eCFR errors into actionable messages."""
    cleaned = _clean_error_body(body)
    low = cleaned.lower() if isinstance(cleaned, str) else ""
    if status == 404:
        return (
            "HTTP 404: Resource not found. Common causes: (1) the date exceeds "
            "the title's up_to_date_as_of value -- use get_latest_date() first; "
            "(2) the section/part does not exist at the requested date; "
            "(3) 'current' is not a valid date keyword -- use a specific YYYY-MM-DD date. "
            f"API response: {cleaned}"
        )
    if status == 406:
        return (
            "HTTP 406: Not Acceptable. The eCFR content endpoint only returns XML. "
            "This server handles the XML parsing automatically -- if you see this "
            "error, the request path may be malformed."
        )
    if status == 400:
        if "section" in low and ("filter" in low or "not supported" in low):
            return (
                "HTTP 400: The structure endpoint does not support section-level "
                "filtering. Use part or subpart filters instead, then walk the "
                "children to find sections."
            )
        if "per_page" in low or "9999" in low:
            return (
                f"HTTP 400: per_page value too high (max {SEARCH_MAX_PER_PAGE}). "
                f"API response: {cleaned}"
            )
        return f"HTTP 400: {cleaned}"
    if status == 429:
        return (
            "HTTP 429: Rate limited by eCFR. Wait a few seconds and retry. "
            "eCFR throttles heavy automated use."
        )
    if 500 <= status < 600:
        return f"HTTP {status}: eCFR server error. {cleaned}. Retry after a short backoff."
    return f"HTTP {status}: {cleaned}"


async def _get_json(
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_JSON,
) -> dict[str, Any]:
    """GET helper for JSON endpoints. Always returns a dict (empty if API returned null)."""
    try:
        r = await _get_client().get(path, params=params or {}, timeout=timeout)
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text))
    try:
        data = r.json()
    except (ValueError, _json.JSONDecodeError) as e:
        preview = _clean_error_body(r.text or "(empty body)")[:200]
        ct = r.headers.get("content-type", "?")
        raise RuntimeError(
            f"eCFR returned a non-JSON response (status {r.status_code}, "
            f"content-type={ct!r}): {preview}"
        ) from e
    if data is None:
        return {}
    if not isinstance(data, (dict, list)):
        raise RuntimeError(
            f"eCFR returned unexpected JSON type {type(data).__name__}: {str(data)[:200]}"
        )
    return data if isinstance(data, dict) else {"_list": data}


async def _get_xml(path: str, params: dict[str, Any] | None = None) -> str:
    """GET helper for XML content endpoints. Returns raw XML string."""
    try:
        r = await _get_client().get(
            path, params=params or {}, timeout=DEFAULT_TIMEOUT_CONTENT
        )
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error calling eCFR: {e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_format_error(r.status_code, r.text))
    text = r.text
    if not isinstance(text, str):
        text = str(text)
    return text


# ---------------------------------------------------------------------------
# XML parsing helpers (server-side so Claude never sees raw XML)
# ---------------------------------------------------------------------------

_HEAD_RE = re.compile(r"<HEAD\b[^>]*>(.*?)</HEAD>", re.IGNORECASE | re.DOTALL)
_CITA_RE = re.compile(r"<CITA\b[^>]*>(.*?)</CITA>", re.IGNORECASE | re.DOTALL)
_P_RE = re.compile(r"<P\b[^>]*>(.*?)</P>", re.IGNORECASE | re.DOTALL)
_EXTRACT_RE = re.compile(r"<EXTRACT\b[^>]*>(.*?)</EXTRACT>", re.IGNORECASE | re.DOTALL)
_XML_DECL_RE = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)
_PI_RE = re.compile(r"<\?[^>]*\?>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_ITAG_RE = re.compile(r"<I\b[^>]*>(.*?)</I>", re.IGNORECASE | re.DOTALL)
_ETAG_RE = re.compile(r"<E\b[^>]*>(.*?)</E>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_META_RE = re.compile(r'hierarchy_metadata="([^"]+)"')


def _clean_inline(s: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    s = _ANY_TAG_RE.sub("", s)
    s = html.unescape(s)
    return s.strip()


def _parse_xml_to_text(xml_content: Any) -> dict[str, Any]:
    """Extract clean text from eCFR XML content response.

    Returns structured data with heading, paragraphs, and citations.
    Handles <I>, <E> (emphasis), <EXTRACT>, <P>, <HEAD>, and <CITA> tags.

    Robust to bytes/None/int input, case variations, and malformed XML.
    """
    if xml_content is None:
        return {"heading": "", "paragraphs": [], "citations": []}
    if isinstance(xml_content, bytes):
        try:
            xml_content = xml_content.decode("utf-8", errors="replace")
        except Exception:
            xml_content = str(xml_content)
    if not isinstance(xml_content, str):
        xml_content = str(xml_content)

    text = _XML_DECL_RE.sub("", xml_content)
    text = _PI_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    # Preserve CDATA content
    text = _CDATA_RE.sub(lambda m: m.group(1), text)

    head_match = _HEAD_RE.search(text)
    heading = _clean_inline(head_match.group(1)) if head_match else ""

    citations = [_clean_inline(c) for c in _CITA_RE.findall(text)]
    citations = [c for c in citations if c]

    clean_paragraphs: list[str] = []
    for p in _P_RE.findall(text):
        p = _ITAG_RE.sub(r"*\1*", p)
        p = _ETAG_RE.sub(r"*\1*", p)
        p = _clean_inline(p)
        if p:
            clean_paragraphs.append(p)

    extract_texts: list[str] = []
    for ex in _EXTRACT_RE.findall(text):
        ex_clean = _clean_inline(ex)
        if ex_clean:
            extract_texts.append(ex_clean)

    metadata: list[Any] = []
    for m in _META_RE.findall(xml_content):
        cleaned = m.replace("&quot;", '"').replace("&amp;quot;", '"')
        try:
            metadata.append(_json.loads(cleaned))
        except (ValueError, _json.JSONDecodeError):
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


def _walk_structure(node: Any, target_type: str = "section") -> list[dict[str, Any]]:
    """Recursively walk a structure tree and collect nodes of a given type.

    Defensive against None, non-dict nodes, and None/non-list children.
    """
    if not isinstance(node, dict):
        return []
    collected: list[dict[str, Any]] = []
    if node.get("type") == target_type:
        collected.append({
            "identifier": node.get("identifier"),
            "label": node.get("label"),
            "label_description": node.get("label_description"),
            "size": node.get("size"),
            "received_on": node.get("received_on"),
        })
    children = node.get("children")
    for child in _as_list(children):
        collected.extend(_walk_structure(child, target_type))
    return collected


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_date(title_number: int) -> str:
    """Resolve the latest available date for a CFR title.

    Called before any versioner endpoint. Using today's date often returns
    404 because eCFR lags 1-2 business days.

    Raises ValueError with an actionable message for reserved titles
    (which have null up_to_date_as_of) rather than building a URL with
    'None' in it.
    """
    data = await _get_json("/api/versioner/v1/titles.json")
    titles = _as_list(_safe_dict(data).get("titles"))
    for title in titles:
        t = _safe_dict(title)
        if _safe_int(t.get("number")) == title_number:
            utd = t.get("up_to_date_as_of")
            if not isinstance(utd, str) or not utd.strip():
                reason = "this title is marked 'reserved'" if t.get("reserved") else (
                    "the API did not return up_to_date_as_of"
                )
                raise ValueError(
                    f"Cannot resolve a date for title {title_number}: {reason}. "
                    f"Reserved or un-issued titles have no published content."
                )
            return utd
    raise ValueError(f"Title {title_number} not found in eCFR titles list.")


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Get Latest Date", "readOnlyHint": True, "destructiveHint": False})
async def get_latest_date(title_number: int = 48) -> dict[str, Any]:
    """Get the most recent available date for a CFR title.

    CRITICAL: eCFR lags 1-2 business days behind the Federal Register.
    Using today's date on versioner endpoints causes 404 errors. Call this
    first to get the safe date, then pass it to other tools.

    Default title 48 = Federal Acquisition Regulations System (FAR, DFARS,
    and all agency supplements). Other common titles: 2 (Grants/Agreements),
    5 (Administrative Personnel), 29 (Labor), 41 (Public Contracts).

    Raises ValueError for titles 1-50 that are reserved (no content).
    """
    title_number = _validate_title_number(title_number)
    data = await _get_json("/api/versioner/v1/titles.json")
    titles = _as_list(_safe_dict(data).get("titles"))
    for title in titles:
        t = _safe_dict(title)
        if _safe_int(t.get("number")) == title_number:
            utd = t.get("up_to_date_as_of")
            if not isinstance(utd, str) or not utd.strip():
                reserved = t.get("reserved")
                raise ValueError(
                    f"Title {title_number} has no available content "
                    f"(reserved={reserved}). Reserved titles are placeholders "
                    f"in the CFR numbering scheme without published regulations."
                )
            return {
                "title": title_number,
                "name": t.get("name"),
                "up_to_date_as_of": utd,
                "latest_amended_on": t.get("latest_amended_on"),
                "latest_issue_date": t.get("latest_issue_date"),
                "reserved": bool(t.get("reserved", False)),
            }
    raise ValueError(f"Title {title_number} not found.")


@mcp.tool(annotations={"title": "Get CFR Content", "readOnlyHint": True, "destructiveHint": False})
async def get_cfr_content(
    title_number: int = 48,
    date: str | None = None,
    part: Any = None,
    subpart: Any = None,
    section: Any = None,
    chapter: Any = None,
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
    - chapter='1' for an entire chapter (often >1 MB, avoid)

    Date auto-resolves to the latest available if not provided. Do NOT use
    today's date directly -- eCFR lags 1-2 business days and today often 404s.

    Title 48 = FAR/DFARS. Chapter 1 = FAR (Parts 1-99), Chapter 2 = DFARS
    (Parts 200-299). Other chapters = agency FAR supplements (GSAR, VAAR, etc.).

    For DFARS clauses, use chapter='2' (e.g., section='252.227-7014').

    part/subpart/section accept int or string. Common prefix mistakes like
    section='FAR 15.305' or '48 CFR 15.305' are stripped automatically.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    chapter = _validate_chapter(chapter, title_number=title_number)

    if not any((section, part, subpart, chapter)):
        raise ValueError(
            "get_cfr_content requires at least one of: section, subpart, part, chapter. "
            "Calling without any filter returns the entire title (often 20+ MB)."
        )

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
    if subpart:
        parsed["subpart"] = subpart
    if chapter:
        parsed["chapter"] = chapter
    return parsed


@mcp.tool(annotations={"title": "Get CFR Structure", "readOnlyHint": True, "destructiveHint": False})
async def get_cfr_structure(
    title_number: int = 48,
    date: str | None = None,
    chapter: Any = None,
    subchapter: Any = None,
    part: Any = None,
    subpart: Any = None,
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

    part/subpart/chapter accept int or string.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    chapter = _validate_chapter(chapter, title_number=title_number)
    subchapter = _coerce_cfr_str(subchapter, field="subchapter", maxlen=8)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)

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


@mcp.tool(annotations={"title": "Get Version History", "readOnlyHint": True, "destructiveHint": False})
async def get_version_history(
    title_number: int = 48,
    part: Any = None,
    section: Any = None,
    subpart: Any = None,
) -> dict[str, Any]:
    """Get the version history of a CFR section, subpart, or part.

    Returns a list of content versions with dates, amendment info, and
    whether each version was a substantive text change vs editorial.

    The 'substantive' field is key: True = the regulatory text actually
    changed. False = only editorial/formatting change.

    History goes back to January 2017 only. Pre-2017 changes are not tracked.

    part/subpart/section accept int or string.
    """
    title_number = _validate_title_number(title_number)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)

    if not any((part, section, subpart)):
        raise ValueError(
            "get_version_history requires at least one of: part, subpart, section."
        )

    path = f"/api/versioner/v1/versions/title-{title_number}"
    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section
    if subpart:
        params["subpart"] = subpart

    return await _get_json(path, params)


@mcp.tool(annotations={"title": "Get Ancestry", "readOnlyHint": True, "destructiveHint": False})
async def get_ancestry(
    title_number: int = 48,
    date: str | None = None,
    part: Any = None,
    section: Any = None,
) -> dict[str, Any]:
    """Get the breadcrumb hierarchy path for a section or part.

    Returns ancestors from title down to the target node: title > chapter >
    subchapter > part > subpart > section. Useful for understanding where
    a section sits in the CFR hierarchy and what regulation it belongs to.

    part/section accept int or string.
    """
    title_number = _validate_title_number(title_number)
    date = _validate_date_ymd(date, field="date")
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True)

    if date is None:
        date = await _resolve_date(title_number)

    path = f"/api/versioner/v1/ancestry/{date}/title-{title_number}.json"
    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if section:
        params["section"] = section

    return await _get_json(path, params)


@mcp.tool(annotations={"title": "Search CFR", "readOnlyHint": True, "destructiveHint": False})
async def search_cfr(
    query: str,
    title: int | None = None,
    chapter: Any = None,
    part: Any = None,
    subpart: Any = None,
    section: Any = None,
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

    per_page capped at 100 by default (server-side soft cap; API max is 5000).
    """
    q = _strip_or_none(query)
    if q is None:
        raise ValueError("query is required and cannot be empty or whitespace-only.")
    q = _clamp_str_len(q, field="query", maximum=500)
    q = _validate_query_safe(q, field="query")

    per_page = _clamp(per_page, field="per_page", lo=1, hi=SEARCH_MAX_PER_PAGE)
    page = _clamp(page, field="page", lo=1, hi=SEARCH_MAX_TOTAL)
    if title is not None:
        title = _validate_title_number(title, field="title")
    chapter = _validate_chapter(chapter, title_number=title)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    subpart = _coerce_cfr_str(subpart, field="subpart", strip_prefixes=True)
    section = _coerce_cfr_str(section, field="section", strip_prefixes=True)
    last_modified_after = _validate_date_ymd(last_modified_after, field="last_modified_after")
    last_modified_before = _validate_date_ymd(last_modified_before, field="last_modified_before")

    params: list[tuple[str, str]] = [("query", q)]
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

    return await _get_json("/api/search/v1/results", dict(params))


@mcp.tool(annotations={"title": "List Agencies", "readOnlyHint": True, "destructiveHint": False})
async def list_agencies(summary_only: bool = True) -> dict[str, Any]:
    """List all agencies with their CFR title and chapter references.

    Returns agency names, slugs, and which CFR titles/chapters they own.
    Useful for finding which chapter corresponds to an agency's FAR supplement.

    summary_only (default True) strips the `children` and most of
    `cfr_references` to keep the response compact (~20 KB vs ~100 KB).
    Set False for the full raw payload.
    """
    data = await _get_json("/api/admin/v1/agencies.json")
    agencies = _as_list(_safe_dict(data).get("agencies"))
    if not summary_only:
        return {"agencies": agencies, "count": len(agencies)}
    summarized: list[dict[str, Any]] = []
    for a in agencies:
        a = _safe_dict(a)
        refs = _as_list(a.get("cfr_references"))
        summarized.append({
            "name": a.get("name"),
            "short_name": a.get("short_name"),
            "slug": a.get("slug"),
            "cfr_references": [
                {"title": _safe_dict(r).get("title"),
                 "chapter": _safe_dict(r).get("chapter")}
                for r in refs
            ],
            "child_count": len(_as_list(a.get("children"))),
        })
    return {
        "agencies": summarized,
        "count": len(summarized),
        "summary_only": True,
    }


@mcp.tool(annotations={"title": "Get Corrections", "readOnlyHint": True, "destructiveHint": False})
async def get_corrections(
    title_number: int = 48,
    limit: int = 50,
    since_year: int | None = None,
) -> dict[str, Any]:
    """Get editorial corrections for a CFR title.

    Returns a list of corrections with CFR references, corrective actions,
    error dates, and FR citations. Useful for checking whether a section's
    current text has been corrected since its last amendment.

    limit caps the number of corrections returned (default 50, max 1000).
    since_year further filters to corrections with year >= since_year.
    Title 48 has ~280 corrections across all years; use since_year to
    focus on recent ones.
    """
    title_number = _validate_title_number(title_number)
    limit = _clamp(limit, field="limit", lo=1, hi=1000)
    if since_year is not None:
        since_year = _clamp(since_year, field="since_year", lo=1995, hi=2100)

    data = await _get_json(
        "/api/admin/v1/corrections.json",
        {"title": str(title_number)},
    )
    corrections = _as_list(_safe_dict(data).get("ecfr_corrections"))
    total = len(corrections)

    if since_year is not None:
        corrections = [
            c for c in corrections
            if _safe_int(_safe_dict(c).get("year"), default=0) >= since_year
        ]

    filtered_count = len(corrections)
    truncated = filtered_count > limit
    corrections = corrections[:limit]

    return {
        "title": title_number,
        "corrections": corrections,
        "count_returned": len(corrections),
        "count_filtered": filtered_count,
        "count_total": total,
        "truncated": truncated,
        "since_year": since_year,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# Workflow / convenience tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"title": "Lookup FAR Clause", "readOnlyHint": True, "destructiveHint": False})
async def lookup_far_clause(
    section_id: Any,
    chapter: Any = "1",
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
    section_id = _coerce_cfr_str(section_id, field="section_id", strip_prefixes=True)
    if not section_id:
        raise ValueError(
            "section_id is required. Pass a FAR/DFARS section like '15.305' or '52.212-4'. "
            f"Common sections: {', '.join(list(COMMON_FAR_SECTIONS.keys())[:5])}."
        )
    chapter = _validate_chapter(chapter, title_number=48)
    date = _validate_date_ymd(date, field="date")
    if date is None:
        date = await _resolve_date(48)
    return await get_cfr_content(
        title_number=48,
        date=date,
        chapter=chapter,
        section=section_id,
    )


@mcp.tool(annotations={"title": "Compare Versions", "readOnlyHint": True, "destructiveHint": False})
async def compare_versions(
    section_id: Any,
    date_before: str,
    date_after: str,
    title_number: int = 48,
    chapter: Any = None,
) -> dict[str, Any]:
    """Compare the text of a CFR section at two different dates.

    Useful for understanding what changed in a regulatory amendment. Returns
    the parsed text at both dates side by side. You can then diff the
    paragraphs to identify specific changes.

    Dates must be in YYYY-MM-DD format and within the eCFR's tracking range
    (January 2017 to present). Both dates must not exceed the title's
    up_to_date_as_of value.

    This tool always returns the section-level XML parsed -- pass a small
    section_id like '15.305', not a whole part. Whole-part comparisons can
    exceed 100 KB per side.
    """
    title_number = _validate_title_number(title_number)
    section_id = _coerce_cfr_str(section_id, field="section_id", strip_prefixes=True)
    if not section_id:
        raise ValueError(
            "section_id is required. Pass a section like '15.305', not a whole part."
        )
    date_before = _validate_date_ymd(date_before, field="date_before")
    date_after = _validate_date_ymd(date_after, field="date_after")
    if date_before is None or date_after is None:
        raise ValueError("Both date_before and date_after are required YYYY-MM-DD dates.")
    if date_before == date_after:
        raise ValueError(
            f"date_before and date_after are identical ({date_before}); "
            f"there is nothing to compare. Pick two distinct dates."
        )
    if date_before > date_after:
        raise ValueError(
            f"date_before ({date_before}) must be earlier than date_after ({date_after})."
        )
    chapter = _validate_chapter(chapter, title_number=title_number)

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


@mcp.tool(annotations={"title": "List Sections in Part", "readOnlyHint": True, "destructiveHint": False})
async def list_sections_in_part(
    part_number: Any,
    chapter: Any = "1",
    title_number: int = 48,
    date: str | None = None,
) -> dict[str, Any]:
    """List all sections in a FAR/DFARS part with their headings.

    Returns a flat list of sections extracted from the structure tree.
    Useful for understanding the scope of a FAR part before drilling into
    specific sections.

    Default chapter='1' (FAR). Use chapter='2' for DFARS.

    part_number accepts int or string.
    """
    title_number = _validate_title_number(title_number)
    part_number = _coerce_cfr_str(part_number, field="part_number", strip_prefixes=True)
    if not part_number:
        raise ValueError("part_number is required. Pass something like '15' or '252'.")
    chapter = _validate_chapter(chapter, title_number=title_number)
    date = _validate_date_ymd(date, field="date")

    if date is None:
        date = await _resolve_date(title_number)

    params: dict[str, str] = {"part": part_number}
    if chapter:
        params["chapter"] = chapter

    structure = await _get_json(
        f"/api/versioner/v1/structure/{date}/title-{title_number}.json",
        params,
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


@mcp.tool(annotations={"title": "Find FAR Definition", "readOnlyHint": True, "destructiveHint": False})
async def find_far_definition(
    term: str,
    date: str | None = None,
    max_matches: int = 20,
) -> dict[str, Any]:
    """Search for a term's definition in FAR 2.101 (master definition section).

    FAR 2.101 contains definitions used throughout the Federal Acquisition
    Regulation. This tool fetches the full section and searches for paragraphs
    containing the term, returning matching paragraphs with surrounding context.

    Note: FAR 2.101 is large (~109KB XML). This tool parses the full section
    server-side and returns only matching paragraphs.

    term must be at least 3 characters. max_matches caps returned matches
    (default 20, max 100); common terms like 'offeror' hit many paragraphs.
    """
    term_clean = _strip_or_none(term)
    if term_clean is None:
        raise ValueError("term is required and cannot be empty or whitespace-only.")
    if len(term_clean) < 3:
        raise ValueError(
            f"term must be at least 3 characters (got {len(term_clean)}). "
            f"Short terms match too broadly and return junk."
        )
    term_clean = _clamp_str_len(term_clean, field="term", maximum=100)
    max_matches = _clamp(max_matches, field="max_matches", lo=1, hi=100)
    date = _validate_date_ymd(date, field="date")

    if date is None:
        date = await _resolve_date(48)

    xml = await _get_xml(
        f"/api/versioner/v1/full/{date}/title-48.xml",
        {"section": "2.101"},
    )
    parsed = _parse_xml_to_text(xml)

    term_lower = term_clean.lower()
    paragraphs = parsed.get("paragraphs", [])
    matches: list[dict[str, Any]] = []
    for i, para in enumerate(paragraphs):
        if term_lower in para.lower():
            start = max(0, i - 1)
            end = min(len(paragraphs), i + 3)
            matches.append({
                "paragraph_index": i,
                "context": paragraphs[start:end],
            })
            if len(matches) >= max_matches:
                break

    # Count all matches beyond the cap for the caller's awareness.
    total_matches = sum(1 for p in paragraphs if term_lower in p.lower())

    return {
        "section": "2.101",
        "date": date,
        "search_term": term_clean,
        "match_count": len(matches),
        "total_matches": total_matches,
        "truncated": total_matches > len(matches),
        "max_matches": max_matches,
        "matches": matches,
        "total_paragraphs": len(paragraphs),
    }


@mcp.tool(annotations={"title": "Find Recent Changes", "readOnlyHint": True, "destructiveHint": False})
async def find_recent_changes(
    since_date: str,
    title: int = 48,
    chapter: Any = None,
    part: Any = None,
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
    since_date = _validate_date_ymd(since_date, field="since_date")
    if since_date is None:
        raise ValueError("since_date is required (YYYY-MM-DD).")
    title = _validate_title_number(title, field="title")
    chapter = _validate_chapter(chapter, title_number=title)
    part = _coerce_cfr_str(part, field="part", strip_prefixes=True)
    per_page = _clamp(per_page, field="per_page", lo=1, hi=SEARCH_MAX_PER_PAGE)

    # Use a broad query that every section matches; eCFR requires a query term.
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
# Strict parameter validation
# ---------------------------------------------------------------------------

def _forbid_extra_params_on_all_tools() -> None:
    """Set extra='forbid' on every registered tool's pydantic arg model.

    FastMCP's default is extra='ignore', which silently drops unknown
    parameter names. A typo like search_cfr(keyword='audit') (the real
    parameter is `query`) would succeed with the typo silently discarded,
    leaving the tool to hit the API with no query at all.
    extra='forbid' raises "Extra inputs are not permitted" on typos
    before any HTTP call.
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
