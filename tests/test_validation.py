# SPDX-License-Identifier: MIT
"""Regression tests for 0.2.0 hardening fixes.

Invoked through the FastMCP registry (mcp.call_tool) so pydantic type coercion
runs exactly as in production. The prior stress_test.py awaited raw coroutines
and bypassed the tool pipeline, missing most bugs.
"""

from __future__ import annotations

import asyncio
import json
import math
import os

import pytest

from gsa_calc_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"


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
# Keyword / search validation
# ---------------------------------------------------------------------------

def test_keyword_search_empty_rejected():
    asyncio.run(_call_expect_error("keyword_search", "cannot be empty", keyword=""))


def test_keyword_search_whitespace_rejected():
    asyncio.run(_call_expect_error("keyword_search", "cannot be empty", keyword="   "))


def test_keyword_search_waf_sql():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="'; DROP TABLE"))


def test_keyword_search_waf_angle_brackets():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="<script>"))


def test_keyword_search_waf_path_traversal():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="../../admin"))


def test_keyword_search_waf_single_quote():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="O'Brien"))


def test_keyword_search_too_long():
    asyncio.run(_call_expect_error(
        "keyword_search", "500 chars", keyword="a" * 600
    ))


def test_keyword_search_unicode_passes():
    """Japanese / emoji should pass validation and URL-encode safely."""
    # Will hit network; the important thing is no ValueError
    try:
        asyncio.run(_call("keyword_search", keyword="ソフトウェア"))
    except Exception as e:
        assert "firewall" not in str(e).lower()


# ---------------------------------------------------------------------------
# page / page_size bounds
# ---------------------------------------------------------------------------

def test_page_below_one():
    asyncio.run(_call_expect_error("keyword_search", "page", keyword="test", page=0))


def test_page_negative():
    asyncio.run(_call_expect_error("keyword_search", "page", keyword="test", page=-5))


def test_page_huge():
    asyncio.run(_call_expect_error(
        "keyword_search", "page", keyword="test", page=9_999_999
    ))


def test_page_size_too_big():
    asyncio.run(_call_expect_error("keyword_search", "page_size", keyword="test", page_size=501))


def test_page_size_zero():
    asyncio.run(_call_expect_error("keyword_search", "page_size", keyword="test", page_size=0))


# ---------------------------------------------------------------------------
# Experience / price range validation
# ---------------------------------------------------------------------------

def test_experience_min_negative():
    asyncio.run(_call_expect_error(
        "keyword_search", "experience_min", keyword="test", experience_min=-1
    ))


def test_experience_reversed():
    asyncio.run(_call_expect_error(
        "keyword_search", "must be <=",
        keyword="test", experience_min=20, experience_max=5
    ))


def test_price_reversed():
    asyncio.run(_call_expect_error(
        "keyword_search", "must be <=",
        keyword="test", price_min=500, price_max=100
    ))


def test_price_min_negative():
    asyncio.run(_call_expect_error(
        "keyword_search", "price_min", keyword="test", price_min=-10
    ))


def test_experience_max_alone_applies_filter():
    """Round 1 bug: experience_max alone used to silently drop.

    Verify _build_filters includes the filter when only max is given.
    """
    from gsa_calc_mcp.server import _build_filters
    filters = _build_filters(experience_max=10)
    assert any("experience_range:0,10" in f for f in filters), f"got {filters}"


# ---------------------------------------------------------------------------
# Code validation (education, worksite, sin, ordering)
# ---------------------------------------------------------------------------

def test_education_level_bogus():
    asyncio.run(_call_expect_error(
        "keyword_search", "education_level", keyword="test", education_level="XYZ"
    ))


def test_education_level_pipe_delimited_works():
    """BA|MA should pass validation (GSA API supports OR)."""
    try:
        asyncio.run(_call("keyword_search", keyword="test", education_level="BA|MA"))
    except Exception as e:
        assert "education_level" not in str(e)


def test_education_level_lowercase_rejected():
    """GSA's API is case-sensitive on education level."""
    asyncio.run(_call_expect_error(
        "keyword_search", "education_level", keyword="test", education_level="ba"
    ))


def test_education_level_empty_pipe():
    asyncio.run(_call_expect_error(
        "keyword_search", "empty entry", keyword="test", education_level="BA|"
    ))


def test_worksite_bogus():
    asyncio.run(_call_expect_error(
        "keyword_search", "worksite", keyword="test", worksite="SpaceStation"
    ))


def test_worksite_case_normalized():
    """'customer' should normalize to 'Customer'."""
    try:
        asyncio.run(_call("keyword_search", keyword="test", worksite="customer"))
    except Exception as e:
        assert "worksite" not in str(e).lower() or "valid" not in str(e).lower()


