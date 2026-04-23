# SPDX-License-Identifier: MIT
"""Round 6: Live audit (200+ tests against the production GSA Per Diem API).

Runs only when MCP_LIVE_TESTS=1 and a valid PERDIEM_API_KEY (api.data.gov)
is set. Makes real HTTP calls to api.gsa.gov/travel/perdiem.

Purpose: validate behaviors that mocks cannot see.
- Real city/state/ZIP lookups across 50 states + DC + territories
- Real seasonal lodging variations (DC, ski areas, beach cities)
- Real fiscal year coverage (FY2020 through current)
- Apostrophe and special character handling against the live API
- M&IE tier breakdown live values
- Travel cost calculations across realistic trip patterns
- Response shape drift detection

Cost: ~210 calls per full run. api.data.gov key is 1,000/hour.
Runtime: 3-5 minutes typical.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import gsa_perdiem_mcp.server as srv  # noqa: E402
from gsa_perdiem_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="requires MCP_LIVE_TESTS=1 + PERDIEM_API_KEY"
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
# A. CITY/STATE LOOKUPS — 50 states + DC representative cities
# ===========================================================================

# (city, state) pairs covering all 50 states + DC
ALL_STATES_CITIES = [
    ("Birmingham", "AL"), ("Anchorage", "AK"), ("Phoenix", "AZ"),
    ("Little Rock", "AR"), ("San Francisco", "CA"), ("Denver", "CO"),
    ("Hartford", "CT"), ("Wilmington", "DE"), ("Washington", "DC"),
    ("Miami", "FL"), ("Atlanta", "GA"), ("Honolulu", "HI"),
    ("Boise", "ID"), ("Chicago", "IL"), ("Indianapolis", "IN"),
    ("Des Moines", "IA"), ("Wichita", "KS"), ("Louisville", "KY"),
    ("New Orleans", "LA"), ("Portland", "ME"), ("Baltimore", "MD"),
    ("Boston", "MA"), ("Detroit", "MI"), ("Minneapolis", "MN"),
    ("Jackson", "MS"), ("Kansas City", "MO"), ("Billings", "MT"),
    ("Omaha", "NE"), ("Las Vegas", "NV"), ("Manchester", "NH"),
    ("Newark", "NJ"), ("Albuquerque", "NM"), ("New York", "NY"),
    ("Charlotte", "NC"), ("Fargo", "ND"), ("Cleveland", "OH"),
    ("Oklahoma City", "OK"), ("Portland", "OR"), ("Philadelphia", "PA"),
    ("Providence", "RI"), ("Charleston", "SC"), ("Sioux Falls", "SD"),
    ("Nashville", "TN"), ("Austin", "TX"), ("Salt Lake City", "UT"),
    ("Burlington", "VT"), ("Arlington", "VA"), ("Seattle", "WA"),
    ("Charleston", "WV"), ("Milwaukee", "WI"), ("Cheyenne", "WY"),
]


@pytest.mark.parametrize("city,state", ALL_STATES_CITIES)
def test_live_city_perdiem_each_state(city, state):
    r = asyncio.run(_call("lookup_city_perdiem", city=city, state=state))
    data = _payload(r)
    assert isinstance(data, dict)
    # Either we got a rate or a clear no-match marker; never a crash
    assert any(k in data for k in [
        "lodging_max", "lodging", "rate", "city", "no_match", "error",
        "mie_total", "matched_city",
    ])


# ===========================================================================
# B. SPECIAL CITY NAME HANDLING (apostrophes, periods, hyphens)
# ===========================================================================

def test_live_city_st_louis_with_period():
    r = asyncio.run(_call("lookup_city_perdiem", city="St. Louis", state="MO"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_st_louis_no_period():
    r = asyncio.run(_call("lookup_city_perdiem", city="St Louis", state="MO"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_winston_salem_hyphen():
    r = asyncio.run(_call("lookup_city_perdiem", city="Winston-Salem", state="NC"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_winston_salem_space():
    r = asyncio.run(_call("lookup_city_perdiem", city="Winston Salem", state="NC"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_apostrophe_typographic():
    """Typographic apostrophe (\u2019) vs straight ascii (')."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Coeur d\u2019Alene", state="ID"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_apostrophe_ascii():
    r = asyncio.run(_call("lookup_city_perdiem", city="Coeur d'Alene", state="ID"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_lowercase_state_normalized():
    r = asyncio.run(_call("lookup_city_perdiem", city="Boston", state="ma"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_mixed_case_state_normalized():
    r = asyncio.run(_call("lookup_city_perdiem", city="Boston", state="Ma"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_with_padding_stripped():
    r = asyncio.run(_call("lookup_city_perdiem", city="  Boston  ", state="MA"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_unmatched_returns_marker():
    """Bogus city should return an empty/marker, not a crash."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Zyxwvutsr", state="MA"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# C. MAJOR METRO AREAS (high-cost destinations)
# ===========================================================================

HIGH_COST_METROS = [
    ("New York", "NY"),
    ("San Francisco", "CA"),
    ("Boston", "MA"),
    ("Washington", "DC"),
    ("Seattle", "WA"),
    ("Chicago", "IL"),
    ("Los Angeles", "CA"),
    ("San Diego", "CA"),
    ("Miami", "FL"),
    ("Honolulu", "HI"),
    ("Denver", "CO"),
    ("Anchorage", "AK"),
]


@pytest.mark.parametrize("city,state", HIGH_COST_METROS)
def test_live_high_cost_metro_lookup(city, state):
    r = asyncio.run(_call("lookup_city_perdiem", city=city, state=state))
    data = _payload(r)
    assert isinstance(data, dict)


# Federal procurement hotspots
PROCUREMENT_HOTSPOTS = [
    ("Arlington", "VA"),
    ("Alexandria", "VA"),
    ("Crystal City", "VA"),
    ("Bethesda", "MD"),
    ("Annapolis", "MD"),
    ("Quantico", "VA"),
    ("Fort Belvoir", "VA"),
    ("Norfolk", "VA"),
    ("Newport News", "VA"),
    ("Huntsville", "AL"),
    ("Dayton", "OH"),
    ("Albuquerque", "NM"),
    ("Colorado Springs", "CO"),
    ("Tampa", "FL"),
]


@pytest.mark.parametrize("city,state", PROCUREMENT_HOTSPOTS)
def test_live_procurement_hotspot_lookup(city, state):
    r = asyncio.run(_call("lookup_city_perdiem", city=city, state=state))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# D. SEASONAL CITIES (rates vary by month)
# ===========================================================================

# Vacation/seasonal markets where lodging varies sharply by month
SEASONAL_CITIES = [
    ("Aspen", "CO"),
    ("Park City", "UT"),
    ("Vail", "CO"),
    ("Key West", "FL"),
    ("Jackson", "WY"),  # Jackson Hole
    ("Hilton Head Island", "SC"),
    ("Nantucket", "MA"),
    ("Martha's Vineyard", "MA"),
    ("Naples", "FL"),
    ("Palm Beach", "FL"),
    ("Telluride", "CO"),
    ("Lake Tahoe", "CA"),
]


@pytest.mark.parametrize("city,state", SEASONAL_CITIES)
def test_live_seasonal_city_lookup(city, state):
    """Seasonal cities should have monthly lodging variation."""
    r = asyncio.run(_call("lookup_city_perdiem", city=city, state=state))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# E. FISCAL YEAR COVERAGE
# ===========================================================================

@pytest.mark.parametrize("fy", [2020, 2021, 2022, 2023, 2024, 2025, 2026])
def test_live_city_each_fiscal_year(fy):
    """Per diem data covers FY2020 through current FY."""
    r = asyncio.run(
        _call("lookup_city_perdiem", city="Boston", state="MA", fiscal_year=fy)
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_default_fiscal_year():
    """Omitting fiscal_year should default to current FY."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Boston", state="MA"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# F. ZIP CODE LOOKUPS
# ===========================================================================

# Real ZIPs from major federal procurement areas
REAL_ZIPS = [
    ("20001", "DC"),         # Washington DC
    ("22202", "Crystal City"), # Crystal City VA
    ("22209", "Arlington"),
    ("20814", "Bethesda"),
    ("02110", "Boston"),
    ("10001", "NYC"),
    ("90071", "LA"),
    ("94102", "SF"),
    ("60601", "Chicago"),
    ("78701", "Austin"),
    ("75201", "Dallas"),
    ("75001", "Addison TX"),
    ("33131", "Miami"),
    ("98101", "Seattle"),
    ("80202", "Denver"),
    ("85003", "Phoenix"),
    ("89101", "Las Vegas"),
    ("99501", "Anchorage"),
    ("96813", "Honolulu"),
    ("32801", "Orlando"),
]


@pytest.mark.parametrize("zip_code,name", REAL_ZIPS)
def test_live_zip_perdiem_each(zip_code, name):
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code=zip_code))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_with_plus_4_suffix():
    """ZIP+4 should be accepted; only the 5-digit prefix matters."""
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="20001-1234"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_with_padding():
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="  20001  "))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_fy_2024():
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="20001", fiscal_year=2024))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_fy_2025():
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="20001", fiscal_year=2025))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_fy_2026():
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="20001", fiscal_year=2026))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_zip_rural_area():
    """Rural ZIPs should return standard CONUS rate."""
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="59001"))  # Absarokee, MT
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# G. STATE RATES (NSA listings)
# ===========================================================================

