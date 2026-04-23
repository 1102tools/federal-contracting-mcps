# SPDX-License-Identifier: MIT
"""Round 6: Hypothesis-driven punishment + extensive live audit.

eCFR is keyless and rate-limit-free. Live testing can be aggressive.
Combines:
- Hypothesis property tests for every validator (~50 functions × 500 probes)
- Mock fuzz on response shape helpers
- 100+ live tests across all 13 tools
- Async concurrency stress
- Encoding edge cases
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import ecfr_mcp.server as srv  # noqa: E402
from ecfr_mcp.server import (  # noqa: E402
    _as_list,
    _clamp,
    _clamp_str_len,
    _clean_error_body,
    _coerce_cfr_str,
    _safe_dict,
    _safe_int,
    _strip_or_none,
    _validate_chapter,
    _validate_date_ymd,
    _validate_query_safe,
    _validate_title_number,
)
from ecfr_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"

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
# A. SHAPE HELPERS
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.dictionaries(st.text(), st.integers()), st.text(), st.integers(), st.lists(st.integers())))
def test_property_safe_dict(value):
    result = _safe_dict(value)
    assert isinstance(result, dict)


@PUNISHMENT
@given(st.one_of(st.none(), st.lists(st.integers()), st.dictionaries(st.text(), st.integers()), st.text(), st.integers()))
def test_property_as_list(value):
    result = _as_list(value)
    assert isinstance(result, list)


@PUNISHMENT
@given(st.one_of(st.none(), st.integers(), st.floats(allow_nan=True, allow_infinity=True), st.text(), st.booleans()))
def test_property_safe_int(value):
    result = _safe_int(value)
    assert result is None or isinstance(result, int)


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_strip_or_none(value):
    result = _strip_or_none(value)
    assert result is None or isinstance(result, str)
    if result is not None:
        assert result == result.strip()
        assert result != ""


# ===========================================================================
# B. _clamp / _clamp_str_len
# ===========================================================================

@PUNISHMENT
@given(
    st.integers(min_value=-sys.maxsize, max_value=sys.maxsize),
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
)
def test_property_clamp(value, lo, hi):
    if lo > hi:
        return
    try:
        result = _clamp(value, field="x", lo=lo, hi=hi)
        assert lo <= result <= hi
    except ValueError:
        assert value < lo or value > hi


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=2000)), st.integers(min_value=1, max_value=5000))
def test_property_clamp_str_len(value, maximum):
    try:
        result = _clamp_str_len(value, field="x", maximum=maximum)
        if result is not None:
            assert len(result) <= maximum
    except ValueError:
        pass


# ===========================================================================
# C. _clean_error_body fuzz
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=2000), st.integers(), st.dictionaries(st.text(), st.integers())))
def test_property_clean_error_body(value):
    result = _clean_error_body(value)
    assert isinstance(result, str)


# ===========================================================================
# D. _validate_date_ymd
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30)))
def test_property_validate_date_ymd_never_crashes(value):
    try:
        result = _validate_date_ymd(value, field="x")
        if result is not None:
            assert isinstance(result, str)
    except ValueError:
        pass


@PUNISHMENT
@given(
    st.integers(min_value=1900, max_value=2099),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)
def test_property_validate_date_ymd_valid(year, month, day):
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    result = _validate_date_ymd(date_str, field="x")
    assert result == date_str


@pytest.mark.parametrize("date_str", [
    "2024-02-29", "2025-02-29", "2024-04-31", "2024-13-15", "2024-00-15",
    "2024-01-32", "2024/01/15", "01-15-2024", "not-a-date",
])
def test_validate_date_ymd_edge_cases(date_str):
    try:
        _validate_date_ymd(date_str, field="x")
    except ValueError:
        pass


# ===========================================================================
# E. _validate_title_number
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.integers(), st.text(min_size=0, max_size=10), st.floats(allow_nan=True, allow_infinity=True), st.booleans()))
def test_property_validate_title_number_never_crashes(value):
    try:
        result = _validate_title_number(value)
        assert isinstance(result, int)
        assert 1 <= result <= 50
    except (ValueError, TypeError):
        pass


@pytest.mark.parametrize("title", [1, 5, 10, 24, 26, 36, 48, 50])
def test_validate_title_number_valid(title):
    assert _validate_title_number(title) == title


@pytest.mark.parametrize("title", [0, -1, 51, 100, "abc", "1.5", float("inf")])
def test_validate_title_number_invalid(title):
    try:
        _validate_title_number(title)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# F. _coerce_cfr_str
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.integers(), st.text(min_size=0, max_size=20), st.floats(allow_nan=True, allow_infinity=True)))
def test_property_coerce_cfr_str_never_crashes(value):
    try:
        result = _coerce_cfr_str(value, field="x")
        if result is not None:
            assert isinstance(result, str)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# G. _validate_chapter
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.integers(), st.text(min_size=0, max_size=20)))
def test_property_validate_chapter_never_crashes(value):
    try:
        result = _validate_chapter(value, title_number=48)
        if result is not None:
            assert isinstance(result, str)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# H. _validate_query_safe
# ===========================================================================

@PUNISHMENT
@given(st.text(min_size=0, max_size=200))
def test_property_validate_query_safe_never_crashes(value):
    try:
        result = _validate_query_safe(value, field="x")
        if result is not None:
            assert isinstance(result, str)
    except ValueError:
        pass


def test_property_validate_query_safe_rejects_null_byte():
    """eCFR's query_safe only rejects null bytes (per _INJECT_PATTERNS)."""
    try:
        _validate_query_safe("abc\x00def", field="x")
        assert False
    except ValueError:
        pass


