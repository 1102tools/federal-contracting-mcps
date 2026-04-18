# SPDX-License-Identifier: MIT
"""Validation tests for ecfr-mcp.

All tests route through mcp.call_tool to cover pydantic schema + handler
logic. The older stress_test*.py files call tools as raw coroutines and
bypass pydantic; they're kept for backward compat but not run by CI.

Tests split into:
- offline: input validation, response-shape fuzzing via mocked _get_json/_get_xml
- live: real eCFR API calls (skipped unless MCP_LIVE_TESTS=1)
"""
from __future__ import annotations

import asyncio
import json
import os
import pytest

import ecfr_mcp.server as srv
from ecfr_mcp.server import mcp

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the shared httpx client before every test.

    pytest creates a fresh event loop per test via asyncio.run. Reusing a
    stale AsyncClient across loops raises 'Event loop is closed'.
    """
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r}, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# Input validation (offline — uses pydantic + handler validators)
# ---------------------------------------------------------------------------

def test_search_rejects_empty_query():
    asyncio.run(_call_expect_error("search_cfr", "empty", query=""))


def test_search_rejects_whitespace_query():
    asyncio.run(_call_expect_error("search_cfr", "empty", query="   "))


def test_search_rejects_null_byte_query():
    asyncio.run(_call_expect_error("search_cfr", "null byte", query="x\x00y"))


def test_search_rejects_query_over_500_chars():
    asyncio.run(_call_expect_error(
        "search_cfr", "exceeds maximum length", query="a" * 600
    ))


def test_search_rejects_per_page_zero():
    asyncio.run(_call_expect_error("search_cfr", "must be >= 1", query="x", per_page=0))


def test_search_rejects_per_page_negative():
    asyncio.run(_call_expect_error("search_cfr", "must be >= 1", query="x", per_page=-5))


def test_search_rejects_per_page_over_max():
    asyncio.run(_call_expect_error("search_cfr", "exceeds maximum", query="x", per_page=99999))


def test_search_rejects_page_zero():
    asyncio.run(_call_expect_error("search_cfr", "must be >= 1", query="x", page=0))


def test_search_rejects_page_negative():
    asyncio.run(_call_expect_error("search_cfr", "must be >= 1", query="x", page=-1))


def test_search_rejects_bad_title():
    asyncio.run(_call_expect_error("search_cfr", "between 1 and 50", query="x", title=999))


def test_search_rejects_bad_date():
    asyncio.run(_call_expect_error(
        "search_cfr", "YYYY-MM-DD", query="x", last_modified_after="not-a-date"
    ))


def test_search_rejects_date_current_keyword():
    asyncio.run(_call_expect_error(
        "search_cfr", "not accepted", query="x", last_modified_after="current"
    ))


def test_get_cfr_content_requires_filter():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "at least one of", title_number=48
    ))


def test_get_cfr_content_rejects_empty_date():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "cannot be empty", title_number=48, date="", section="15.305"
    ))


def test_get_cfr_content_rejects_bad_date_format():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "YYYY-MM-DD",
        title_number=48, date="2026/04/16", section="15.305",
    ))


def test_get_cfr_content_rejects_iso_date():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "YYYY-MM-DD",
        title_number=48, date="2026-04-16T00:00:00Z", section="15.305",
    ))


def test_get_cfr_content_rejects_date_current():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "not accepted",
        title_number=48, date="current", section="15.305",
    ))


def test_get_cfr_content_rejects_invalid_calendar_date():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "not a valid calendar date",
        title_number=48, date="2026-02-30", section="15.305",
    ))


def test_get_cfr_content_rejects_title_out_of_range():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "between 1 and 50",
        title_number=999, section="15.305",
    ))


def test_get_cfr_content_rejects_negative_title():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "between 1 and 50",
        title_number=-1, section="15.305",
    ))


def test_get_cfr_content_rejects_bad_chapter_for_title_48():
    asyncio.run(_call_expect_error(
        "get_cfr_content", "not a valid title 48 chapter",
        title_number=48, chapter="27",
    ))


def test_get_cfr_content_normalizes_far_prefix():
    # Local test: coerce path runs before any network call if chapter is default.
    # Can't actually fire without mocking. Just verify prefix stripper alone.
    from ecfr_mcp.server import _coerce_cfr_str
    assert _coerce_cfr_str("FAR 15.305", field="s", strip_prefixes=True) == "15.305"
    assert _coerce_cfr_str("48 CFR 15.305", field="s", strip_prefixes=True) == "15.305"
    assert _coerce_cfr_str("DFARS 252.204-7012", field="s", strip_prefixes=True) == "252.204-7012"
    assert _coerce_cfr_str(" 15.305 ", field="s", strip_prefixes=True) == "15.305"


def test_coerce_cfr_str_rejects_null_byte():
    from ecfr_mcp.server import _coerce_cfr_str
    with pytest.raises(ValueError, match="null byte"):
        _coerce_cfr_str("15.305\x00", field="s")


def test_coerce_cfr_str_rejects_newline():
    from ecfr_mcp.server import _coerce_cfr_str
    with pytest.raises(ValueError, match="newline"):
        _coerce_cfr_str("15.305\n", field="s")


def test_coerce_cfr_str_accepts_int():
    from ecfr_mcp.server import _coerce_cfr_str
    assert _coerce_cfr_str(15, field="part") == "15"


def test_coerce_cfr_str_rejects_bool():
    from ecfr_mcp.server import _coerce_cfr_str
    with pytest.raises(ValueError, match="not bool"):
        _coerce_cfr_str(True, field="part")


def test_coerce_cfr_str_rejects_list():
    from ecfr_mcp.server import _coerce_cfr_str
    with pytest.raises(ValueError, match="string or integer"):
        _coerce_cfr_str(["1"], field="part")


def test_coerce_cfr_str_length_limit():
    from ecfr_mcp.server import _coerce_cfr_str
    with pytest.raises(ValueError, match="exceeds maximum"):
        _coerce_cfr_str("x" * 1000, field="section")


def test_lookup_far_clause_rejects_empty():
    asyncio.run(_call_expect_error("lookup_far_clause", "required", section_id=""))


def test_lookup_far_clause_rejects_whitespace():
    asyncio.run(_call_expect_error("lookup_far_clause", "required", section_id="   "))


def test_compare_versions_rejects_identical_dates():
    asyncio.run(_call_expect_error(
        "compare_versions", "identical",
        section_id="15.305", date_before="2024-01-01", date_after="2024-01-01",
    ))


def test_compare_versions_rejects_swapped_dates():
    asyncio.run(_call_expect_error(
        "compare_versions", "must be earlier",
        section_id="15.305", date_before="2025-01-01", date_after="2024-01-01",
    ))


def test_compare_versions_rejects_bad_date_before():
    asyncio.run(_call_expect_error(
        "compare_versions", "YYYY-MM-DD",
        section_id="15.305", date_before="bogus", date_after="2025-01-01",
    ))


def test_compare_versions_rejects_empty_section():
    asyncio.run(_call_expect_error(
        "compare_versions", "required",
        section_id="", date_before="2024-01-01", date_after="2025-01-01",
    ))


def test_find_far_definition_rejects_empty():
    asyncio.run(_call_expect_error("find_far_definition", "empty", term=""))


def test_find_far_definition_rejects_short_term():
    asyncio.run(_call_expect_error("find_far_definition", "at least 3", term="a"))


def test_find_far_definition_rejects_2_char_term():
    asyncio.run(_call_expect_error("find_far_definition", "at least 3", term="ab"))


def test_find_far_definition_rejects_bad_max_matches():
    asyncio.run(_call_expect_error(
        "find_far_definition", "must be >= 1", term="offer", max_matches=0
    ))


def test_find_recent_changes_rejects_bad_date():
    asyncio.run(_call_expect_error(
        "find_recent_changes", "YYYY-MM-DD", since_date="20260101"
    ))


def test_find_recent_changes_rejects_empty_date():
    asyncio.run(_call_expect_error(
        "find_recent_changes", "cannot be empty", since_date=""
    ))


def test_list_sections_in_part_rejects_empty_part():
    asyncio.run(_call_expect_error("list_sections_in_part", "required", part_number=""))


def test_get_corrections_rejects_bad_title():
    asyncio.run(_call_expect_error(
        "get_corrections", "between 1 and 50", title_number=999
    ))


def test_get_corrections_rejects_bad_limit():
    asyncio.run(_call_expect_error(
        "get_corrections", "must be >= 1", title_number=48, limit=0
    ))


def test_get_corrections_rejects_limit_over_max():
    asyncio.run(_call_expect_error(
        "get_corrections", "exceeds maximum", title_number=48, limit=5000
    ))


def test_version_history_requires_filter():
    asyncio.run(_call_expect_error(
        "get_version_history", "at least one of", title_number=48
    ))


def test_get_latest_date_rejects_bad_title():
    asyncio.run(_call_expect_error("get_latest_date", "between 1 and 50", title_number=0))


def test_get_latest_date_rejects_negative_title():
    asyncio.run(_call_expect_error("get_latest_date", "between 1 and 50", title_number=-5))


# ---------------------------------------------------------------------------
# Response-shape defense (offline — mock _get_json / _get_xml)
# ---------------------------------------------------------------------------

def _with_mock_json(response):
    """Context-manager-ish: swap _get_json, yield, restore."""
    orig = srv._get_json
    async def fake(path, params=None, timeout=15):
        return response
    srv._get_json = fake
    return orig


def _restore_json(orig):
    srv._get_json = orig


def test_resolve_date_handles_none_response():
    orig = _with_mock_json(None)
    try:
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(srv._resolve_date(48))
    finally:
        _restore_json(orig)


def test_resolve_date_handles_empty_titles():
    orig = _with_mock_json({"titles": []})
    try:
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(srv._resolve_date(48))
    finally:
        _restore_json(orig)


def test_resolve_date_handles_titles_as_string():
    orig = _with_mock_json({"titles": "oops"})
    try:
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(srv._resolve_date(48))
    finally:
        _restore_json(orig)


def test_resolve_date_handles_null_titles_entries():
    orig = _with_mock_json({"titles": [None, {"number": 48, "up_to_date_as_of": "2026-01-01"}]})
    try:
        r = asyncio.run(srv._resolve_date(48))
        assert r == "2026-01-01"
    finally:
        _restore_json(orig)


def test_resolve_date_handles_string_titles_entries():
    orig = _with_mock_json({"titles": ["junk", {"number": 48, "up_to_date_as_of": "2026-01-01"}]})
    try:
        r = asyncio.run(srv._resolve_date(48))
        assert r == "2026-01-01"
    finally:
        _restore_json(orig)


def test_resolve_date_handles_missing_number_field():
    orig = _with_mock_json({"titles": [{"name": "x"}, {"number": 48, "up_to_date_as_of": "2026-01-01"}]})
    try:
        r = asyncio.run(srv._resolve_date(48))
        assert r == "2026-01-01"
    finally:
        _restore_json(orig)


def test_resolve_date_handles_string_number():
    orig = _with_mock_json({"titles": [{"number": "48", "up_to_date_as_of": "2026-01-01"}]})
    try:
        r = asyncio.run(srv._resolve_date(48))
        assert r == "2026-01-01"
    finally:
        _restore_json(orig)


def test_resolve_date_reserved_title_raises():
    orig = _with_mock_json({"titles": [{"number": 35, "up_to_date_as_of": None, "reserved": True}]})
    try:
        with pytest.raises(ValueError, match="reserved"):
            asyncio.run(srv._resolve_date(35))
    finally:
        _restore_json(orig)


def test_resolve_date_empty_up_to_date_raises():
    orig = _with_mock_json({"titles": [{"number": 48, "up_to_date_as_of": ""}]})
    try:
        with pytest.raises(ValueError, match="reserved|up_to_date_as_of"):
            asyncio.run(srv._resolve_date(48))
    finally:
        _restore_json(orig)


def test_list_sections_handles_none_structure():
    orig = _with_mock_json(None)
    try:
        r = asyncio.run(srv.list_sections_in_part(part_number="15", date="2026-01-01"))
        assert r["section_count"] == 0
        assert r["sections"] == []
    finally:
        _restore_json(orig)


def test_list_sections_handles_dict_children():
    orig = _with_mock_json({"type": "part", "children": {"oddly": "adict"}})
    try:
        # Should not crash; walk treats dict as single child
        r = asyncio.run(srv.list_sections_in_part(part_number="15", date="2026-01-01"))
        assert isinstance(r["sections"], list)
    finally:
        _restore_json(orig)


def test_list_sections_handles_null_child_entry():
    orig = _with_mock_json({
        "type": "part",
        "children": [None, {"type": "section", "identifier": "15.1"}],
    })
    try:
        r = asyncio.run(srv.list_sections_in_part(part_number="15", date="2026-01-01"))
        assert r["section_count"] == 1
    finally:
        _restore_json(orig)


def test_list_agencies_handles_none():
    orig = _with_mock_json(None)
    try:
        r = asyncio.run(srv.list_agencies())
        assert r["count"] == 0
    finally:
        _restore_json(orig)


def test_list_agencies_handles_missing_key():
    orig = _with_mock_json({"data": []})
    try:
        r = asyncio.run(srv.list_agencies())
        assert r["count"] == 0
    finally:
        _restore_json(orig)


def test_get_corrections_handles_none():
    orig = _with_mock_json(None)
    try:
        r = asyncio.run(srv.get_corrections(title_number=48))
        assert r["count_total"] == 0
    finally:
        _restore_json(orig)


def test_get_corrections_paginates():
    orig = _with_mock_json({"ecfr_corrections": [{"id": i, "year": 2024} for i in range(200)]})
    try:
        r = asyncio.run(srv.get_corrections(title_number=48, limit=50))
        assert r["count_returned"] == 50
        assert r["count_total"] == 200
        assert r["truncated"] is True
    finally:
        _restore_json(orig)


def test_get_corrections_filters_since_year():
    orig = _with_mock_json({"ecfr_corrections": [
        {"id": 1, "year": 2018},
        {"id": 2, "year": 2024},
        {"id": 3, "year": 2025},
    ]})
    try:
        r = asyncio.run(srv.get_corrections(title_number=48, since_year=2024))
        assert r["count_filtered"] == 2
    finally:
        _restore_json(orig)


# ---------------------------------------------------------------------------
# XML parser defense (offline — pure function)
# ---------------------------------------------------------------------------

def test_parse_xml_handles_none():
    r = srv._parse_xml_to_text(None)
    assert r == {"heading": "", "paragraphs": [], "citations": []}


def test_parse_xml_handles_bytes():
    r = srv._parse_xml_to_text(b"<HEAD>Title</HEAD><P>para</P>")
    assert r["heading"] == "Title"
    assert r["paragraphs"] == ["para"]


def test_parse_xml_handles_int():
    r = srv._parse_xml_to_text(42)
    assert r["heading"] == ""


def test_parse_xml_unescapes_heading_entities():
    r = srv._parse_xml_to_text("<HEAD>R&amp;D &lt;contract&gt;</HEAD>")
    assert r["heading"] == "R&D <contract>"


def test_parse_xml_unescapes_citation_entities():
    r = srv._parse_xml_to_text("<CITA>47 FR 12345 &amp; 47 FR 67890</CITA>")
    assert r["citations"] == ["47 FR 12345 & 47 FR 67890"]


def test_parse_xml_case_insensitive_tags():
    r = srv._parse_xml_to_text("<head>Title</head><p>para</p>")
    assert r["heading"] == "Title"
    assert r["paragraphs"] == ["para"]


def test_parse_xml_head_with_attributes():
    r = srv._parse_xml_to_text('<HEAD class="x">Title</HEAD>')
    assert r["heading"] == "Title"


def test_parse_xml_cita_with_attributes():
    r = srv._parse_xml_to_text('<CITA type="N">47 FR 123</CITA>')
    assert r["citations"] == ["47 FR 123"]


def test_parse_xml_strips_comments():
    r = srv._parse_xml_to_text("<P>before<!-- hidden -->after</P>")
    assert r["paragraphs"] == ["beforeafter"]


def test_parse_xml_preserves_cdata():
    r = srv._parse_xml_to_text("<P><![CDATA[literal <tags>]]></P>")
    assert "literal" in r["paragraphs"][0]


def test_parse_xml_handles_long_paragraph():
    long_text = "a" * 50000
    r = srv._parse_xml_to_text(f"<P>{long_text}</P>")
    assert len(r["paragraphs"]) == 1


def test_parse_xml_handles_unicode():
    r = srv._parse_xml_to_text("<HEAD>Título</HEAD><P>español</P>")
    assert r["heading"] == "Título"
    assert r["paragraphs"] == ["español"]


def test_parse_xml_strips_xml_decl():
    r = srv._parse_xml_to_text('<?xml version="1.0"?><HEAD>T</HEAD>')
    assert r["heading"] == "T"


def test_walk_structure_handles_none():
    assert srv._walk_structure(None) == []


def test_walk_structure_handles_string():
    assert srv._walk_structure("not a dict") == []


def test_walk_structure_handles_null_children():
    r = srv._walk_structure({"type": "section", "children": None, "identifier": "x"})
    assert len(r) == 1


def test_walk_structure_handles_dict_children():
    r = srv._walk_structure({
        "type": "part",
        "children": {"type": "section", "identifier": "y"},
    })
    assert len(r) == 1


def test_walk_structure_skips_null_children_entries():
    r = srv._walk_structure({
        "type": "part",
        "children": [None, {"type": "section", "identifier": "z"}, None],
    })
    assert len(r) == 1


# ---------------------------------------------------------------------------
# HTTP layer defense
# ---------------------------------------------------------------------------

def test_get_json_handles_non_json_body():
    """200 with HTML body should raise a descriptive RuntimeError."""
    import httpx

    class FakeResp:
        status_code = 200
        text = "<html>maintenance</html>"
        headers = {"content-type": "text/html"}
        def raise_for_status(self):
            pass
        def json(self):
            raise json.JSONDecodeError("msg", self.text, 0)

    class FakeClient:
        is_closed = False
        async def get(self, *a, **kw):
            return FakeResp()

    orig = srv._client
    srv._client = FakeClient()
    try:
        with pytest.raises(RuntimeError, match="non-JSON"):
            asyncio.run(srv._get_json("/x"))
    finally:
        srv._client = orig


def test_get_json_handles_empty_body():
    class FakeResp:
        status_code = 200
        text = ""
        headers = {"content-type": "application/json"}
        def raise_for_status(self):
            pass
        def json(self):
            raise json.JSONDecodeError("msg", "", 0)
    class FakeClient:
        is_closed = False
        async def get(self, *a, **kw):
            return FakeResp()
    orig = srv._client
    srv._client = FakeClient()
    try:
        with pytest.raises(RuntimeError, match="non-JSON"):
            asyncio.run(srv._get_json("/x"))
    finally:
        srv._client = orig


def test_get_json_handles_timeout():
    import httpx
    class FakeClient:
        is_closed = False
        async def get(self, *a, **kw):
            raise httpx.TimeoutException("timed out")
    orig = srv._client
    srv._client = FakeClient()
    try:
        with pytest.raises(RuntimeError, match="Network error"):
            asyncio.run(srv._get_json("/x"))
    finally:
        srv._client = orig


def test_format_error_handles_bytes():
    msg = srv._format_error(500, b"<html>error</html>")
    assert "HTTP 500" in msg


def test_format_error_handles_none():
    msg = srv._format_error(500, None)
    assert "HTTP 500" in msg


def test_clean_error_body_strips_html():
    r = srv._clean_error_body("<html><head><title>Error 500</title></head><body>oops</body></html>")
    assert "Error 500" in r
    assert "<html>" not in r


# ---------------------------------------------------------------------------
# LIVE tests (require real eCFR API access)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_search_actually_filters():
    """The P0: verify that filters actually reach the API and change results."""
    r = asyncio.run(_call("search_cfr", query="deviation", title=48, per_page=3))
    data = _payload(r)
    assert isinstance(data, dict)
    meta = data.get("meta", {})
    # Filtered title=48 search should return a few hundred, not the 10K cap.
    assert 0 < meta.get("total_count", 0) < 5000
    assert len(data.get("results", [])) <= 3


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_search_per_page_is_applied():
    """Verify per_page actually reduces result count (P0 regression)."""
    async def _run():
        r3 = await _call("search_cfr", query="contract", per_page=3)
        r10 = await _call("search_cfr", query="contract", per_page=10)
        return r3, r10
    r3, r10 = asyncio.run(_run())
    assert len(_payload(r3).get("results", [])) == 3
    assert len(_payload(r10).get("results", [])) == 10


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_get_latest_date():
    r = asyncio.run(_call("get_latest_date", title_number=48))
    data = _payload(r)
    assert data["title"] == 48
    assert data["up_to_date_as_of"].startswith("20")


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_get_ancestry_int_part():
    r = asyncio.run(_call("get_ancestry", title_number=48, part=15))
    data = _payload(r)
    ancestors = data.get("ancestors", [])
    assert any(a.get("identifier") == "15" for a in ancestors)


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_lookup_far_clause_strips_prefix():
    r = asyncio.run(_call("lookup_far_clause", section_id="FAR 15.305"))
    data = _payload(r)
    assert "Proposal evaluation" in data.get("heading", "")


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_list_agencies_summary_is_compact():
    r = asyncio.run(_call("list_agencies"))
    data = _payload(r)
    assert "summary_only" in data
    size = len(json.dumps(data))
    # Full payload is ~100 KB; summary should be under 50 KB.
    assert size < 50_000, f"summary too large: {size}"


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_list_agencies_full_is_larger():
    r = asyncio.run(_call("list_agencies", summary_only=False))
    data = _payload(r)
    assert data.get("summary_only") is None
    size = len(json.dumps(data))
    assert size > 50_000


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_get_corrections_paginates():
    r = asyncio.run(_call("get_corrections", title_number=48, limit=10))
    data = _payload(r)
    assert data["count_returned"] == 10
    assert data["count_total"] > 50


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_reserved_title_35_clear_error():
    with pytest.raises(Exception) as exc:
        asyncio.run(_call("get_latest_date", title_number=35))
    assert "reserved" in str(exc.value).lower()


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_find_far_definition():
    r = asyncio.run(_call("find_far_definition", term="offeror", max_matches=5))
    data = _payload(r)
    assert data["match_count"] > 0
    assert data["match_count"] <= 5


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_find_recent_changes_filter_actually_applied():
    r = asyncio.run(_call("find_recent_changes", since_date="2025-01-01", title=48, per_page=5))
    data = _payload(r)
    # With real filter, should return a small number, not the 10K cap.
    assert 0 < data.get("meta", {}).get("total_count", 0) < 10000


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_list_sections_in_part_int_accepted():
    r = asyncio.run(_call("list_sections_in_part", part_number=15, chapter="1"))
    data = _payload(r)
    assert data["section_count"] > 0


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_get_cfr_content_dfars_chapter_2():
    r = asyncio.run(_call("get_cfr_content", title_number=48, chapter="2", section="252.204-7012"))
    data = _payload(r)
    assert len(data.get("paragraphs", [])) > 3


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop.
    FastMCP default is extra='ignore' which lets silent-wrong-data through."""
    async def _run():
        try:
            await mcp.call_tool(
                "search_cfr", {"query": "audit", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())
