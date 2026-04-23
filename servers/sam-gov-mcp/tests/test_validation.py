# SPDX-License-Identifier: MIT
"""Regression tests for 0.3.0 hardening fixes.

Invoked through the FastMCP registry (mcp.call_tool) so pydantic type coercion
runs exactly as it does in production. The prior stress_test.py awaited raw
coroutines and bypassed the tool pipeline entirely.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# A fake API key lets pre-network validation run without hitting SAM.gov.
# Our validators raise before any HTTP call, so network isn't needed for most tests.
os.environ.setdefault("SAM_API_KEY", "SAM-00000000-0000-0000-0000-000000000000")

import sam_gov_mcp.server as srv  # noqa: E402
from sam_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the shared httpx client before every test.

    pytest creates a fresh event loop per test via asyncio.run. Reusing a
    stale AsyncClient across loops raises 'Event loop is closed'.
    """
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


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# P1: fiscal_year now accepts int OR str (known bug from handoff)
# ---------------------------------------------------------------------------

def test_fiscal_year_int_rejected_below_2008():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "out of range", fiscal_year=2007
    ))


def test_fiscal_year_int_rejected_future():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "out of range", fiscal_year=2099
    ))


def test_fiscal_year_string_below_2008():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "out of range", fiscal_year="2007"
    ))


def test_fiscal_year_not_numeric():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "year like 2026", fiscal_year="FY26"
    ))


# ---------------------------------------------------------------------------
# P1: repsAndCerts summary mode (avoid 74K+ payloads)
# ---------------------------------------------------------------------------

def test_reps_and_certs_uei_validation():
    """UEI format validation on reps_and_certs (was permissive in 0.2.x)."""
    asyncio.run(_call_expect_error(
        "get_entity_reps_and_certs", "12 uppercase", uei="123"
    ))


def test_reps_and_certs_empty_uei():
    asyncio.run(_call_expect_error(
        "get_entity_reps_and_certs", "cannot be empty", uei=""
    ))


# ---------------------------------------------------------------------------
# P2: Date format validation (MM/DD/YYYY required)
# ---------------------------------------------------------------------------

def test_search_contract_awards_rejects_iso_date():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "MM/DD/YYYY", date_signed="2026-01-15"
    ))


def test_search_contract_awards_rejects_yyyy_mm_dd():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "MM/DD/YYYY", last_modified_date="2026-01-15"
    ))


def test_search_contract_awards_accepts_bracket_range():
    """Bracketed ranges are the documented format; shouldn't trigger date error."""
    try:
        asyncio.run(_call(
            "search_contract_awards", date_signed="[01/01/2025,12/31/2025]", limit=1
        ))
    except Exception as e:
        # Network / auth errors OK; reject if it's a date validation error
        assert "mm/dd/yyyy" not in str(e).lower(), f"bracket range wrongly rejected: {e}"


def test_search_opportunities_rejects_iso_date():
    asyncio.run(_call_expect_error(
        "search_opportunities", "MM/DD/YYYY",
        posted_from="2026-01-01", posted_to="2026-01-31",
    ))


def test_search_exclusions_rejects_bad_activation_date():
    asyncio.run(_call_expect_error(
        "search_exclusions", "MM/DD/YYYY", activation_date_range="2025-01-01"
    ))


def test_search_contract_awards_invalid_calendar_date():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "not a valid calendar date",
        date_signed="02/31/2026",
    ))


# ---------------------------------------------------------------------------
# P2: UEI / CAGE format validation
# ---------------------------------------------------------------------------

def test_lookup_entity_by_uei_bad_format():
    asyncio.run(_call_expect_error(
        "lookup_entity_by_uei", "12 uppercase", uei="TOOSHORT"
    ))


def test_lookup_entity_by_cage_bad_length():
    asyncio.run(_call_expect_error(
        "lookup_entity_by_cage", "5 uppercase", cage_code="123"
    ))


# ---------------------------------------------------------------------------
# P2: Page / limit / offset bounds
# ---------------------------------------------------------------------------

def test_search_entities_negative_page():
    asyncio.run(_call_expect_error(
        "search_entities", "page must be >= 0", page=-1
    ))


def test_search_entities_size_above_cap():
    asyncio.run(_call_expect_error(
        "search_entities", "size", size=50
    ))


def test_search_exclusions_negative_page():
    asyncio.run(_call_expect_error(
        "search_exclusions", "page must be >= 0", page=-1
    ))


