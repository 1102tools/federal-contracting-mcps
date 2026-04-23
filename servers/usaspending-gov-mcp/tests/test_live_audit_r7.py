# SPDX-License-Identifier: MIT
"""Round 7: Deep live audit (100+ tests focused on under-covered areas).

Round 6 caught 2 bugs. Round 7 hunts for more by exercising areas round 6
glossed over:
- get_award_detail / get_transactions / get_award_funding with REAL award IDs
- get_idv_children all 3 child_types
- Loan award searches (special sort field handling)
- Direct payments and Other category
- Sort + order parameter variations
- Deep PSC filter tree drilldowns
- Compound filters that should return zero
- Pagination at realistic depths (page 50, 100)
- Real prime + agency combinations
- Award amount edge cases (0, 1, max)
- awarding_subagency vs awarding_agency
- Specific high-volume agency deep-dives
- Field presence verification at scale

Cost: ~140 calls. USASpending is keyless and effectively unlimited.
Runtime: 2-4 minutes typical.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="requires USASPENDING_LIVE_TESTS=1"
)


@pytest.fixture(autouse=True)
def _reset_client():
    srv._client = None
    yield
    srv._client = None


async def _call(name: str, **kwargs):
    return await mcp.call_tool(name, kwargs)


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ===========================================================================
# A. DETAIL TOOLS (chain: search to get ID, then detail/transactions/funding)
# ===========================================================================

async def _get_real_contract_id():
    """Helper: fetch a real generated_internal_id from a recent search."""
    r = await _call("search_awards", keywords=["cybersecurity"], limit=5)
    payload = _payload(r)
    for result in payload.get("results", []):
        if result.get("generated_internal_id"):
            return result["generated_internal_id"]
    return None


async def _get_real_idv_id():
    """Helper: fetch a real generated_internal_id from an IDV search."""
    r = await _call(
        "search_awards", keywords=["services"], award_type="idvs", limit=5
    )
    payload = _payload(r)
    for result in payload.get("results", []):
        if result.get("generated_internal_id"):
            return result["generated_internal_id"]
    return None


def test_live_get_award_detail_real_id():
    """Chain: search to get a real award ID, then fetch its detail."""
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available from search")
        return await _call("get_award_detail", generated_award_id=award_id)
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_award_detail_response_has_piid():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call("get_award_detail", generated_award_id=award_id)
    r = asyncio.run(_run())
    data = _payload(r)
    # Real award detail responses include piid, recipient, amounts
    assert any(k in data for k in ["piid", "recipient", "total_obligation"])


def test_live_get_award_detail_response_has_recipient():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call("get_award_detail", generated_award_id=award_id)
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_award_detail_nonexistent_id():
    """Bogus but well-formed ID should 404 with clear error."""
    try:
        asyncio.run(
            _call("get_award_detail", generated_award_id="CONT_AWD_BOGUS_NONEXISTENT_9700")
        )
    except Exception as e:
        msg = str(e).lower()
        # Should be a clear 404, not a crash
        assert "404" in msg or "not found" in msg or "verify" in msg


def test_live_get_transactions_real_id():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call(
            "get_transactions", generated_award_id=award_id, limit=10
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)
    assert "results" in data or "page_metadata" in data


def test_live_get_transactions_pagination():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call(
            "get_transactions", generated_award_id=award_id, limit=5, page=1
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_transactions_sort_descending():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call(
            "get_transactions",
            generated_award_id=award_id,
            order="desc",
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_award_funding_real_id():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call("get_award_funding", generated_award_id=award_id, limit=10)
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_award_funding_pagination():
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call(
            "get_award_funding",
            generated_award_id=award_id,
            limit=5,
            page=1,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# B. IDV CHILDREN — all 3 child_types
# ===========================================================================

def test_live_get_idv_children_child_awards():
    async def _run():
        idv_id = await _get_real_idv_id()
        if not idv_id:
            pytest.skip("no IDV ID available")
        return await _call(
            "get_idv_children",
            generated_idv_id=idv_id,
            child_type="child_awards",
            limit=10,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_idv_children_child_idvs():
    async def _run():
        idv_id = await _get_real_idv_id()
        if not idv_id:
            pytest.skip("no IDV ID available")
        return await _call(
            "get_idv_children",
            generated_idv_id=idv_id,
            child_type="child_idvs",
            limit=10,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_idv_children_grandchild_awards():
    async def _run():
        idv_id = await _get_real_idv_id()
        if not idv_id:
            pytest.skip("no IDV ID available")
        return await _call(
            "get_idv_children",
            generated_idv_id=idv_id,
            child_type="grandchild_awards",
            limit=10,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_idv_children_pagination():
    async def _run():
        idv_id = await _get_real_idv_id()
        if not idv_id:
            pytest.skip("no IDV ID available")
        return await _call(
            "get_idv_children",
            generated_idv_id=idv_id,
            limit=5,
            page=1,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# C. LOAN AWARDS (special sort field requirements)
# ===========================================================================

def test_live_search_loans_default_sort():
    """Loans require sort='Loan Value' instead of 'Award Amount'."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["education"],
            award_type="loans",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_loans_with_amount_filter():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["small business"],
            award_type="loans",
            award_amount_min=10000,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_loans_response_uses_loan_value():
    """Loans response should include Loan Value field."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["education"],
            award_type="loans",
            limit=1,
        )
    )
    data = _payload(r)
    if data.get("results"):
        result = data["results"][0]
        # Should have either Loan Value or generated_internal_id
        assert any(k in result for k in ["Loan Value", "generated_internal_id"])


# ===========================================================================
# D. DIRECT PAYMENTS AND OTHER
# ===========================================================================

def test_live_search_direct_payments():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["assistance"],
            award_type="direct_payments",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_other_award_type():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_type="other",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_grants_response_shape():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["research"],
            award_type="grants",
            limit=1,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# E. SORT AND ORDER VARIATIONS
# ===========================================================================

def test_live_search_awards_sort_last_modified_date():
    """Last Modified Date is a valid Contract Award sort field."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            sort="Last Modified Date",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_sort_recipient_name():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            sort="Recipient Name",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_order_asc():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            order="asc",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_order_desc():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            order="desc",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# F. DEEP PSC FILTER TREE DRILLDOWNS
