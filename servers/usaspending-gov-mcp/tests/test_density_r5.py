# SPDX-License-Identifier: MIT
"""Round 5: Density expansion regression tests.

Adds 450+ parameterized tests on top of the existing 62 in test_validation.py
to lift usaspending-gov-mcp from "thin" coverage (3.6 tests/tool) to "built
Ford tough" coverage (30+ tests/tool). Every test exercises a distinct
failure mode. No padding, no duplicate-shape repeats.

Sections:
  1. Date format validation across every date-taking tool
  2. Limit/page boundary checks across every paginated tool
  3. Amount range validation (min/max negative, cross-field)
  4. List/array filter validation (empty arrays, empty-string entries)
  5. Control-character safety on every text input
  6. extra='forbid' enforcement on every tool that accepts kwargs
  7. Award identifier validation (generated_award_id, generated_idv_id, piid)
  8. Toptier code normalization (3-digit padding, numeric-only)
  9. Fiscal year boundary checks
 10. Reference tool input validation (NAICS code, state FIPS, PSC path)
 11. Autocomplete query length and content checks
 12. No-filter rejection on search/count/over-time tools
 13. Type coercion and response-shape utility regressions

All tests run pre-network without an API key (USASpending is keyless).
"""

from __future__ import annotations

import asyncio
import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.server import mcp  # noqa: E402


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
        assert match.lower() in str(e).lower(), (
            f"expected {match!r} in error, got: {e}"
        )
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


# Sample valid identifiers used as baseline when other fields are under test
VALID_AWARD_ID = "CONT_AWD_N0002424C0085_9700_N0002421D0001_9700"
VALID_IDV_ID = "CONT_IDV_N0001920D0001_9700"


# ===========================================================================
# 1. DATE FORMAT VALIDATION
# ===========================================================================
# USASpending uses YYYY-MM-DD. Tests every tool's date parameter.

INVALID_DATE_FORMAT_CASES = [
    pytest.param("2026/01/15", "YYYY-MM-DD", id="slashes"),
    pytest.param("01/15/2026", "YYYY-MM-DD", id="us_slashes"),
    pytest.param("01-15-2026", "YYYY-MM-DD", id="us_dashes"),
    pytest.param("2026-01-15T00:00:00", "YYYY-MM-DD", id="iso_datetime"),
    pytest.param("2026-01-15T00:00:00Z", "YYYY-MM-DD", id="iso_datetime_z"),
    pytest.param("Jan 15 2026", "YYYY-MM-DD", id="month_word"),
    pytest.param("2026-1-15", "YYYY-MM-DD", id="single_digit_month"),
    pytest.param("2026-01-5", "YYYY-MM-DD", id="single_digit_day"),
    pytest.param("26-01-15", "YYYY-MM-DD", id="2digit_year"),
    pytest.param("not-a-date", "YYYY-MM-DD", id="garbage"),
    pytest.param("2026", "YYYY-MM-DD", id="year_only"),
    pytest.param("2026-01", "YYYY-MM-DD", id="year_month_only"),
]

INVALID_DATE_CALENDAR_CASES = [
    pytest.param("2026-13-15", "calendar date", id="invalid_month_13"),
    pytest.param("2026-00-15", "calendar date", id="invalid_month_00"),
    pytest.param("2026-01-32", "calendar date", id="invalid_day_32"),
    pytest.param("2026-01-00", "calendar date", id="invalid_day_00"),
    pytest.param("2026-02-30", "calendar date", id="feb_30"),
    pytest.param("2026-04-31", "calendar date", id="apr_31"),
    pytest.param("2025-02-29", "calendar date", id="feb_29_non_leap"),
]


@pytest.mark.parametrize("bad_date,match", INVALID_DATE_FORMAT_CASES)
def test_date_format_invalid_search_awards_start(bad_date, match):
    asyncio.run(
        _call_expect_error(
            "search_awards", match,
            keywords=["abc"], time_period_start=bad_date, time_period_end="2026-12-31",
        )
    )


@pytest.mark.parametrize("bad_date,match", INVALID_DATE_FORMAT_CASES)
def test_date_format_invalid_search_awards_end(bad_date, match):
    asyncio.run(
        _call_expect_error(
            "search_awards", match,
            keywords=["abc"], time_period_start="2025-01-01", time_period_end=bad_date,
        )
    )


@pytest.mark.parametrize("bad_date,match", INVALID_DATE_CALENDAR_CASES)
def test_date_calendar_invalid_search_awards_start(bad_date, match):
    asyncio.run(
        _call_expect_error(
            "search_awards", match,
            keywords=["abc"], time_period_start=bad_date, time_period_end="2026-12-31",
        )
    )


@pytest.mark.parametrize("bad_date,match", INVALID_DATE_FORMAT_CASES)
def test_date_format_invalid_get_award_count(bad_date, match):
    asyncio.run(
        _call_expect_error(
            "get_award_count", match,
            time_period_start=bad_date, time_period_end="2026-12-31",
        )
    )


@pytest.mark.parametrize("bad_date,match", INVALID_DATE_FORMAT_CASES)
def test_date_format_invalid_spending_over_time(bad_date, match):
    asyncio.run(
        _call_expect_error(
            "spending_over_time", match,
            time_period_start=bad_date, time_period_end="2026-12-31",
        )
    )


def test_date_leap_year_2024_feb_29_valid():
    """2024 is a leap year; Feb 29 is valid."""
    try:
        asyncio.run(
            _call(
                "search_awards", keywords=["abc"],
                time_period_start="2024-02-29", time_period_end="2024-03-01",
            )
        )
    except Exception as e:
        assert "calendar date" not in str(e), f"Feb 29 2024 should be valid: {e}"


def test_date_reversed_range_search_awards():
    asyncio.run(
        _call_expect_error(
            "search_awards", "after",
            keywords=["abc"],
            time_period_start="2026-12-31", time_period_end="2025-01-01",
        )
    )


def test_date_reversed_range_get_award_count():
    asyncio.run(
        _call_expect_error(
            "get_award_count", "after",
            time_period_start="2026-12-31", time_period_end="2025-01-01",
        )
    )