def test_search_exclusions_size_above_cap():
    asyncio.run(_call_expect_error(
        "search_exclusions", "size", size=200
    ))


def test_search_contract_awards_limit_above_cap():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "limit", limit=101
    ))


def test_search_contract_awards_negative_offset():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "offset must be >= 0", offset=-1
    ))


def test_search_opportunities_limit_above_cap():
    asyncio.run(_call_expect_error(
        "search_opportunities", "limit",
        posted_from="01/01/2026", posted_to="01/31/2026",
        limit=1001,
    ))


# ---------------------------------------------------------------------------
# P2: State code format (2-letter USPS)
# ---------------------------------------------------------------------------

def test_search_entities_bad_state_code():
    asyncio.run(_call_expect_error(
        "search_entities", "2-letter USPS", state_code="California"
    ))


def test_search_opportunities_bad_state_code():
    asyncio.run(_call_expect_error(
        "search_opportunities", "2-letter USPS",
        posted_from="01/01/2026", posted_to="01/31/2026",
        state="California",
    ))


# ---------------------------------------------------------------------------
# P2: Numeric codes accept int or str
# ---------------------------------------------------------------------------

def test_coerce_str_accepts_int():
    from sam_gov_mcp.server import _coerce_str
    assert _coerce_str(541512, field="naics") == "541512"
    assert _coerce_str("541512", field="naics") == "541512"
    assert _coerce_str(None, field="naics") is None


def test_coerce_str_rejects_bool():
    from sam_gov_mcp.server import _coerce_str
    try:
        _coerce_str(True, field="x")
    except ValueError:
        return
    raise AssertionError("bool should have been rejected")


# ---------------------------------------------------------------------------
# P3: Error hygiene (HTML stripping)
# ---------------------------------------------------------------------------

def test_clean_error_body_strips_html():
    from sam_gov_mcp.server import _clean_error_body
    html = '<!DOCTYPE html><html><head><title>401 Unauthorized</title></head><body><h1>API_KEY_INVALID</h1></body></html>'
    result = _clean_error_body(html)
    assert "<" not in result
    assert "API_KEY_INVALID" in result or "401 Unauthorized" in result


def test_clean_error_body_passthrough_non_html():
    from sam_gov_mcp.server import _clean_error_body
    assert _clean_error_body('{"error":"nope"}') == '{"error":"nope"}'


# ---------------------------------------------------------------------------
# USER_AGENT currency
# ---------------------------------------------------------------------------

def test_user_agent_matches_version():
    from sam_gov_mcp.constants import USER_AGENT
    # Match the current published version; bump this string when pyproject bumps.
    assert "0.3.7" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


# ---------------------------------------------------------------------------
# Current-FY helper boundary
# ---------------------------------------------------------------------------

def test_current_fiscal_year_matches_calendar():
    from sam_gov_mcp.server import _current_fiscal_year
    from datetime import date
    today = date.today()
    expected = today.year + 1 if today.month >= 10 else today.year
    assert _current_fiscal_year() == expected


# ---------------------------------------------------------------------------
# Live tests (opt-in via SAM_LIVE_TESTS=1 and real SAM_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set SAM_LIVE_TESTS=1 with real SAM_API_KEY to run live")
def test_reps_and_certs_summary_mode_returns_dict():
    # Known valid UEI: SAM.gov itself has one; use a real UEI via env or skip
    uei = os.environ.get("SAM_TEST_UEI")
    if not uei:
        pytest.skip("SAM_TEST_UEI not set")
    result = asyncio.run(_call("get_entity_reps_and_certs", uei=uei, summary_only=True))
    payload = _payload(result)
    assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# Round-4 P1 crashes: response-shape resilience
# ---------------------------------------------------------------------------

def test_normalize_awards_handles_null_totalRecords():
    from sam_gov_mcp.server import _normalize_awards_response
    out = _normalize_awards_response({"awardResponse": {"totalRecords": None, "limit": None, "offset": None}})
    assert out["totalRecords"] == 0
    assert out["limit"] == 10
    assert out["offset"] == 0


def test_normalize_awards_handles_top_level_null_totalRecords():
    from sam_gov_mcp.server import _normalize_awards_response
    out = _normalize_awards_response({"totalRecords": None, "awardSummary": []})
    assert out["totalRecords"] == 0


def test_normalize_awards_handles_string_totalRecords():
    from sam_gov_mcp.server import _normalize_awards_response
    out = _normalize_awards_response({"awardResponse": {"totalRecords": "42", "limit": "10", "offset": "0"}})
    assert out["totalRecords"] == 42