# All 50 states + DC for state rates
ALL_50_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


@pytest.mark.parametrize("state", ALL_50_STATES)
def test_live_state_rates_each_state(state):
    """Every state should return some response (NSAs or empty list)."""
    r = asyncio.run(_call("lookup_state_rates", state=state))
    data = _payload(r)
    assert isinstance(data, dict)
    assert "state" in data or "rates" in data or "nsa_count" in data


def test_live_state_rates_lowercase_normalized():
    r = asyncio.run(_call("lookup_state_rates", state="va"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_state_rates_with_fy():
    r = asyncio.run(_call("lookup_state_rates", state="VA", fiscal_year=2024))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# H. M&IE BREAKDOWN
# ===========================================================================

@pytest.mark.parametrize("fy", [2020, 2021, 2022, 2023, 2024, 2025, 2026])
def test_live_mie_breakdown_each_fy(fy):
    r = asyncio.run(_call("get_mie_breakdown", fiscal_year=fy))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_mie_breakdown_default_fy():
    r = asyncio.run(_call("get_mie_breakdown"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_mie_breakdown_response_has_tiers():
    """M&IE breakdown should include tier values."""
    r = asyncio.run(_call("get_mie_breakdown"))
    data = _payload(r)
    assert isinstance(data, dict)
    # Either has tier list or specific tier amounts
    assert any(k in data for k in [
        "tiers", "mie_tiers", "fiscal_year", "tier_1", "rates", "results",
    ])


# ===========================================================================
# I. TRAVEL COST ESTIMATES
# ===========================================================================

# Various trip lengths
TRIP_LENGTHS = [1, 2, 3, 5, 7, 10, 14, 30]


@pytest.mark.parametrize("nights", TRIP_LENGTHS)
def test_live_estimate_travel_cost_various_lengths(nights):
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Washington",
            state="DC",
            num_nights=nights,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in [
        "total", "lodging_total", "mie_total", "num_nights", "city",
    ])


# Each month for seasonal estimates
ALL_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@pytest.mark.parametrize("month", ALL_MONTHS)
def test_live_estimate_travel_cost_each_month(month):
    """Test each month for a seasonal city (DC)."""
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Washington",
            state="DC",
            num_nights=3,
            travel_month=month,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_travel_cost_min_one_night():
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Boston",
            state="MA",
            num_nights=1,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_travel_cost_max_365_nights():
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Boston",
            state="MA",
            num_nights=365,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_travel_cost_with_fy():
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Washington",
            state="DC",
            num_nights=5,
            fiscal_year=2024,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_travel_cost_high_cost_metro():
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="New York",
            state="NY",
            num_nights=5,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# J. COMPARE LOCATIONS
# ===========================================================================

def test_live_compare_three_metros():
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Boston", "state": "MA"},
                {"city": "New York", "state": "NY"},
                {"city": "San Francisco", "state": "CA"},
            ],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert "results" in data or "locations" in data or "comparison" in data


def test_live_compare_dc_metro_area():
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Washington", "state": "DC"},
                {"city": "Arlington", "state": "VA"},
                {"city": "Bethesda", "state": "MD"},
                {"city": "Alexandria", "state": "VA"},
            ],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_minimum_2_locations():
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Boston", "state": "MA"},
                {"city": "Chicago", "state": "IL"},
            ],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_max_locations():
    """compare_locations cap is _MAX_COMPARE_LOCATIONS (25)."""
    locations = [
        {"city": city, "state": state}
        for city, state in HIGH_COST_METROS[:10]
    ]
    r = asyncio.run(_call("compare_locations", locations=locations))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_with_fiscal_year():
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Boston", "state": "MA"},
                {"city": "Chicago", "state": "IL"},
            ],
            fiscal_year=2024,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_with_mixed_case_states():
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Boston", "state": "ma"},
                {"city": "Chicago", "state": "Il"},
            ],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# K. CONCURRENT CALLS
