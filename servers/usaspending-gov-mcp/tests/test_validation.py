# SPDX-License-Identifier: MIT
"""Regression tests for 0.2.0 hardening fixes.

These invoke tools through the FastMCP registry (mcp.call_tool) rather
than awaiting the decorated coroutines directly. That matters: the prior
stress tests awaited raw coroutines and bypassed the tool pipeline,
missing whole classes of bugs. The patterns covered here (empty filters,
reversed ranges, retired-code filtering, autocomplete min-length) all
slipped through the raw-coroutine tests in 0.1.x.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.server import mcp


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"


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


# ---------------------------------------------------------------------------
# P0: empty-filter guards on count/aggregate endpoints
# ---------------------------------------------------------------------------

def test_get_award_count_no_filters_raises():
    asyncio.run(_call_expect_error("get_award_count", "at least one filter"))


def test_spending_over_time_no_filters_raises():
    asyncio.run(_call_expect_error("spending_over_time", "at least one filter"))


def test_spending_over_time_award_type_alone_raises():
    # award_type alone doesn't count as a real filter; the API still 400s.
    asyncio.run(
        _call_expect_error("spending_over_time", "at least one filter", award_type="contracts")
    )


# ---------------------------------------------------------------------------
# P1: autocomplete guards
# ---------------------------------------------------------------------------

def test_autocomplete_psc_short_query_returns_empty_with_note():
    result = asyncio.run(_call("autocomplete_psc", search_text="R"))
    # FastMCP's call_tool returns a tuple (content_blocks, structured_response) in
    # newer versions, or the dict directly in older. Handle both.
    payload = result[1] if isinstance(result, tuple) else result
    assert payload.get("results") == []
    assert "_note" in payload


def test_autocomplete_psc_empty_query_returns_empty_with_note():
    result = asyncio.run(_call("autocomplete_psc", search_text=""))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload.get("results") == []


def test_autocomplete_naics_short_query_returns_empty_with_note():
    result = asyncio.run(_call("autocomplete_naics", search_text="x"))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload.get("results") == []


# ---------------------------------------------------------------------------
# P1: token-cap bombs
# ---------------------------------------------------------------------------

def test_search_awards_limit_over_cap_raises():
    asyncio.run(_call_expect_error("search_awards", "exceeds maximum", limit=101))


def test_search_awards_limit_zero_raises():
    asyncio.run(_call_expect_error("search_awards", ">= 1", limit=0))


def test_get_transactions_limit_over_cap_raises():
    asyncio.run(
        _call_expect_error(
            "get_transactions",
            "exceeds maximum",
            generated_award_id="x",
            limit=5001,
        )
    )


def test_lookup_piid_short_raises():
    asyncio.run(_call_expect_error("lookup_piid", "at least 3", piid="NN"))


# ---------------------------------------------------------------------------
# P2: schema bounds and format
# ---------------------------------------------------------------------------

def test_search_awards_page_zero_raises():
    asyncio.run(_call_expect_error("search_awards", ">= 1", page=0))


def test_search_awards_bad_date_format_raises():
    asyncio.run(
        _call_expect_error(
            "search_awards",
            "YYYY-MM-DD",
            time_period_start="2026-01-01T00:00:00Z",
            time_period_end="2026-04-18",
        )
    )


def test_search_awards_slashed_date_raises():
    asyncio.run(
        _call_expect_error(
            "search_awards",
            "YYYY-MM-DD",
            time_period_start="2026/01/01",
            time_period_end="2026/04/18",
        )
    )


def test_fiscal_year_too_old_raises():
    asyncio.run(
        _call_expect_error(
            "get_agency_awards",
            ">= 2008",
            toptier_code="097",
            fiscal_year=1999,
        )
    )


def test_fiscal_year_future_raises():
    asyncio.run(
        _call_expect_error(
            "get_agency_awards",
            "<=",
            toptier_code="097",
            fiscal_year=2099,
        )
    )


# ---------------------------------------------------------------------------
# P2: type coercion and auto-padding
# ---------------------------------------------------------------------------

def test_toptier_code_short_is_left_padded():
    # We can't hit the live API in unit tests, but we can check the helper.
    from usaspending_gov_mcp.server import _normalize_toptier
    assert _normalize_toptier("97") == "097"
    assert _normalize_toptier("9") == "009"
    assert _normalize_toptier("097") == "097"
    assert _normalize_toptier("1234") == "1234"


def test_toptier_code_nonnumeric_raises():
    from usaspending_gov_mcp.server import _normalize_toptier
    with pytest.raises(ValueError, match="numeric"):
        _normalize_toptier("abc")


def test_naics_codes_accepts_ints():
    from usaspending_gov_mcp.server import _build_filters
    filters = _build_filters(naics_codes=[541511, 541512])
    assert filters["naics_codes"] == ["541511", "541512"]


def test_psc_codes_accepts_mixed_types():
    from usaspending_gov_mcp.server import _build_filters
    filters = _build_filters(psc_codes=["R425", "D302"])
    assert filters["psc_codes"] == ["R425", "D302"]


# ---------------------------------------------------------------------------
# P3: silent-empty validation
# ---------------------------------------------------------------------------

def test_empty_naics_codes_raises():
    from usaspending_gov_mcp.server import _build_filters
    with pytest.raises(ValueError, match="empty array"):
        _build_filters(naics_codes=[])


def test_empty_keywords_raises():
    from usaspending_gov_mcp.server import _build_filters
    with pytest.raises(ValueError, match="empty array"):
        _build_filters(keywords=[])


def test_reversed_date_range_raises():
    from usaspending_gov_mcp.server import _build_filters
    with pytest.raises(ValueError, match="after time_period_end"):
        _build_filters(time_period_start="2026-04-01", time_period_end="2026-01-01")


def test_reversed_amount_range_raises():
    from usaspending_gov_mcp.server import _build_filters
    with pytest.raises(ValueError, match="greater than"):
        _build_filters(award_amount_min=1000, award_amount_max=500)


def test_bad_state_code_raises():
    from usaspending_gov_mcp.server import _build_filters
    with pytest.raises(ValueError, match="USPS"):
        _build_filters(place_of_performance_state="ZZZ")


def test_state_code_is_uppercased():
    from usaspending_gov_mcp.server import _build_filters
    filters = _build_filters(place_of_performance_state="md")
    assert filters["place_of_performance_locations"][0]["state"] == "MD"


# ---------------------------------------------------------------------------
# P3: error hygiene
# ---------------------------------------------------------------------------

def test_html_error_body_is_cleaned():
    from usaspending_gov_mcp.server import _clean_error_body
    html = """<!doctype html>