def test_sin_special_chars_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "sin", keyword="test", sin="abc;DROP"
    ))


def test_sin_accepts_int():
    try:
        asyncio.run(_call("keyword_search", keyword="test", sin=54151))
    except Exception as e:
        assert "sin" not in str(e).lower() or "alphanumeric" not in str(e).lower()


def test_ordering_bogus():
    asyncio.run(_call_expect_error(
        "keyword_search", "ordering", keyword="test", ordering="price_descending"
    ))


def test_ordering_with_sql_suffix():
    asyncio.run(_call_expect_error(
        "keyword_search", "ordering", keyword="test", ordering="current_price DESC"
    ))


def test_ordering_whitespace_stripped():
    """'  current_price  ' should strip and validate OK."""
    try:
        asyncio.run(_call("keyword_search", keyword="test", ordering="  current_price  "))
    except Exception as e:
        assert "ordering" not in str(e).lower() or "valid" not in str(e).lower()


# ---------------------------------------------------------------------------
# price_reasonableness_check
# ---------------------------------------------------------------------------

def test_price_reasonableness_zero():
    asyncio.run(_call_expect_error(
        "price_reasonableness_check", "must be > 0",
        labor_category="Software Developer", proposed_rate=0
    ))


def test_price_reasonableness_negative():
    asyncio.run(_call_expect_error(
        "price_reasonableness_check", "must be > 0",
        labor_category="Software Developer", proposed_rate=-100
    ))


def test_price_reasonableness_empty_labor_category():
    asyncio.run(_call_expect_error(
        "price_reasonableness_check", "cannot be empty",
        labor_category="", proposed_rate=100
    ))


# ---------------------------------------------------------------------------
# suggest_contains
# ---------------------------------------------------------------------------

def test_suggest_contains_one_char():
    asyncio.run(_call_expect_error(
        "suggest_contains", "2 non-whitespace", field="vendor_name", term="x"
    ))


def test_suggest_contains_whitespace():
    asyncio.run(_call_expect_error(
        "suggest_contains", "2 non-whitespace", field="vendor_name", term="  "
    ))


# ---------------------------------------------------------------------------
# igce_benchmark
# ---------------------------------------------------------------------------

def test_igce_benchmark_empty_labor():
    asyncio.run(_call_expect_error(
        "igce_benchmark", "cannot be empty", labor_category=""
    ))


def test_igce_benchmark_waf_in_labor():
    asyncio.run(_call_expect_error(
        "igce_benchmark", "firewall", labor_category="'; DROP"
    ))


# ---------------------------------------------------------------------------
# vendor_rate_card
# ---------------------------------------------------------------------------

def test_vendor_rate_card_short():
    asyncio.run(_call_expect_error(
        "vendor_rate_card", "2 non-whitespace", vendor_name="x"
    ))


def test_vendor_rate_card_empty():
    asyncio.run(_call_expect_error(
        "vendor_rate_card", "2 non-whitespace", vendor_name=""
    ))


# ---------------------------------------------------------------------------
# sin_analysis
# ---------------------------------------------------------------------------

def test_sin_analysis_empty():
    asyncio.run(_call_expect_error(
        "sin_analysis", "cannot be empty", sin_code=""
    ))


def test_sin_analysis_special_chars():
    asyncio.run(_call_expect_error(
        "sin_analysis", "alphanumeric", sin_code="54151S;DROP"
    ))


def test_sin_analysis_accepts_int():
    try:
        asyncio.run(_call("sin_analysis", sin_code=541510))
    except Exception as e:
        assert "alphanumeric" not in str(e)


# ---------------------------------------------------------------------------
# Response-shape crash regressions
# ---------------------------------------------------------------------------

def test_extract_stats_empty():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({})
    assert r["total_rates"] == 0
    assert r["avg_rate"] is None


def test_extract_stats_aggregations_null():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": None, "hits": {"total": {"value": 5}}})
    assert r["total_rates"] == 5


def test_extract_stats_aggregations_list():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": []})
    assert r["total_rates"] == 0


def test_extract_stats_aggregations_string():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": "error"})
    assert r["total_rates"] == 0


def test_extract_stats_buckets_none():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"education_level_counts": {"buckets": None}}})
    assert r["education_breakdown"] == {}


def test_extract_stats_buckets_missing_keys():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"education_level_counts": {"buckets": [{}]}}})
    assert r["education_breakdown"] == {}


def test_extract_stats_buckets_partial():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"business_size": {"buckets": [{"key": "S"}, {"doc_count": 10}]}}})
    assert r["business_size_breakdown"] == {}


