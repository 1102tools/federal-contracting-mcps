# SPDX-License-Identifier: MIT
"""Validation tests for regulationsgov-mcp 0.2.0 hardening pass.

All tests route through mcp.call_tool. Live tests (REGULATIONS_LIVE_TESTS=1)
require REGULATIONS_GOV_API_KEY set to an api.data.gov key.
"""
from __future__ import annotations

import asyncio
import os
import pytest

import regulationsgov_mcp.server as srv
from regulationsgov_mcp.server import mcp

LIVE = os.environ.get("REGULATIONS_LIVE_TESTS") == "1"


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
        assert match.lower() in str(e).lower(), f"expected {match!r}, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# Cross-fix: extra='forbid'
# ---------------------------------------------------------------------------

def test_unknown_param_search_documents():
    asyncio.run(_call_expect_error(
        "search_documents", "extra inputs are not permitted",
        agency_id="FAR", bogus_typo="x",
    ))


def test_unknown_param_search_dockets():
    async def _run():
        try:
            await mcp.call_tool("search_dockets", {"agency_id": "FAR", "typo": "x"})
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected rejection")
    asyncio.run(_run())


def test_unknown_param_get_docket_detail():
    async def _run():
        try:
            await mcp.call_tool(
                "get_docket_detail", {"docket_id": "FAR-2023-0008", "typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected rejection")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# agency_id validation
# ---------------------------------------------------------------------------

def test_agency_id_empty_rejected():
    """P1: empty string used to return all 1.95M records."""
    asyncio.run(_call_expect_error(
        "search_documents", "cannot be empty",
        agency_id="",
    ))


def test_agency_id_with_space_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "not a valid agency code",
        agency_id="FAR DOD",
    ))


def test_agency_id_numeric_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "not a valid agency code",
        agency_id="123",
    ))


def test_agency_id_angle_brackets_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "not a valid agency code",
        agency_id="<script>",
    ))


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------

def test_date_iso_t_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "YYYY-MM-DD",
        agency_id="FAR", posted_date_ge="2025-01-01T00:00:00Z",
    ))


def test_date_slashes_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "YYYY-MM-DD",
        agency_id="FAR", posted_date_ge="2025/01/01",
    ))


def test_date_invalid_calendar_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "valid calendar date",
        agency_id="FAR", posted_date_ge="2025-02-30",
    ))


def test_date_swapped_range_rejected():
    """posted_date_ge > posted_date_le used to return 0 silently."""
    asyncio.run(_call_expect_error(
        "search_documents", "after",
        agency_id="FAR", posted_date_ge="2025-12-31", posted_date_le="2025-01-01",
    ))


def test_last_modified_iso_rejected():
    asyncio.run(_call_expect_error(
        "search_dockets", "YYYY-MM-DD HH:MM:SS",
        agency_id="FAR", last_modified_date_ge="2025-01-01T00:00:00Z",
    ))


def test_last_modified_date_only_rejected():
    asyncio.run(_call_expect_error(
        "search_dockets", "YYYY-MM-DD HH:MM:SS",
        agency_id="FAR", last_modified_date_ge="2025-01-01",
    ))


def test_last_modified_correct_format_accepted():
    """'YYYY-MM-DD HH:MM:SS' should pass validation."""
    async def _run():
        try:
            await mcp.call_tool("search_dockets", {
                "agency_id": "FAR",
                "last_modified_date_ge": "2025-01-01 00:00:00",
                "page_size": 5,
            })
        except Exception as e:
            assert "YYYY-MM-DD" not in str(e), f"correct format rejected: {e}"
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# search_term validation
# ---------------------------------------------------------------------------

def test_search_term_null_byte_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        agency_id="FAR", search_term="x\x00y",
    ))


def test_search_term_newline_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "control characters",
        agency_id="FAR", search_term="x\ny",
    ))


def test_search_term_length_clamped():
    asyncio.run(_call_expect_error(
        "search_documents", "500 chars",
        agency_id="FAR", search_term="a" * 600,
    ))


# ---------------------------------------------------------------------------
# ID validation
# ---------------------------------------------------------------------------

def test_document_id_empty_rejected():
    asyncio.run(_call_expect_error(
        "get_document_detail", "cannot be empty", document_id="",
    ))