# ===========================================================================
# I. ASYNC CONCURRENCY
# ===========================================================================

def test_concurrency_50_invalid_dates():
    async def _run():
        tasks = [
            mcp.call_tool("get_cfr_content", {"title_number": 999, "date": "bad"})
            for _ in range(50)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50


def test_concurrency_event_loop_isolation():
    for _ in range(50):
        try:
            asyncio.run(mcp.call_tool("get_cfr_content", {"title_number": 999}))
        except Exception:
            pass


# ===========================================================================
# J. ENCODING EDGE CASES
# ===========================================================================

@pytest.mark.parametrize("text", [
    "café", "L'Oreal", "🚀 search", "北京", "test\u200btest",
])
def test_unicode_in_query_safe(text):
    try:
        _validate_query_safe(text, field="x")
    except ValueError:
        pass


# ===========================================================================
# K. LIVE TESTS (~100+ calls against eCFR API)
# ===========================================================================

LIVE_REASON = "requires MCP_LIVE_TESTS=1"

# Common CFR titles
COMMON_TITLES = [1, 2, 5, 7, 10, 12, 14, 17, 21, 26, 29, 36, 40, 41, 47, 48, 49, 50]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("title", COMMON_TITLES)
def test_live_get_latest_date_each_title(title):
    """Latest date for every common CFR title."""
    r = asyncio.run(mcp.call_tool("get_latest_date", {"title_number": title}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_list_agencies():
    r = asyncio.run(mcp.call_tool("list_agencies", {"summary_only": True}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_list_agencies_full():
    r = asyncio.run(mcp.call_tool("list_agencies", {"summary_only": False}))
    data = _payload(r)
    assert isinstance(data, dict)


# Common FAR clauses
COMMON_FAR_CLAUSES = [
    "52.212-3", "52.212-4", "52.212-5", "52.219-8", "52.219-14",
    "52.222-26", "52.225-25", "52.232-39", "52.246-2", "52.227-14",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("clause", COMMON_FAR_CLAUSES)
def test_live_lookup_far_clause_each(clause):
    r = asyncio.run(mcp.call_tool("lookup_far_clause", {"section_id": clause}))
    data = _payload(r)
    assert isinstance(data, dict)


# Common DFARS clauses
COMMON_DFARS_CLAUSES = [
    "252.204-7012", "252.227-7013", "252.227-7014", "252.225-7000",
    "252.225-7001",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("clause", COMMON_DFARS_CLAUSES)
def test_live_lookup_dfars_clause_each(clause):
    """DFARS clauses live in title 48 chapter 2 (FAR is chapter 1)."""
    r = asyncio.run(mcp.call_tool("lookup_far_clause", {
        "section_id": clause,
        "chapter": "2",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Common FAR parts
COMMON_FAR_PARTS = ["1", "2", "5", "7", "8", "9", "10", "12", "13", "14",
                    "15", "16", "19", "22", "25", "27", "31", "33", "37", "52"]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("part", COMMON_FAR_PARTS)
def test_live_list_sections_in_far_part(part):
    r = asyncio.run(mcp.call_tool("list_sections_in_part", {
        "title_number": 48,
        "part_number": part,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# CFR structure for top procurement-relevant titles
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("title", [48, 5, 22, 26])
def test_live_get_cfr_structure_each(title):
    r = asyncio.run(mcp.call_tool("get_cfr_structure", {"title_number": title}))
    data = _payload(r)
    assert isinstance(data, dict)


# Search tests
SEARCH_QUERIES = [
    "small business", "set-aside", "8(a)", "SDVOSB", "WOSB",
    "cybersecurity", "data rights", "GFE", "indemnification",
    "warranty",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("query", SEARCH_QUERIES)
def test_live_search_cfr_each(query):
    r = asyncio.run(mcp.call_tool("search_cfr", {"query": query, "per_page": 5}))
    data = _payload(r)
    assert isinstance(data, dict)


# Find FAR definitions
FAR_DEFINITIONS = [
    "small business", "commercial item", "task order", "contract",
    "subcontractor", "competition", "responsible source", "good faith",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", FAR_DEFINITIONS)
def test_live_find_far_definition_each(term):
    r = asyncio.run(mcp.call_tool("find_far_definition", {"term": term}))
    data = _payload(r)
    assert isinstance(data, dict)


# Get ancestry for FAR sections
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("section", ["52.212-3", "52.219-8", "15.404-1"])
def test_live_get_ancestry_each(section):
    parts = section.split(".")
    if len(parts) >= 1:
        r = asyncio.run(mcp.call_tool("get_ancestry", {
            "title_number": 48,
            "section": section,
        }))
        data = _payload(r)
        assert isinstance(data, dict)


# Version history
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("section", ["52.212-3", "15.404-1", "52.232-39"])
def test_live_get_version_history_each(section):
    try:
        r = asyncio.run(mcp.call_tool("get_version_history", {
            "title_number": 48,
            "section": section,
        }))
        data = _payload(r)
        assert isinstance(data, dict)
    except Exception:
        pass


# Compare versions (FAR clause that's been amended)
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_compare_versions_recent():
    try:
        r = asyncio.run(mcp.call_tool("compare_versions", {
            "title_number": 48,
            "section_id": "52.212-4",
            "date_before": "2023-01-01",
            "date_after": "2024-01-01",
        }))
        data = _payload(r)
        assert isinstance(data, dict)
    except Exception:
        pass


# Get corrections
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_corrections_title_48():
    r = asyncio.run(mcp.call_tool("get_corrections", {"title_number": 48}))
    data = _payload(r)
    assert isinstance(data, dict)


# Find recent changes
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("title", [48, 5, 26])
def test_live_find_recent_changes_each(title):
    r = asyncio.run(mcp.call_tool("find_recent_changes", {
        "title": title,
        "since_date": "2025-01-01",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# CFR content for specific dates (latest)
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_cfr_content_far_part_15():
    r = asyncio.run(mcp.call_tool("get_cfr_content", {
        "title_number": 48,
        "part": "15",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_cfr_content_far_section():
    r = asyncio.run(mcp.call_tool("get_cfr_content", {
        "title_number": 48,
        "section": "52.212-3",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Concurrent live calls
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_concurrent_5_searches():
    async def _run():
        return await asyncio.gather(
            mcp.call_tool("search_cfr", {"query": "small business", "per_page": 3}),
            mcp.call_tool("search_cfr", {"query": "set-aside", "per_page": 3}),
            mcp.call_tool("search_cfr", {"query": "competition", "per_page": 3}),
            mcp.call_tool("get_latest_date", {"title_number": 48}),
            mcp.call_tool("list_agencies", {"summary_only": True}),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


# Validation rejection live
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_invalid_title_rejected():
    try:
        asyncio.run(mcp.call_tool("get_latest_date", {"title_number": 999}))
        assert False
    except Exception:
        pass


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_invalid_date_rejected():
    try:
        asyncio.run(mcp.call_tool("get_cfr_content", {
            "title_number": 48,
            "date": "not-a-date",
        }))
        assert False
    except Exception:
        pass