def test_extract_stats_buckets_with_none_entries():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"education_level_counts": {"buckets": [{"key": "BA", "doc_count": 10}, None, "invalid"]}}})
    assert r["education_breakdown"] == {"BA": 10}


def test_extract_stats_histogram_percentiles_none():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"histogram_percentiles": None}})
    assert r["percentiles"]["p50_median"] is None


def test_extract_stats_percentiles_values_none():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"histogram_percentiles": {"values": None}}})
    assert r["percentiles"]["p50_median"] is None


def test_extract_stats_wage_stats_none():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"wage_stats": None}})
    assert r["avg_rate"] is None


def test_extract_stats_std_deviation_bounds_none():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"wage_stats": {"std_deviation_bounds": None}}})
    assert r["outlier_bounds_2sigma"] == {"lower": None, "upper": None}


def test_extract_stats_hits_total_legacy_int():
    """ES 6 returns total as int, not {value, relation}."""
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"hits": {"total": 50}})
    assert r["total_rates"] == 50
    assert r["hits_capped"] is False


def test_extract_stats_hits_total_null():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"hits": {"total": None}})
    assert r["total_rates"] == 0


def test_extract_stats_hits_null():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"hits": None})
    assert r["total_rates"] == 0


def test_extract_stats_nan_filtered():
    """NaN avg/std should be coerced to None (they're unjsonable)."""
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"wage_stats": {"avg": math.nan, "std_deviation": math.nan}}})
    assert r["avg_rate"] is None
    assert r["std_deviation"] is None


def test_extract_stats_inf_filtered():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"wage_stats": {"avg": math.inf}}})
    assert r["avg_rate"] is None


def test_extract_stats_hits_capped():
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"hits": {"total": {"value": 10000, "relation": "gte"}}})
    assert r["hits_capped"] is True


def test_extract_stats_percentiles_int_keys():
    """GSA might return percentiles with integer keys (10 vs '10.0')."""
    from gsa_calc_mcp.server import _extract_stats
    r = _extract_stats({"aggregations": {"histogram_percentiles": {"values": {10: 50, 50: 100}}}})
    assert r["percentiles"]["p10"] == 50
    assert r["percentiles"]["p50_median"] == 100


# ---------------------------------------------------------------------------
# URL encoding of filters and exclude
# ---------------------------------------------------------------------------

def test_filter_values_url_encoded():
    """Round 3 bug: filter values were sent raw to URL."""
    from gsa_calc_mcp.server import _build_query_string
    qs = _build_query_string(filters=["worksite:Both & Customer"])
    # '&' in value should be encoded
    assert "&+Customer" in qs or "%26" in qs, f"ampersand not encoded: {qs}"


def test_exclude_url_encoded():
    """Round 3 bug: exclude param was sent raw."""
    from gsa_calc_mcp.server import _build_query_string
    qs = _build_query_string(keyword="test", exclude="id1&admin=1")
    # Count of 'admin=1' after encoding: should appear as query-part of exclude value
    # NOT as a separate query param
    segments = qs.split("&")
    # One segment should be the exclude with the whole value encoded
    exclude_segment = next((s for s in segments if s.startswith("exclude=")), None)
    assert exclude_segment is not None
    assert "admin" in exclude_segment, f"exclude value broken up: {qs}"


def test_filters_as_string_rejected():
    """Round 4 bug: filters as str iterated char-by-char."""
    from gsa_calc_mcp.server import _build_query_string
    try:
        _build_query_string(filters="education_level:BA")
    except ValueError:
        return
    raise AssertionError("filters as str should be rejected")


def test_search_modes_multiple_rejected():
    from gsa_calc_mcp.server import _build_query_string
    try:
        _build_query_string(keyword="a", search_field="vendor_name", search_value="b")
    except ValueError:
        return
    raise AssertionError("keyword + search combo should be rejected")


# ---------------------------------------------------------------------------
# _get non-JSON / empty body / malformed JSON
# ---------------------------------------------------------------------------

def test_query_bls_handles_non_json_200():
    """Round 5 bug: JSONDecodeError leaked raw."""
    import gsa_calc_mcp.server as S
    import httpx

    class FakeClient:
        async def get(self, url, **kw):
            return httpx.Response(200, content=b"<html>maint</html>", request=httpx.Request("GET", url))

    orig = S._get_client
    S._get_client = lambda: FakeClient()
    try:
        try:
            asyncio.run(S._get("keyword=test"))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "non-JSON" in str(e)
    finally:
        S._get_client = orig