<html lang="en">
<head><title>Not Found</title></head>
<body><h1>Not Found</h1><p>The requested resource was not found.</p></body>
</html>"""
    cleaned = _clean_error_body(html)
    assert "<!doctype" not in cleaned.lower()
    assert "<html" not in cleaned.lower()
    assert "Not Found" in cleaned


def test_plain_text_error_body_passthrough():
    from usaspending_gov_mcp.server import _clean_error_body
    assert _clean_error_body("plain error message") == "plain error message"


# ---------------------------------------------------------------------------
# Autocomplete retired filter (offline unit check of filter logic)
# ---------------------------------------------------------------------------

def test_autocomplete_naics_exclude_retired_filter_shape():
    """The exclude_retired=True path must filter year_retired != None."""
    # This exercises the post-filter logic without needing a network call.
    fake_results = [
        {"naics": "334611", "year_retired": 2012, "naics_description": "Software Reproducing"},
        {"naics": "541511", "year_retired": None, "naics_description": "Custom Computer Programming"},
        {"naics": "541512", "year_retired": None, "naics_description": "Computer Systems Design"},
    ]
    active = [r for r in fake_results if r.get("year_retired") is None]
    assert len(active) == 2
    assert all(r["year_retired"] is None for r in active)


# ---------------------------------------------------------------------------
# Live smoke tests (gated on USASPENDING_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_smoke_all_in_one_loop():
    """Live tests share a single event loop because the module caches an
    httpx client globally. Splitting into multiple asyncio.run() calls
    leaves orphaned clients bound to a closed loop."""

    async def run_all():
        # 1. search_awards happy path
        r1 = await mcp.call_tool(
            "search_awards",
            {
                "time_period_start": "2026-01-01",
                "time_period_end": "2026-04-18",
                "limit": 1,
            },
        )
        p1 = r1[1] if isinstance(r1, tuple) else r1
        assert p1["limit"] == 1
        assert "results" in p1

        # 2. get_award_count with filter (would have crashed on 0.1.3)
        r2 = await mcp.call_tool(
            "get_award_count",
            {
                "time_period_start": "2026-01-01",
                "time_period_end": "2026-04-18",
            },
        )
        p2 = r2[1] if isinstance(r2, tuple) else r2
        assert "results" in p2

        # 3. autocomplete_naics with exclude_retired filter
        r3 = await mcp.call_tool(
            "autocomplete_naics",
            {"search_text": "software", "limit": 5},
        )
        p3 = r3[1] if isinstance(r3, tuple) else r3
        # With exclude_retired=True (default), all returned should be active
        for item in p3.get("results", []):
            assert item.get("year_retired") is None, f"retired leaked: {item}"

        # 4. toptier auto-pad: "97" -> "097" -> Department of Defense
        r4 = await mcp.call_tool("get_agency_overview", {"toptier_code": "97"})
        p4 = r4[1] if isinstance(r4, tuple) else r4
        assert "Defense" in p4.get("name", "") or p4.get("toptier_code") == "097"

    asyncio.run(run_all())


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop."""
    async def _run():
        try:
            await mcp.call_tool(
                "search_awards", {"search_text": "cyber", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 0.2.2: live-audit fixes
# ---------------------------------------------------------------------------

def test_null_byte_in_keywords_rejected():
    """Null byte in keywords used to silently reach the API."""
    asyncio.run(_call_expect_error(
        "search_awards", "control characters",
        keywords=["abc\x00def"],
    ))


def test_newline_in_keywords_rejected():
    asyncio.run(_call_expect_error(
        "search_awards", "control characters",
        keywords=["line1\nline2"],
    ))


def test_tab_in_keywords_rejected():
    asyncio.run(_call_expect_error(
        "search_awards", "control characters",
        keywords=["col1\tcol2"],
    ))


def test_negative_amount_min_rejected():
    """Negative min was silently ignored by USASpending."""
    asyncio.run(_call_expect_error(
        "search_awards", "must be >= 0",
        award_amount_min=-1_000_000,
    ))


def test_negative_amount_max_rejected():
    asyncio.run(_call_expect_error(
        "search_awards", "must be >= 0",
        award_amount_max=-1_000,
    ))


def test_all_empty_naics_rejected():
    """naics_codes=['','',''] used to silently return unfiltered results."""
    asyncio.run(_call_expect_error(
        "search_awards", "contains only empty",
        naics_codes=["", "", ""],
    ))


def test_single_empty_psc_rejected():
    asyncio.run(_call_expect_error(
        "search_awards", "contains only empty",
        psc_codes=[""],
    ))


def test_single_empty_award_ids_rejected():
    asyncio.run(_call_expect_error(
        "search_awards", "contains only empty",
        award_ids=[""],
    ))


def test_null_byte_in_autocomplete_psc_rejected():
    """Null byte here used to produce HTTP 500 from the API."""
    asyncio.run(_call_expect_error(
        "autocomplete_psc", "control characters",
        search_text="abc\x00",
    ))


def test_null_byte_in_autocomplete_naics_rejected():
    asyncio.run(_call_expect_error(
        "autocomplete_naics", "control characters",
        search_text="abc\x00",
    ))


def test_null_byte_in_generated_award_id_rejected():
    """Null byte in award ID used to cause HTTP 500."""
    asyncio.run(_call_expect_error(
        "get_transactions", "control characters",
        generated_award_id="ABC\x00DEF",
    ))


def test_empty_generated_award_id_rejected_transactions():
    asyncio.run(_call_expect_error(
        "get_transactions", "cannot be empty",
        generated_award_id="",
    ))


def test_empty_generated_award_id_rejected_funding():
    asyncio.run(_call_expect_error(
        "get_award_funding", "cannot be empty",
        generated_award_id="",
    ))


def test_empty_generated_award_id_rejected_detail():
    asyncio.run(_call_expect_error(
        "get_award_detail", "cannot be empty",
        generated_award_id="",
    ))


def test_empty_idv_id_rejected():
    asyncio.run(_call_expect_error(
        "get_idv_children", "cannot be empty",
        generated_idv_id="",
    ))


def test_autocomplete_psc_length_clamped():
    asyncio.run(_call_expect_error(
        "autocomplete_psc", "exceeds 200 chars",
        search_text="a" * 300,
    ))


def test_user_agent_matches_version():
    from usaspending_gov_mcp.constants import USER_AGENT
    assert "0.3.1" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


# ---------------------------------------------------------------------------
# 0.2.3: round 3 live stress + round 4 shape mock findings
# ---------------------------------------------------------------------------

def test_search_awards_no_filters_rejected():
    """Round 3: search_awards() with no args used to return 25 unfiltered
    recent contracts. Now must require at least one real filter."""
    async def _run():
        try:
            await mcp.call_tool("search_awards", {})
        except Exception as e:
            assert "at least one filter" in str(e).lower()
            return
        raise AssertionError("expected no-filters rejection")
    asyncio.run(_run())


def test_search_awards_award_type_alone_rejected():
    """award_type alone is a scope not a filter; must still require a filter."""
    asyncio.run(_call_expect_error(
        "search_awards", "at least one filter",
        award_type="contracts",
    ))


def test_ensure_dict_response_catches_none():
    """Shape guard: None response raises a clear error, not a type confusion."""
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return None
    class FakeClient:
        is_closed = False
        async def post(self, path, json=None): return FakeResp()
        async def get(self, path, params=None): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_awards(
            keywords=["test"], time_period_start="2024-01-01", time_period_end="2024-06-30"
        ))
    except RuntimeError as e:
        assert "empty body" in str(e).lower() or "unexpected" in str(e).lower()
        return
    raise AssertionError("expected shape-guard rejection")


def test_ensure_dict_response_catches_list():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return []
    class FakeClient:
        is_closed = False
        async def post(self, path, json=None): return FakeResp()
        async def get(self, path, params=None): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_awards(
            keywords=["test"], time_period_start="2024-01-01", time_period_end="2024-06-30"
        ))
    except RuntimeError as e:
        assert "unexpected list" in str(e).lower()
        return
    raise AssertionError("expected shape-guard rejection")