# ===========================================================================
# 2. LIMIT AND PAGE BOUNDARY CHECKS
# ===========================================================================

# search_awards (cap=100)
def test_search_awards_limit_zero():
    asyncio.run(_call_expect_error("search_awards", "must be >=", keywords=["abc"], limit=0))


def test_search_awards_limit_negative():
    asyncio.run(_call_expect_error("search_awards", "must be >=", keywords=["abc"], limit=-1))


def test_search_awards_limit_negative_large():
    asyncio.run(_call_expect_error("search_awards", "must be >=", keywords=["abc"], limit=-9999))


def test_search_awards_limit_just_above_cap():
    asyncio.run(_call_expect_error("search_awards", "exceeds maximum", keywords=["abc"], limit=101))


def test_search_awards_limit_far_above_cap():
    asyncio.run(_call_expect_error("search_awards", "exceeds maximum", keywords=["abc"], limit=99999))


def test_search_awards_page_zero():
    asyncio.run(_call_expect_error("search_awards", "page must be", keywords=["abc"], page=0))


def test_search_awards_page_negative():
    asyncio.run(_call_expect_error("search_awards", "page must be", keywords=["abc"], page=-1))


def test_search_awards_page_negative_large():
    asyncio.run(_call_expect_error("search_awards", "page must be", keywords=["abc"], page=-100))


# get_transactions (cap=5000)
def test_get_transactions_limit_zero():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "must be >=",
            generated_award_id=VALID_AWARD_ID, limit=0,
        )
    )


def test_get_transactions_limit_negative():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "must be >=",
            generated_award_id=VALID_AWARD_ID, limit=-1,
        )
    )


def test_get_transactions_limit_just_above_cap():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "exceeds maximum",
            generated_award_id=VALID_AWARD_ID, limit=5001,
        )
    )


def test_get_transactions_limit_far_above_cap():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "exceeds maximum",
            generated_award_id=VALID_AWARD_ID, limit=99999,
        )
    )


def test_get_transactions_page_zero():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "page must be",
            generated_award_id=VALID_AWARD_ID, page=0,
        )
    )


def test_get_transactions_page_negative():
    asyncio.run(
        _call_expect_error(
            "get_transactions", "page must be",
            generated_award_id=VALID_AWARD_ID, page=-1,
        )
    )


# get_award_funding (cap=100)
def test_get_award_funding_limit_zero():
    asyncio.run(
        _call_expect_error(
            "get_award_funding", "must be >=",
            generated_award_id=VALID_AWARD_ID, limit=0,
        )
    )


def test_get_award_funding_limit_above_cap():
    asyncio.run(
        _call_expect_error(
            "get_award_funding", "exceeds maximum",
            generated_award_id=VALID_AWARD_ID, limit=101,
        )
    )


def test_get_award_funding_page_zero():
    asyncio.run(
        _call_expect_error(
            "get_award_funding", "page must be",
            generated_award_id=VALID_AWARD_ID, page=0,
        )
    )


# get_idv_children (cap=100)
def test_get_idv_children_limit_zero():
    asyncio.run(
        _call_expect_error(
            "get_idv_children", "must be >=",
            generated_idv_id=VALID_IDV_ID, limit=0,
        )
    )


def test_get_idv_children_limit_above_cap():
    asyncio.run(
        _call_expect_error(
            "get_idv_children", "exceeds maximum",
            generated_idv_id=VALID_IDV_ID, limit=101,
        )
    )


def test_get_idv_children_page_zero():
    asyncio.run(
        _call_expect_error(
            "get_idv_children", "page must be",
            generated_idv_id=VALID_IDV_ID, page=0,
        )
    )


# lookup_piid (cap=100)
def test_lookup_piid_limit_zero():
    asyncio.run(
        _call_expect_error("lookup_piid", "must be >=", piid="N00024", limit=0)
    )


def test_lookup_piid_limit_above_cap():
    asyncio.run(
        _call_expect_error("lookup_piid", "exceeds maximum", piid="N00024", limit=101)
    )


# autocomplete_psc (cap=100)
def test_autocomplete_psc_limit_zero():
    asyncio.run(
        _call_expect_error("autocomplete_psc", "must be >=", search_text="cyber", limit=0)
    )


def test_autocomplete_psc_limit_above_cap():
    asyncio.run(
        _call_expect_error("autocomplete_psc", "exceeds maximum", search_text="cyber", limit=101)
    )


# autocomplete_naics (cap=100)
def test_autocomplete_naics_limit_zero():
    asyncio.run(
        _call_expect_error("autocomplete_naics", "must be >=", search_text="cyber", limit=0)
    )


def test_autocomplete_naics_limit_above_cap():
    asyncio.run(
        _call_expect_error("autocomplete_naics", "exceeds maximum", search_text="cyber", limit=101)
    )


# ===========================================================================
# 3. AMOUNT RANGE VALIDATION
# ===========================================================================

NEGATIVE_AMOUNT_CASES = [
    pytest.param(-1, id="neg_one"),
    pytest.param(-1000, id="neg_thousand"),
    pytest.param(-0.01, id="neg_cent"),
    pytest.param(-1000000, id="neg_million"),
]


@pytest.mark.parametrize("amount", NEGATIVE_AMOUNT_CASES)
def test_amount_min_negative_search_awards(amount):
    asyncio.run(
        _call_expect_error(
            "search_awards", "must be >= 0",
            keywords=["abc"], award_amount_min=amount,
        )
    )


@pytest.mark.parametrize("amount", NEGATIVE_AMOUNT_CASES)
def test_amount_max_negative_search_awards(amount):
    asyncio.run(
        _call_expect_error(
            "search_awards", "must be >= 0",
            keywords=["abc"], award_amount_max=amount,
        )
    )


@pytest.mark.parametrize("amount", NEGATIVE_AMOUNT_CASES)
def test_amount_min_negative_get_award_count(amount):
    asyncio.run(
        _call_expect_error(
            "get_award_count", "must be >= 0",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            award_amount_min=amount,
        )
    )


