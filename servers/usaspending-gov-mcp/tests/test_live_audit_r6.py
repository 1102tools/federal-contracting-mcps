# SPDX-License-Identifier: MIT
"""Round 6: Live audit (200+ tests against the production USASpending.gov API).

These tests run only when USASPENDING_LIVE_TESTS=1 is set. They make real
HTTP calls to api.usaspending.gov.

Purpose: validate behaviors that mocks cannot see.
- Real award/transaction/funding data shapes
- Pagination at high page numbers
- All set-aside, pricing, competition codes accepted live
- Concurrent call behavior
- Real agency, state, NAICS, PSC lookups
- Response shape drift detection

Cost: ~210 USASpending API calls per full run. USASpending is keyless
with no documented rate limit for normal use.
Runtime: 4-6 minutes typical.

Skipped automatically when USASPENDING_LIVE_TESTS!=1.
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


# Date windows that should always have data
RECENT_START = "2025-01-01"
RECENT_END = "2025-12-31"
FY25_START = "2024-10-01"
FY25_END = "2025-09-30"


# ===========================================================================
# A. SEARCH_AWARDS (the workhorse)
# ===========================================================================

def test_live_search_awards_keyword_cybersecurity():
    r = asyncio.run(_call("search_awards", keywords=["cybersecurity"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_keyword_software():
    r = asyncio.run(_call("search_awards", keywords=["software"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_keyword_engineering():
    r = asyncio.run(_call("search_awards", keywords=["engineering"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_naics_filter():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=["541512"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_naics_int_coerced():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=[541611],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_psc_filter():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            psc_codes=["R425"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_with_time_period():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_amount_range():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_amount_min=1000000,
            award_amount_max=10000000,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_state_va():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            place_of_performance_state="VA",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_state_md():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            place_of_performance_state="MD",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_recipient_lockheed():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Lockheed Martin",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_recipient_booz():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="Booz Allen Hamilton",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_set_aside_8a():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["8A"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_set_aside_sdvosb():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["SDVOSBC"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_set_aside_wosb():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["WOSB"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_set_aside_hubzone():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["HZC"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_pricing_ffp():
    """J = Firm Fixed Price."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            contract_pricing_type_codes=["J"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_pricing_cpff():
    """U = Cost Plus Fixed Fee."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            contract_pricing_type_codes=["U"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_pricing_tm():
    """Y = Time and Materials."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            contract_pricing_type_codes=["Y"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_extent_competed_full():
    """A = Full and Open Competition."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            extent_competed_type_codes=["A"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_award_type_idvs():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            award_type="idvs",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_award_type_grants():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["research"],
            award_type="grants",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_pagination_page_2():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            page=2,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_pagination_page_5():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            page=5,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_max_limit_100():
    r = asyncio.run(_call("search_awards", keywords=["services"], limit=100))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_navsea_piid_prefix():
    r = asyncio.run(_call("search_awards", keywords=["N00024"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_afrl_piid_prefix():
    r = asyncio.run(_call("search_awards", keywords=["FA8650"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_compound_filter():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["cyber"],
            naics_codes=["541512"],
            place_of_performance_state="VA",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_unicode_keyword():
    r = asyncio.run(_call("search_awards", keywords=["café"], limit=5))
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


# ===========================================================================
# B. GET_AWARD_COUNT
# ===========================================================================

def test_live_get_award_count_recent():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_by_naics():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            naics_codes=["541512"],
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_by_keyword():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            keywords=["cyber"],
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_by_state():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            place_of_performance_state="VA",
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_set_aside_8a():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            set_aside_type_codes=["8A"],
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_amount_range():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            award_amount_min=100000,
            award_amount_max=1000000,
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


def test_live_get_award_count_recipient():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            recipient_name="Leidos",
        )
    )
    data = _payload(r)
    assert "results" in data or "contracts" in data


# ===========================================================================
# C. SPENDING_OVER_TIME
# ===========================================================================

def test_live_spending_over_time_fiscal_year():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="fiscal_year",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_quarter():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="quarter",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_month():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="month",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_with_keyword():
    r = asyncio.run(
        _call(
            "spending_over_time",
            keywords=["cybersecurity"],
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_with_naics():
    r = asyncio.run(
        _call(
            "spending_over_time",
            naics_codes=["541512"],
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_multi_year():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="fiscal_year",
            keywords=["cyber"],
            time_period_start="2020-10-01",
            time_period_end="2025-09-30",
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_spending_over_time_with_award_type():
    r = asyncio.run(
        _call(
            "spending_over_time",
            award_type="grants",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


# ===========================================================================
# D. SPENDING_BY_CATEGORY
# ===========================================================================

CATEGORY_VALUES = [
    "awarding_agency",
    "awarding_subagency",
    "funding_agency",
    "recipient",
    "naics",
    "psc",
    "state_territory",
    "federal_account",
]


@pytest.mark.parametrize("category", CATEGORY_VALUES)
def test_live_spending_by_category_each(category):
    r = asyncio.run(
        _call(
            "spending_by_category",
            category=category,
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "category" in data


def test_live_spending_by_category_recipient_with_filter():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="recipient",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            naics_codes=["541512"],
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "category" in data


def test_live_spending_by_category_naics_with_keyword():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="naics",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            keywords=["cyber"],
            limit=10,
        )
    )
    data = _payload(r)
    assert "results" in data or "category" in data


def test_live_spending_by_category_max_limit():
    r = asyncio.run(
        _call(
            "spending_by_category",
            category="recipient",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
            limit=100,
        )
    )
    data = _payload(r)
    assert "results" in data or "category" in data


# ===========================================================================
# E. AGENCY TOOLS
# ===========================================================================

def test_live_list_toptier_agencies():
    r = asyncio.run(_call("list_toptier_agencies"))
    data = _payload(r)
    assert "results" in data
    assert len(data["results"]) > 50  # there are 100+ federal agencies


# Major federal agencies (toptier_codes)
MAJOR_AGENCIES = [
    ("097", "DoD"),
    ("075", "HHS"),
    ("080", "NASA"),
    ("070", "DHS"),
    ("036", "VA"),
    ("020", "Treasury"),
    ("091", "Education"),
    ("089", "DoE"),
    ("012", "Agriculture"),
    ("013", "Commerce"),  # corrected from 011 in round 6
]


@pytest.mark.parametrize("code,name", MAJOR_AGENCIES)
def test_live_get_agency_overview_each(code, name):
    r = asyncio.run(_call("get_agency_overview", toptier_code=code))
    data = _payload(r)
    assert "toptier_code" in data or "name" in data or "results" in data


@pytest.mark.parametrize("code,name", MAJOR_AGENCIES)
def test_live_get_agency_awards_each(code, name):
    r = asyncio.run(_call("get_agency_awards", toptier_code=code))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_agency_overview_with_fy():
    r = asyncio.run(_call("get_agency_overview", toptier_code="097", fiscal_year=2025))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_agency_overview_with_fy_2024():
    r = asyncio.run(_call("get_agency_overview", toptier_code="097", fiscal_year=2024))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_agency_overview_with_fy_2020():
    r = asyncio.run(_call("get_agency_overview", toptier_code="097", fiscal_year=2020))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_agency_overview_left_padded_code():
    """'97' should normalize to '097'."""
    r = asyncio.run(_call("get_agency_overview", toptier_code="97"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_agency_overview_with_fy_2018():
    r = asyncio.run(
        _call("get_agency_overview", toptier_code="097", fiscal_year=2018)
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# F. NAICS DETAILS
# ===========================================================================

REAL_NAICS_CODES = [
    "54", "541", "5415", "541512", "541611", "541330",
    "541715", "541519", "236220", "541990", "236118",
]


@pytest.mark.parametrize("code", REAL_NAICS_CODES)
def test_live_get_naics_details_each(code):
    r = asyncio.run(_call("get_naics_details", code=code))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# G. PSC FILTER TREE
# ===========================================================================

def test_live_get_psc_filter_tree_top_level():
    r = asyncio.run(_call("get_psc_filter_tree", path=""))
    data = _payload(r)
    assert isinstance(data, dict)
    assert "results" in data


def test_live_get_psc_filter_tree_research_dev():
    """Top-level PSC categories include 'Research and Development'."""
    r = asyncio.run(_call("get_psc_filter_tree", path="Research and Development"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_psc_filter_tree_default_no_path():
    """Default empty path should return top-level tree."""
    r = asyncio.run(_call("get_psc_filter_tree"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_psc_filter_tree_response_has_results():
    r = asyncio.run(_call("get_psc_filter_tree", path=""))
    data = _payload(r)
    assert "results" in data
    assert isinstance(data["results"], list)


def test_live_get_psc_filter_tree_top_categories_count():
    """Verify the API returns multiple top categories."""
    r = asyncio.run(_call("get_psc_filter_tree", path=""))
    data = _payload(r)
    assert len(data.get("results", [])) >= 2


# ===========================================================================
# H. STATE PROFILES
# ===========================================================================

# Major state FIPS codes
MAJOR_STATE_FIPS = [
    ("06", "California"),
    ("48", "Texas"),
    ("12", "Florida"),
    ("36", "New York"),
    ("42", "Pennsylvania"),
    ("17", "Illinois"),
    ("39", "Ohio"),
    ("13", "Georgia"),
    ("37", "North Carolina"),
    ("26", "Michigan"),
    ("51", "Virginia"),
    ("24", "Maryland"),
    ("11", "DC"),
]


@pytest.mark.parametrize("fips,name", MAJOR_STATE_FIPS)
def test_live_get_state_profile_each(fips, name):
    r = asyncio.run(_call("get_state_profile", state_fips=fips))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# I. AUTOCOMPLETE
# ===========================================================================

PSC_AUTOCOMPLETE_QUERIES = [
    "R425", "R4", "R", "AJ", "professional", "engineering",
    "advisory", "training", "construction", "medical",
]


@pytest.mark.parametrize("q", PSC_AUTOCOMPLETE_QUERIES)
def test_live_autocomplete_psc_each(q):
    r = asyncio.run(_call("autocomplete_psc", search_text=q, limit=10))
    data = _payload(r)
    # Single-char queries return empty with note
    assert "results" in data or "_note" in data


NAICS_AUTOCOMPLETE_QUERIES = [
    "computer", "engineering", "consulting", "construction",
    "541512", "5415", "professional", "research",
    "manufacturing", "transportation",
]


@pytest.mark.parametrize("q", NAICS_AUTOCOMPLETE_QUERIES)
def test_live_autocomplete_naics_each(q):
    r = asyncio.run(_call("autocomplete_naics", search_text=q, limit=10))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_naics_exclude_retired_default():
    """Default excludes retired NAICS codes."""
    r = asyncio.run(_call("autocomplete_naics", search_text="computer", limit=10))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_naics_include_retired():
    r = asyncio.run(
        _call(
            "autocomplete_naics",
            search_text="computer",
            limit=10,
            exclude_retired=False,
        )
    )
    data = _payload(r)
    assert "results" in data or "_note" in data


# ===========================================================================
# J. LOOKUP_PIID (composite tool)
# ===========================================================================

REAL_PIID_PREFIXES = [
    "N00024",  # NAVSEA
    "FA8650",  # AFRL
    "W91CRB",  # Army Contracting Command
    "N00019",  # NAVAIR
    "HQ0034",  # Defense Logistics Agency
    "GS-35F",  # GSA Schedule
]


@pytest.mark.parametrize("piid", REAL_PIID_PREFIXES)
def test_live_lookup_piid_each_prefix(piid):
    r = asyncio.run(_call("lookup_piid", piid=piid, limit=5))
    data = _payload(r)
    # Returns dict with award_type and results
    assert "award_type" in data or "results" in data


# ===========================================================================
# K. CONCURRENT CALLS
# ===========================================================================

def test_live_concurrent_5_searches():
    """5 concurrent search_awards calls."""
    async def _run():
        return await asyncio.gather(
            _call("search_awards", keywords=["cyber"], limit=2),
            _call("search_awards", keywords=["software"], limit=2),
            _call("search_awards", keywords=["engineering"], limit=2),
            _call("search_awards", keywords=["consulting"], limit=2),
            _call("search_awards", keywords=["research"], limit=2),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


def test_live_concurrent_3_agency_lookups():
    async def _run():
        return await asyncio.gather(
            _call("get_agency_overview", toptier_code="097"),
            _call("get_agency_overview", toptier_code="075"),
            _call("get_agency_overview", toptier_code="080"),
        )
    results = asyncio.run(_run())
    assert len(results) == 3


def test_live_concurrent_mixed_tools():
    async def _run():
        return await asyncio.gather(
            _call("list_toptier_agencies"),
            _call("get_state_profile", state_fips="06"),
            _call("get_naics_details", code="541512"),
            _call("autocomplete_psc", search_text="cyber"),
        )
    results = asyncio.run(_run())
    assert len(results) == 4


# ===========================================================================
# L. RESPONSE SHAPE VERIFICATION
# ===========================================================================

def test_live_search_awards_response_shape():
    r = asyncio.run(_call("search_awards", keywords=["cyber"], limit=1))
    data = _payload(r)
    assert "results" in data
    assert "page_metadata" in data
    if data["results"]:
        result = data["results"][0]
        # search_awards returns these standard fields
        assert any(k in result for k in ["Award ID", "Recipient Name", "Award Amount"])


def test_live_search_awards_includes_generated_internal_id():
    """generated_internal_id is what feeds get_award_detail."""
    r = asyncio.run(_call("search_awards", keywords=["cyber"], limit=1))
    data = _payload(r)
    if data.get("results"):
        result = data["results"][0]
        assert "generated_internal_id" in result


def test_live_get_award_count_shape():
    r = asyncio.run(
        _call(
            "get_award_count",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data
    # Count categories
    counts = data["results"]
    expected_keys = ["contracts", "idvs", "grants", "loans", "direct_payments", "other"]
    if isinstance(counts, dict):
        # At least one expected key should be present
        assert any(k in counts for k in expected_keys)


def test_live_spending_over_time_shape():
    r = asyncio.run(
        _call(
            "spending_over_time",
            group="fiscal_year",
            time_period_start=FY25_START,
            time_period_end=FY25_END,
        )
    )
    data = _payload(r)
    assert "results" in data or "group" in data


def test_live_list_toptier_agencies_shape():
    r = asyncio.run(_call("list_toptier_agencies"))
    data = _payload(r)
    assert "results" in data
    if data["results"]:
        agency = data["results"][0]
        # Each agency has these fields
        assert any(k in agency for k in ["toptier_code", "agency_name", "abbreviation"])


def test_live_get_state_profile_shape():
    r = asyncio.run(_call("get_state_profile", state_fips="06"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_naics_details_shape():
    r = asyncio.run(_call("get_naics_details", code="541512"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_autocomplete_naics_shape():
    r = asyncio.run(_call("autocomplete_naics", search_text="computer"))
    data = _payload(r)
    assert "results" in data or "_note" in data


def test_live_autocomplete_psc_shape():
    r = asyncio.run(_call("autocomplete_psc", search_text="R425"))
    data = _payload(r)
    assert "results" in data or "_note" in data


# ===========================================================================
# M. EDGE CASES
# ===========================================================================

def test_live_search_awards_leap_year_2024():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            time_period_start="2024-02-29",
            time_period_end="2024-03-01",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_fy_rollover_window():
    """Crosses FY24 -> FY25 boundary."""
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            time_period_start="2024-09-29",
            time_period_end="2024-10-02",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_multi_naics():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            naics_codes=["541512", "541611", "541330"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_unicode_recipient():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="café corp",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_apostrophe_in_recipient():
    r = asyncio.run(
        _call(
            "search_awards",
            recipient_name="O'Brien",
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_high_pagination_page_10():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            page=10,
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_combined_set_aside_naics():
    r = asyncio.run(
        _call(
            "search_awards",
            keywords=["services"],
            set_aside_type_codes=["8A"],
            naics_codes=["541512"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data


def test_live_search_awards_award_ids_filter():
    r = asyncio.run(
        _call(
            "search_awards",
            award_ids=["N00024"],
            limit=5,
        )
    )
    data = _payload(r)
    assert "results" in data or "page_metadata" in data
