# SPDX-License-Identifier: MIT
"""Regression tests for 0.2.0 hardening fixes.

These invoke tools through the FastMCP registry (mcp.call_tool) rather than
awaiting the decorated coroutines directly. That matters: the prior stress
tests awaited raw coroutines and bypassed the tool pipeline, missing whole
classes of bugs. The list_agencies pydantic crash slipped through the
raw-coroutine tests in 0.1.x.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import federal_register_mcp.server as srv  # noqa: E402
from federal_register_mcp.server import mcp


LIVE = os.environ.get("FR_LIVE_TESTS") == "1"


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


async def _call_expect_error(name: str, match: str, **kwargs):
    try:
        await mcp.call_tool(name, kwargs)
    except Exception as e:
        assert match.lower() in str(e).lower(), f"expected {match!r} in error, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------

def test_search_rejects_non_iso_date():
    asyncio.run(_call_expect_error(
        "search_documents", "YYYY-MM-DD", pub_date_gte="2026/01/01"
    ))


def test_search_rejects_datetime_string():
    asyncio.run(_call_expect_error(
        "search_documents", "YYYY-MM-DD", pub_date_gte="2026-01-01T00:00:00Z"
    ))


def test_search_rejects_bad_month():
    asyncio.run(_call_expect_error(
        "search_documents", "valid calendar date", pub_date_gte="2026-13-01"
    ))


def test_search_rejects_reversed_date_range():
    asyncio.run(_call_expect_error(
        "search_documents", "is after",
        pub_date_gte="2026-06-01", pub_date_lte="2026-01-01",
    ))


def test_search_rejects_reversed_comment_range():
    asyncio.run(_call_expect_error(
        "search_documents", "is after",
        comment_date_gte="2026-06-01", comment_date_lte="2026-01-01",
    ))


# ---------------------------------------------------------------------------
# Empty-list validation
# ---------------------------------------------------------------------------

def test_search_rejects_empty_agencies_list():
    asyncio.run(_call_expect_error(
        "search_documents", "silently ignored", agencies=[]
    ))


def test_search_rejects_empty_doc_types_list():
    asyncio.run(_call_expect_error(
        "search_documents", "silently ignored", doc_types=[]
    ))


def test_open_comment_periods_rejects_empty_agencies():
    asyncio.run(_call_expect_error(
        "open_comment_periods", "silently ignored", agencies=[]
    ))


# ---------------------------------------------------------------------------
# Clamp validation
# ---------------------------------------------------------------------------

def test_search_rejects_per_page_below_one():
    asyncio.run(_call_expect_error(
        "search_documents", "per_page", per_page=0
    ))


def test_search_rejects_per_page_above_cap():
    asyncio.run(_call_expect_error(
        "search_documents", "per_page", per_page=1001
    ))


def test_search_rejects_page_below_one():
    asyncio.run(_call_expect_error(
        "search_documents", "page", page=0
    ))


def test_public_inspection_rejects_limit_zero():
    asyncio.run(_call_expect_error(
        "get_public_inspection", "limit", limit=0
    ))


def test_public_inspection_rejects_limit_too_high():
    asyncio.run(_call_expect_error(
        "get_public_inspection", "limit", limit=501
    ))


def test_open_comment_periods_rejects_limit_too_high():
    asyncio.run(_call_expect_error(
        "open_comment_periods", "limit", limit=101
    ))


# ---------------------------------------------------------------------------
# get_document empty input
# ---------------------------------------------------------------------------

def test_get_document_rejects_empty_string():
    asyncio.run(_call_expect_error(
        "get_document", "cannot be empty", document_number=""
    ))


def test_get_documents_batch_rejects_empty_list():
    asyncio.run(_call_expect_error(
        "get_documents_batch", "cannot be empty", document_numbers=[]
    ))


def test_get_documents_batch_rejects_over_twenty():
    asyncio.run(_call_expect_error(
        "get_documents_batch", "Max 20",
        document_numbers=[f"2026-0{i:04d}" for i in range(21)],
    ))


def test_far_case_history_rejects_empty():
    asyncio.run(_call_expect_error(
        "far_case_history", "at least 3", docket_id=""
    ))


def test_far_case_history_rejects_single_char():
    asyncio.run(_call_expect_error(
        "far_case_history", "at least 3", docket_id="x"
    ))


def test_far_case_history_rejects_whitespace_padded_short():
    asyncio.run(_call_expect_error(
        "far_case_history", "at least 3", docket_id="  a  "
    ))


# ---------------------------------------------------------------------------
# P1 fixes: new in round 2 of 0.2.0
# ---------------------------------------------------------------------------

def test_get_documents_batch_rejects_empty_string_entries():
    asyncio.run(_call_expect_error(
        "get_documents_batch", "cannot be empty",
        document_numbers=["", "", ""],
    ))


def test_get_documents_batch_rejects_bogus_format_entry():
    asyncio.run(_call_expect_error(
        "get_documents_batch", "invalid format",
        document_numbers=["2026-07731", "../../admin"],
    ))


def test_get_documents_batch_rejects_whitespace_entries():
    asyncio.run(_call_expect_error(
        "get_documents_batch", "cannot be empty",
        document_numbers=["  ", "  "],
    ))


def test_search_rejects_10k_char_term():
    asyncio.run(_call_expect_error(
        "search_documents", "maximum length", term="a" * 10_000
    ))


def test_search_clamps_per_page_above_100():
    asyncio.run(_call_expect_error(
        "search_documents", "per_page", per_page=101
    ))


# ---------------------------------------------------------------------------
# P2 fixes: get_facet_counts gets same validators as search_documents
# ---------------------------------------------------------------------------

def test_facet_counts_requires_filter():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "requires at least one filter", facet="agency"
    ))


def test_facet_counts_rejects_bad_date_format():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "YYYY-MM-DD",
        facet="type", pub_date_gte="2026/01/01"
    ))


def test_facet_counts_rejects_empty_agencies():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "silently ignored",
        facet="type", agencies=[]
    ))


def test_facet_counts_rejects_reversed_date_range():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "is after",
        facet="type", pub_date_gte="2026-06-01", pub_date_lte="2026-01-01"
    ))


# ---------------------------------------------------------------------------
# P2 fixes: whitespace-only strings, long strings
# ---------------------------------------------------------------------------

def test_search_docket_id_long_string_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "maximum length",
        docket_id="A" * 500,
    ))


def test_search_regulation_id_number_long_string_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "maximum length",
        regulation_id_number="B" * 100,
    ))


def test_search_whitespace_term_normalized_to_none():
    """Whitespace-only term becomes None (no filter applied), not 'All Documents' match."""
    # Without filter, we need SOMETHING that won't hit the network. Use a bad page to raise.
    # Goal: confirm the whitespace term doesn't raise on its own (it gets stripped to None).
    try:
        asyncio.run(_call("search_documents", term="   ", per_page=0))
    except Exception as e:
        # Should be the per_page=0 error, NOT a term-related error
        assert "per_page" in str(e).lower(), f"expected per_page error, got: {e}"


def test_search_whitespace_docket_normalized_to_none():
    try:
        asyncio.run(_call("search_documents", docket_id="   ", per_page=0))
    except Exception as e:
        assert "per_page" in str(e).lower(), f"expected per_page error, got: {e}"


# ---------------------------------------------------------------------------
# P3 fixes: polish
# ---------------------------------------------------------------------------

def test_search_rejects_pre_1994_date():
    asyncio.run(_call_expect_error(
        "search_documents", "predates",
        pub_date_gte="1800-01-01",
    ))


def test_get_document_rejects_hash_in_number():
    asyncio.run(_call_expect_error(
        "get_document", "invalid format", document_number="2026#07731"
    ))


def test_get_document_rejects_slash_in_number():
    asyncio.run(_call_expect_error(
        "get_document", "invalid format", document_number="2026/07731"
    ))


def test_get_document_rejects_spaces_in_number():
    asyncio.run(_call_expect_error(
        "get_document", "invalid format", document_number="2026 07731"
    ))


def test_get_document_accepts_valid_format():
    """Sanity: well-formed number passes validation (network call may still 404 but won't raise ValueError)."""
    # Use a bogus-but-well-formed number; we only check it passed validation
    try:
        asyncio.run(_call("get_document", document_number="9999-99999"))
    except Exception as e:
        # Accept network/404 errors; reject ValueError from our validator
        msg = str(e).lower()
        assert "invalid format" not in msg, f"validator wrongly rejected valid format: {e}"


def test_get_document_accepts_correction_prefix():
    try:
        asyncio.run(_call("get_document", document_number="C1-2026-01234"))
    except Exception as e:
        assert "invalid format" not in str(e).lower(), f"correction prefix wrongly rejected: {e}"


def test_user_agent_version_matches():
    from federal_register_mcp.constants import USER_AGENT
    assert "0.2.2" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


def test_clean_error_body_strips_html():
    from federal_register_mcp.server import _clean_error_body
    html = '<!DOCTYPE html><html><head><title>404 Not Found</title></head><body><h1>Not Found</h1></body></html>'
    result = _clean_error_body(html)
    assert "<" not in result, f"HTML leaked: {result}"
    assert "404 Not Found" in result or "Not Found" in result


def test_clean_error_body_passthrough_non_html():
    from federal_register_mcp.server import _clean_error_body
    assert _clean_error_body('{"error":"nope"}') == '{"error":"nope"}'


def test_list_agencies_whitespace_query_normalized():
    """Empty-string and whitespace-only queries should both normalize to None (no filter).

    In 0.1.x, query='   ' returned 0 results (substring matching whitespace)
    while query='' returned all 470. After the fix they behave the same.
    """
    # No network — just confirm the normalizer returns None
    from federal_register_mcp.server import _strip_or_none
    assert _strip_or_none("") is None
    assert _strip_or_none("   ") is None
    assert _strip_or_none(None) is None
    assert _strip_or_none("defense") == "defense"
    assert _strip_or_none("  defense  ") == "defense"


# ---------------------------------------------------------------------------
# Live tests (opt-in via FR_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set FR_LIVE_TESTS=1 to run live API calls")
def test_list_agencies_live_returns_dict_not_list():
    """Regression: in 0.1.x the tool returned a raw list which crashed pydantic."""
    result = asyncio.run(_call("list_agencies"))
    payload = _payload(result)
    assert isinstance(payload, dict), f"expected dict, got {type(payload).__name__}"
    assert "agencies" in payload
    assert "total_agencies" in payload
    assert isinstance(payload["agencies"], list)


@pytest.mark.skipif(not LIVE, reason="Set FR_LIVE_TESTS=1 to run live API calls")
def test_list_agencies_live_slim_by_default():
    result = asyncio.run(_call("list_agencies"))
    payload = _payload(result)
    agencies = payload["agencies"]
    assert agencies, "expected non-empty list"
    sample = agencies[0]
    assert "description" not in sample, "slim mode should strip description"
    assert "slug" in sample


@pytest.mark.skipif(not LIVE, reason="Set FR_LIVE_TESTS=1 to run live API calls")
def test_list_agencies_live_query_filter():
    result = asyncio.run(_call("list_agencies", query="defense"))
    payload = _payload(result)
    assert payload["returned"] > 0
    assert payload["returned"] < payload["total_agencies"]


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop."""
    async def _run():
        try:
            await mcp.call_tool(
                "search_documents", {"term": "acquisition", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 0.2.2: live-audit fixes (rounds 1-4)
# ---------------------------------------------------------------------------

def test_search_documents_no_filters_rejected():
    """P1: unfiltered search used to return 10,000 "most recent" FR docs."""
    asyncio.run(_call_expect_error(
        "search_documents", "at least one filter",
    ))


def test_search_documents_empty_term_alone_rejected():
    """Empty string via term shouldn't be silently accepted as no filter."""
    asyncio.run(_call_expect_error(
        "search_documents", "at least one filter",
        term="",
    ))


def test_search_documents_whitespace_term_alone_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "at least one filter",
        term="   ",
    ))