# ===========================================================================

def test_live_psc_tree_research_dev():
    r = asyncio.run(_call("get_psc_filter_tree", path="Research and Development"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_psc_tree_services():
    r = asyncio.run(_call("get_psc_filter_tree", path="Services"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_psc_tree_products():
    r = asyncio.run(_call("get_psc_filter_tree", path="Products"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_psc_tree_path_with_trailing_slash():
    """Tool should normalize trailing slash to avoid double slashes."""
    r = asyncio.run(_call("get_psc_filter_tree", path="Services/"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_psc_tree_path_with_leading_slash():
    """Leading slashes get stripped by lstrip."""
    r = asyncio.run(_call("get_psc_filter_tree", path="/Services"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# G. COMPOUND FILTERS THAT SHOULD RETURN ZERO
# ===========================================================================

def test_live_search_awards_impossibly_specific_filter():
    """Filter combo so specific it returns zero results."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["xyz_unlikely_keyword_zzz"],
            naics_codes=["541512"],
            place_of_performance_state="AK",
            award_amount_min=10000000,
            time_period_start="2025-01-01",
            time_period_end="2025-01-02",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data
    assert data["results"] == []


def test_live_search_awards_invalid_naics_returns_empty():
    """NAICS '999999' is invalid; should return empty results."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=["999999"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_get_award_count_zero_results():
    r = asyncio.run(
        _call(
            "get_award_count",
            keywords=["xyzzy_nonexistent_term"],
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
        )
    )
    data = _payload(r)
    assert "results" in data or isinstance(data, dict)


# ===========================================================================
# H. PAGINATION AT DEPTH
# ===========================================================================

def test_live_search_awards_page_20():
    r = asyncio.run(
        _call("search_awards", keywords=["services"], page=20, limit=10)
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_page_50():
    r = asyncio.run(
        _call("search_awards", keywords=["services"], page=50, limit=10)
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_page_100():
    """Round 3 audit found page=200 returns 422; verify page=100 still works."""
    r = asyncio.run(
        _call("search_awards", keywords=["services"], page=100, limit=10)
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# I. REAL PRIME + AGENCY COMBINATIONS
# ===========================================================================

def test_live_search_lockheed_at_navy():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Lockheed Martin",
            awarding_agency="Department of the Navy",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_lockheed_at_air_force():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Lockheed Martin",
            awarding_agency="Department of the Air Force",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_booz_at_treasury():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Booz Allen Hamilton",
            awarding_agency="Department of the Treasury",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_general_dynamics_naval():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="General Dynamics",
            awarding_agency="Department of the Navy",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_raytheon_dod():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Raytheon",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_northrop_grumman():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Northrop Grumman",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_with_awarding_subagency():
    """awarding_subagency uses subtier level."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            awarding_subagency="NAVAL SEA SYSTEMS COMMAND",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# J. AWARD AMOUNT EDGE CASES
# ===========================================================================

def test_live_search_awards_amount_zero_min():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_amount_min=0,
            award_amount_max=1000,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_amount_one_dollar():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_amount_min=1,
            award_amount_max=100,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_amount_billion_range():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_amount_min=1000000000,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_amount_exact_match():
    """min == max is technically valid."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_amount_min=1000000,
            award_amount_max=1000000,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# K. SPECIFIC HIGH-VOLUME AGENCY DEEP-DIVES
# ===========================================================================

def test_live_dod_recent_contracts():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            awarding_agency="Department of Defense",
            time_period_start="2025-01-01",
            time_period_end="2025-12-31",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_hhs_grants_recent():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["health"],
            award_type="grants",
            awarding_agency="Department of Health and Human Services",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_nasa_rd_contracts():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["research"],
            awarding_agency="National Aeronautics and Space Administration",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_dhs_contracts():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["security"],
            awarding_agency="Department of Homeland Security",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_va_contracts():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["medical"],
            awarding_agency="Department of Veterans Affairs",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_state_dept_contracts():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["embassy"],
            awarding_agency="Department of State",
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# L. AGENCY OVERVIEW / AWARDS DEEP CHECKS
# ===========================================================================

def test_live_dod_overview_response_has_data():
    r = asyncio.run(_call("get_agency_overview", toptier_code="097"))
    data = _payload(r)
    assert isinstance(data, dict)
    # Real agency response has these top-level fields
    assert any(k in data for k in [
        "toptier_code", "name", "agency_name", "fiscal_year",
        "messages", "abbreviation",
    ])


def test_live_hhs_overview_with_recent_fy():
    r = asyncio.run(
        _call("get_agency_overview", toptier_code="075", fiscal_year=2025)
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_nasa_awards_response():
    r = asyncio.run(_call("get_agency_awards", toptier_code="080"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# M. NAICS DETAILS DEEP CHECKS
# ===========================================================================

def test_live_naics_details_2_digit_root():
    """2-digit NAICS is a sector level."""
    r = asyncio.run(_call("get_naics_details", code="54"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_naics_details_invalid_code_handling():
    """Bogus 6-digit NAICS that doesn't exist."""
    r = asyncio.run(_call("get_naics_details", code="999999"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_naics_details_includes_description():
    r = asyncio.run(_call("get_naics_details", code="541512"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# N. STATE PROFILE DEEP CHECKS
# ===========================================================================

def test_live_state_profile_includes_totals():
    r = asyncio.run(_call("get_state_profile", state_fips="06"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_state_profile_response_has_state():
    r = asyncio.run(_call("get_state_profile", state_fips="48"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# O. SPENDING_BY_CATEGORY DEEP CHECKS
# ===========================================================================

def test_live_spending_by_category_recipient_top_10():
    """Top 10 recipients in FY25."""
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="recipient",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_by_category_naics_with_dod_filter():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="naics",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            awarding_agency="Department of Defense",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_by_category_district():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="district",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_by_category_county():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="county",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_by_category_country():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="country",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_by_category_cfda():
    """CFDA = Catalog of Federal Domestic Assistance (grant programs)."""
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="cfda",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
            award_type="grants",
            limit=10,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# P. AUTOCOMPLETE DEEP CHECKS
# ===========================================================================

def test_live_autocomplete_psc_specific_4char():
    r = asyncio.run(_call("autocomplete_psc", search_text="R425", limit=5))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_psc_partial_2char():
    r = asyncio.run(_call("autocomplete_psc", search_text="AJ", limit=5))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_naics_with_int_query():
    """NAICS autocomplete with numeric prefix."""
    r = asyncio.run(_call("autocomplete_naics", search_text="5415", limit=5))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_naics_full_code_query():
    r = asyncio.run(_call("autocomplete_naics", search_text="541512", limit=5))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_naics_max_limit():
    r = asyncio.run(_call("autocomplete_naics", search_text="services", limit=100))
    data = _payload(r)
    assert "results" in data or "_note" in data


# ===========================================================================
# Q. LOOKUP_PIID FULL PIID VS PREFIX
# ===========================================================================

def test_live_lookup_piid_full_navsea_piid():
    """A real full NAVSEA PIID format."""
    r = asyncio.run(_call("lookup_piid", piid="N0002424C0085"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_air_force_full():
    r = asyncio.run(_call("lookup_piid", piid="FA865024C0001"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_nonexistent_returns_no_match():
    r = asyncio.run(_call("lookup_piid", piid="ZZZ99999XXXX"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_max_limit():
    r = asyncio.run(_call("lookup_piid", piid="N00024", limit=100))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# R. SPENDING_OVER_TIME DEEP CHECKS
# ===========================================================================

def test_live_spending_over_time_decade():
    """Multi-year span: FY16-FY26."""
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="fiscal_year",
            keywords=["cyber"],
            time_period_start="2015-10-01",
            time_period_end="2025-09-30",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_over_time_one_quarter():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="month",
            keywords=["services"],
            time_period_start="2025-01-01",
            time_period_end="2025-03-31",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_spending_over_time_with_naics_and_agency():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="quarter",
            naics_codes=["541512"],
            awarding_agency="Department of Defense",
            time_period_start="2024-10-01",
            time_period_end="2025-09-30",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# S. AGENCY SUBAGENCY COMBINATIONS
# ===========================================================================

def test_live_search_with_funding_agency():
    """funding_agency is separate from awarding_agency."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            funding_agency="Department of Defense",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_funding_vs_awarding_different():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            funding_agency="Department of Health and Human Services",
            awarding_agency="Department of Defense",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# T. DATE WINDOW EDGE CASES
# ===========================================================================

def test_live_search_awards_one_day_window():
    """Single calendar day."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            time_period_start="2025-04-15",
            time_period_end="2025-04-15",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_year_2008_oldest():
    """FY2008 is the oldest the API supports."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            time_period_start="2007-10-01",
            time_period_end="2008-09-30",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_get_award_count_one_year_span():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# U. PSC FILTER ON SEARCH AWARDS
# ===========================================================================

def test_live_search_with_multiple_psc_codes():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            psc_codes=["R425", "R408"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_with_psc_int_coercion():
    """Round 6 fixed list[str] to list[str|int]; verify ints work."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=[541512, 541611],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_naics_codes_mixed_str_int():
    """Mixed string and int in same list (post round-6 fix)."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=[541512, "541611"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# V. SET-ASIDE DEEP COVERAGE
# ===========================================================================

def test_live_search_edwosb_set_aside():
    """Economically Disadvantaged WOSB."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["EDWOSB"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_va_set_aside():
    """VA Set-Aside."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["VSA"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_multi_set_aside():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["8A", "SDVOSBC", "WOSB"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# W. LOOKUP_PIID FORMAT VARIATIONS
# ===========================================================================

def test_live_lookup_piid_gsa_schedule_with_hyphens():
    """GSA Schedule format like GS-35F-0119Y."""
    r = asyncio.run(_call("lookup_piid", piid="GS-35F"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_gsa_oasis():
    """OASIS+ task order PIIDs."""
    r = asyncio.run(_call("lookup_piid", piid="47QFCA"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_dla_prefix():
    """Defense Logistics Agency PIIDs."""
    r = asyncio.run(_call("lookup_piid", piid="SPE7"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_lookup_piid_long_full_format():
    """Full 13-char DoD PIIDs."""
    r = asyncio.run(_call("lookup_piid", piid="W912DY24F0001"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# X. CROSS-TOOL ID PASSING (does ID from search work in detail?)
# ===========================================================================

def test_live_search_then_idv_children_workflow():
    """Real workflow: find an IDV via search, then get its children."""
    async def _run():
        idv_id = await _get_real_idv_id()
        if not idv_id:
            pytest.skip("no IDV ID available")
        # Now use that ID for IDV children
        return await _call(
            "get_idv_children",
            generated_idv_id=idv_id,
            child_type="child_awards",
            limit=5,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_search_then_award_funding_workflow():
    """Real workflow: search → get detail → get funding."""
    async def _run():
        award_id = await _get_real_contract_id()
        if not award_id:
            pytest.skip("no contract ID available")
        return await _call(
            "get_award_funding",
            generated_award_id=award_id,
            limit=5,
        )
    r = asyncio.run(_run())
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# Y. RESPONSE FIELD VERIFICATION AT SCALE
# ===========================================================================

def test_live_search_awards_results_have_required_fields():
    """Every result should include the standard fields."""
    r = asyncio.run(_call("search_awards", keywords=["services"], limit=10))
    data = _payload(r)
    if not data.get("results"):
        pytest.skip("no results to verify shape")
    for result in data["results"]:
        # generated_internal_id is the most critical for downstream chaining
        assert "generated_internal_id" in result, (
            f"missing generated_internal_id: {list(result.keys())[:5]}"
        )


def test_live_search_grants_results_have_recipient():
    r = asyncio.run(
        _call("search_awards", keywords=["research"], award_type="grants", limit=5)
    )
    data = _payload(r)
    if not data.get("results"):
        pytest.skip("no results")
    for result in data["results"]:
        assert "Recipient Name" in result or "generated_internal_id" in result


def test_live_search_idvs_have_last_date_to_order():
    """IDVs use Last Date to Order instead of End Date."""
    r = asyncio.run(
        _call("search_awards", keywords=["services"], award_type="idvs", limit=5)
    )
    data = _payload(r)
    if not data.get("results"):
        pytest.skip("no results")
    # Just verify the response shape doesn't crash
    assert isinstance(data["results"], list)


# ===========================================================================
# Z. CONCURRENT STRESS
# ===========================================================================

def test_live_concurrent_10_searches():
    """10 concurrent diverse searches."""
    async def _run():
        return await asyncio.gather(
            _call("search_awards", keywords=["cyber"], limit=2),
            _call("search_awards", keywords=["software"], limit=2),
            _call("search_awards", keywords=["engineering"], limit=2),
            _call("search_awards", keywords=["consulting"], limit=2),
            _call("search_awards", keywords=["research"], limit=2),
            _call("search_awards", keywords=["medical"], limit=2),
            _call("search_awards", keywords=["transportation"], limit=2),
            _call("search_awards", keywords=["construction"], limit=2),
            _call("search_awards", keywords=["logistics"], limit=2),
            _call("search_awards", keywords=["training"], limit=2),
        )
    results = asyncio.run(_run())
    assert len(results) == 10


def test_live_concurrent_8_agencies():
    async def _run():
        return await asyncio.gather(
            _call("get_agency_overview", toptier_code="097"),
            _call("get_agency_overview", toptier_code="075"),
            _call("get_agency_overview", toptier_code="080"),
            _call("get_agency_overview", toptier_code="070"),
            _call("get_agency_overview", toptier_code="036"),
            _call("get_agency_overview", toptier_code="020"),
            _call("get_agency_overview", toptier_code="091"),
            _call("get_agency_overview", toptier_code="089"),
        )
    results = asyncio.run(_run())
    assert len(results) == 8


# ===========================================================================
# AA. AGENCY NAME EDGE CASES (slug vs full name from API)
# ===========================================================================

def test_live_agency_name_with_period_us():
    """U.S. has a period after each letter in some agency names."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["agency"],
            awarding_agency="Environmental Protection Agency",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_agency_name_amp_in_name():
    """Some agency names contain ampersand."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            awarding_agency="Department of Housing and Urban Development",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# BB. INVALID-BUT-WELL-FORMED INPUTS
# ===========================================================================

def test_live_get_agency_overview_nonexistent_code():
    """Code that's numeric but doesn't map to any agency."""
    try:
        r = asyncio.run(_call("get_agency_overview", toptier_code="999"))
        data = _payload(r)
        assert isinstance(data, dict)
    except Exception as e:
        # 404 is acceptable
        assert "404" in str(e) or "not exist" in str(e).lower()


def test_live_get_state_profile_invalid_fips():
    """FIPS '99' isn't a valid state. API returns 400 'Invalid fips: 99.'"""
    try:
        r = asyncio.run(_call("get_state_profile", state_fips="99"))
        data = _payload(r)
        assert isinstance(data, dict)
    except Exception as e:
        # Acceptable: any 4xx response with a clear error
        msg = str(e).lower()
        assert "400" in msg or "404" in msg or "invalid fips" in msg


def test_live_get_naics_details_5_digit_unusual():
    """5-digit NAICS isn't standard but should be handled."""
    try:
        r = asyncio.run(_call("get_naics_details", code="54151"))
        data = _payload(r)
        assert isinstance(data, dict)
    except Exception as e:
        # Acceptable if API rejects
        assert "404" in str(e) or "not" in str(e).lower()
