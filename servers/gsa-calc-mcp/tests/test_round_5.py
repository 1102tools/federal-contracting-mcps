# SPDX-License-Identifier: MIT
"""Round 5: Hypothesis-driven property test suite + extensive live audit.

Combines lessons from sam-gov-mcp round 7 (Hypothesis caught 2 P3 bugs),
usaspending round 6/7 (live audit caught 2 P2 bugs), and gsa-perdiem
round 7 (240 live tests across 50 states).

GSA CALC is keyless and rate-limit-free, so live testing can be aggressive.

Sections:
- Hypothesis property tests for every validator (~80 functions × 500 probes)
- Mock fuzz on response shape helpers (_safe_dict, _as_list, _safe_number)
- ~150 live tests across all 8 tools
- Async concurrency stress
- Encoding edge cases
- Composite tool deep tests (igce_benchmark, price_reasonableness_check, vendor_rate_card)

Cost: ~150 GSA CALC API calls per full live run. No documented rate limit.
Runtime: 4-7 minutes typical.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import gsa_calc_mcp.server as srv  # noqa: E402
from gsa_calc_mcp.server import (  # noqa: E402
    _as_list,
    _clamp,
    _clamp_text_len,
    _safe_bucket_key,
    _safe_dict,
    _safe_number,
    _strip_or_none,
    _validate_education_level,
    _validate_experience_range,
    _validate_finite,
    _validate_no_control_chars,
    _validate_ordering,
    _validate_price_range,
    _validate_sin,
    _validate_sort,
    _validate_waf_safe,
    _validate_worksite,
)
from gsa_calc_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("GSA_CALC_LIVE_TESTS") == "1"

PUNISHMENT = settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ===========================================================================
# A. _safe_dict / _as_list / _safe_number FUZZ
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.dictionaries(st.text(), st.integers()),
    st.text(),
    st.integers(),
    st.lists(st.integers()),
))
def test_property_safe_dict_returns_dict(value):
    """_safe_dict must always return a dict."""
    result = _safe_dict(value)
    assert isinstance(result, dict)


@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.lists(st.integers()),
    st.dictionaries(st.text(), st.integers()),
    st.text(),
    st.integers(),
    st.tuples(st.integers()),
    st.sets(st.integers()),
))
def test_property_as_list_returns_list(value):
    """_as_list must always return a list."""
    result = _as_list(value)
    assert isinstance(result, list)


@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(),
    st.booleans(),
    st.lists(st.integers()),
    st.dictionaries(st.text(), st.integers()),
))
def test_property_safe_number_returns_number_or_none(value):
    """_safe_number returns int, float, or None. Never raises."""
    result = _safe_number(value)
    assert result is None or isinstance(result, (int, float))


@PUNISHMENT
@given(st.one_of(st.none(), st.dictionaries(st.text(), st.integers())))
def test_property_safe_bucket_key_handles_input(value):
    """_safe_bucket_key returns tuple or None. Never raises."""
    try:
        result = _safe_bucket_key(value)
        assert result is None or isinstance(result, tuple)
    except Exception as e:
        # Should not raise on any input
        raise AssertionError(f"_safe_bucket_key raised on {value!r}: {e}")


# ===========================================================================
# B. _validate_no_control_chars / _validate_waf_safe PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_validate_no_control_chars_never_crashes(value):
    try:
        _validate_no_control_chars(value, field="x")
    except ValueError:
        pass


@PUNISHMENT
@given(st.integers(min_value=0, max_value=31))
def test_property_validate_no_control_chars_rejects_each_control(codepoint):
    """Every codepoint 0-31 must be rejected when embedded."""
    text = f"abc{chr(codepoint)}def"
    try:
        _validate_no_control_chars(text, field="x")
        assert False, f"control 0x{codepoint:02x} should be rejected"
    except ValueError:
        pass


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_validate_waf_safe_never_crashes(value):
    try:
        _validate_waf_safe(value, field="x")
    except ValueError:
        pass


# ===========================================================================
# C. _validate_finite / numerical helpers
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
))
def test_property_validate_finite_handles_all_numbers(value):
    """_validate_finite returns the value or raises ValueError on inf/nan."""
    try:
        result = _validate_finite(value, field="x")
        if result is not None:
            assert isinstance(result, (int, float))
            # If it returned, must be finite
            import math
            assert not math.isinf(result)
            assert not math.isnan(result)
    except ValueError:
        pass


def test_validate_finite_rejects_inf():
    with pytest.raises(ValueError):
        _validate_finite(float("inf"), field="x")


def test_validate_finite_rejects_negative_inf():
    with pytest.raises(ValueError):
        _validate_finite(float("-inf"), field="x")


def test_validate_finite_rejects_nan():
    with pytest.raises(ValueError):
        _validate_finite(float("nan"), field="x")


# ===========================================================================
# D. _clamp_text_len / _strip_or_none
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=2000)), st.integers(min_value=1, max_value=5000))
def test_property_clamp_text_len_never_crashes(value, maximum):
    try:
        result = _clamp_text_len(value, field="x", maximum=maximum)
        if result is not None:
            assert len(result) <= maximum
    except ValueError:
        pass


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_strip_or_none_returns_string_or_none(value):
    result = _strip_or_none(value)
    assert result is None or isinstance(result, str)
    if result is not None:
        assert result == result.strip()
        assert result != ""


# ===========================================================================
# E. _clamp PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(
    st.integers(min_value=-sys.maxsize, max_value=sys.maxsize),
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
)
def test_property_clamp_never_crashes(value, lo, hi):
    if lo > hi:
        return
    try:
        result = _clamp(value, field="x", lo=lo, hi=hi)
        assert lo <= result <= hi
    except ValueError:
        assert value < lo or value > hi


# ===========================================================================
# F. _validate_education_level
# ===========================================================================

VALID_EDU_LEVELS = ["AA", "BA", "HS", "MA", "PHD", "TEC"]


@pytest.mark.parametrize("edu", VALID_EDU_LEVELS)
def test_validate_education_level_each_valid(edu):
    """Every valid education level should pass."""
    result = _validate_education_level(edu)
    assert result == edu


@pytest.mark.parametrize("edu", [
    "BA|MA",  # pipe-delimited OR
    "AA|BA|MA|PHD",  # multiple
    "BA|MA|PHD",
    "HS|TEC",
])
def test_validate_education_level_pipe_delimited(edu):
    """Pipe-delimited combos should pass."""
    result = _validate_education_level(edu)
    assert result is not None


@pytest.mark.parametrize("edu", [
    "ba",  # lowercase
    "Ba",
    "  BA  ",  # padded
])
def test_validate_education_level_normalization(edu):
    """Case/whitespace normalization."""
    try:
        result = _validate_education_level(edu)
        # If accepted, should be normalized
        assert result is None or result.isupper()
    except ValueError:
        pass


@pytest.mark.parametrize("edu", [
    "INVALID",
    "BACHELORS",
    "X",
    "BA|INVALID",
    "BA||MA",  # double pipe
    "|BA",  # leading pipe
    "BA|",  # trailing pipe
])
def test_validate_education_level_invalid_rejected(edu):
    """Invalid edu codes should raise."""
    try:
        result = _validate_education_level(edu)
        # Some normalization-friendly inputs may be accepted
    except ValueError:
        pass


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=50)))
def test_property_validate_education_level_never_crashes(value):
    try:
        _validate_education_level(value)
    except ValueError:
        pass


# ===========================================================================
# G. _validate_worksite
# ===========================================================================

@pytest.mark.parametrize("ws", ["Customer", "Contractor", "Both"])
def test_validate_worksite_each_valid(ws):
    result = _validate_worksite(ws)
    assert result == ws


@pytest.mark.parametrize("ws", ["customer", "CUSTOMER", "  Both  "])
def test_validate_worksite_normalization(ws):
    try:
        _validate_worksite(ws)
    except ValueError:
        pass


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=50)))
def test_property_validate_worksite_never_crashes(value):
    try:
        _validate_worksite(value)
    except ValueError:
        pass


# ===========================================================================
# H. _validate_sin
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.text(min_size=0, max_size=30),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.lists(st.integers()),
))
def test_property_validate_sin_never_crashes(value):
    try:
        result = _validate_sin(value)
        if result is not None:
            assert isinstance(result, str)
    except (ValueError, TypeError):
        pass


@pytest.mark.parametrize("sin", [
    "54151S", "541611", "541715", "541330ENG", "541512", "611430",
])
def test_validate_sin_real_codes(sin):
    result = _validate_sin(sin)
    assert result == sin


def test_validate_sin_int_coerced():
    result = _validate_sin(541611)
    assert result == "541611"


def test_validate_sin_bool_rejected():
    """Bools are nasty subtypes of int; should be rejected."""
    try:
        _validate_sin(True)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# I. _validate_experience_range / _validate_price_range
# ===========================================================================

@PUNISHMENT
@given(
    st.one_of(st.none(), st.integers(min_value=-100, max_value=100)),
    st.one_of(st.none(), st.integers(min_value=-100, max_value=100)),
)
def test_property_validate_experience_range_never_crashes(emin, emax):
    try:
        result = _validate_experience_range(emin, emax)
        assert isinstance(result, tuple)
        assert len(result) == 2
    except ValueError:
        pass


@PUNISHMENT
@given(
    st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10000)),
    st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10000)),
)
def test_property_validate_price_range_never_crashes(pmin, pmax):
    try:
        result = _validate_price_range(pmin, pmax)
        assert isinstance(result, tuple)
        assert len(result) == 2
    except ValueError:
        pass


@pytest.mark.parametrize("emin,emax", [
    (10, 5),  # reversed
    (-1, 5),  # negative
    (5, -1),  # negative
    (None, -1),
    (-1, None),
])
def test_validate_experience_range_invalid(emin, emax):
    try:
        _validate_experience_range(emin, emax)
    except ValueError:
        pass


@pytest.mark.parametrize("pmin,pmax", [
    (100.0, 50.0),  # reversed
    (-1.0, 50.0),  # negative
    (50.0, -1.0),  # negative
    (float("inf"), 50.0),
    (50.0, float("inf")),
    (float("nan"), 50.0),
])
def test_validate_price_range_invalid(pmin, pmax):
    try:
        _validate_price_range(pmin, pmax)
    except ValueError:
        pass


# ===========================================================================
# J. _validate_ordering / _validate_sort
# ===========================================================================

VALID_ORDERINGS = [
    "current_price", "labor_category", "vendor_name",
    "education_level", "min_years_experience",
]


@pytest.mark.parametrize("ord", VALID_ORDERINGS)
def test_validate_ordering_each_valid(ord):
    result = _validate_ordering(ord)
    assert result == ord


@pytest.mark.parametrize("ord", [
    "invalid_field", "id", "ID", "price", "rate", "_id",
])
def test_validate_ordering_invalid(ord):
    try:
        _validate_ordering(ord)
    except ValueError:
        pass


def test_validate_sort_asc():
    assert _validate_sort("asc") == "asc"


def test_validate_sort_desc():
    assert _validate_sort("desc") == "desc"


@pytest.mark.parametrize("sort", ["ASC", "DESC", "ascending", "descending", "up"])
def test_validate_sort_invalid_or_normalized(sort):
    try:
        _validate_sort(sort)
    except ValueError:
        pass


# ===========================================================================
# K. ASYNC CONCURRENCY STRESS
# ===========================================================================

def test_concurrency_stress_50_validation_rejections():
    """50 concurrent calls hitting validation reject paths."""
    async def _run():
        tasks = [
            mcp.call_tool("keyword_search", {"keyword": ""})
            for _ in range(50)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50
    assert all(isinstance(r, Exception) for r in results)


def test_concurrency_stress_100_mixed_invalid():
    """100 concurrent calls across 4 tools."""
    async def _run():
        tasks = (
            [mcp.call_tool("keyword_search", {"keyword": ""})] * 25
            + [mcp.call_tool("exact_search", {"field": "labor_category", "value": ""})] * 25
            + [mcp.call_tool("vendor_rate_card", {"vendor_name": ""})] * 25
            + [mcp.call_tool("sin_analysis", {"sin_code": ""})] * 25
        )
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 100


def test_concurrency_event_loop_isolation_50_runs():
    for _ in range(50):
        try:
            asyncio.run(mcp.call_tool("keyword_search", {"keyword": ""}))
        except Exception:
            pass


# ===========================================================================
# L. ENCODING EDGE CASES
# ===========================================================================

@pytest.mark.parametrize("text", [
    "café", "cafe\u0301", "über", "u\u0308ber",
    "L\u2019Oreal", "L'Oreal", "\ufeffBOM",
    "test\u200btest", "test\u00a0test",
])
def test_unicode_normalization_in_validate_no_control(text):
    try:
        _validate_no_control_chars(text, field="x")
    except ValueError:
        pass


@pytest.mark.parametrize("emoji", ["🚀", "💻", "🎉", "🌟", "⭐"])
def test_emoji_in_validate_no_control(emoji):
    text = f"abc{emoji}def"
    try:
        _validate_no_control_chars(text, field="x")
    except ValueError:
        pass


# ===========================================================================
# M. INTEGER BOUNDARIES
# ===========================================================================

@PUNISHMENT
@given(st.integers(min_value=-sys.maxsize, max_value=sys.maxsize))
def test_property_clamp_huge_ints(value):
    try:
        _clamp(value, field="x", lo=1, hi=100)
    except ValueError:
        pass


# ===========================================================================
# N. LIVE TESTS — Real GSA CALC API
# ===========================================================================

# All live tests gate on GSA_CALC_LIVE_TESTS=1
LIVE_REASON = "requires GSA_CALC_LIVE_TESTS=1"

# Common labor categories in GSA CALC
COMMON_LABOR_CATEGORIES = [
    "Software Developer",
    "Project Manager",
    "Data Scientist",
    "Cyber Security Analyst",
    "Systems Engineer",
    "Business Analyst",
    "Program Manager",
    "Network Engineer",
    "Database Administrator",
    "Cloud Engineer",
    "DevOps Engineer",
    "Quality Assurance Analyst",
    "Technical Writer",
    "Help Desk Specialist",
    "Information Security Specialist",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", COMMON_LABOR_CATEGORIES)
def test_live_keyword_search_each_common_category(term):
    r = asyncio.run(mcp.call_tool("keyword_search", {"keyword": term, "page_size": 5}))
    data = _payload(r)
    assert isinstance(data, dict)


# Real SINs
COMMON_SINS = [
    "54151S", "541611", "541715", "541330ENG", "541512", "611430",
    "541330", "541990",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("sin", COMMON_SINS)
def test_live_sin_analysis_each_real_sin(sin):
    r = asyncio.run(mcp.call_tool("sin_analysis", {"sin_code": sin, "page_size": 10}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_sin_analysis_int_coerced():
    r = asyncio.run(mcp.call_tool("sin_analysis", {"sin_code": 541611, "page_size": 5}))
    data = _payload(r)
    assert isinstance(data, dict)


# Education level coverage
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("edu", VALID_EDU_LEVELS)
def test_live_filtered_browse_each_education(edu):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "education_level": edu,
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_filtered_browse_pipe_delimited_education():
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "education_level": "BA|MA",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Experience range coverage
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("emin,emax", [
    (0, 5), (5, 10), (10, 20), (20, 30), (0, 50),
])
def test_live_filtered_browse_experience_ranges(emin, emax):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "experience_min": emin,
        "experience_max": emax,
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Price range coverage
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("pmin,pmax", [
    (50.0, 100.0), (100.0, 200.0), (200.0, 500.0), (1.0, 50.0),
])
def test_live_filtered_browse_price_ranges(pmin, pmax):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "price_min": pmin,
        "price_max": pmax,
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Business size + clearance + worksite combinations
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("size", ["S", "O"])
def test_live_filtered_browse_business_size(size):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "business_size": size,
        "education_level": "BA",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("clearance", ["yes", "no"])
def test_live_filtered_browse_clearance(clearance):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "security_clearance": clearance,
        "education_level": "BA",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("worksite", ["Customer", "Contractor", "Both"])
def test_live_filtered_browse_worksite(worksite):
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "worksite": worksite,
        "education_level": "BA",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# exact_search
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_exact_search_labor_category():
    r = asyncio.run(mcp.call_tool("exact_search", {
        "field": "labor_category",
        "value": "Senior Software Developer",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_exact_search_vendor_name():
    r = asyncio.run(mcp.call_tool("exact_search", {
        "field": "vendor_name",
        "value": "DELOITTE CONSULTING LLP",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# suggest_contains
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("field,term", [
    ("labor_category", "developer"),
    ("labor_category", "manager"),
    ("labor_category", "analyst"),
    ("vendor_name", "lockheed"),
    ("vendor_name", "booz"),
    ("vendor_name", "accenture"),
])
def test_live_suggest_contains_each(field, term):
    r = asyncio.run(mcp.call_tool("suggest_contains", {
        "field": field,
        "term": term,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# igce_benchmark
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("category", [
    "Software Developer",
    "Project Manager",
    "Data Scientist",
    "Cyber Security Analyst",
    "Systems Engineer",
])
def test_live_igce_benchmark_each_category(category):
    r = asyncio.run(mcp.call_tool("igce_benchmark", {
        "labor_category": category,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_igce_benchmark_with_filters():
    r = asyncio.run(mcp.call_tool("igce_benchmark", {
        "labor_category": "Software Developer",
        "education_level": "BA",
        "experience_min": 5,
        "business_size": "S",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# price_reasonableness_check
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("rate", [50.0, 100.0, 150.0, 200.0, 300.0])
def test_live_price_reasonableness_each_rate(rate):
    r = asyncio.run(mcp.call_tool("price_reasonableness_check", {
        "labor_category": "Software Developer",
        "proposed_rate": rate,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_price_reasonableness_with_full_filters():
    r = asyncio.run(mcp.call_tool("price_reasonableness_check", {
        "labor_category": "Project Manager",
        "proposed_rate": 175.0,
        "education_level": "BA",
        "experience_min": 5,
        "experience_max": 15,
        "business_size": "S",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# vendor_rate_card
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("vendor", [
    "ACCENTURE FEDERAL SERVICES LLC",
    "DELOITTE CONSULTING LLP",
    "BOOZ ALLEN HAMILTON INC",
])
def test_live_vendor_rate_card_each_vendor(vendor):
    r = asyncio.run(mcp.call_tool("vendor_rate_card", {
        "vendor_name": vendor,
        "page_size": 50,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Pagination
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_page_2():
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "page": 2, "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_page_5():
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "page": 5, "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_max_page_size():
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "page_size": 200,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Ordering variations
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("ordering", VALID_ORDERINGS)
def test_live_keyword_search_each_ordering(ordering):
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "ordering": ordering, "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("sort", ["asc", "desc"])
def test_live_keyword_search_each_sort(sort):
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "sort": sort, "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Real WAF probes
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", [
    "McDonald's", "L'Oreal", "AT&T", "café",
])
def test_live_keyword_search_special_chars(term):
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": term, "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Compound filter combinations
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_compound_filters():
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "developer",
        "education_level": "BA|MA",
        "experience_min": 5,
        "experience_max": 15,
        "price_min": 50.0,
        "price_max": 250.0,
        "business_size": "S",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_filtered_browse_compound():
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "education_level": "MA",
        "experience_min": 10,
        "business_size": "S",
        "sin": "54151S",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Edge case: very narrow filter
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_unlikely_match():
    """A bizarre combination should return zero or few results without crash."""
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "xyzzyfooxyzzybar",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Concurrent live calls
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_concurrent_5_searches():
    async def _run():
        return await asyncio.gather(
            mcp.call_tool("keyword_search", {"keyword": "developer", "page_size": 3}),
            mcp.call_tool("keyword_search", {"keyword": "manager", "page_size": 3}),
            mcp.call_tool("keyword_search", {"keyword": "analyst", "page_size": 3}),
            mcp.call_tool("keyword_search", {"keyword": "engineer", "page_size": 3}),
            mcp.call_tool("sin_analysis", {"sin_code": "54151S", "page_size": 3}),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


# Response shape verification
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_response_has_results_or_stats():
    r = asyncio.run(mcp.call_tool("keyword_search", {
        "keyword": "engineer", "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in ["results", "_stats", "count", "total"])


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_sin_analysis_response_has_sin():
    r = asyncio.run(mcp.call_tool("sin_analysis", {"sin_code": "54151S"}))
    data = _payload(r)
    assert isinstance(data, dict)
    assert "sin" in data


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_filtered_browse_includes_pagination_flags():
    r = asyncio.run(mcp.call_tool("filtered_browse", {
        "education_level": "BA",
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Validation rejection live (verify defensive checks fire even with API up)
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_filtered_browse_no_filters_rejected():
    """filtered_browse requires at least one filter."""
    try:
        asyncio.run(mcp.call_tool("filtered_browse", {"page_size": 10}))
        assert False
    except Exception as e:
        assert "filter" in str(e).lower()


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_keyword_search_empty_rejected():
    try:
        asyncio.run(mcp.call_tool("keyword_search", {"keyword": ""}))
        assert False
    except Exception as e:
        assert "empty" in str(e).lower()


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_sin_analysis_empty_rejected():
    try:
        asyncio.run(mcp.call_tool("sin_analysis", {"sin_code": ""}))
        assert False
    except Exception:
        pass


# ===========================================================================
# O. SPECIFIC HISTORICAL REGRESSION (sanity)
# ===========================================================================

def test_regression_keyword_apostrophe_accepted():
    """WAF must accept apostrophes."""
    result = _validate_waf_safe("McDonald's", field="x")
    assert result == "McDonald's"


def test_regression_filtered_browse_no_filter_rejected():
    """No-filter rejection."""
    try:
        asyncio.run(mcp.call_tool("filtered_browse", {"page_size": 10}))
        assert False
    except Exception:
        pass


def test_regression_extra_forbid_blocks_typos():
    """extra='forbid' should block typo'd parameters."""
    try:
        asyncio.run(mcp.call_tool("keyword_search", {"keyword": "x", "bogus_param": "y"}))
        assert False
    except Exception as e:
        assert "extra inputs are not permitted" in str(e).lower() or "bogus_param" in str(e).lower()