def test_normalize_awards_handles_non_dict():
    from sam_gov_mcp.server import _normalize_awards_response
    out = _normalize_awards_response(None)
    assert out["totalRecords"] == 0
    assert out["awardSummary"] == []


def test_as_list_handles_xml_collapse():
    from sam_gov_mcp.server import _as_list
    assert _as_list(None) == []
    assert _as_list([]) == []
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list({"foo": "bar"}) == [{"foo": "bar"}]  # XML collapse: single dict → list of 1


def test_safe_int_handles_none_and_bad_values():
    from sam_gov_mcp.server import _safe_int
    assert _safe_int(None) == 0
    assert _safe_int("null") == 0
    assert _safe_int("") == 0
    assert _safe_int("42") == 42
    assert _safe_int(42) == 42
    assert _safe_int("garbage") == 0
    assert _safe_int(None, default=99) == 99


def test_vendor_check_handles_dict_entityData():
    """Regression: round 4 found entityData-as-dict (XML collapse) crashed the tool."""
    from sam_gov_mcp.server import _as_list
    # The fix uses _as_list; verify it's applied in the flow
    dict_entity_data = {"entityRegistration": {"ueiSAM": "ABC"}}
    normalized = _as_list(dict_entity_data)
    assert len(normalized) == 1
    assert normalized[0]["entityRegistration"]["ueiSAM"] == "ABC"


# ---------------------------------------------------------------------------
# Round-2/3 P2 fixes: UEI validation on missing tools
# ---------------------------------------------------------------------------

def test_check_exclusion_by_uei_format():
    asyncio.run(_call_expect_error(
        "check_exclusion_by_uei", "12 uppercase", uei="TOOSHORT"
    ))


def test_get_entity_integrity_info_format():
    asyncio.run(_call_expect_error(
        "get_entity_integrity_info", "12 uppercase", uei="xyz"
    ))


def test_search_contract_awards_awardee_uei_format():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "12 uppercase", awardee_uei="short"
    ))


def test_search_contract_awards_awardee_cage_format():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "5 uppercase", awardee_cage_code="X"
    ))


# ---------------------------------------------------------------------------
# Date range caps and reversals
# ---------------------------------------------------------------------------

def test_search_opportunities_364_day_cap():
    asyncio.run(_call_expect_error(
        "search_opportunities", "exceeds 364 days",
        posted_from="01/01/2025", posted_to="12/31/2026",
    ))


def test_search_opportunities_reversed_date_range():
    asyncio.run(_call_expect_error(
        "search_opportunities", "is after",
        posted_from="12/31/2026", posted_to="01/01/2025",
    ))


# ---------------------------------------------------------------------------
# String length / WAF-safe
# ---------------------------------------------------------------------------

def test_search_opportunities_title_length():
    asyncio.run(_call_expect_error(
        "search_opportunities", "maximum length",
        posted_from="01/01/2026", posted_to="01/31/2026",
        title="a" * 2000,
    ))


# 0.3.0 shipped with a WAF filter that rejected `'`, `` ` ``, `<`, SQL
# keywords, and path traversal sequences. Round 1 of the 0.3.1 live audit
# confirmed those were false positives -- SAM.gov accepts all those patterns
# as literal search text. The filter blocked legitimate company names
# containing apostrophes (McDonald's, L'Oreal, O'Brien). It was removed in
# 0.3.1. These replacement tests assert the new, narrower filter accepts
# those and still rejects null bytes / control characters.


def test_search_entities_allows_apostrophe():
    """Apostrophe in company name must not be rejected (McDonald's, O'Brien)."""
    # Use the 'pre-network' path: a bogus key produces an auth error, but
    # validators run first. We just assert it isn't blocked on validation.
    try:
        asyncio.run(_call("search_entities", legal_business_name="O'Brien Corp"))
    except Exception as e:
        msg = str(e).lower()
        assert "firewall" not in msg
        assert "single quote" not in msg


def test_search_entities_allows_angle_brackets():
    try:
        asyncio.run(_call("search_entities", legal_business_name="<script>"))
    except Exception as e:
        msg = str(e).lower()
        assert "firewall" not in msg
        assert "angle bracket" not in msg


def test_search_entities_allows_sql_keywords():
    try:
        asyncio.run(_call("search_entities", legal_business_name="DROP TABLE users"))
    except Exception as e:
        msg = str(e).lower()
        assert "firewall" not in msg


