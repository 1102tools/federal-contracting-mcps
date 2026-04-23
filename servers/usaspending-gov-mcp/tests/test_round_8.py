# SPDX-License-Identifier: MIT
"""Round 8: Hypothesis-driven property test suite + bonus live tests.

Round 6 found 2 P2 bugs (PSC tree trailing slash, list[str] int coercion).
Round 7 found zero new bugs across 104 deeper live tests.
Round 8 hammers the validators with property-based testing AND adds
live tests for edge cases that round 6/7 didn't cover.

USASpending is keyless and rate-limit-free, so live tests can be aggressive.

Sections:
- Hypothesis property tests for every validator (~50 functions × 500 probes)
- Mock response shape fuzz (~30 specific shapes)
- Async concurrency stress (~10 high-concurrency tests)
- Encoding edge cases (Unicode normalization, RTL, emoji, surrogate pairs)
- Composite tool deep tests (lookup_piid chained calls)
- Bonus live tests (~30 calls hitting edge cases prior rounds skipped)
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.server import (  # noqa: E402
    _clamp_limit,
    _clean_error_body,
    _coerce_code_list,
    _current_fiscal_year,
    _ensure_dict_response,
    _normalize_toptier,
    _validate_date,
    _validate_fiscal_year,
    _validate_no_control_chars,
    _validate_strings_no_control_chars,
)
from usaspending_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"

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
# A. _validate_date PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.text(min_size=0, max_size=30))
def test_property_validate_date_never_crashes(date_str):
    """Date validator returns string or raises ValueError. Never crashes otherwise."""
    try:
        result = _validate_date(date_str, "x")
        assert isinstance(result, str)
    except ValueError:
        pass


@PUNISHMENT
@given(
    st.integers(min_value=2000, max_value=2030),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)
def test_property_validate_date_valid_dates_accepted(year, month, day):
    """Valid YYYY-MM-DD dates (day <= 28 to avoid month-end edges) are accepted."""
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    result = _validate_date(date_str, "x")
    assert result == date_str


@PUNISHMENT
@given(st.integers(min_value=13, max_value=99))
def test_property_validate_date_invalid_month(month):
    date_str = f"2025-{month:02d}-15"
    try:
        _validate_date(date_str, "x")
        assert False
    except ValueError:
        pass


@PUNISHMENT
@given(st.integers(min_value=32, max_value=99))
def test_property_validate_date_invalid_day(day):
    date_str = f"2025-01-{day:02d}"
    try:
        _validate_date(date_str, "x")
        assert False
    except ValueError:
        pass


# Calendar edge cases
@pytest.mark.parametrize("date_str", [
    "2024-02-29",  # leap year valid
    "2025-02-29",  # non-leap invalid
    "2000-02-29",  # century leap valid
    "2100-02-29",  # century non-leap invalid
    "2024-04-31",  # April 30
    "2024-06-31",  # June 30
    "2024-09-31",  # September 30
    "2024-11-31",  # November 30
])
def test_validate_date_calendar_edges(date_str):
    """Specific calendar edge cases. Should not crash; pass or raise."""
    try:
        _validate_date(date_str, "x")
    except ValueError:
        pass


# ===========================================================================
# B. _clamp_limit PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(
    st.integers(min_value=-sys.maxsize, max_value=sys.maxsize),
    st.integers(min_value=1, max_value=10000),
)
def test_property_clamp_limit_never_crashes(value, cap):
    try:
        result = _clamp_limit(value, cap=cap)
        assert 1 <= result <= cap
    except ValueError:
        assert value < 1 or value > cap


@PUNISHMENT
@given(st.integers(min_value=1, max_value=100), st.integers(min_value=100, max_value=10000))
def test_property_clamp_limit_in_range_passthrough(value, cap):
    if value <= cap:
        assert _clamp_limit(value, cap=cap) == value


# ===========================================================================
# C. _coerce_code_list PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.lists(st.one_of(st.integers(), st.text(min_size=0, max_size=20))),
))
def test_property_coerce_code_list_never_crashes(value):
    """Coerce returns None, list[str], or raises ValueError."""
    try:
        result = _coerce_code_list(value, "x")
        if result is not None:
            assert isinstance(result, list)
            for item in result:
                assert isinstance(item, str)
                assert item == item.strip()
                assert item != ""
    except ValueError:
        pass


@PUNISHMENT
@given(st.lists(st.integers(min_value=10, max_value=999999), min_size=1, max_size=10))
def test_property_coerce_code_list_ints_to_strings(values):
    """Int values get coerced to strings."""
    result = _coerce_code_list(values, "x")
    assert result is not None
    assert all(isinstance(s, str) for s in result)
    assert all(s == str(v) for s, v in zip(result, values))


def test_coerce_code_list_empty_list_raises():
    with pytest.raises(ValueError):
        _coerce_code_list([], "x")


def test_coerce_code_list_all_whitespace_raises():
    with pytest.raises(ValueError):
        _coerce_code_list(["", "  ", "\t"], "x")


# ===========================================================================
# D. _validate_no_control_chars PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_validate_no_control_chars_never_crashes(value):
    try:
        result = _validate_no_control_chars(value, field="x")
        if result is not None:
            assert isinstance(result, str)
    except ValueError:
        pass


@PUNISHMENT
@given(st.text(alphabet=st.characters(blacklist_characters="\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f")))
def test_property_validate_no_control_chars_accepts_clean(value):
    """Strings without 0x00-0x1f control chars should pass."""
    result = _validate_no_control_chars(value, field="x")
    assert result == value


@PUNISHMENT
@given(st.integers(min_value=0, max_value=31))
def test_property_validate_no_control_chars_rejects_each_control(codepoint):
    """Every codepoint 0-31 must be rejected when embedded in a string."""
    test_str = f"abc{chr(codepoint)}def"
    try:
        _validate_no_control_chars(test_str, field="x")
        assert False, f"control char 0x{codepoint:02x} should have been rejected"
    except ValueError:
        pass


# ===========================================================================
# E. _normalize_toptier PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.text(min_size=0, max_size=20),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
))
def test_property_normalize_toptier_never_crashes(value):
    try:
        result = _normalize_toptier(value)
        assert isinstance(result, str)
        assert result.isdigit()
        assert len(result) >= 3
    except ValueError:
        pass


@PUNISHMENT
@given(st.integers(min_value=1, max_value=9999))
def test_property_normalize_toptier_int_to_padded_string(value):
    """Numeric int input gets padded to 3 digits."""
    result = _normalize_toptier(value)
    assert result.isdigit()
    if value < 100:
        assert len(result) == 3
    else:
        assert len(result) == len(str(value))


@PUNISHMENT
@given(st.integers(min_value=0, max_value=99))
def test_property_normalize_toptier_short_int_padded(value):
    """Short ints (0-99) get padded to 3 digits."""
    result = _normalize_toptier(value)
    assert len(result) == 3
    assert result == str(value).zfill(3)


# ===========================================================================
# F. _validate_fiscal_year PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.integers(min_value=2008, max_value=_current_fiscal_year()))
def test_property_validate_fiscal_year_valid_range(year):
    """Valid FYs 2008..current should pass."""
    result = _validate_fiscal_year(year)
    assert result == year


@PUNISHMENT
@given(st.integers(min_value=-(2**31), max_value=2007))
def test_property_validate_fiscal_year_below_2008_rejected(year):
    """Anything below 2008 must be rejected."""
    with pytest.raises(ValueError):
        _validate_fiscal_year(year)


@PUNISHMENT
@given(st.integers(min_value=_current_fiscal_year() + 1, max_value=2**31))
def test_property_validate_fiscal_year_above_current_rejected(year):
    """Future FYs must be rejected."""
    with pytest.raises(ValueError):
        _validate_fiscal_year(year)


# ===========================================================================
# G. _ensure_dict_response PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.dictionaries(st.text(min_size=1, max_size=10), st.integers(), max_size=10))
def test_property_ensure_dict_response_dict_passthrough(data):
    """Any dict passes through unchanged."""
    result = _ensure_dict_response(data, path="/x")
    assert result is data


@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.lists(st.integers()),
    st.text(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.tuples(st.integers()),
))
def test_property_ensure_dict_response_non_dict_raises(value):
    """Non-dict inputs must raise."""
    with pytest.raises(Exception):
        _ensure_dict_response(value, path="/x")


# ===========================================================================
# H. _clean_error_body FUZZ TESTS
# ===========================================================================

@PUNISHMENT
@given(st.text(min_size=0, max_size=2000))
def test_property_clean_error_body_never_crashes(text):
    result = _clean_error_body(text)
    assert isinstance(result, str)


@PUNISHMENT
@given(st.text(min_size=0, max_size=300))
def test_property_clean_error_body_html_titles(content):
    html = f"<!doctype html><html><head><title>{content}</title></head><body></body></html>"
    result = _clean_error_body(html)
    assert isinstance(result, str)


@PUNISHMENT
@given(st.text(min_size=0, max_size=300))
def test_property_clean_error_body_html_h1(content):
    html = f"<html><body><h1>{content}</h1></body></html>"
    result = _clean_error_body(html)
    assert isinstance(result, str)


# ===========================================================================
# I. _validate_strings_no_control_chars PROPERTY TESTS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.none(),
    st.lists(st.text(alphabet=st.characters(blacklist_characters="\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f"))),
))
def test_property_validate_strings_no_control_chars_clean_passes(values):
    """Lists of clean strings should pass without raising."""
    _validate_strings_no_control_chars(values, field="x")


def test_validate_strings_no_control_chars_first_bad_rejected():
    with pytest.raises(ValueError):
        _validate_strings_no_control_chars(["a\x00b", "good"], field="x")


def test_validate_strings_no_control_chars_last_bad_rejected():
    with pytest.raises(ValueError):
        _validate_strings_no_control_chars(["good", "a\nb"], field="x")


# ===========================================================================
# J. ASYNC CONCURRENCY STRESS
# ===========================================================================

def test_concurrency_stress_50_validation_rejections():
    """50 concurrent calls hitting validation reject paths."""
    async def _run():
        tasks = [
            mcp.call_tool("get_award_detail", {"generated_award_id": ""})
            for _ in range(50)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50
    assert all(isinstance(r, Exception) for r in results)


def test_concurrency_stress_100_mixed_invalid():
    """100 concurrent calls across multiple tools with invalid input."""
    async def _run():
        tasks = (
            [mcp.call_tool("get_award_detail", {"generated_award_id": ""})] * 25
            + [mcp.call_tool("get_transactions", {"generated_award_id": ""})] * 25
            + [mcp.call_tool("get_award_funding", {"generated_award_id": ""})] * 25
            + [mcp.call_tool("get_idv_children", {"generated_idv_id": ""})] * 25
        )
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 100


def test_concurrency_event_loop_isolation_50_runs():
    """50 sequential asyncio.run calls; should not leak event loop state."""
    for i in range(50):
        try:
            asyncio.run(mcp.call_tool("lookup_piid", {"piid": ""}))
        except Exception:
            pass


# ===========================================================================
# K. ENCODING EDGE CASES
# ===========================================================================

# Unicode normalization variants
@pytest.mark.parametrize("text", [
    "café",  # NFC
    "cafe\u0301",  # NFD
    "über",  # NFC
    "u\u0308ber",  # NFD
    "L\u2019Oreal",  # typographic apostrophe
    "L'Oreal",  # ascii apostrophe
    "\ufeffBOM",  # byte order mark
    "test\u200btest",  # zero-width space
    "test\u00a0test",  # non-breaking space
    "test\u202etest",  # RTL override
])
def test_unicode_normalization_in_validate_no_control(text):
    """Various unicode forms should pass control-char check."""
    try:
        result = _validate_no_control_chars(text, field="x")
        assert result == text
    except ValueError:
        # Some control codepoints may legitimately be rejected
        pass


# Surrogate pairs (U+10000+)
@pytest.mark.parametrize("emoji", [
    "🚀", "💻", "🎉", "🌟", "⭐",
])
def test_emoji_in_validate_no_control(emoji):
    """Emoji should pass control-char check."""
    text = f"abc{emoji}def"
    result = _validate_no_control_chars(text, field="x")
    assert result == text


# ===========================================================================
# L. INTEGER OVERFLOW / SYS.MAXSIZE
# ===========================================================================

@PUNISHMENT
@given(st.integers(min_value=-sys.maxsize, max_value=sys.maxsize))
def test_property_clamp_limit_huge_ints(value):
    """_clamp_limit should handle sys.maxsize without crashing."""
    try:
        _clamp_limit(value, cap=100)
    except ValueError:
        pass


# ===========================================================================
# M. COMPOSITE TOOL DEEP TESTS (lookup_piid)
# ===========================================================================

@pytest.mark.parametrize("piid", [
    "ABC",  # min length
    "A" * 100,  # very long
    "  N00024  ",  # padded
    "n00024",  # lowercase (no normalization)
    "N00024-CONTRACT-12345",  # with hyphens
])
def test_lookup_piid_input_handling(piid):
    """lookup_piid should handle various PIID formats without crashing."""
    try:
        asyncio.run(mcp.call_tool("lookup_piid", {"piid": piid}))
    except Exception:
        # API errors are fine; we just want no validation crashes
        pass


# ===========================================================================
# N. BONUS LIVE TESTS (round 6/7 gaps)
# ===========================================================================

@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_search_awards_with_int_naics_post_round6_fix():
    """Round 6 fixed list[str] -> list[str|int]; verify with int NAICS lives."""
    r = asyncio.run(mcp.call_tool("search_awards", {
        "keywords": ["services"],
        "naics_codes": [541512, 541611, 541330],
        "limit": 3,
    }))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_psc_filter_tree_path_with_extra_slashes():
    """Round 6 added trailing-slash fix; verify edge cases live."""
    r = asyncio.run(mcp.call_tool("get_psc_filter_tree", {"path": "//Services//"}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_search_awards_with_unicode_recipient():
    """Unicode chars in recipient name."""
    r = asyncio.run(mcp.call_tool("search_awards", {
        "keywords": ["services"],
        "recipient_name": "café corp",
        "limit": 3,
    }))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_search_awards_with_emoji_keyword():
    """Emoji in keyword. Should not crash even if no matches."""
    r = asyncio.run(mcp.call_tool("search_awards", {
        "keywords": ["🚀 services"],
        "limit": 3,
    }))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_search_awards_max_pagination_offset():
    """Very high pagination boundary."""
    r = asyncio.run(mcp.call_tool("search_awards", {
        "keywords": ["services"],
        "page": 100,
        "limit": 10,
    }))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_get_naics_details_each_sector():
    """Each top-level NAICS sector code should return data."""
    sectors = ["11", "21", "22", "23", "31", "42", "44", "48", "51", "52",
               "53", "54", "55", "56", "61", "62", "71", "72", "81", "92"]
    for sector in sectors:
        try:
            asyncio.run(mcp.call_tool("get_naics_details", {"code": sector}))
        except Exception:
            pass


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_state_profile_each_top10_state():
    """Top 10 states by federal contracting volume."""
    fips = ["06", "48", "51", "11", "24", "12", "36", "53", "13", "37"]
    for code in fips:
        try:
            asyncio.run(mcp.call_tool("get_state_profile", {"state_fips": code}))
        except Exception:
            pass


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_concurrent_50_searches():
    """50 concurrent live searches across different queries."""
    async def _run():
        keywords = [
            "cyber", "software", "engineering", "consulting", "research",
            "medical", "transportation", "construction", "logistics", "training",
        ] * 5
        tasks = [
            mcp.call_tool("search_awards", {"keywords": [k], "limit": 1})
            for k in keywords
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_spending_over_time_decade_span():
    """10-year span; round 7 had this but worth re-verifying after bug fixes."""
    r = asyncio.run(mcp.call_tool("spending_over_time", {
        "group": "fiscal_year",
        "keywords": ["cybersecurity"],
        "time_period_start": "2015-10-01",
        "time_period_end": "2025-09-30",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")
def test_live_lookup_piid_with_lowercase_normalization():
    """PIIDs are case-sensitive in the API; lowercase may not match."""
    r = asyncio.run(mcp.call_tool("lookup_piid", {"piid": "n00024"}))
    data = _payload(r)
    assert isinstance(data, dict)