def test_query_handles_empty_body():
    import gsa_calc_mcp.server as S
    import httpx

    class FakeClient:
        async def get(self, url, **kw):
            return httpx.Response(200, content=b"", request=httpx.Request("GET", url))

    orig = S._get_client
    S._get_client = lambda: FakeClient()
    try:
        try:
            asyncio.run(S._get("keyword=test"))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "non-JSON" in str(e)
    finally:
        S._get_client = orig


def test_query_handles_malformed_json():
    import gsa_calc_mcp.server as S
    import httpx

    class FakeClient:
        async def get(self, url, **kw):
            return httpx.Response(200, content=b"{incomplete", request=httpx.Request("GET", url))

    orig = S._get_client
    S._get_client = lambda: FakeClient()
    try:
        try:
            asyncio.run(S._get("keyword=test"))
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "non-JSON" in str(e)
    finally:
        S._get_client = orig


# ---------------------------------------------------------------------------
# Defensive hits iteration in vendor_rate_card
# ---------------------------------------------------------------------------

def test_vendor_rate_card_hits_null():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        if "suggest-contains" in qs:
            return {"aggregations": {"vendor_name": {"buckets": [{"key": "X", "doc_count": 1}]}}, "hits": {"total": {"value": 1}}}
        return {"hits": {"hits": None, "total": {"value": 0}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.vendor_rate_card(vendor_name="xx"))
        assert r["returned"] == 0
    finally:
        S._get = orig


def test_vendor_rate_card_source_null():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        if "suggest-contains" in qs:
            return {"aggregations": {"vendor_name": {"buckets": [{"key": "X", "doc_count": 1}]}}, "hits": {"total": {"value": 1}}}
        return {"hits": {"hits": [{"_source": None}], "total": {"value": 1}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.vendor_rate_card(vendor_name="xx"))
        assert r["returned"] == 1
    finally:
        S._get = orig


def test_vendor_rate_card_hits_nondict_items():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        if "suggest-contains" in qs:
            return {"aggregations": {"vendor_name": {"buckets": [{"key": "X", "doc_count": 1}]}}, "hits": {"total": {"value": 1}}}
        return {"hits": {"hits": [None, "str_item", 42, {"_source": {"labor_category": "Dev"}}], "total": {"value": 4}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.vendor_rate_card(vendor_name="xx"))
        assert r["returned"] == 1  # only the valid dict item counts
    finally:
        S._get = orig


def test_vendor_rate_card_multiple_suggestions_note():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        if "suggest-contains" in qs:
            return {"aggregations": {"vendor_name": {"buckets": [
                {"key": "ACME CORP", "doc_count": 900},
                {"key": "ACME INC", "doc_count": 500},
                {"key": "ACME LLC", "doc_count": 100},
            ]}}, "hits": {"total": {"value": 1500}}}
        return {"hits": {"hits": [], "total": {"value": 0}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.vendor_rate_card(vendor_name="acme"))
        assert "_note" in r
        assert "_candidates" in r
        assert len(r["_candidates"]) == 3
    finally:
        S._get = orig


def test_suggest_contains_buckets_missing_key():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        return {"aggregations": {"vendor_name": {"buckets": [{"key": "A", "doc_count": 1}, {}, {"key": "B", "doc_count": 2}]}}, "hits": {"total": {"value": 3}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.suggest_contains(field="vendor_name", term="test"))
        assert len(r["suggestions"]) == 2
    finally:
        S._get = orig


# ---------------------------------------------------------------------------
# price_reasonableness NO_DATA and none-safe median
# ---------------------------------------------------------------------------

def test_price_reasonableness_vs_median_unknown_when_missing():
    import gsa_calc_mcp.server as S

    async def fake(qs):
        return {"hits": {"total": {"value": 10}}, "aggregations": {"wage_stats": {"count": 10, "avg": 100, "std_deviation": 20}, "histogram_percentiles": {"values": {"10.0": 50}}}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.price_reasonableness_check(labor_category="test", proposed_rate=75))
        assert "unknown" in r["analysis"]["vs_median"]
    finally:
        S._get = orig


# ---------------------------------------------------------------------------
# USER_AGENT currency
# ---------------------------------------------------------------------------

def test_user_agent_matches_version():
    from gsa_calc_mcp.constants import USER_AGENT
    assert "0.2.0" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


# ---------------------------------------------------------------------------
# Live tests (opt-in)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1 to run live API calls")
def test_live_igce_benchmark_software_dev():
    result = asyncio.run(_call("igce_benchmark", labor_category="Software Developer"))
    payload = _payload(result)
    assert payload.get("total_rates", 0) > 0


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1 to run live API calls")
def test_live_suggest_contains_booz():
    result = asyncio.run(_call("suggest_contains", field="vendor_name", term="booz"))
    payload = _payload(result)
    assert len(payload.get("suggestions", [])) > 0