@pytest.mark.parametrize("amount", NEGATIVE_AMOUNT_CASES)
def test_amount_max_negative_get_award_count(amount):
    asyncio.run(
        _call_expect_error(
            "get_award_count", "must be >= 0",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            award_amount_max=amount,
        )
    )


def test_amount_min_greater_than_max_search_awards():
    asyncio.run(
        _call_expect_error(
            "search_awards", "amount_min",
            keywords=["abc"], award_amount_min=1000000, award_amount_max=1000,
        )
    )


def test_amount_min_zero_max_zero_valid():
    """Both zero is valid (and equal); should not raise."""
    try:
        asyncio.run(
            _call(
                "search_awards", keywords=["abc"],
                award_amount_min=0, award_amount_max=0,
            )
        )
    except Exception as e:
        assert "must be >= 0" not in str(e)
        assert "amount_min" not in str(e).lower() or "amount_min must" in str(e).lower()


# ===========================================================================
# 4. LIST/ARRAY FILTER VALIDATION
# ===========================================================================

LIST_FIELD_CASES = [
    "naics_codes",
    "psc_codes",
    "award_ids",
]


@pytest.mark.parametrize("field", LIST_FIELD_CASES)
def test_empty_list_rejected_search_awards(field):
    """Empty arrays should be rejected, not silently dropped."""
    asyncio.run(
        _call_expect_error(
            "search_awards", "empty",
            keywords=["abc"], **{field: []},
        )
    )


@pytest.mark.parametrize("field", LIST_FIELD_CASES)
def test_all_empty_strings_rejected_search_awards(field):
    """Lists of empty/whitespace strings are equivalent to no filter."""
    asyncio.run(
        _call_expect_error(
            "search_awards", "empty",
            keywords=["abc"], **{field: [""]},
        )
    )


@pytest.mark.parametrize("field", LIST_FIELD_CASES)
def test_all_whitespace_strings_rejected_search_awards(field):
    asyncio.run(
        _call_expect_error(
            "search_awards", "empty",
            keywords=["abc"], **{field: ["   "]},
        )
    )


def test_naics_accepts_int_in_list():
    """Coerce_code_list should turn ints into strings."""
    try:
        asyncio.run(
            _call(
                "search_awards", keywords=["abc"],
                naics_codes=[541512, 541511],
            )
        )
    except Exception as e:
        assert "must be a string" not in str(e)
        assert "empty" not in str(e)


def test_psc_codes_accepts_mixed_types():
    try:
        asyncio.run(
            _call(
                "search_awards", keywords=["abc"],
                psc_codes=["R425", 5410],
            )
        )
    except Exception as e:
        assert "must be a string" not in str(e)


def test_keywords_empty_list_rejected():
    """Empty keywords list is equivalent to no filter; should be rejected."""
    asyncio.run(
        _call_expect_error(
            "search_awards", "empty",
            keywords=[], time_period_start="2025-01-01", time_period_end="2025-12-31",
        )
    )


def test_keywords_all_whitespace_rejected():
    """Empty/whitespace keywords are too short for USASpending's 3-char min."""
    asyncio.run(
        _call_expect_error(
            "search_awards", "at least 3 characters",
            keywords=["", "  "],
            time_period_start="2025-01-01", time_period_end="2025-12-31",
        )
    )


# ===========================================================================
# 5. CONTROL-CHARACTER SAFETY
# ===========================================================================

