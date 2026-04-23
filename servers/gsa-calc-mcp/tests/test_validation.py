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


@pytest.fixture(autouse=True)
def _reset_client():
    """httpx.AsyncClient gets bound to an asyncio loop; reusing across
    asyncio.run() invocations raises 'Event loop is closed'. Reset per-test."""
    import gsa_calc_mcp.server as S
    S._client = None
    yield
    S._client = None


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


# 0.2.0 shipped a WAF filter copied from sam-gov-mcp that rejected single
# quotes, SQL keywords, backticks, and semicolons. Round-1 of the 0.2.1
# live audit proved those were false positives -- GSA CALC accepts all of
# them as literal search text. Filter narrowed to just angle brackets,
# path traversal, and null bytes (which DO trigger GSA's WAF with 403).


def test_keyword_search_waf_angle_brackets_still_rejected():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="<script>"))


def test_keyword_search_waf_path_traversal_still_rejected():
    asyncio.run(_call_expect_error("keyword_search", "firewall", keyword="../../admin"))


def test_keyword_search_apostrophe_accepted():
    """Apostrophe in labor-category name (O'Brien, O'Reilly) must not be blocked."""
    try:
        asyncio.run(_call("keyword_search", keyword="O'Brien"))
    except Exception as e:
        msg = str(e).lower()
        assert "firewall" not in msg
        assert "single quote" not in msg


def test_keyword_search_sql_keywords_accepted():
    try:
        asyncio.run(_call("keyword_search", keyword="DROP TABLE"))
    except Exception as e:
        assert "firewall" not in str(e).lower()


def test_keyword_search_backtick_accepted():
    try:
        asyncio.run(_call("keyword_search", keyword="a`b"))
    except Exception as e:
        assert "firewall" not in str(e).lower()


def test_keyword_search_semicolon_accepted():
    try:
        asyncio.run(_call("keyword_search", keyword="a;b"))
    except Exception as e:
        assert "firewall" not in str(e).lower()


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


def test_igce_benchmark_waf_accepts_apostrophe_sql():
    """labor_category with apostrophe and SQL keywords must be accepted."""
    try:
        asyncio.run(_call("igce_benchmark", labor_category="'; DROP"))
    except Exception as e:
        assert "firewall" not in str(e).lower()


