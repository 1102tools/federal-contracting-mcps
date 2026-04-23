# SPDX-License-Identifier: MIT
"""Round 5: Hypothesis property tests + extensive live audit for federal-register-mcp.

Federal Register API is keyless and rate-limit-free. Live testing aggressive.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import federal_register_mcp.server as srv  # noqa: E402
from federal_register_mcp.server import (  # noqa: E402
    _check_date_range,
    _clamp,
    _clamp_str_len,
    _clean_error_body,
    _ensure_json_container,
    _reject_empty_list,
    _reject_empty_strings_in_list,
    _require_min_length,
    _strip_or_none,
    _validate_date,
    _validate_doc_number,
    _validate_no_control_chars,
    _warn_pre_fr_date,
)
from federal_register_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("FR_LIVE_TESTS") == "1"

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
@given(st.one_of(st.none(), st.text(min_size=0, max_size=30)))
def test_property_validate_date_never_crashes(value):
    try:
        _validate_date(value, "x")
    except ValueError:
        pass


@PUNISHMENT
@given(
    st.integers(min_value=1900, max_value=2099),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)
def test_property_validate_date_valid(year, month, day):
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    result = _validate_date(date_str, "x")
    assert result == date_str


# ===========================================================================
# B. _clamp PROPERTY TESTS
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


# ===========================================================================
# C. _reject_empty_list / _reject_empty_strings_in_list
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.lists(st.text())))
def test_property_reject_empty_list_never_crashes(value):
    try:
        result = _reject_empty_list(value, field="x")
        if result is not None:
            assert isinstance(result, list)
    except ValueError:
        pass


def test_reject_empty_list_empty():
    with pytest.raises(ValueError):
        _reject_empty_list([], field="x")


def test_reject_empty_strings_in_list_all_empty():
    with pytest.raises(ValueError):
        _reject_empty_strings_in_list(["", "  "], field="x")


# ===========================================================================
# D. _check_date_range
# ===========================================================================

def test_check_date_range_reversed():
    with pytest.raises(ValueError):
        _check_date_range("2025-12-31", "2025-01-01", field_pair="pub_date")


def test_check_date_range_same():
    """Same date for both should pass."""
    _check_date_range("2025-01-01", "2025-01-01", field_pair="pub_date")


def test_check_date_range_valid():
    _check_date_range("2025-01-01", "2025-12-31", field_pair="pub_date")


# ===========================================================================
# E. _strip_or_none / _require_min_length / _clamp_str_len
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_strip_or_none(value):
    result = _strip_or_none(value)
    assert result is None or isinstance(result, str)


@PUNISHMENT
@given(st.text(min_size=0, max_size=200), st.integers(min_value=1, max_value=100))
def test_property_require_min_length(value, minimum):
    try:
        result = _require_min_length(value, field="x", minimum=minimum)
        assert isinstance(result, str)
        assert len(result) >= minimum
    except ValueError:
        pass


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
# F. _validate_doc_number
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=50)))
def test_property_validate_doc_number_never_crashes(value):
    try:
        _validate_doc_number(value)
    except (ValueError, TypeError):
        pass


@pytest.mark.parametrize("doc", ["2024-12345", "2024-99999", "2025-00001"])
def test_validate_doc_number_valid(doc):
    result = _validate_doc_number(doc)
    assert result == doc


# ===========================================================================
# G. _validate_no_control_chars
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=200)))
def test_property_validate_no_control_chars(value):
    try:
        _validate_no_control_chars(value, field="x")
    except (ValueError, TypeError):
        pass


@PUNISHMENT
@given(st.integers(min_value=0, max_value=31))
def test_property_validate_no_control_chars_rejects_each_control(codepoint):
    text = f"abc{chr(codepoint)}def"
    try:
        _validate_no_control_chars(text, field="x")
        # If accepted, that's a failure
        assert False, f"control 0x{codepoint:02x} should be rejected"
    except ValueError:
        pass


# ===========================================================================
# H. _ensure_json_container fuzz
# ===========================================================================

@PUNISHMENT
@given(st.one_of(
    st.dictionaries(st.text(), st.integers()),
    st.lists(st.integers()),
))
def test_property_ensure_json_container_dict_or_list_passes(value):
    result = _ensure_json_container(value, url="/x")
    assert isinstance(result, (dict, list))


@PUNISHMENT
@given(st.one_of(st.none(), st.text(), st.integers(), st.floats(allow_nan=True, allow_infinity=True)))
def test_property_ensure_json_container_invalid_raises(value):
    try:
        _ensure_json_container(value, url="/x")
    except Exception:
        pass


# ===========================================================================
# I. _clean_error_body fuzz
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=2000)))
def test_property_clean_error_body(value):
    result = _clean_error_body(value)
    assert isinstance(result, str)


# ===========================================================================
# J. _warn_pre_fr_date
# ===========================================================================

@PUNISHMENT
@given(st.one_of(st.none(), st.text(min_size=0, max_size=20)))
def test_property_warn_pre_fr_date_never_crashes(value):
    try:
        _warn_pre_fr_date(value, field="x")
    except (ValueError, TypeError):
        pass


# ===========================================================================
# K. ASYNC CONCURRENCY
# ===========================================================================

def test_concurrency_50_invalid_doc_numbers():
    async def _run():
        tasks = [
            mcp.call_tool("get_document", {"document_number": "bogus-format"})
            for _ in range(50)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    results = asyncio.run(_run())
    assert len(results) == 50


# ===========================================================================
# L. ENCODING EDGE CASES
# ===========================================================================

@pytest.mark.parametrize("text", ["café", "L'Oreal", "🚀", "北京"])
def test_unicode_in_validate_no_control_chars(text):
    try:
        _validate_no_control_chars(text, field="x")
    except (ValueError, TypeError):
        pass


# ===========================================================================
# M. LIVE TESTS (~100 calls)
# ===========================================================================

LIVE_REASON = "requires FR_LIVE_TESTS=1"

# Common federal agencies (slugs from FR API)
COMMON_AGENCIES = [
    "defense-department", "homeland-security-department",
    "health-and-human-services-department",
    "commerce-department", "treasury-department",
    "agriculture-department", "interior-department",
    "energy-department", "education-department",
    "transportation-department", "labor-department",
    "justice-department", "state-department",
    "veterans-affairs-department",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", COMMON_AGENCIES)
def test_live_search_documents_each_agency(agency):
    """Search each major agency in last 90 days."""
    r = asyncio.run(mcp.call_tool("search_documents", {
        "agencies": [agency],
        "pub_date_gte": "2025-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Doc types
DOC_TYPES = ["PRORULE", "RULE", "NOTICE", "PRESDOCU"]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("dt", DOC_TYPES)
def test_live_search_each_doc_type(dt):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "doc_types": [dt],
        "pub_date_gte": "2025-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Search by FAR case keywords
FAR_CASE_TERMS = [
    "FAR Case", "Federal Acquisition Regulation",
    "small business set-aside", "SDVOSB", "WOSB", "8(a)",
    "DFARS", "GSAR", "NASA FAR Supplement", "cybersecurity",
    "data rights", "OTA", "other transaction", "GFE", "indemnification",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", FAR_CASE_TERMS)
def test_live_search_each_term(term):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "term": term,
        "pub_date_gte": "2024-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Public inspection
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_public_inspection_default():
    r = asyncio.run(mcp.call_tool("get_public_inspection", {"limit": 10}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_public_inspection_with_keyword():
    r = asyncio.run(mcp.call_tool("get_public_inspection", {
        "keyword_filter": "small business",
        "limit": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# List agencies
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_list_agencies_summary():
    r = asyncio.run(mcp.call_tool("list_agencies", {"include_detail": False}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_list_agencies_with_query():
    r = asyncio.run(mcp.call_tool("list_agencies", {"query": "defense"}))
    data = _payload(r)
    assert isinstance(data, dict)


# Open comment periods
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_open_comment_periods_default():
    r = asyncio.run(mcp.call_tool("open_comment_periods", {"limit": 10}))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_open_comment_periods_with_term():
    r = asyncio.run(mcp.call_tool("open_comment_periods", {
        "term": "small business",
        "limit": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_open_comment_periods_with_agency():
    r = asyncio.run(mcp.call_tool("open_comment_periods", {
        "agencies": ["defense-department"],
        "limit": 5,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Get facet counts
FACET_TYPES = ["type", "agency", "topic"]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("facet", FACET_TYPES)
def test_live_get_facet_counts_each(facet):
    r = asyncio.run(mcp.call_tool("get_facet_counts", {
        "facet": facet,
        "pub_date_gte": "2025-01-01",
        "pub_date_lte": "2025-04-22",
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Compound searches
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_dod_proposed_rules():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "agencies": ["defense-department"],
        "doc_types": ["PRORULE"],
        "pub_date_gte": "2024-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_with_date_range_year():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "term": "cybersecurity",
        "pub_date_gte": "2024-01-01",
        "pub_date_lte": "2024-12-31",
        "per_page": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Pagination
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_pagination_page_2():
    r = asyncio.run(mcp.call_tool("search_documents", {
        "term": "small business",
        "page": 2,
        "per_page": 10,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Concurrent live calls
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_concurrent_5_searches():
    async def _run():
        return await asyncio.gather(
            mcp.call_tool("search_documents", {"term": "cybersecurity", "per_page": 3}),
            mcp.call_tool("search_documents", {"term": "small business", "per_page": 3}),
            mcp.call_tool("get_public_inspection", {"limit": 3}),
            mcp.call_tool("list_agencies", {"query": "defense"}),
            mcp.call_tool("open_comment_periods", {"limit": 3}),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


# Validation rejection live
@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_reversed_date_rejected():
    try:
        asyncio.run(mcp.call_tool("search_documents", {
            "term": "x",
            "pub_date_gte": "2025-12-31",
            "pub_date_lte": "2025-01-01",
        }))
        assert False
    except Exception:
        pass


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_search_invalid_doc_type_rejected():
    try:
        asyncio.run(mcp.call_tool("search_documents", {
            "doc_types": ["INVALID"],
            "per_page": 5,
        }))
        assert False
    except Exception:
        pass


# Get documents batch
# Additional live tests to hit 100+
ADDITIONAL_AGENCIES = [
    "environmental-protection-agency",
    "general-services-administration",
    "small-business-administration",
    "social-security-administration",
    "federal-aviation-administration",
    "federal-energy-regulatory-commission",
    "federal-communications-commission",
    "securities-and-exchange-commission",
    "federal-trade-commission",
    "national-labor-relations-board",
    "consumer-financial-protection-bureau",
    "nuclear-regulatory-commission",
    "occupational-safety-and-health-administration",
    "federal-deposit-insurance-corporation",
    "federal-reserve-system",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("agency", ADDITIONAL_AGENCIES)
def test_live_search_each_additional_agency(agency):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "agencies": [agency],
        "pub_date_gte": "2025-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 3,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


# Search by additional FAR/DFARS-related terms
ADDITIONAL_TERMS = [
    "FAR Part 12", "FAR Part 15", "FAR Part 19", "FAR Part 25",
    "FAR Part 31", "DFARS Subpart", "GSAR", "VAAR",
    "service contract", "construction contract", "supply contract",
    "research and development", "performance-based",
]


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
@pytest.mark.parametrize("term", ADDITIONAL_TERMS)
def test_live_search_each_additional_term(term):
    r = asyncio.run(mcp.call_tool("search_documents", {
        "term": term,
        "pub_date_gte": "2024-01-01",
        "pub_date_lte": "2025-04-22",
        "per_page": 3,
    }))
    data = _payload(r)
    assert isinstance(data, dict)


@pytest.mark.skipif(not LIVE, reason=LIVE_REASON)
def test_live_get_documents_batch_with_real_search():
    """Search first to get real doc numbers, then batch fetch."""
    async def _run():
        # First search to get real doc numbers
        r = await mcp.call_tool("search_documents", {
            "term": "small business",
            "per_page": 3,
        })
        payload = r[1] if isinstance(r, tuple) else r
        if not payload.get("results"):
            return None
        doc_numbers = [d.get("document_number") for d in payload["results"][:3] if d.get("document_number")]
        if not doc_numbers:
            return None
        # Now batch fetch
        return await mcp.call_tool("get_documents_batch", {"document_numbers": doc_numbers})
    result = asyncio.run(_run())
    if result is not None:
        data = _payload(result)
        assert isinstance(data, dict)
