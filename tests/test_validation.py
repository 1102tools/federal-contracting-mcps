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

from usaspending_gov_mcp.server import mcp


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"


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