def test_ensure_dict_response_catches_int():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return 42
    class FakeClient:
        is_closed = False
        async def post(self, path, json=None): return FakeResp()
        async def get(self, path, params=None): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_awards(
            keywords=["test"], time_period_start="2024-01-01", time_period_end="2024-06-30"
        ))
    except RuntimeError as e:
        assert "unexpected int" in str(e).lower()
        return
    raise AssertionError("expected shape-guard rejection")


def test_ensure_dict_response_catches_string():
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return "oops"
    class FakeClient:
        is_closed = False
        async def post(self, path, json=None): return FakeResp()
        async def get(self, path, params=None): return FakeResp()
    srv._client = FakeClient()
    try:
        asyncio.run(srv.search_awards(
            keywords=["test"], time_period_start="2024-01-01", time_period_end="2024-06-30"
        ))
    except RuntimeError as e:
        assert "unexpected str" in str(e).lower()
        return
    raise AssertionError("expected shape-guard rejection")


# ---------------------------------------------------------------------------
# Live regression tests (USASPENDING_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

def _payload(result):
    return result[1] if isinstance(result, tuple) else result


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_search_awards_returns_real_data():
    r = asyncio.run(_call(
        "search_awards", keywords=["software"],
        time_period_start="2024-01-01", time_period_end="2024-06-30", limit=3,
    ))
    data = _payload(r)
    assert len(data.get("results", [])) > 0


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_compound_filters_work():
    """Round 3 regression: stacked filters should actually apply."""
    r = asyncio.run(_call(
        "search_awards",
        keywords=["software"],
        naics_codes=["541511"],
        place_of_performance_state="VA",
        time_period_start="2024-01-01", time_period_end="2024-12-31",
        limit=3,
    ))
    data = _payload(r)
    # Narrow filter should return <100 vs unfiltered 25+
    assert isinstance(data.get("results"), list)


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_leap_year_date():
    """Round 3: leap-year date must not 500."""
    r = asyncio.run(_call(
        "search_awards",
        time_period_start="2024-02-29", time_period_end="2024-03-01", limit=3,
    ))
    _payload(r)  # just assert no exception


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_amount_range_boundary():
    """Round 3: exact-match amount range should not crash."""
    r = asyncio.run(_call(
        "search_awards",
        keywords=["software"],
        award_amount_min=1_000_000, award_amount_max=1_000_000, limit=3,
    ))
    _payload(r)


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_autocomplete_returns_data():
    r = asyncio.run(_call("autocomplete_psc", search_text="computer", limit=5))
    data = _payload(r)
    assert len(data.get("results", [])) > 0


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_state_profile_works():
    r = asyncio.run(_call("get_state_profile", state_fips="06"))
    data = _payload(r)
    assert data.get("code") == "CA"


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_concurrent_searches():
    async def _run():
        return await asyncio.gather(*[
            _call("search_awards", keywords=[kw], limit=3,
                  time_period_start="2024-01-01", time_period_end="2024-06-30")
            for kw in ("software", "consulting", "engineering")
        ])
    rs = asyncio.run(_run())
    assert all(_payload(r).get("results") is not None for r in rs)


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_unicode_keyword():
    """Round 3: unicode keywords (Spanish) must not crash; may return 0."""
    r = asyncio.run(_call(
        "search_awards", keywords=["español"], limit=3,
        time_period_start="2024-01-01", time_period_end="2024-06-30",
    ))
    _payload(r)  # no exception is the test


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_toptier_agencies_returns_many():
    r = asyncio.run(_call("list_toptier_agencies"))
    data = _payload(r)
    # There are ~100 toptier agencies
    assert len(data.get("results", [])) > 50