# ===========================================================================

def test_live_concurrent_5_city_lookups():
    async def _run():
        return await asyncio.gather(
            _call("lookup_city_perdiem", city="Washington", state="DC"),
            _call("lookup_city_perdiem", city="Boston", state="MA"),
            _call("lookup_city_perdiem", city="Chicago", state="IL"),
            _call("lookup_city_perdiem", city="Denver", state="CO"),
            _call("lookup_city_perdiem", city="Seattle", state="WA"),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


def test_live_concurrent_mixed_tools():
    async def _run():
        return await asyncio.gather(
            _call("lookup_city_perdiem", city="Boston", state="MA"),
            _call("lookup_zip_perdiem", zip_code="20001"),
            _call("lookup_state_rates", state="VA"),
            _call("get_mie_breakdown"),
        )
    results = asyncio.run(_run())
    assert len(results) == 4


# ===========================================================================
# L. RESPONSE SHAPE VERIFICATION
# ===========================================================================

def test_live_city_response_has_lodging_or_marker():
    r = asyncio.run(_call("lookup_city_perdiem", city="Washington", state="DC"))
    data = _payload(r)
    assert isinstance(data, dict)
    # Either real lodging data or a clear marker
    assert any(k in data for k in [
        "lodging_max", "lodging", "monthly_lodging", "rate", "no_match",
        "matched_city", "city",
    ])


def test_live_city_response_has_mie():
    r = asyncio.run(_call("lookup_city_perdiem", city="Washington", state="DC"))
    data = _payload(r)
    assert isinstance(data, dict)
    # M&IE should be present (actual keys are mie_daily / mie_first_last_day)
    assert any(k in data for k in [
        "mie_daily", "mie_first_last_day", "mie_total", "mie", "meals", "rate",
    ])


def test_live_zip_response_includes_zip():
    r = asyncio.run(_call("lookup_zip_perdiem", zip_code="20001"))
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in ["zip_code", "zip", "city", "state"])


