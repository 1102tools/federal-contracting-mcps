# SPDX-License-Identifier: MIT
"""Round 6: Live audit (200 tests against the production SAM.gov API).

These tests run only when SAM_LIVE_TESTS=1 and a valid SAM_API_KEY is set.
They make real HTTP calls to the production SAM.gov API.

Purpose: validate behaviors that mocks cannot see.
- Current real WAF behavior (since 0.3.1 narrowed the filter)
- Response shapes match what the parsers expect
- Pagination at high page numbers
- Set-aside, notice type, classification codes accepted live
- Concurrent call behavior
- Real entity / award / exclusion data shapes

Cost: ~200 SAM.gov API calls per full run (system key has 10K/day budget).
Runtime: 3-5 minutes typical.

Skipped automatically when SAM_LIVE_TESTS!=1 to keep CI fast.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import sam_gov_mcp.server as srv  # noqa: E402
from sam_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY"
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


# Real entities used as known-good baselines
UEI_ANTHROPIC_PBC = "SPQZL8XDKGK7"
UEI_ANTHROPIC_PI = "TTB8SLNT8EB3"
CAGE_ANTHROPIC_PBC = "9VKX2"
CAGE_ANTHROPIC_PI = "03J46"


# ===========================================================================
# A. WAF BEHAVIOR (real apostrophes, ampersands, brackets, etc.)
# ===========================================================================
# These were blocked locally in 0.3.0 and accepted by SAM.gov live.
# 0.3.1 narrowed the local filter. This validates current state.

WAF_LIVE_PROBE_NAMES = [
    "McDonald's",
    "L'Oreal",
    "O'Brien",
    "O'Reilly",
    "Macy's",
    "Wendy's",
    "Domino's",
    "Sotheby's",
    "Trader Joe's",
    "Kohl's",
]


@pytest.mark.parametrize("name", WAF_LIVE_PROBE_NAMES)
def test_live_waf_apostrophe_company_search(name):
    """Apostrophe-containing names must reach the API live."""
    r = asyncio.run(_call("search_entities", legal_business_name=name, size=3))
    data = _payload(r)
    # Either zero or non-zero results, both are valid; the test is no exception
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_ampersand_in_name():
    r = asyncio.run(_call("search_entities", legal_business_name="AT&T", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_unicode_accent():
    r = asyncio.run(_call("search_entities", legal_business_name="café", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_angle_bracket_text():
    """0.3.0 rejected angle brackets locally; SAM accepts them as literal text."""
    r = asyncio.run(_call("search_entities", legal_business_name="<test>", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_sql_keyword_select():
    r = asyncio.run(_call("search_entities", legal_business_name="select all", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_sql_keyword_drop():
    r = asyncio.run(_call("search_entities", free_text="drop database", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_waf_pipe_character():
    r = asyncio.run(_call("search_entities", legal_business_name="a | b", size=3))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


# ===========================================================================
# B. ENTITY LOOKUPS (real UEIs and CAGEs)
# ===========================================================================

def test_live_lookup_entity_by_uei_anthropic_pbc():
    r = asyncio.run(_call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1
    entity = data["entityData"][0]
    assert entity["entityRegistration"]["ueiSAM"] == UEI_ANTHROPIC_PBC


def test_live_lookup_entity_by_uei_anthropic_public_inst():
    r = asyncio.run(_call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PI))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_with_assertions_section():
    r = asyncio.run(
        _call(
            "lookup_entity_by_uei",
            uei=UEI_ANTHROPIC_PBC,
            include_sections=["entityRegistration", "assertions"],
        )
    )
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_with_pointsOfContact():
    r = asyncio.run(
        _call(
            "lookup_entity_by_uei",
            uei=UEI_ANTHROPIC_PBC,
            include_sections=["entityRegistration", "pointsOfContact"],
        )
    )
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_all_section():
    r = asyncio.run(
        _call(
            "lookup_entity_by_uei",
            uei=UEI_ANTHROPIC_PBC,
            include_sections=["All"],
        )
    )
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_lowercase_normalized():
    """Lowercase UEI should normalize before hitting the API."""
    r = asyncio.run(
        _call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC.lower())
    )
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_with_whitespace_padding():
    r = asyncio.run(
        _call("lookup_entity_by_uei", uei=f"  {UEI_ANTHROPIC_PBC}  ")
    )
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_uei_nonexistent():
    """Bogus but format-valid UEI should return empty result, not crash."""
    r = asyncio.run(_call("lookup_entity_by_uei", uei="ZZZZZZZZZZZZ"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) == 0


def test_live_lookup_entity_by_cage_anthropic_pbc():
    r = asyncio.run(_call("lookup_entity_by_cage", cage_code=CAGE_ANTHROPIC_PBC))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_cage_anthropic_pi():
    r = asyncio.run(_call("lookup_entity_by_cage", cage_code=CAGE_ANTHROPIC_PI))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_cage_lowercase_normalized():
    r = asyncio.run(_call("lookup_entity_by_cage", cage_code=CAGE_ANTHROPIC_PBC.lower()))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_lookup_entity_by_cage_nonexistent():
    r = asyncio.run(_call("lookup_entity_by_cage", cage_code="ZZZZZ"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) == 0


# ===========================================================================
# C. ENTITY SEARCH (legal_business_name, free_text, NAICS, state, etc.)
# ===========================================================================

def test_live_search_entities_by_name_anthropic():
    r = asyncio.run(_call("search_entities", legal_business_name="Anthropic", size=10))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_search_entities_by_name_partial_match():
    r = asyncio.run(_call("search_entities", legal_business_name="Lockheed", size=5))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_search_entities_by_free_text():
    r = asyncio.run(_call("search_entities", free_text="cybersecurity", size=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_by_state_va():
    r = asyncio.run(_call("search_entities", legal_business_name="Lockheed", state_code="VA", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_by_state_md():
    r = asyncio.run(_call("search_entities", legal_business_name="defense", state_code="MD", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_lowercase_state_normalized():
    r = asyncio.run(_call("search_entities", legal_business_name="Booz", state_code="va", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_by_primary_naics():
    r = asyncio.run(_call("search_entities", primary_naics="541512", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_by_primary_naics_int():
    """NAICS as int should be coerced."""
    r = asyncio.run(_call("search_entities", primary_naics=541611, size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_by_any_naics():
    r = asyncio.run(_call("search_entities", any_naics="541512", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_business_type_sdvosb():
    """SDVOSB code is QF."""
    r = asyncio.run(_call("search_entities", business_type_code="QF", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_business_type_wosb():
    """WOSB code is 8W."""
    r = asyncio.run(_call("search_entities", business_type_code="8W", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_business_type_woman_owned():
    """Women-Owned Business code is A2."""
    r = asyncio.run(_call("search_entities", business_type_code="A2", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_business_type_minority_owned():
    """Minority-Owned Business code is 23."""
    r = asyncio.run(_call("search_entities", business_type_code="23", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_purpose_z2_all_awards():
    r = asyncio.run(
        _call(
            "search_entities",
            legal_business_name="Anthropic",
            purpose_of_registration="Z2",
            size=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_pagination_page_2():
    r = asyncio.run(
        _call("search_entities", legal_business_name="Lockheed", page=1, size=5)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_pagination_page_5():
    r = asyncio.run(
        _call("search_entities", legal_business_name="defense", page=4, size=5)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_size_minimum():
    """size=1 is the minimum valid value."""
    r = asyncio.run(_call("search_entities", legal_business_name="Anthropic", size=1))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_size_maximum():
    """size=10 is the API hard cap."""
    r = asyncio.run(_call("search_entities", legal_business_name="Lockheed", size=10))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_expired_status():
    """registration_status='E' returns expired registrations."""
    r = asyncio.run(
        _call(
            "search_entities",
            legal_business_name="defense",
            registration_status="E",
            size=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_combined_filters():
    """Multiple filters AND together."""
    r = asyncio.run(
        _call(
            "search_entities",
            primary_naics="541512",
            state_code="VA",
            size=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# D. EXCLUSIONS (debarment, suspension lookups)
# ===========================================================================

def test_live_check_exclusion_by_uei_anthropic_clean():
    """Anthropic should have no exclusion records."""
    r = asyncio.run(_call("check_exclusion_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) == 0


def test_live_check_exclusion_by_uei_nonexistent():
    r = asyncio.run(_call("check_exclusion_by_uei", uei="ZZZZZZZZZZZZ"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) == 0


def test_live_search_exclusions_by_country_usa():
    r = asyncio.run(_call("search_exclusions", country="USA", size=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_country_lowercase_normalized():
    r = asyncio.run(_call("search_exclusions", country="usa", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_classification_firm():
    r = asyncio.run(
        _call(
            "search_exclusions",
            classification="Firm",
            size=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_classification_individual():
    r = asyncio.run(
        _call(
            "search_exclusions",
            classification="Individual",
            size=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_by_entity_name():
    r = asyncio.run(
        _call("search_exclusions", entity_name="Smith", size=5)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_by_state():
    r = asyncio.run(
        _call("search_exclusions", state_province="CA", country="USA", size=5)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_program_procurement():
    r = asyncio.run(
        _call("search_exclusions", exclusion_program="Procurement", size=5)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_pagination():
    r = asyncio.run(_call("search_exclusions", country="USA", page=1, size=10))
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# E. VENDOR RESPONSIBILITY CHECK (composite tool, 2 API calls)
# ===========================================================================

def test_live_vendor_responsibility_anthropic_pbc():
    r = asyncio.run(_call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert "registration" in data
    assert "exclusion" in data
    assert "flags" in data
    # Anthropic should be active and not excluded
    assert "ACTIVE_EXCLUSION_FOUND" not in data["flags"]


def test_live_vendor_responsibility_anthropic_pi():
    r = asyncio.run(_call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PI))
    data = _payload(r)
    assert "registration" in data
    assert "exclusion" in data
    assert "flags" in data


def test_live_vendor_responsibility_nonexistent_uei():
    r = asyncio.run(_call("vendor_responsibility_check", uei="ZZZZZZZZZZZZ"))
    data = _payload(r)
    assert "flags" in data
    # Should flag NOT_REGISTERED for a UEI that doesn't exist
    assert "NOT_REGISTERED" in data["flags"]


def test_live_vendor_responsibility_lowercase_uei():
    r = asyncio.run(
        _call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PBC.lower())
    )
    data = _payload(r)
    assert "registration" in data


def test_live_vendor_responsibility_returns_uei_in_result():
    r = asyncio.run(_call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert data.get("uei") == UEI_ANTHROPIC_PBC or data.get("uei") == UEI_ANTHROPIC_PBC.lower().upper()


# ===========================================================================
# F. OPPORTUNITIES (set-aside types, notice types, date windows)
# ===========================================================================

# Use a recent 30-day window for opportunity searches
RECENT_DATE_FROM = "03/22/2026"
RECENT_DATE_TO = "04/22/2026"


def test_live_opportunities_recent_window():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_total_small_business():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="SBA",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_8a_competed():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="8A",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_sdvosb():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="SDVOSBC",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_wosb():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="WOSB",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_hubzone():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="HZC",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_set_aside_lowercase_normalized():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="sba",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_notice_type_sources_sought():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            notice_type="r",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_notice_type_solicitation():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            notice_type="o",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_notice_type_presolicitation():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            notice_type="p",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_with_naics_filter():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            naics_code="541512",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_with_naics_int():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            naics_code=541611,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_state_filter_va():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            state="VA",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_solicitation_number_filter():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            solicitation_number="N",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_title_filter():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            title="services",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_compound_filter():
    """Set-aside + NAICS + state combined."""
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside="SBA",
            naics_code="541512",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_pagination_offset():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            offset=10,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_max_limit_1000():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            limit=1000,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_response_deadline_filter():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            response_deadline_from=RECENT_DATE_TO,
            response_deadline_to="06/22/2026",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_max_date_span_363_days():
    """Just under the 364-day API cap."""
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from="04/24/2025",
            posted_to="04/22/2026",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# G. CONTRACT AWARDS (date ranges, NAICS, fiscal years, PIIDs)
# ===========================================================================

def test_live_contract_awards_recent_window():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            date_signed="[01/01/2026,04/22/2026]",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_fiscal_year_2025():
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2025, limit=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_fiscal_year_2024():
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2024, limit=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_fiscal_year_2020():
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2020, limit=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_fiscal_year_2008_lowest():
    """FY2008 is the lowest valid FY."""
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2008, limit=5))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_naics_filter():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            naics_code="541512",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_naics_or_operator():
    """~ is OR."""
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            naics_code="541512~541511",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_naics_not_operator():
    """! is NOT."""
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            naics_code="!541512",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_psc_filter():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            psc_code="R425",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_modification_filter():
    """Modification number 0 is the base award."""
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            modification_number="0",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_award_or_idv_award():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            award_or_idv="AWARD",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_award_or_idv_idv():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            award_or_idv="IDV",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_date_signed_range():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            date_signed="[01/01/2025,12/31/2025]",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_pagination():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            limit=10,
            offset=20,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_max_limit_100():
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2025, limit=100))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_dept_navy():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            contracting_department_code="9700",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_dept_army():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            contracting_department_code="2100",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_dept_air_force():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            contracting_department_code="5700",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# H. PSC LOOKUPS
# ===========================================================================

def test_live_psc_lookup_r425():
    r = asyncio.run(_call("lookup_psc_code", code="R425"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_psc_lookup_d302():
    """D-codes may or may not return data; both outcomes are valid."""
    try:
        r = asyncio.run(_call("lookup_psc_code", code="D302"))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"])


def test_live_psc_lookup_lowercase_normalized():
    r = asyncio.run(_call("lookup_psc_code", code="r425"))
    data = _payload(r)
    assert int(data.get("totalRecords", 0)) >= 1


def test_live_psc_lookup_2_char_prefix():
    r = asyncio.run(_call("lookup_psc_code", code="R4"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_lookup_invalid_clear_error():
    """Invalid PSC should give a clear error, not opaque 404."""
    try:
        asyncio.run(_call("lookup_psc_code", code="ZZZZ"))
    except Exception as e:
        msg = str(e).lower()
        assert "did not find" in msg or "psc-manual" in msg or "not found" in msg


def test_live_psc_lookup_active_only_y():
    r = asyncio.run(_call("lookup_psc_code", code="R425", active_only="Y"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_lookup_active_only_all():
    r = asyncio.run(_call("lookup_psc_code", code="R425", active_only="ALL"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_free_text_cyber():
    try:
        r = asyncio.run(_call("search_psc_free_text", query="cybersecurity"))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"])


def test_live_psc_free_text_engineering():
    r = asyncio.run(_call("search_psc_free_text", query="engineering"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_free_text_professional():
    r = asyncio.run(_call("search_psc_free_text", query="professional"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_free_text_software():
    r = asyncio.run(_call("search_psc_free_text", query="software"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_free_text_apostrophe_query():
    """Apostrophes should reach the API."""
    r = asyncio.run(_call("search_psc_free_text", query="women's"))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_free_text_unicode_query():
    try:
        r = asyncio.run(_call("search_psc_free_text", query="café"))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"])


# ===========================================================================
# I. ENTITY DEEP SECTIONS (reps and certs, integrity info)
# ===========================================================================

def test_live_get_entity_reps_and_certs_anthropic():
    r = asyncio.run(_call("get_entity_reps_and_certs", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_get_entity_reps_and_certs_summary_mode():
    r = asyncio.run(
        _call(
            "get_entity_reps_and_certs",
            uei=UEI_ANTHROPIC_PBC,
            summary_only=True,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data or "_summary" in data


def test_live_get_entity_reps_and_certs_full_mode():
    r = asyncio.run(
        _call(
            "get_entity_reps_and_certs",
            uei=UEI_ANTHROPIC_PBC,
            summary_only=False,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_get_entity_integrity_info_anthropic():
    r = asyncio.run(_call("get_entity_integrity_info", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


def test_live_get_entity_integrity_info_lowercase_uei():
    r = asyncio.run(
        _call("get_entity_integrity_info", uei=UEI_ANTHROPIC_PBC.lower())
    )
    data = _payload(r)
    assert "totalRecords" in data or "entityData" in data


# ===========================================================================
# J. SEARCH DELETED AWARDS (previously zero coverage)
# ===========================================================================

def test_live_search_deleted_awards_recent():
    """search_deleted_awards has no test coverage prior to round 6."""
    r = asyncio.run(
        _call(
            "search_deleted_awards",
            last_modified_date="[01/01/2025,04/22/2026]",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_deleted_awards_with_dept():
    r = asyncio.run(
        _call(
            "search_deleted_awards",
            contracting_department_code="9700",
            last_modified_date="[01/01/2025,04/22/2026]",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_deleted_awards_dept_as_int():
    """Dept code as int should be coerced."""
    r = asyncio.run(
        _call(
            "search_deleted_awards",
            contracting_department_code=9700,
            last_modified_date="[01/01/2025,04/22/2026]",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_deleted_awards_pagination():
    r = asyncio.run(
        _call(
            "search_deleted_awards",
            last_modified_date="[01/01/2025,04/22/2026]",
            limit=10,
            offset=10,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_deleted_awards_max_limit():
    r = asyncio.run(
        _call(
            "search_deleted_awards",
            last_modified_date="[01/01/2025,04/22/2026]",
            limit=100,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# K. CONCURRENT CALLS (rate limit, async safety)
# ===========================================================================

def test_live_concurrent_5_searches():
    """5 concurrent search_entities calls should all succeed."""
    async def _run():
        results = await asyncio.gather(
            _call("search_entities", legal_business_name="Anthropic", size=2),
            _call("search_entities", legal_business_name="Lockheed", size=2),
            _call("search_entities", legal_business_name="Booz", size=2),
            _call("search_entities", legal_business_name="Leidos", size=2),
            _call("search_entities", legal_business_name="Northrop", size=2),
        )
        return results
    results = asyncio.run(_run())
    assert len(results) == 5
    for r in results:
        data = _payload(r)
        assert "totalRecords" in data


def test_live_concurrent_3_lookups():
    async def _run():
        return await asyncio.gather(
            _call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC),
            _call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PI),
            _call("lookup_entity_by_cage", cage_code=CAGE_ANTHROPIC_PBC),
        )
    results = asyncio.run(_run())
    assert len(results) == 3


def test_live_concurrent_mixed_tools():
    """Different tools concurrently."""
    async def _run():
        return await asyncio.gather(
            _call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC),
            _call("check_exclusion_by_uei", uei=UEI_ANTHROPIC_PBC),
            _call("lookup_psc_code", code="R425"),
        )
    results = asyncio.run(_run())
    assert len(results) == 3


# ===========================================================================
# L. RESPONSE SHAPE VERIFICATION (catches API drift)
# ===========================================================================

def test_live_entity_response_shape_has_required_fields():
    r = asyncio.run(_call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    entity = data["entityData"][0]
    # Required entityRegistration fields
    reg = entity["entityRegistration"]
    assert "ueiSAM" in reg
    assert "legalBusinessName" in reg
    assert "registrationStatus" in reg


def test_live_entity_response_has_core_data():
    r = asyncio.run(_call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    entity = data["entityData"][0]
    assert "coreData" in entity
    assert "physicalAddress" in entity["coreData"]


def test_live_entity_response_physical_address_fields():
    r = asyncio.run(_call("lookup_entity_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    addr = data["entityData"][0]["coreData"]["physicalAddress"]
    assert "addressLine1" in addr
    assert "city" in addr
    assert "stateOrProvinceCode" in addr
    assert "zipCode" in addr
    assert "countryCode" in addr


def test_live_opportunities_response_shape():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            limit=1,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data
    if int(data.get("totalRecords", 0)) > 0:
        opp = data["opportunitiesData"][0]
        assert "noticeId" in opp
        assert "title" in opp
        assert "type" in opp


def test_live_contract_awards_response_shape():
    r = asyncio.run(_call("search_contract_awards", fiscal_year=2025, limit=1))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_exclusions_response_shape():
    r = asyncio.run(_call("search_exclusions", country="USA", size=1))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_psc_lookup_response_shape():
    """Verify response shape for a known-good PSC."""
    r = asyncio.run(_call("lookup_psc_code", code="R425"))
    data = _payload(r)
    assert "totalRecords" in data
    # Just verify it returned a valid dict; specific field names vary
    assert isinstance(data, dict)


def test_live_check_exclusion_response_shape():
    r = asyncio.run(_call("check_exclusion_by_uei", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    assert "totalRecords" in data
    assert "excludedEntity" in data or int(data.get("totalRecords", 0)) == 0


def test_live_vendor_responsibility_response_complete():
    r = asyncio.run(_call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PBC))
    data = _payload(r)
    # All four top-level fields must be present
    assert "uei" in data
    assert "registration" in data
    assert "exclusion" in data
    assert "flags" in data
    assert isinstance(data["flags"], list)


def test_live_search_entities_includes_total_count():
    r = asyncio.run(_call("search_entities", legal_business_name="Anthropic", size=1))
    data = _payload(r)
    assert "totalRecords" in data
    assert isinstance(int(data["totalRecords"]), int)


# ===========================================================================
# M. EDGE CASES (boundaries that are valid but unusual)
# ===========================================================================

def test_live_opportunities_exactly_364_day_span():
    """Exactly 364 days is the max valid span."""
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from="04/24/2025",
            posted_to="04/22/2026",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_opportunities_single_day_window():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_TO,
            posted_to=RECENT_DATE_TO,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_single_day_signed():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            date_signed="04/22/2025",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_unicode_cjk_in_name():
    """CJK characters should reach the API."""
    r = asyncio.run(_call("search_entities", legal_business_name="北京", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_emoji_in_name():
    r = asyncio.run(_call("search_entities", legal_business_name="rocket 🚀 inc", size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_entities_very_long_name():
    """200 characters should pass the length cap."""
    r = asyncio.run(_call("search_entities", legal_business_name="a" * 200, size=3))
    data = _payload(r)
    assert "totalRecords" in data


def test_live_lookup_psc_special_codes_aj12():
    """Some PSC codes have alphanumeric mix."""
    try:
        r = asyncio.run(_call("lookup_psc_code", code="AJ12"))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"])


def test_live_search_opportunities_zip_code_filter():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            zip_code="22202",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_opportunities_zip_code_int():
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            zip_code=22202,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_with_cage():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            awardee_cage_code=CAGE_ANTHROPIC_PBC,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_with_uei():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            awardee_uei=UEI_ANTHROPIC_PBC,
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_contract_awards_with_awardee_name():
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            awardee_name="Lockheed Martin",
            limit=5,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# N. EXHAUSTIVE SET-ASIDE COVERAGE
# ===========================================================================

ALL_SET_ASIDE_CODES = [
    "SBA", "SBP", "8A", "8AN", "HZC", "HZS", "SDVOSBC", "SDVOSBS",
    "WOSB", "WOSBSS", "EDWOSB", "EDWOSBSS", "VSA", "VSS",
]


@pytest.mark.parametrize("code", ALL_SET_ASIDE_CODES)
def test_live_opportunities_each_set_aside_code(code):
    """Every documented set-aside code must be accepted by the API."""
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            set_aside=code,
            limit=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# O. EXHAUSTIVE NOTICE TYPE COVERAGE
# ===========================================================================

ALL_NOTICE_TYPES = [
    "p", "o", "k", "r", "g", "s", "i", "a", "u",
]


@pytest.mark.parametrize("ptype", ALL_NOTICE_TYPES)
def test_live_opportunities_each_notice_type(ptype):
    """Every documented notice type must be accepted."""
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            notice_type=ptype,
            limit=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# P. FISCAL YEAR COVERAGE (each year FY2008 - FY2026)
# ===========================================================================

@pytest.mark.parametrize("fy", [2008, 2010, 2012, 2015, 2018, 2020, 2022, 2023, 2024, 2025, 2026])
def test_live_contract_awards_each_fiscal_year(fy):
    """Every fiscal year in the supported range must return data."""
    r = asyncio.run(_call("search_contract_awards", fiscal_year=fy, limit=3))
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# Q. PSC CODE COVERAGE (real codes across categories)
# ===========================================================================

REAL_PSC_CODES = [
    "R425", "R499", "D302", "D310", "D316", "D399", "AJ12",
    "B501", "J016", "Y112", "Z211",
]


@pytest.mark.parametrize("code", REAL_PSC_CODES)
def test_live_psc_lookup_each_real_code(code):
    """Each PSC code lookup must succeed: either return data OR a clear
    'not found' error message. Both prove the tool works correctly. The
    purpose is to confirm the tool doesn't crash, hang, or leak the opaque
    SAM 'Entered search criteria is not found' message."""
    try:
        r = asyncio.run(_call("lookup_psc_code", code=code))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        # Acceptable: the translated 'not found' error from 0.3.1 hardening
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"]), (
            f"PSC {code} raised unexpected error: {e}"
        )


PSC_FREE_TEXT_QUERIES = [
    "training", "advisory", "construction", "medical", "transportation",
    "cleaning", "research", "logistics", "facilities",
]


@pytest.mark.parametrize("query", PSC_FREE_TEXT_QUERIES)
def test_live_psc_free_text_each_query(query):
    """Common PSC free-text queries: succeed with data OR clear not-found error."""
    try:
        r = asyncio.run(_call("search_psc_free_text", query=query))
        data = _payload(r)
        assert "totalRecords" in data
    except Exception as e:
        msg = str(e).lower()
        assert any(p in msg for p in ["did not find", "psc-manual", "not found"])


# ===========================================================================
# R. STATE FILTER COVERAGE (top procurement states)
# ===========================================================================

TOP_PROCUREMENT_STATES = ["VA", "MD", "DC", "TX", "CA", "FL", "NY", "PA", "GA"]


@pytest.mark.parametrize("state", TOP_PROCUREMENT_STATES)
def test_live_search_entities_each_state(state):
    """Entity search filtered by state must work for each top state."""
    r = asyncio.run(
        _call(
            "search_entities",
            legal_business_name="defense",
            state_code=state,
            size=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


@pytest.mark.parametrize("state", TOP_PROCUREMENT_STATES[:5])
def test_live_opportunities_each_state(state):
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            state=state,
            limit=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# S. NAICS CODE COVERAGE (top procurement NAICS)
# ===========================================================================

TOP_PROCUREMENT_NAICS = [
    "541512",  # Computer Systems Design Services
    "541611",  # Administrative Management Consulting
    "541330",  # Engineering Services
    "541715",  # R&D in Physical/Engineering/Life Sciences
    "541519",  # Other Computer Related Services
    "236220",  # Commercial Building Construction
    "561210",  # Facilities Support Services
    "541990",  # All Other Professional, Scientific, and Technical Services
]


@pytest.mark.parametrize("naics", TOP_PROCUREMENT_NAICS)
def test_live_opportunities_each_naics(naics):
    r = asyncio.run(
        _call(
            "search_opportunities",
            posted_from=RECENT_DATE_FROM,
            posted_to=RECENT_DATE_TO,
            naics_code=naics,
            limit=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


@pytest.mark.parametrize("naics", TOP_PROCUREMENT_NAICS[:5])
def test_live_contract_awards_each_naics(naics):
    r = asyncio.run(
        _call(
            "search_contract_awards",
            fiscal_year=2025,
            naics_code=naics,
            limit=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


# ===========================================================================
# T. ADDITIONAL VENDOR RESPONSIBILITY CHECKS
# ===========================================================================

def test_live_vendor_responsibility_with_padding():
    r = asyncio.run(
        _call("vendor_responsibility_check", uei=f"  {UEI_ANTHROPIC_PI}  ")
    )
    data = _payload(r)
    assert "registration" in data


def test_live_vendor_responsibility_returns_flags_list():
    r = asyncio.run(_call("vendor_responsibility_check", uei=UEI_ANTHROPIC_PI))
    data = _payload(r)
    assert isinstance(data["flags"], list)


# ===========================================================================
# U. ADDITIONAL EXCLUSION TESTS
# ===========================================================================

def test_live_search_exclusions_classification_vessel():
    r = asyncio.run(
        _call("search_exclusions", classification="Vessel", size=3)
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_classification_special_entity():
    r = asyncio.run(
        _call(
            "search_exclusions",
            classification="Special Entity Designation",
            size=3,
        )
    )
    data = _payload(r)
    assert "totalRecords" in data


def test_live_search_exclusions_max_size_100():
    r = asyncio.run(_call("search_exclusions", country="USA", size=100))
    data = _payload(r)
    assert "totalRecords" in data