def test_igce_benchmark_waf_rejects_angle_brackets():
    asyncio.run(_call_expect_error(
        "igce_benchmark", "firewall", labor_category="<script>"
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


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop."""
    async def _run():
        try:
            await mcp.call_tool(
                "keyword_search", {"keyword": "engineer", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 0.2.2: live-audit regressions
# ---------------------------------------------------------------------------

# F1: control chars in free-text fields. Previously \n/\r/\t/\b slipped
# through because _strip_or_none eats leading/trailing whitespace but not
# internal control chars, and _validate_waf_safe only checked null byte.
def test_keyword_newline_rejected():
    asyncio.run(_call_expect_error("keyword_search", "control characters", keyword="a\nb"))


def test_keyword_tab_rejected():
    asyncio.run(_call_expect_error("keyword_search", "control characters", keyword="a\tb"))


def test_keyword_cr_rejected():
    asyncio.run(_call_expect_error("keyword_search", "control characters", keyword="a\rb"))


def test_keyword_backspace_rejected():
    asyncio.run(_call_expect_error("keyword_search", "control characters", keyword="a\x08b"))


def test_exact_search_value_newline_rejected():
    asyncio.run(_call_expect_error(
        "exact_search", "control characters",
        field="labor_category", value="a\nb"
    ))


def test_suggest_contains_term_newline_rejected():
    asyncio.run(_call_expect_error(
        "suggest_contains", "control characters",
        field="labor_category", term="a\nb"
    ))


def test_igce_benchmark_labor_category_newline_rejected():
    asyncio.run(_call_expect_error(
        "igce_benchmark", "control characters", labor_category="a\nb"
    ))


def test_vendor_rate_card_vendor_name_newline_rejected():
    asyncio.run(_call_expect_error(
        "vendor_rate_card", "control characters", vendor_name="a\nb"
    ))


def test_exclude_newline_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "control characters", keyword="dev", exclude="a\nb"
    ))


def test_exclude_null_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "control characters", keyword="dev", exclude="a\x00b"
    ))


# F2: exclude param not WAF-checked locally, round-tripped to GSA.
def test_exclude_angle_brackets_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "firewall", keyword="dev", exclude="<script>"
    ))


def test_exclude_path_traversal_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "firewall", keyword="dev", exclude="../etc"
    ))


def test_exclude_too_long():
    asyncio.run(_call_expect_error(
        "keyword_search", "exclude exceeds", keyword="dev", exclude="x"*600
    ))


# F3: filtered_browse with no filters returned 265k unfiltered records.
def test_filtered_browse_no_filters_rejected():
    asyncio.run(_call_expect_error(
        "filtered_browse", "at least one filter"
    ))


def test_filtered_browse_one_filter_ok():
    """One filter should satisfy the guard -- don't break legit browsing."""
    from gsa_calc_mcp.server import _build_filters
    # Proof the guard is filter-count-based: _build_filters with just
    # education_level produces one entry.
    assert _build_filters(education_level="PHD") == ["education_level:PHD"]


# F4: sin=True coerces bool->int 1 via pydantic Union before _validate_sin
# sees it. BeforeValidator now rejects bool at pydantic layer.
def test_sin_bool_true_rejected():
    async def _run():
        try:
            await mcp.call_tool("keyword_search", {"keyword": "dev", "sin": True})
        except Exception as e:
            assert "boolean" in str(e).lower()
            return
        raise AssertionError("sin=True should be rejected as bool")
    asyncio.run(_run())


def test_sin_bool_false_rejected():
    async def _run():
        try:
            await mcp.call_tool("keyword_search", {"keyword": "dev", "sin": False})
        except Exception as e:
            assert "boolean" in str(e).lower()
            return
        raise AssertionError("sin=False should be rejected as bool")
    asyncio.run(_run())


def test_sin_analysis_bool_rejected():
    async def _run():
        try:
            await mcp.call_tool("sin_analysis", {"sin_code": True})
        except Exception as e:
            assert "boolean" in str(e).lower()
            return
        raise AssertionError("sin_code=True should be rejected")
    asyncio.run(_run())


def test_sin_too_long():
    asyncio.run(_call_expect_error(
        "sin_analysis", "exceeds 20", sin_code="5"*200
    ))


# F5: proposed_rate=NaN produced vs_median="equal" and iqr_position="above P75"
# because NaN comparisons always return False and fall to else branches.
def test_proposed_rate_nan_rejected():
    asyncio.run(_call_expect_error(
        "price_reasonableness_check", "finite",
        labor_category="Software Developer", proposed_rate=float('nan')
    ))


def test_proposed_rate_inf_rejected():
    asyncio.run(_call_expect_error(
        "price_reasonableness_check", "finite",
        labor_category="Software Developer", proposed_rate=float('inf')
    ))


# F6: price_min/max=NaN/Inf passed pydantic (float type no finite constraint)
# and only failed at the API with HTTP 406.
def test_price_min_nan_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "finite", keyword="dev", price_min=float('nan')
    ))


def test_price_max_inf_rejected():
    asyncio.run(_call_expect_error(
        "keyword_search", "finite", keyword="dev", price_max=float('inf')
    ))


# F7: pagination past end (page*page_size > total) silently returned empty
# with no indication whether it was truly no data or we paged past the end.
def test_paged_past_end_flag():
    """Paging past the last-data page must set paged_past_end."""
    import gsa_calc_mcp.server as S

    async def fake(qs):
        # total=500, caller asks page=100 ps=10 -> offset 990 >> 500.
        # Within ES 10k window (100*10=1000) but past total.
        return {
            "hits": {"total": {"value": 500}, "hits": []},
            "aggregations": {},
        }

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.mcp.call_tool(
            "keyword_search", {"keyword": "test", "page": 100, "page_size": 10}
        ))
        payload = r[1] if isinstance(r, tuple) else r
        assert payload.get("paged_past_end") is True
        assert "last page with data is page" in payload.get("paged_past_end_reason", "")
    finally:
        S._get = orig


def test_paged_past_end_not_set_on_normal_page():
    """A normal page-1 call should NOT set paged_past_end."""
    import gsa_calc_mcp.server as S

    async def fake(qs):
        return {
            "hits": {"total": {"value": 2076}, "hits": [{"_source": {"labor_category": "X"}}]},
            "aggregations": {},
        }

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.mcp.call_tool(
            "keyword_search", {"keyword": "test", "page": 1, "page_size": 100}
        ))
        payload = r[1] if isinstance(r, tuple) else r
        assert "paged_past_end" not in payload
    finally:
        S._get = orig