def test_document_id_whitespace_rejected():
    asyncio.run(_call_expect_error(
        "get_document_detail", "cannot be empty", document_id="   ",
    ))


def test_document_id_with_slash_rejected():
    """Slashes used to produce HTTP 500 from the API."""
    asyncio.run(_call_expect_error(
        "get_document_detail", "outside [A-Za-z0-9_.-]", document_id="a/b",
    ))


def test_document_id_traversal_rejected():
    asyncio.run(_call_expect_error(
        "get_document_detail", "outside [A-Za-z0-9_.-]", document_id="../admin",
    ))


def test_document_id_with_control_char_rejected():
    asyncio.run(_call_expect_error(
        "get_document_detail", "control characters", document_id="FAR-2023-0008\n",
    ))


def test_docket_id_empty_rejected():
    asyncio.run(_call_expect_error(
        "get_docket_detail", "cannot be empty", docket_id="",
    ))


def test_comment_id_empty_rejected():
    asyncio.run(_call_expect_error(
        "get_comment_detail", "cannot be empty", comment_id="",
    ))


# ---------------------------------------------------------------------------
# Page size / number
# ---------------------------------------------------------------------------

def test_page_size_too_small():
    asyncio.run(_call_expect_error(
        "search_documents", "must be >= 5",
        agency_id="FAR", page_size=4,
    ))


def test_page_size_too_large():
    asyncio.run(_call_expect_error(
        "search_documents", "exceeds maximum of 250",
        agency_id="FAR", page_size=251,
    ))


def test_page_size_zero():
    asyncio.run(_call_expect_error(
        "search_documents", "must be >= 5",
        agency_id="FAR", page_size=0,
    ))


def test_page_number_zero():
    asyncio.run(_call_expect_error(
        "search_documents", "must be >= 1",
        agency_id="FAR", page_number=0,
    ))


def test_page_number_negative():
    asyncio.run(_call_expect_error(
        "search_documents", "must be >= 1",
        agency_id="FAR", page_number=-1,
    ))


def test_page_number_over_cap():
    asyncio.run(_call_expect_error(
        "search_documents", "exceeds maximum of 20",
        agency_id="FAR", page_number=21,
    ))


# ---------------------------------------------------------------------------
# Sort validation
# ---------------------------------------------------------------------------

def test_sort_bogus_rejected():
    asyncio.run(_call_expect_error(
        "search_documents", "not a valid sort field",
        agency_id="FAR", sort="bogus",
    ))


def test_sort_descending_accepted():
    """Prefix '-' must be accepted."""
    async def _run():
        try:
            await mcp.call_tool("search_documents", {
                "agency_id": "FAR", "sort": "-postedDate", "page_size": 5,
            })
        except Exception as e:
            assert "not a valid sort field" not in str(e).lower()
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Workflow tool validation
# ---------------------------------------------------------------------------

def test_open_comment_periods_empty_list_rejected():
    asyncio.run(_call_expect_error(
        "open_comment_periods", "cannot be empty",
        agency_ids=[],
    ))


def test_open_comment_periods_too_many():
    asyncio.run(_call_expect_error(
        "open_comment_periods", "capped at 20",
        agency_ids=["FAR"] * 25,
    ))


def test_open_comment_periods_bad_agency_in_list():
    asyncio.run(_call_expect_error(
        "open_comment_periods", "not a valid agency",
        agency_ids=["FAR", "FAR DOD"],
    ))


# ---------------------------------------------------------------------------
# Response shape defense (mock _get)
# ---------------------------------------------------------------------------

def _mock_get(response):
    orig = srv._get
    async def fake(path, params=None):
        return response
    srv._get = fake
    return orig


def _restore_get(orig):
    srv._get = orig


def test_search_documents_handles_empty_response():
    """API returning {} (which _get already coerces from None/empty)."""
    orig = _mock_get({})
    try:
        r = asyncio.run(srv.search_documents(agency_id="FAR"))
        assert r.get("no_data") is True
        assert "no_data_reason" in r
    finally:
        _restore_get(orig)