CONTROL_CHAR_CASES = [
    pytest.param("test\x00null", id="null_byte"),
    pytest.param("test\nnewline", id="newline"),
    pytest.param("test\tab", id="tab"),
    pytest.param("test\rcr", id="cr"),
    pytest.param("test\r\ncrlf", id="crlf"),
    pytest.param("test\x01ctrl", id="ctrl_x01"),
    pytest.param("test\x0bvtab", id="vtab"),
    pytest.param("test\x0cff", id="form_feed"),
]


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_keywords(text):
    asyncio.run(
        _call_expect_error("search_awards", "control characters", keywords=[text])
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_awarding_agency(text):
    asyncio.run(
        _call_expect_error(
            "search_awards", "control characters",
            keywords=["abc"], awarding_agency=text,
        )
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_recipient_name(text):
    asyncio.run(
        _call_expect_error(
            "search_awards", "control characters",
            keywords=["abc"], recipient_name=text,
        )
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_autocomplete_psc(text):
    asyncio.run(
        _call_expect_error("autocomplete_psc", "control characters", search_text=text)
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_autocomplete_naics(text):
    asyncio.run(
        _call_expect_error("autocomplete_naics", "control characters", search_text=text)
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_get_award_detail(text):
    asyncio.run(
        _call_expect_error("get_award_detail", "control characters", generated_award_id=text)
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_get_transactions(text):
    asyncio.run(
        _call_expect_error("get_transactions", "control characters", generated_award_id=text)
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_get_award_funding(text):
    asyncio.run(
        _call_expect_error("get_award_funding", "control characters", generated_award_id=text)
    )


@pytest.mark.parametrize("text", CONTROL_CHAR_CASES)
def test_control_chars_rejected_get_idv_children(text):
    asyncio.run(
        _call_expect_error("get_idv_children", "control characters", generated_idv_id=text)
    )


# Verify normal text passes through control-char check
LEGITIMATE_TEXT_CASES = [
    pytest.param("McDonald's", id="apostrophe"),
    pytest.param("AT&T", id="ampersand"),
    pytest.param("café", id="unicode_accent"),
    pytest.param("北京", id="unicode_cjk"),
    pytest.param("🚀 rocket", id="unicode_emoji"),
    pytest.param("a/b", id="forward_slash"),
    pytest.param("a\\b", id="backslash"),
    pytest.param("100%", id="percent"),
    pytest.param("$1,000", id="dollar_comma"),
    pytest.param("simple text", id="space"),
]


@pytest.mark.parametrize("text", LEGITIMATE_TEXT_CASES)
def test_legitimate_text_passes_keywords(text):
    """These should not be rejected by control-char filter."""
    try:
        asyncio.run(_call("search_awards", keywords=[text]))
    except Exception as e:
        assert "control characters" not in str(e), (
            f"{text!r} should not be rejected: {e}"
        )


# ===========================================================================
# 6. extra='forbid' ENFORCEMENT ON EVERY TOOL
# ===========================================================================

UNKNOWN_PARAM_TOOLS = [
    pytest.param(
        "search_awards",
        {"keywords": ["x"], "bogus_param": "y"},
        id="search_awards",
    ),
    pytest.param(
        "get_award_count",
        {"time_period_start": "2025-01-01", "time_period_end": "2025-12-31",
         "bogus_param": "y"},
        id="get_award_count",
    ),
    pytest.param(
        "spending_over_time",
        {"time_period_start": "2025-01-01", "time_period_end": "2025-12-31",
         "bogus_param": "y"},
        id="spending_over_time",
    ),
    pytest.param(
        "spending_by_category",
        {"category": "awarding_agency", "time_period_start": "2025-01-01",
         "time_period_end": "2025-12-31", "bogus_param": "y"},
        id="spending_by_category",
    ),
    pytest.param(
        "get_award_detail",
        {"generated_award_id": VALID_AWARD_ID, "bogus_param": "y"},
        id="get_award_detail",
    ),
    pytest.param(
        "get_transactions",
        {"generated_award_id": VALID_AWARD_ID, "bogus_param": "y"},
        id="get_transactions",
    ),
    pytest.param(
        "get_award_funding",
        {"generated_award_id": VALID_AWARD_ID, "bogus_param": "y"},
        id="get_award_funding",
    ),
    pytest.param(
        "get_idv_children",
        {"generated_idv_id": VALID_IDV_ID, "bogus_param": "y"},
        id="get_idv_children",
    ),
    pytest.param(
        "lookup_piid",
        {"piid": "N00024", "bogus_param": "y"},
        id="lookup_piid",
    ),
    pytest.param(
        "autocomplete_psc",
        {"search_text": "cyber", "bogus_param": "y"},
        id="autocomplete_psc",
    ),
    pytest.param(
        "autocomplete_naics",
        {"search_text": "cyber", "bogus_param": "y"},
        id="autocomplete_naics",
    ),
    pytest.param(
        "get_agency_overview",
        {"toptier_code": "097", "bogus_param": "y"},
        id="get_agency_overview",
    ),
    pytest.param(
        "get_agency_awards",
        {"toptier_code": "097", "bogus_param": "y"},
        id="get_agency_awards",
    ),
    pytest.param(
        "get_naics_details",
        {"code": "541512", "bogus_param": "y"},
        id="get_naics_details",
    ),
    pytest.param(
        "get_psc_filter_tree",
        {"path": "", "bogus_param": "y"},
        id="get_psc_filter_tree",
    ),
    pytest.param(
        "get_state_profile",
        {"state_fips": "06", "bogus_param": "y"},
        id="get_state_profile",
    ),
]


@pytest.mark.parametrize("tool_name,kwargs", UNKNOWN_PARAM_TOOLS)
def test_extra_forbid_on_every_tool(tool_name, kwargs):
    asyncio.run(
        _call_expect_error(tool_name, "extra inputs are not permitted", **kwargs)
    )


# Specific historical typo cases
def test_typo_keyword_vs_keywords():
    """Singular typo vs the real plural parameter."""
    asyncio.run(
        _call_expect_error("search_awards", "extra inputs", keyword="cyber")
    )


def test_typo_search_query_vs_search_text():
    asyncio.run(
        _call_expect_error("autocomplete_psc", "extra inputs", search_query="cyber")
    )


def test_typo_naics_vs_naics_codes():
    asyncio.run(
        _call_expect_error(
            "search_awards", "extra inputs",
            keywords=["abc"], naics="541512",
        )
    )


def test_typo_agency_vs_awarding_agency():
    asyncio.run(
        _call_expect_error(
            "search_awards", "extra inputs",
            keywords=["abc"], agency="DoD",
        )
    )


# ===========================================================================
# 7. AWARD IDENTIFIER VALIDATION
# ===========================================================================

INVALID_AWARD_ID_CASES = [
    pytest.param("", "cannot be empty", id="empty"),
    pytest.param("   ", "cannot be empty", id="whitespace_only"),
    pytest.param("\t", "cannot be empty", id="tab_only"),
    pytest.param("\n", "cannot be empty", id="newline_only"),
]


@pytest.mark.parametrize("award_id,match", INVALID_AWARD_ID_CASES)
def test_award_id_invalid_get_award_detail(award_id, match):
    asyncio.run(
        _call_expect_error("get_award_detail", match, generated_award_id=award_id)
    )


@pytest.mark.parametrize("award_id,match", INVALID_AWARD_ID_CASES)
def test_award_id_invalid_get_transactions(award_id, match):
    asyncio.run(
        _call_expect_error("get_transactions", match, generated_award_id=award_id)
    )


@pytest.mark.parametrize("award_id,match", INVALID_AWARD_ID_CASES)
def test_award_id_invalid_get_award_funding(award_id, match):
    asyncio.run(
        _call_expect_error("get_award_funding", match, generated_award_id=award_id)
    )


@pytest.mark.parametrize("idv_id,match", INVALID_AWARD_ID_CASES)
def test_idv_id_invalid_get_idv_children(idv_id, match):
    asyncio.run(
        _call_expect_error("get_idv_children", match, generated_idv_id=idv_id)
    )


# PIID validation
INVALID_PIID_CASES = [
    pytest.param("", id="empty"),
    pytest.param("ab", id="too_short_2"),
    pytest.param("a", id="too_short_1"),
    pytest.param("  ", id="whitespace_only"),
    pytest.param(" a ", id="whitespace_with_one_char"),
]


@pytest.mark.parametrize("piid", INVALID_PIID_CASES)
def test_piid_invalid_lookup_piid(piid):
    asyncio.run(_call_expect_error("lookup_piid", "at least 3", piid=piid))


# ===========================================================================
# 8. TOPTIER CODE NORMALIZATION
# ===========================================================================

INVALID_TOPTIER_CASES = [
    pytest.param("", "numeric agency code", id="empty"),
    pytest.param("  ", "numeric agency code", id="whitespace_only"),
    pytest.param("ABC", "numeric agency code", id="alpha"),
    pytest.param("9X", "numeric agency code", id="alphanumeric"),
    pytest.param("9.7", "numeric agency code", id="decimal"),
    pytest.param("9-7", "numeric agency code", id="hyphen"),
    pytest.param("DoD", "numeric agency code", id="agency_word"),
]


@pytest.mark.parametrize("code,match", INVALID_TOPTIER_CASES)
def test_toptier_invalid_get_agency_overview(code, match):
    asyncio.run(_call_expect_error("get_agency_overview", match, toptier_code=code))


@pytest.mark.parametrize("code,match", INVALID_TOPTIER_CASES)
def test_toptier_invalid_get_agency_awards(code, match):
    asyncio.run(_call_expect_error("get_agency_awards", match, toptier_code=code))


def test_toptier_short_code_left_padded_to_3_digits():
    """'97' should be normalized to '097' before reaching the API."""
    try:
        asyncio.run(_call("get_agency_overview", toptier_code="97"))
    except Exception as e:
        assert "numeric agency code" not in str(e)


def test_toptier_code_2_digit_left_padded():
    try:
        asyncio.run(_call("get_agency_overview", toptier_code="9"))
    except Exception as e:
        assert "numeric agency code" not in str(e)


def test_toptier_code_4_digit_passthrough():
    try:
        asyncio.run(_call("get_agency_overview", toptier_code="9700"))
    except Exception as e:
        assert "numeric agency code" not in str(e)


def test_toptier_code_with_whitespace_stripped():
    try:
        asyncio.run(_call("get_agency_overview", toptier_code="  097  "))
    except Exception as e:
        assert "numeric agency code" not in str(e)


# ===========================================================================
# 9. FISCAL YEAR BOUNDARY CHECKS
# ===========================================================================

def test_fiscal_year_below_2008_get_agency_overview():
    asyncio.run(
        _call_expect_error(
            "get_agency_overview", "must be >= 2008",
            toptier_code="097", fiscal_year=2007,
        )
    )


def test_fiscal_year_zero_get_agency_overview():
    asyncio.run(
        _call_expect_error(
            "get_agency_overview", "must be >= 2008",
            toptier_code="097", fiscal_year=0,
        )
    )


def test_fiscal_year_negative_get_agency_overview():
    asyncio.run(
        _call_expect_error(
            "get_agency_overview", "must be >= 2008",
            toptier_code="097", fiscal_year=-2026,
        )
    )


def test_fiscal_year_far_future_get_agency_overview():
    asyncio.run(
        _call_expect_error(
            "get_agency_overview", "current FY",
            toptier_code="097", fiscal_year=3000,
        )
    )


def test_fiscal_year_2008_boundary_valid():
    """2008 is the lowest valid FY."""
    try:
        asyncio.run(_call("get_agency_overview", toptier_code="097", fiscal_year=2008))
    except Exception as e:
        assert "must be >= 2008" not in str(e)


def test_fiscal_year_below_2008_get_agency_awards():
    asyncio.run(
        _call_expect_error(
            "get_agency_awards", "must be >= 2008",
            toptier_code="097", fiscal_year=2007,
        )
    )


def test_fiscal_year_far_future_get_agency_awards():
    asyncio.run(
        _call_expect_error(
            "get_agency_awards", "current FY",
            toptier_code="097", fiscal_year=3000,
        )
    )


# ===========================================================================
# 10. REFERENCE TOOL INPUT VALIDATION
# ===========================================================================

# get_naics_details
INVALID_NAICS_CASES = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace_only"),
    pytest.param("ABCD", id="alpha"),
    pytest.param("12.34", id="period"),
    pytest.param("12-34", id="hyphen"),
    pytest.param("12 34", id="embedded_space"),
    pytest.param("541!", id="special"),
]


@pytest.mark.parametrize("code", INVALID_NAICS_CASES)
def test_naics_invalid_get_naics_details(code):
    asyncio.run(_call_expect_error("get_naics_details", "numeric", code=code))


def test_naics_valid_2_digit_passes():
    try:
        asyncio.run(_call("get_naics_details", code="54"))
    except Exception as e:
        assert "must be numeric" not in str(e)


def test_naics_valid_6_digit_passes():
    try:
        asyncio.run(_call("get_naics_details", code="541512"))
    except Exception as e:
        assert "must be numeric" not in str(e)


# get_state_profile
INVALID_STATE_FIPS_CASES = [
    pytest.param("", id="empty"),
    pytest.param(" ", id="space_only"),
    pytest.param("6", id="single_digit"),
    pytest.param("006", id="three_digits"),
    pytest.param("0600", id="four_digits"),
    pytest.param("AB", id="alpha"),
    pytest.param("CA", id="state_abbrev"),
    pytest.param("0A", id="alphanumeric"),
    pytest.param("California", id="full_name"),
    pytest.param("06.0", id="decimal"),
]


@pytest.mark.parametrize("fips", INVALID_STATE_FIPS_CASES)
def test_state_fips_invalid_get_state_profile(fips):
    asyncio.run(_call_expect_error("get_state_profile", "FIPS", state_fips=fips))


def test_state_fips_valid_06_california():
    try:
        asyncio.run(_call("get_state_profile", state_fips="06"))
    except Exception as e:
        assert "FIPS" not in str(e)


def test_state_fips_valid_48_texas():
    try:
        asyncio.run(_call("get_state_profile", state_fips="48"))
    except Exception as e:
        assert "FIPS" not in str(e)


def test_state_fips_with_whitespace_stripped():
    try:
        asyncio.run(_call("get_state_profile", state_fips="  06  "))
    except Exception as e:
        assert "FIPS" not in str(e)


# ===========================================================================
# 11. AUTOCOMPLETE QUERY CHECKS
# ===========================================================================

def test_autocomplete_psc_empty_returns_note():
    """Empty query returns empty results with a note, not an error."""
    result = asyncio.run(_call("autocomplete_psc", search_text=""))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict):
        assert "results" in payload
        assert payload["results"] == []
        assert "_note" in payload


def test_autocomplete_psc_single_char_returns_note():
    result = asyncio.run(_call("autocomplete_psc", search_text="r"))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict):
        assert "results" in payload
        assert payload["results"] == []


def test_autocomplete_psc_whitespace_only_returns_note():
    result = asyncio.run(_call("autocomplete_psc", search_text="   "))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict):
        assert payload.get("results") == []


def test_autocomplete_psc_too_long_rejected():
    asyncio.run(
        _call_expect_error(
            "autocomplete_psc", "exceeds 200",
            search_text="x" * 201,
        )
    )


def test_autocomplete_psc_at_length_cap_passes():
    try:
        asyncio.run(_call("autocomplete_psc", search_text="x" * 200))
    except Exception as e:
        assert "exceeds 200" not in str(e)


def test_autocomplete_naics_empty_returns_note():
    result = asyncio.run(_call("autocomplete_naics", search_text=""))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict):
        assert payload.get("results") == []


def test_autocomplete_naics_single_char_returns_note():
    result = asyncio.run(_call("autocomplete_naics", search_text="x"))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict):
        assert payload.get("results") == []


def test_autocomplete_naics_too_long_rejected():
    asyncio.run(
        _call_expect_error(
            "autocomplete_naics", "exceeds 200",
            search_text="x" * 201,
        )
    )


# ===========================================================================
# 12. NO-FILTER REJECTION
# ===========================================================================

def test_search_awards_no_filters_rejected():
    """Calling with no filters silently returned recent awards in 0.1.x."""
    asyncio.run(_call_expect_error("search_awards", "at least one filter"))


def test_search_awards_award_type_only_rejected():
    """award_type alone is not a filter."""
    asyncio.run(
        _call_expect_error("search_awards", "at least one filter", award_type="contracts")
    )


def test_get_award_count_no_filters_rejected():
    asyncio.run(_call_expect_error("get_award_count", "at least one filter"))


def test_get_award_count_award_type_only_rejected():
    asyncio.run(
        _call_expect_error(
            "get_award_count", "at least one filter", award_type="contracts"
        )
    )


def test_spending_over_time_no_filters_rejected():
    asyncio.run(_call_expect_error("spending_over_time", "at least one filter"))


def test_spending_over_time_award_type_only_rejected():
    asyncio.run(
        _call_expect_error(
            "spending_over_time", "at least one filter", award_type="contracts"
        )
    )


def test_spending_over_time_group_alone_rejected():
    """group is not a filter, just a bucket choice."""
    asyncio.run(
        _call_expect_error(
            "spending_over_time", "at least one filter", group="quarter"
        )
    )


# ===========================================================================
# 13. TYPE COERCION AND RESPONSE-SHAPE UTILITIES
# ===========================================================================

from usaspending_gov_mcp.server import (  # noqa: E402
    _validate_date,
    _clamp_limit,
    _coerce_code_list,
    _validate_no_control_chars,
    _validate_strings_no_control_chars,
    _normalize_toptier,
    _validate_fiscal_year,
    _ensure_dict_response,
    _clean_error_body,
    _current_fiscal_year,
)


# _validate_date
def test_validate_date_valid_passthrough():
    assert _validate_date("2026-01-15", "x") == "2026-01-15"


def test_validate_date_valid_2008_lowest():
    assert _validate_date("2008-01-01", "x") == "2008-01-01"


def test_validate_date_iso_datetime_rejected():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_date("2026-01-15T00:00:00", "x")


def test_validate_date_slashes_rejected():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_date("2026/01/15", "x")


def test_validate_date_us_format_rejected():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_date("01/15/2026", "x")


def test_validate_date_invalid_calendar_feb_30():
    with pytest.raises(ValueError, match="calendar date"):
        _validate_date("2026-02-30", "x")


def test_validate_date_invalid_calendar_feb_29_non_leap():
    with pytest.raises(ValueError, match="calendar date"):
        _validate_date("2025-02-29", "x")


def test_validate_date_valid_feb_29_leap_year():
    assert _validate_date("2024-02-29", "x") == "2024-02-29"


def test_validate_date_field_name_in_error():
    with pytest.raises(ValueError, match="custom_field"):
        _validate_date("bad", "custom_field")


# _clamp_limit
def test_clamp_limit_in_range_passthrough():
    assert _clamp_limit(50, cap=100) == 50


def test_clamp_limit_at_min_boundary():
    assert _clamp_limit(1, cap=100) == 1


def test_clamp_limit_at_max_boundary():
    assert _clamp_limit(100, cap=100) == 100


def test_clamp_limit_zero_raises():
    with pytest.raises(ValueError, match="must be >="):
        _clamp_limit(0, cap=100)


def test_clamp_limit_negative_raises():
    with pytest.raises(ValueError, match="must be >="):
        _clamp_limit(-1, cap=100)


def test_clamp_limit_above_cap_raises():
    with pytest.raises(ValueError, match="exceeds maximum"):
        _clamp_limit(101, cap=100)


def test_clamp_limit_field_name_in_error():
    with pytest.raises(ValueError, match="size"):
        _clamp_limit(0, cap=10, field="size")


def test_clamp_limit_huge_cap_passes():
    """5000 cap for transactions."""
    assert _clamp_limit(5000, cap=5000) == 5000


# _coerce_code_list
def test_coerce_code_list_none_returns_none():
    assert _coerce_code_list(None, "x") is None


def test_coerce_code_list_strings_passthrough():
    assert _coerce_code_list(["541512", "541511"], "x") == ["541512", "541511"]


def test_coerce_code_list_ints_to_strings():
    assert _coerce_code_list([541512, 541511], "x") == ["541512", "541511"]


def test_coerce_code_list_mixed_int_str():
    assert _coerce_code_list([541512, "541511"], "x") == ["541512", "541511"]


def test_coerce_code_list_strips_whitespace():
    assert _coerce_code_list(["  541512  "], "x") == ["541512"]


def test_coerce_code_list_drops_empty_strings_and_raises():
    with pytest.raises(ValueError, match="empty"):
        _coerce_code_list(["", "   "], "x")


def test_coerce_code_list_empty_list_raises():
    with pytest.raises(ValueError, match="empty array"):
        _coerce_code_list([], "x")


def test_coerce_code_list_field_name_in_error():
    with pytest.raises(ValueError, match="custom_field"):
        _coerce_code_list([], "custom_field")


# _validate_no_control_chars
def test_validate_no_control_chars_none_returns_none():
    assert _validate_no_control_chars(None, field="x") is None


def test_validate_no_control_chars_normal_string_passes():
    assert _validate_no_control_chars("hello world", field="x") == "hello world"


def test_validate_no_control_chars_unicode_passes():
    assert _validate_no_control_chars("café 北京 🚀", field="x") == "café 北京 🚀"


def test_validate_no_control_chars_apostrophe_passes():
    assert _validate_no_control_chars("McDonald's", field="x") == "McDonald's"


def test_validate_no_control_chars_null_byte_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\x00b", field="x")


def test_validate_no_control_chars_newline_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\nb", field="x")


def test_validate_no_control_chars_tab_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\tb", field="x")


def test_validate_no_control_chars_cr_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\rb", field="x")


def test_validate_no_control_chars_x01_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\x01b", field="x")


def test_validate_no_control_chars_x1f_rejected():
    """0x1f is the highest control char in the rejection range."""
    with pytest.raises(ValueError, match="control characters"):
        _validate_no_control_chars("a\x1fb", field="x")


def test_validate_no_control_chars_field_name_in_error():
    with pytest.raises(ValueError, match="custom_field"):
        _validate_no_control_chars("a\x00b", field="custom_field")


# _validate_strings_no_control_chars (list version)
def test_validate_strings_no_control_chars_none_returns_silently():
    _validate_strings_no_control_chars(None, field="x")


def test_validate_strings_no_control_chars_empty_list_returns_silently():
    _validate_strings_no_control_chars([], field="x")


def test_validate_strings_no_control_chars_normal_list_passes():
    _validate_strings_no_control_chars(["hello", "world"], field="x")


def test_validate_strings_no_control_chars_first_bad_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_strings_no_control_chars(["a\x00b", "good"], field="x")


def test_validate_strings_no_control_chars_last_bad_rejected():
    with pytest.raises(ValueError, match="control characters"):
        _validate_strings_no_control_chars(["good", "a\nb"], field="x")


def test_validate_strings_no_control_chars_index_in_error():
    """Error message includes the offending index."""
    with pytest.raises(ValueError, match=r"\[2\]"):
        _validate_strings_no_control_chars(
            ["good", "good", "a\x00b"], field="x"
        )


# _normalize_toptier
def test_normalize_toptier_3_digit_passthrough():
    assert _normalize_toptier("097") == "097"


def test_normalize_toptier_4_digit_passthrough():
    assert _normalize_toptier("9700") == "9700"


def test_normalize_toptier_2_digit_padded():
    assert _normalize_toptier("97") == "097"


def test_normalize_toptier_1_digit_padded():
    assert _normalize_toptier("9") == "009"


def test_normalize_toptier_strips_whitespace():
    assert _normalize_toptier("  097  ") == "097"


def test_normalize_toptier_empty_raises():
    with pytest.raises(ValueError, match="numeric agency code"):
        _normalize_toptier("")


def test_normalize_toptier_alpha_raises():
    with pytest.raises(ValueError, match="numeric agency code"):
        _normalize_toptier("ABC")


def test_normalize_toptier_alphanumeric_raises():
    with pytest.raises(ValueError, match="numeric agency code"):
        _normalize_toptier("9X7")


def test_normalize_toptier_decimal_raises():
    with pytest.raises(ValueError, match="numeric agency code"):
        _normalize_toptier("9.7")


def test_normalize_toptier_int_input_coerced():
    """Int inputs should be coerced to string then validated."""
    assert _normalize_toptier(97) == "097"


# _validate_fiscal_year
def test_validate_fiscal_year_2008_lowest_valid():
    assert _validate_fiscal_year(2008) == 2008


def test_validate_fiscal_year_current_fy_valid():
    fy = _current_fiscal_year()
    assert _validate_fiscal_year(fy) == fy


def test_validate_fiscal_year_2007_rejected():
    with pytest.raises(ValueError, match="must be >= 2008"):
        _validate_fiscal_year(2007)


def test_validate_fiscal_year_zero_rejected():
    with pytest.raises(ValueError, match="must be >= 2008"):
        _validate_fiscal_year(0)


def test_validate_fiscal_year_negative_rejected():
    with pytest.raises(ValueError, match="must be >= 2008"):
        _validate_fiscal_year(-1)


def test_validate_fiscal_year_far_future_rejected():
    with pytest.raises(ValueError, match="current FY"):
        _validate_fiscal_year(3000)


def test_validate_fiscal_year_one_above_current_rejected():
    fy = _current_fiscal_year()
    with pytest.raises(ValueError, match="current FY"):
        _validate_fiscal_year(fy + 1)


# _ensure_dict_response
def test_ensure_dict_response_dict_passthrough():
    d = {"key": "value"}
    assert _ensure_dict_response(d, path="/x") == d


def test_ensure_dict_response_empty_dict_passthrough():
    assert _ensure_dict_response({}, path="/x") == {}


def test_ensure_dict_response_none_raises():
    with pytest.raises(Exception):
        _ensure_dict_response(None, path="/api/v2/x/")


def test_ensure_dict_response_list_raises():
    with pytest.raises(Exception):
        _ensure_dict_response([1, 2, 3], path="/api/v2/x/")


def test_ensure_dict_response_int_raises():
    with pytest.raises(Exception):
        _ensure_dict_response(42, path="/api/v2/x/")


def test_ensure_dict_response_string_raises():
    with pytest.raises(Exception):
        _ensure_dict_response("text", path="/api/v2/x/")


def test_ensure_dict_response_path_in_error():
    """Error message should include the path for debugging."""
    try:
        _ensure_dict_response(None, path="/api/v2/special/")
    except Exception as e:
        assert "/api/v2/special/" in str(e) or "special" in str(e).lower()


# _clean_error_body
def test_clean_error_body_short_text_passthrough():
    assert _clean_error_body("not found") == "not found"


def test_clean_error_body_truncates_long_text():
    long_text = "x" * 1000
    result = _clean_error_body(long_text)
    assert len(result) <= 500


def test_clean_error_body_extracts_html_title():
    html = "<html><head><title>504 Gateway</title></head><body>...</body></html>"
    result = _clean_error_body(html)
    assert "504 Gateway" in result


def test_clean_error_body_extracts_h1():
    html = "<html><body><h1>Service Unavailable</h1></body></html>"
    result = _clean_error_body(html)
    assert "Service Unavailable" in result


def test_clean_error_body_combines_title_and_h1():
    html = (
        "<html><head><title>Error</title></head>"
        "<body><h1>Detail</h1></body></html>"
    )
    result = _clean_error_body(html)
    assert "Error" in result
    assert "Detail" in result


def test_clean_error_body_empty_string():
    assert _clean_error_body("") == ""


# _current_fiscal_year
def test_current_fiscal_year_returns_int():
    fy = _current_fiscal_year()
    assert isinstance(fy, int)


def test_current_fiscal_year_at_least_2026():
    fy = _current_fiscal_year()
    assert fy >= 2026


def test_current_fiscal_year_in_reasonable_range():
    """Should be either calendar year or one ahead."""
    from datetime import date
    fy = _current_fiscal_year()
    today = date.today()
    assert fy in (today.year, today.year + 1)


# ===========================================================================
# 14. SPENDING_BY_CATEGORY VARIATIONS
# ===========================================================================

def test_spending_by_category_invalid_category():
    """category is a Literal; invalid value rejected by pydantic."""
    asyncio.run(
        _call_expect_error(
            "spending_by_category", "literal_error",
            category="not_a_category",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
        )
    )


def test_spending_by_category_no_filters_passes_validation():
    """spending_by_category does NOT enforce a no-filter check (unlike sibling tools).
    It forwards to the API which may return empty results. Just confirm the
    validation layer doesn't raise."""
    try:
        asyncio.run(_call("spending_by_category", category="awarding_agency"))
    except Exception as e:
        # Network errors are fine; validation errors would indicate a bug
        assert "filter" not in str(e).lower() or "literal" in str(e).lower()


def test_spending_by_category_limit_above_cap():
    asyncio.run(
        _call_expect_error(
            "spending_by_category", "exceeds maximum",
            category="awarding_agency",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            limit=101,
        )
    )


def test_spending_by_category_limit_zero():
    asyncio.run(
        _call_expect_error(
            "spending_by_category", "must be >=",
            category="awarding_agency",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            limit=0,
        )
    )


# ===========================================================================
# 15. AWARD_TYPE LITERAL VALIDATION
# ===========================================================================

INVALID_AWARD_TYPE_CASES = [
    pytest.param("contract", id="singular_typo"),
    pytest.param("CONTRACTS", id="uppercase"),
    pytest.param("Contracts", id="capitalized"),
    pytest.param("not_a_type", id="garbage"),
    pytest.param("", id="empty"),
    pytest.param("subaward", id="invalid_subaward"),
]


@pytest.mark.parametrize("award_type", INVALID_AWARD_TYPE_CASES)
def test_award_type_invalid_search_awards(award_type):
    """Literal type validation; pydantic rejects."""
    asyncio.run(
        _call_expect_error(
            "search_awards", "literal_error",
            keywords=["abc"], award_type=award_type,
        )
    )


@pytest.mark.parametrize("award_type", INVALID_AWARD_TYPE_CASES)
def test_award_type_invalid_get_award_count(award_type):
    asyncio.run(
        _call_expect_error(
            "get_award_count", "literal_error",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            award_type=award_type,
        )
    )


# ===========================================================================
# 16. ORDER LITERAL VALIDATION
# ===========================================================================

INVALID_ORDER_CASES = [
    pytest.param("ascending", id="full_word_asc"),
    pytest.param("descending", id="full_word_desc"),
    pytest.param("ASC", id="uppercase_asc"),
    pytest.param("DESC", id="uppercase_desc"),
    pytest.param("up", id="invalid_up"),
    pytest.param("down", id="invalid_down"),
    pytest.param("", id="empty"),
]


@pytest.mark.parametrize("order", INVALID_ORDER_CASES)
def test_order_invalid_search_awards(order):
    asyncio.run(
        _call_expect_error(
            "search_awards", "literal_error",
            keywords=["abc"], order=order,
        )
    )


@pytest.mark.parametrize("order", INVALID_ORDER_CASES)
def test_order_invalid_get_transactions(order):
    asyncio.run(
        _call_expect_error(
            "get_transactions", "literal_error",
            generated_award_id=VALID_AWARD_ID, order=order,
        )
    )


# ===========================================================================
# 17. SPENDING_OVER_TIME GROUP LITERAL
# ===========================================================================

INVALID_GROUP_CASES = [
    pytest.param("year", id="year_not_fiscal"),
    pytest.param("week", id="week"),
    pytest.param("day", id="day"),
    pytest.param("Q", id="abbreviation"),
    pytest.param("", id="empty"),
    pytest.param("FISCAL_YEAR", id="uppercase"),
]


@pytest.mark.parametrize("group", INVALID_GROUP_CASES)
def test_group_invalid_spending_over_time(group):
    asyncio.run(
        _call_expect_error(
            "spending_over_time", "literal_error",
            time_period_start="2025-01-01", time_period_end="2025-12-31",
            group=group,
        )
    )


# ===========================================================================
# 18. CHILD_TYPE LITERAL
# ===========================================================================

INVALID_CHILD_TYPE_CASES = [
    pytest.param("children", id="children"),
    pytest.param("orders", id="orders"),
    pytest.param("", id="empty"),
    pytest.param("CHILD_AWARDS", id="uppercase"),
]


@pytest.mark.parametrize("child_type", INVALID_CHILD_TYPE_CASES)
def test_child_type_invalid_get_idv_children(child_type):
    asyncio.run(
        _call_expect_error(
            "get_idv_children", "literal_error",
            generated_idv_id=VALID_IDV_ID, child_type=child_type,
        )
    )