# F8: GSA CALC's Elasticsearch has a 10,000-result window. page*page_size>10k
# previously round-tripped to a cryptic 406.
def test_es_window_page_times_page_size_over_10k():
    asyncio.run(_call_expect_error(
        "keyword_search", "10,000-result", keyword="dev", page=101, page_size=100
    ))


def test_es_window_page_500_ps_21():
    asyncio.run(_call_expect_error(
        "keyword_search", "10,000-result", keyword="dev", page=21, page_size=500
    ))


def test_es_window_ok_at_boundary():
    """page=100, page_size=100 == 10000 offset exactly, should pass."""
    import gsa_calc_mcp.server as S

    async def fake(qs):
        return {"hits": {"total": {"value": 50000}, "hits": []}, "aggregations": {}}

    orig = S._get
    S._get = fake
    try:
        r = asyncio.run(S.mcp.call_tool(
            "keyword_search", {"keyword": "test", "page": 100, "page_size": 100}
        ))
        # Should succeed (boundary == 10000, not > 10000)
        assert r is not None
    finally:
        S._get = orig


# F9-F12: length caps on free-text fields to pre-empt HTTP 406.
def test_igce_benchmark_labor_category_too_long():
    asyncio.run(_call_expect_error(
        "igce_benchmark", "labor_category exceeds", labor_category="x"*600
    ))


def test_suggest_contains_term_too_long():
    asyncio.run(_call_expect_error(
        "suggest_contains", "term exceeds",
        field="labor_category", term="x"*600
    ))


def test_vendor_rate_card_name_too_long():
    asyncio.run(_call_expect_error(
        "vendor_rate_card", "vendor_name exceeds", vendor_name="x"*600
    ))


# USER_AGENT freshness
def test_user_agent_bumped_026():
    from gsa_calc_mcp.constants import USER_AGENT
    assert "0.2.6" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


# ---------------------------------------------------------------------------
# Live-gated integration tests (GSA_CALC_LIVE_TESTS=1 to run)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_filtered_browse_one_filter_works():
    """Even with the at-least-one-filter guard, a single filter must still work."""
    result = asyncio.run(_call("filtered_browse", education_level="PHD", page_size=1))
    payload = _payload(result)
    assert payload.get("_stats", {}).get("total_rates", 0) > 0


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_apostrophe_vendor_passes():
    """Vendor names with apostrophes (O'Connor Davies) must be accepted."""
    result = asyncio.run(_call("vendor_rate_card", vendor_name="O'C"))
    payload = _payload(result)
    # Should either find a vendor or return a clear no-match error;
    # the key thing is no WAF firewall rejection.
    assert "firewall" not in str(payload).lower()


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_compound_filters_narrow():
    """Stacking 5+ filters should narrow, not accidentally widen."""
    result = asyncio.run(_call(
        "keyword_search",
        keyword="Software Developer",
        education_level="MA",
        experience_min=5, experience_max=15,
        business_size="S", security_clearance="yes",
        page_size=1,
    ))
    payload = _payload(result)
    total = payload.get("_stats", {}).get("total_rates", 0)
    # Stacked filters should yield a small, narrowed set.
    assert total < 1000, f"expected narrowing, got {total}"


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_concurrent_calls():
    """5 parallel calls should not clobber each other."""
    async def _run():
        res = await asyncio.gather(
            _call("keyword_search", keyword="engineer", page_size=1),
            _call("keyword_search", keyword="scientist", page_size=1),
            _call("keyword_search", keyword="analyst", page_size=1),
            _call("keyword_search", keyword="developer", page_size=1),
            _call("keyword_search", keyword="manager", page_size=1),
        )
        for r in res:
            payload = _payload(r)
            assert payload.get("_stats", {}).get("total_rates", 0) > 0
    asyncio.run(_run())


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_paged_past_end_real_api():
    """page 100 of 'Software Developer' (~2076 records) should flag paged_past_end."""
    async def _run():
        # 2076 / 100 ~= 21 pages, so page 100 is way past end.
        result = await _call(
            "keyword_search", keyword="Software Developer",
            page=100, page_size=100,
        )
        payload = _payload(result)
        assert payload.get("paged_past_end") is True
    asyncio.run(_run())


@pytest.mark.skipif(not LIVE, reason="Set GSA_CALC_LIVE_TESTS=1")
def test_live_unicode_keyword_roundtrip():
    """Japanese/emoji/accented chars round-trip without 403."""
    result = asyncio.run(_call("keyword_search", keyword="café", page_size=1))
    payload = _payload(result)
    assert "firewall" not in str(payload).lower()