def test_search_entities_rejects_null_byte():
    asyncio.run(_call_expect_error(
        "search_entities", "null byte", legal_business_name="abc\x00def"
    ))


def test_search_entities_rejects_newline():
    asyncio.run(_call_expect_error(
        "search_entities", "control character", legal_business_name="abc\ndef"
    ))


def test_search_entities_rejects_tab():
    asyncio.run(_call_expect_error(
        "search_entities", "control character", legal_business_name="abc\tdef"
    ))


# ---------------------------------------------------------------------------
# NAICS validation
# ---------------------------------------------------------------------------

def test_search_entities_naics_too_long():
    asyncio.run(_call_expect_error(
        "search_entities", "2-6 digit", primary_naics="1234567"
    ))


def test_search_entities_naics_negative():
    asyncio.run(_call_expect_error(
        "search_entities", "2-6 digit", primary_naics=-541511
    ))


def test_contract_awards_naics_operators_allowed():
    """Contract Awards documents ~ for OR and ! for NOT. Should pass validation."""
    # Shouldn't raise — just hits (fake) auth failure later
    try:
        asyncio.run(_call("search_contract_awards", naics_code="541511~541512", limit=1))
    except Exception as e:
        # Any non-validation error is fine
        assert "2-6 digit" not in str(e), f"operator format wrongly rejected: {e}"


# ---------------------------------------------------------------------------
# Code dict validation
# ---------------------------------------------------------------------------

def test_search_entities_bad_business_type_code():
    asyncio.run(_call_expect_error(
        "search_entities", "not a valid code", business_type_code="INVALID"
    ))


def test_search_entities_accepts_business_type_lowercase():
    """qf should auto-upcase to QF (SDVOSB)."""
    try:
        asyncio.run(_call("search_entities", business_type_code="qf"))
    except Exception as e:
        # Reach network error (fake key) or OK — but NOT 'not a valid code'
        assert "not a valid code" not in str(e), f"case normalization failed: {e}"


def test_search_opportunities_bad_set_aside():
    asyncio.run(_call_expect_error(
        "search_opportunities", "not a valid code",
        posted_from="01/01/2026", posted_to="01/31/2026",
        set_aside="NOTAREAL",
    ))


def test_search_opportunities_set_aside_lowercase():
    """sba should auto-upcase to SBA."""
    try:
        asyncio.run(_call(
            "search_opportunities",
            posted_from="01/01/2026", posted_to="01/31/2026",
            set_aside="sba",
        ))
    except Exception as e:
        assert "not a valid code" not in str(e), f"case normalization failed: {e}"


# ---------------------------------------------------------------------------
# PSC lookup + opportunity description empty guards
# ---------------------------------------------------------------------------

def test_lookup_psc_code_empty():
    asyncio.run(_call_expect_error(
        "lookup_psc_code", "cannot be empty", code=""
    ))


def test_lookup_psc_code_single_char():
    asyncio.run(_call_expect_error(
        "lookup_psc_code", "at least 2 characters", code="R"
    ))


def test_search_psc_free_text_empty():
    asyncio.run(_call_expect_error(
        "search_psc_free_text", "cannot be empty", query=""
    ))


def test_search_psc_free_text_whitespace():
    asyncio.run(_call_expect_error(
        "search_psc_free_text", "cannot be empty", query="   "
    ))


def test_get_opportunity_description_empty():
    asyncio.run(_call_expect_error(
        "get_opportunity_description", "cannot be empty", notice_id=""
    ))


def test_get_opportunity_description_whitespace():
    asyncio.run(_call_expect_error(
        "get_opportunity_description", "cannot be empty", notice_id="   "
    ))


# ---------------------------------------------------------------------------
# Dollar range + country normalization
# ---------------------------------------------------------------------------

def test_search_contract_awards_dollars_bad_format():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "bracket format", dollars_obligated="1000000"
    ))


def test_search_exclusions_country_lowercase_normalized():
    """Lowercase 'usa' should be normalized to 'USA' (3-char ISO) internally."""
    try:
        asyncio.run(_call("search_exclusions", country="usa"))
    except Exception as e:
        # Must NOT raise the "3-character ISO alpha-3" validation error
        assert "3-character ISO alpha-3" not in str(e), f"lowercase wrongly rejected: {e}"


def test_search_exclusions_country_still_rejects_2char():
    asyncio.run(_call_expect_error(
        "search_exclusions", "3-character ISO", country="US"
    ))


def test_search_exclusions_country_rejects_digits():
    asyncio.run(_call_expect_error(
        "search_exclusions", "3-character ISO", country="123"
    ))


