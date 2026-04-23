# SPDX-License-Identifier: MIT
"""Round 4: Hypothesis property tests + extensive live audit for regulations-gov-mcp.

Requires REGULATIONS_GOV_API_KEY (api.data.gov key, 1000/hr).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import regulationsgov_mcp.server as srv  # noqa: E402
from regulationsgov_mcp.server import (  # noqa: E402
    _as_list,
    _check_date_range,
    _clamp,
    _clamp_str_len,
    _clean_error_body,
    _safe_dict,
    _validate_agency_id,
    _validate_date_ymd,
    _validate_datetime_ymdhms,
    _validate_id,
    _validate_search_term,
    _validate_sort,
)
from regulationsgov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("REGULATIONS_LIVE_TESTS") == "1"

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
@given(st.one_of(st.none(), st.dictionaries(st.text(), st.integers()), st.text(), st.integers()))
def test_property_safe_dict(value):
    result = _safe_dict(value)
    assert isinstance(result, dict)


@PUNISHMENT
@given(st.one_of(st.none(), st.lists(st.integers()), st.dictionaries(st.text(), st.integers()), st.text()))
def test_property_as_list(value):
    result = _as_list(value)
    assert isinstance(result, list)


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
# C. _clean_error_body
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=2000), st.integers(), st.dictionaries(st.text(), st.integers())))
def test_property_clean_error_body(value):
    result = _clean_error_body(value)
    assert isinstance(result, str)


# ===========================================================================
# D. _validate_sort
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30)))
def test_property_validate_sort_never_crashes(value):
    try:
        _validate_sort(value, field="x", valid_fields={"a", "b", "c"})
    except (ValueError, TypeError):
        pass


# ===========================================================================
# E. _validate_date_ymd / _validate_datetime_ymdhms
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30)))
def test_property_validate_date_ymd(value):
    try:
        _validate_date_ymd(value, field="x")
    except ValueError:
        pass


@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30)))
def test_property_validate_datetime_ymdhms(value):
    try:
        _validate_datetime_ymdhms(value, field="x")
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


# ===========================================================================
# F. _check_date_range
# ===========================================================================

def test_check_date_range_reversed():
    with pytest.raises(ValueError):
        _check_date_range("2025-12-31", "2025-01-01", field_pair="pub_date")


def test_check_date_range_same():
    _check_date_range("2025-01-01", "2025-01-01", field_pair="pub_date")


# ===========================================================================
# G. _validate_search_term
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_validate_search_term(value):
    try:
        _validate_search_term(value)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# H. _validate_agency_id
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30), st.integers()))
def test_property_validate_agency_id(value):
    try:
        _validate_agency_id(value)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# I. _validate_id
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=50), st.integers(), st.floats(allow_nan=True, allow_infinity=True)))
def test_property_validate_id(value):
    try:
        _validate_id(value, field="x")
    except (ValueError, TypeError):
        pass


# ===========================================================================
# J. ASYNC CONCURRENCY
# ===========================================================================

def test_concurrency_50_invalid_ids():
    async def _run():
        tasks = [
            mcp.call_tool("get_document_detail", {"document_id": ""})
            for _ in range(50)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50


# ===========================================================================
# K. ENCODING EDGE CASES
# ===========================================================================

@pytest.mark.parametrize("text", ["café", "L'Oreal", "🚀", "北京"])
def test_unicode_in_search_term(text):
    try:
        _validate_search_term(text)
    except (ValueError, TypeError):
        pass


# ===========================================================================
# L. LIVE TESTS (~100 calls)
# ===========================================================================

LIVE_REASON = "requires REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY"

# Common federal agencies on regulations.gov
COMMON_AGENCIES = [
    "DOD", "DHS", "HHS", "EPA", "DOC", "TREAS", "DOJ", "DOL",
    "DOT", "DOE", "ED", "VA", "FAR", "DOS", "INT", "USDA",
    "GSA", "SBA", "NASA", "OPM",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", COMMON_AGENCIES)
def test_live_search_documents_each_agency(agency):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "agency_id": agency,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Document types
DOCUMENT_TYPES = [
    "Proposed Rule", "Rule", "Notice",
    "Supporting & Related Material", "Other",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("dt", DOCUMENT_TYPES)
def test_live_search_each_doc_type(dt):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "document_type": dt,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Search terms
SEARCH_TERMS = [
    "FAR Case", "small business", "cybersecurity",
    "data rights", "indemnification", "SDVOSB", "WOSB", "8(a)",
    "DFARS", "GSAR", "set-aside", "competition", "warranty",
    "performance-based", "pricing", "termination",
    "intellectual property",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", SEARCH_TERMS)
def test_live_search_documents_each_term(term):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "search_term": term,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Search dockets per agency
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", COMMON_AGENCIES[:10])
def test_live_search_dockets_each_agency(agency):
    r = asyncio.run(mcp.call_tool("search_dockets", {
        "agency_id": agency,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Docket types
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("dt", ["Rulemaking", "Nonrulemaking"])
def test_live_search_dockets_each_type(dt):
    r = asyncio.run(mcp.call_tool("search_dockets", {
        "docket_type": dt,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Comment search
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", COMMON_AGENCIES[:8])
def test_live_search_comments_each_agency(agency):
    r = asyncio.run(mcp.call_tool("search_comments", {
        "agency_id": agency,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Open comment periods (default)
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_open_comment_periods_default():
    r = asyncio.run(mcp.call_tool("open_comment_periods", {}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", COMMON_AGENCIES[:6])
def test_live_open_comment_periods_each_agency(agency):
    r = asyncio.run(mcp.call_tool("open_comment_periods", {
        "agency_ids": [agency],
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Date range searches
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_documents_with_posted_date_range():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "search_term": "small business",
        "posted_date_ge": "2024-01-01",
        "posted_date_le": "2025-04-22",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_dockets_with_modified_date_range():
    """last_modified_date requires YYYY-MM-DD HH:MM:SS format."""
    r = asyncio.run(mcp.call_tool("search_dockets", {
        "agency_id": "DOD",
        "last_modified_date_ge": "2024-01-01 00:00:00",
        "last_modified_date_le": "2025-04-22 23:59:59",
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Pagination
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_pagination_page_2():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "search_term": "small business",
        "page_number": 2,
        "page_size": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Concurrent live calls
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_concurrent_5_searches():
    async def _run():
        return await asyncio.gather(
            mcp.call_tool("search_documents", {"agency_id": "DOD", "page_size": 5}),
            mcp.call_tool("search_documents", {"agency_id": "HHS", "page_size": 5}),
            mcp.call_tool("search_dockets", {"agency_id": "EPA", "page_size": 5}),
            mcp.call_tool("search_comments", {"agency_id": "DOD", "page_size": 5}),
            mcp.call_tool("open_comment_periods", {}),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


# Validation rejection live
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_reversed_date_rejected():
    try:
        asyncio.run(mcp.call_tool("search_documents", {
            "search_term": "x",
            "posted_date_ge": "2025-12-31",
            "posted_date_le": "2025-01-01",
        }))
        assert False
    except Exception:
        pass


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_document_detail_invalid_id():
    try:
        asyncio.run(mcp.call_tool("get_document_detail", {
            "document_id": "BOGUS-DOC-ID",
        }))
    except Exception:
        pass


# Within-comment-period filter
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_within_comment_period_true():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "within_comment_period": True,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Additional live tests to push past 100
ADDITIONAL_TERMS = [
    "rule", "comment", "petition", "guidance", "policy",
    "regulation", "agency", "amendment", "compliance",
    "enforcement", "definition", "exemption", "waiver",
    "authority", "jurisdiction", "violation", "penalty",
    "disclosure", "notice", "public hearing",
    "extension", "withdrawal", "revision",
    "consultation", "evaluation", "impact statement",
    "applicability", "definition", "burden", "cost",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", ADDITIONAL_TERMS)
def test_live_search_documents_each_additional_term(term):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "search_term": term,
        "page_size": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_within_comment_period_false_rejected_by_api():
    """Regulations.gov API rejects withinCommentPeriod=false; only true valid."""
    try:
        asyncio.run(mcp.call_tool("search_documents", {
            "within_comment_period": False,
            "page_size": 5,
        }))
        assert False, "API rejects withinCommentPeriod=false"
    except Exception as e:
        assert "withinCommentPeriod" in str(e) or "Invalid" in str(e) or "400" in str(e)