def test_search_documents_null_byte_in_term_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        term="x\x00y",
    ))


def test_search_documents_newline_in_term_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        term="x\ny",
    ))


def test_search_documents_tab_in_term_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        term="x\ty",
    ))


def test_search_documents_cr_in_term_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        term="x\ry",
    ))


def test_search_documents_all_empty_agencies_rejected():
    """P1: agencies=[''] used to return 10,000 default results."""
    asyncio.run(_call_expect_error(
        "search_documents", "contains only empty",
        agencies=[""],
    ))


def test_search_documents_whitespace_agencies_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "contains only empty",
        agencies=["   ", ""],
    ))


def test_search_documents_null_byte_in_docket_id_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        docket_id="x\x00y",
    ))


def test_search_documents_null_byte_in_rin_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        regulation_id_number="x\x00y",
    ))


def test_get_public_inspection_null_byte_in_keyword_filter():
    asyncio.run(_call_expect_error(
        "get_public_inspection", "control characters",
        keyword_filter="x\x00y",
    ))


def test_get_public_inspection_null_byte_in_agency_filter():
    asyncio.run(_call_expect_error(
        "get_public_inspection", "control characters",
        agency_filter="x\x00y",
    ))


def test_get_facet_counts_null_byte_in_term():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "control characters",
        facet="type", term="x\x00y",
    ))