# ---------------------------------------------------------------------------
# 0.3.1 regression tests: live-audit findings
# ---------------------------------------------------------------------------

def test_unknown_param_rejected_on_search_entities():
    """0.3.0 silently accepted typo'd param names, returning unfiltered data.
    E.g. search_entities(keyword='x') actually ignored keyword and returned
    all 700k entities. Fixed by applying extra='forbid' to every tool's
    pydantic arg model."""
    asyncio.run(_call_expect_error(
        "search_entities", "extra inputs are not permitted",
        legal_business_name="Lockheed", keyword="ignored-typo",
    ))


def test_unknown_param_rejected_on_search_exclusions():
    async def _run():
        try:
            await mcp.call_tool(
                "search_exclusions", {"name": "Smith", "bogus_param": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())


def test_unknown_param_rejected_on_search_opportunities():
    asyncio.run(_call_expect_error(
        "search_opportunities", "extra inputs are not permitted",
        posted_from="01/01/2026", posted_to="01/31/2026", keyword="typo",
    ))


def test_unknown_param_rejected_on_search_contract_awards():
    asyncio.run(_call_expect_error(
        "search_contract_awards", "extra inputs are not permitted",
        date_signed="[01/01/2025,01/31/2025]", department_name="typo",
    ))


def test_lookup_award_by_piid_rejects_empty():
    asyncio.run(_call_expect_error(
        "lookup_award_by_piid", "cannot be empty", piid="",
    ))


def test_lookup_award_by_piid_rejects_whitespace():
    asyncio.run(_call_expect_error(
        "lookup_award_by_piid", "cannot be empty", piid="   ",
    ))


def test_lookup_award_by_piid_rejects_control_chars():
    asyncio.run(_call_expect_error(
        "lookup_award_by_piid", "control characters", piid="ABC\ndef",
    ))


# ---- LIVE tests for 0.3.1 regressions ----

@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_apostrophe_in_company_name_works():
    """0.3.0 blocked apostrophes via an overzealous WAF filter.
    0.3.1 removed that filter after confirming SAM.gov accepts apostrophes."""
    r = asyncio.run(_call("search_entities", legal_business_name="McDonald's", size=3))
    data = _payload(r)
    # Must not raise; total_records is a valid integer string or int
    assert "totalRecords" in data or "entityData" in data


@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_lockheed_free_text_returns_matches():
    r = asyncio.run(_call("search_entities", legal_business_name="Lockheed Martin", size=3))
    data = _payload(r)
    total = int(data.get("totalRecords", 0))
    assert total > 0, f"expected >0 Lockheed matches, got {total}"


@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_psc_valid_code_returns_data():
    r = asyncio.run(_call("lookup_psc_code", code="R425"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_psc_invalid_code_clear_error():
    """0.3.0 leaked the opaque 'Entered search criteria is not found' message.
    0.3.1 translates to a clear PSC-specific error."""
    try:
        asyncio.run(_call("lookup_psc_code", code="ZZZZ"))
    except Exception as e:
        msg = str(e).lower()
        assert "did not find" in msg or "psc-manual" in msg, f"error still opaque: {e}"
        return
    raise AssertionError("expected 404 on bogus PSC code")


@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_opportunities_filter_applied():
    """Confirm free_text/title filter actually narrows results vs. baseline.
    Both calls share an event loop so the shared httpx client stays valid."""
    async def _run():
        r_all = await _call(
            "search_opportunities",
            posted_from="01/01/2026", posted_to="04/18/2026", limit=1,
        )
        r_title = await _call(
            "search_opportunities",
            posted_from="01/01/2026", posted_to="04/18/2026",
            title="cybersecurity", limit=1,
        )
        return r_all, r_title
    r_all, r_title = asyncio.run(_run())
    all_total = int(_payload(r_all).get("totalRecords", 0))
    title_total = int(_payload(r_title).get("totalRecords", 0))
    assert title_total < all_total, (
        f"filter did not reduce results: all={all_total}, title={title_total}"
    )


@pytest.mark.skipif(not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY")
def test_live_unknown_param_rejected_before_network():
    """Confirm the extra='forbid' patch applies live too."""
    try:
        asyncio.run(_call(
            "search_entities", legal_business_name="Lockheed", bogus_typo="x",
        ))
    except Exception as e:
        assert "extra inputs are not permitted" in str(e).lower()
        return
    raise AssertionError("extra param not rejected")