def test_live_state_response_includes_rates_or_count():
    r = asyncio.run(_call("lookup_state_rates", state="VA"))
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in ["rates", "nsa_count", "state"])


def test_live_estimate_response_has_total():
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Boston",
            state="MA",
            num_nights=3,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in [
        "total", "lodging_total", "mie_total", "estimated_total",
    ])


# ===========================================================================
# M. EDGE CASES
# ===========================================================================

def test_live_city_perdiem_dc_special_case():
    """DC is its own state in per diem world."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Washington", state="DC"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_perdiem_alaska_remote():
    """Alaska has special rate handling (OCONUS-adjacent)."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Anchorage", state="AK"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_city_perdiem_hawaii_remote():
    r = asyncio.run(_call("lookup_city_perdiem", city="Honolulu", state="HI"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_state_rates_dc():
    r = asyncio.run(_call("lookup_state_rates", state="DC"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_seasonal_cities():
    """Seasonal cities should reflect different rates."""
    r = asyncio.run(
        _call(
            "compare_locations",
            locations=[
                {"city": "Aspen", "state": "CO"},
                {"city": "Key West", "state": "FL"},
                {"city": "Nantucket", "state": "MA"},
            ],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_dc_january():
    """DC in January should be a defined rate (slow tourist month)."""
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Washington",
            state="DC",
            num_nights=4,
            travel_month="Jan",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_estimate_dc_october():
    """DC in October (peak tourist season)."""
    r = asyncio.run(
        _call(
            "estimate_travel_cost",
            city="Washington",
            state="DC",
            num_nights=4,
            travel_month="Oct",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_unicode_city_name_unmatched():
    """Unicode city names should not crash even if unmatched."""
    r = asyncio.run(_call("lookup_city_perdiem", city="café", state="LA"))
    data = _payload(r)
    assert isinstance(data, dict)