def test_get_facet_counts_empty_agencies_rejected():
    asyncio.run(_call_expect_error(
        "get_facet_counts", "contains only empty",
        facet="type", agencies=[""],
    ))


# --- Response shape guard ---

def test_ensure_json_container_rejects_none():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return None
        @property
        def text(self): return ""
    class FakeClient:
        is_closed = False
        async def get(self, url, **kw): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_documents(term="test"))
    except RuntimeError as e:
        assert "empty body" in str(e).lower()
        return
    raise AssertionError("expected RuntimeError")


def test_ensure_json_container_rejects_int():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return 42
        @property
        def text(self): return "42"
    class FakeClient:
        is_closed = False
        async def get(self, url, **kw): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_documents(term="test"))
    except RuntimeError as e:
        assert "unexpected int" in str(e).lower()
        return
    raise AssertionError("expected RuntimeError")


def test_ensure_json_container_accepts_list():
    """/agencies.json returns a list. Shape guard must allow it."""
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return [{"id": 1, "name": "A", "slug": "a"}]
        @property
        def text(self): return "[]"
    class FakeClient:
        is_closed = False
        async def get(self, url, **kw): return FakeResp()
    srv._client = FakeClient()
    r = asyncio.run(srv.list_agencies())
    assert r.get("total_agencies") == 1