def test_search_documents_handles_missing_data_key():
    """API returns meta but no data key -> treat as empty."""
    orig = _mock_get({"meta": {"totalElements": 0}})
    try:
        r = asyncio.run(srv.search_documents(agency_id="FAR"))
        assert r.get("no_data") is True
    finally:
        _restore_get(orig)


def test_search_documents_no_flag_when_real_results():
    """Real results (data list non-empty) must not get the no_data flag."""
    orig = _mock_get({
        "data": [{"id": "X", "attributes": {}}],
        "meta": {"totalElements": 1},
    })
    try:
        r = asyncio.run(srv.search_documents(agency_id="FAR"))
        assert r.get("no_data") is not True
    finally:
        _restore_get(orig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_user_agent_matches_version():
    from regulationsgov_mcp.constants import USER_AGENT
    assert "0.2.4" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


def test_safe_dict():
    assert srv._safe_dict(None) == {}
    assert srv._safe_dict([1, 2]) == {}
    assert srv._safe_dict({"a": 1}) == {"a": 1}


def test_as_list():
    assert srv._as_list(None) == []
    assert srv._as_list([1, 2]) == [1, 2]
    assert srv._as_list({"a": 1}) == [{"a": 1}]


def test_clean_error_body_strips_html():
    r = srv._clean_error_body("<html><head><title>500 Err</title></head></html>")
    assert "500 Err" in r
    assert "<html>" not in r


def test_clean_error_body_handles_bytes():
    assert "hi" in srv._clean_error_body(b"hi")


def test_clean_error_body_handles_none():
    assert srv._clean_error_body(None) == "(empty body)"


# ---------------------------------------------------------------------------
# LIVE tests (require REGULATIONS_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY")
def test_live_far_search():
    r = asyncio.run(_call("search_documents", agency_id="FAR", page_size=5))
    data = _payload(r)
    assert (data.get("meta", {}).get("totalElements", 0)) > 100


@pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY")
def test_live_docket_detail():
    r = asyncio.run(_call("get_docket_detail", docket_id="FAR-2023-0008"))
    data = _payload(r)
    attrs = data.get("data", {}).get("attributes", {})
    assert attrs.get("title")


@pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY")
def test_live_bad_agency_flags_no_data():
    """Round-1 P1 regression: unknown agency must flag no_data."""
    r = asyncio.run(_call("search_documents", agency_id="ZZZ", page_size=5))
    data = _payload(r)
    assert data.get("no_data") is True


@pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY")
def test_live_empty_agency_rejected():
    """Round-1 P1 regression: empty agency used to return 1.95M records."""
    try:
        asyncio.run(_call("search_documents", agency_id="", page_size=5))
    except Exception as e:
        assert "cannot be empty" in str(e).lower()
        return
    raise AssertionError("expected empty-agency rejection")


# ---------------------------------------------------------------------------
# Round 3 enhancement: paged_past_end flag differentiates from no_data
# ---------------------------------------------------------------------------

def test_paged_past_end_flag():
    """Empty data with total > 0 should set paged_past_end, not no_data."""
    orig = _mock_get({
        "data": [],
        "meta": {"totalElements": 2152},
    })
    try:
        r = asyncio.run(srv.search_documents(
            agency_id="FAR", page_size=250, page_number=20,
        ))
        assert r.get("paged_past_end") is True
        assert r.get("no_data") is not True
        assert "page 9" in r["paged_past_end_reason"]  # 2152 / 250 = 9 pages
    finally:
        _restore_get(orig)


def test_no_data_flag_when_total_zero():
    """Empty data with total=0 should set no_data, not paged_past_end."""
    orig = _mock_get({
        "data": [],
        "meta": {"totalElements": 0},
    })
    try:
        r = asyncio.run(srv.search_documents(agency_id="FAR"))
        assert r.get("no_data") is True
        assert r.get("paged_past_end") is not True
    finally:
        _restore_get(orig)


@pytest.mark.skipif(not LIVE, reason="requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY")
def test_live_paged_past_end():
    """Round-3 enhancement: pages past end must be flagged distinctly."""
    r = asyncio.run(_call(
        "search_documents", agency_id="FAR", page_size=250, page_number=20,
    ))
    data = _payload(r)
    assert data.get("paged_past_end") is True
    assert data.get("no_data") is not True