def test_ensure_json_container_rejects_string():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return "oops"
        @property
        def text(self): return "oops"
    class FakeClient:
        is_closed = False
        async def get(self, url, **kw): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_documents(term="test"))
    except RuntimeError as e:
        assert "unexpected str" in str(e).lower()
        return
    raise AssertionError("expected RuntimeError")


def test_user_agent_matches_version():
    from federal_register_mcp.constants import USER_AGENT
    assert "0.2.2" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


# ---- LIVE tests ----


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_search_with_term_returns_data():
    r = asyncio.run(_call("search_documents", term="cybersecurity", per_page=5))
    data = _payload(r)
    assert (data.get("count") or 0) > 0
    assert len(data.get("results", [])) > 0


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_search_compound_filter_narrows():
    r = asyncio.run(_call(
        "search_documents",
        term="cybersecurity",
        agencies=["defense-department"],
        doc_types=["RULE"],
        pub_date_gte="2024-01-01", pub_date_lte="2024-12-31",
        per_page=3,
    ))
    data = _payload(r)
    # Compound filter should return <1000 vs unfiltered 10,000
    assert (data.get("count") or 0) < 1000


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_get_document_real():
    """Two calls on one event loop so the shared httpx client stays valid."""
    async def _run():
        r1 = await _call("search_documents", term="cybersecurity", per_page=1)
        doc_num = _payload(r1)["results"][0]["document_number"]
        r2 = await _call("get_document", document_number=doc_num)
        return doc_num, _payload(r2)
    doc_num, data = asyncio.run(_run())
    assert data.get("document_number") == doc_num


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_list_agencies_returns_many():
    r = asyncio.run(_call("list_agencies"))
    data = _payload(r)
    # There are ~470 FR agencies
    assert data.get("total_agencies", 0) > 100


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_facet_counts():
    r = asyncio.run(_call("get_facet_counts", facet="type", term="cybersecurity"))
    data = _payload(r)
    # Facet response has type codes as top-level keys
    assert isinstance(data, dict) and len(data) > 0


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_public_inspection():
    r = asyncio.run(_call("get_public_inspection", limit=5))
    data = _payload(r)
    assert "total_pi_documents" in data


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_far_case_history():
    r = asyncio.run(_call("far_case_history", docket_id="FAR-2023-0008"))
    data = _payload(r)
    assert data.get("total_documents", 0) > 0


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_date_range_works():
    r = asyncio.run(_call(
        "search_documents",
        pub_date_gte="2024-06-01", pub_date_lte="2024-06-30",
        term="rule", per_page=3,
    ))
    data = _payload(r)
    assert isinstance(data.get("results"), list)


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_concurrent_searches():
    async def _run():
        return await asyncio.gather(*[
            _call("search_documents", term=t, per_page=3)
            for t in ("cyber", "grant", "contract", "rule", "notice")
        ])
    rs = asyncio.run(_run())
    assert all(_payload(r).get("results") is not None for r in rs)


@pytest.mark.skipif(not LIVE, reason="requires FR_LIVE_TESTS=1")
def test_live_boolean_filter_significant():
    r = asyncio.run(_call(
        "search_documents", term="cyber", significant=True, per_page=3,
    ))
    data = _payload(r)
    # significant=True should still return some results
    assert isinstance(data.get("results"), list)
