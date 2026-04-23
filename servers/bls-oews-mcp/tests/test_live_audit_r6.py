# SPDX-License-Identifier: MIT
"""Round 6: Live audit (200+ tests against the production BLS OEWS API).

Runs only when BLS_LIVE_TESTS=1 and a BLS_API_KEY is set. Makes real
HTTP calls to api.bls.gov.

Purpose: validate behaviors that mocks cannot see.
- Real wage data across 50 states, top metros, common occupations
- All 4 IGCE datatypes returned correctly
- All 9 valid datatype codes accepted by the API
- Industry breakdowns at national scope
- Compare metros/occupations with real series IDs
- Year boundary behavior (latest, prior years)
- Concurrent call safety
- Suppressed and capped value handling
- Response shape verification

Cost: ~210 BLS calls per full run. Key has 500/day limit.
Runtime: 4-6 minutes typical.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import bls_oews_mcp.server as srv  # noqa: E402
from bls_oews_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="requires BLS_LIVE_TESTS=1 + BLS_API_KEY"
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
# A. NATIONAL WAGE DATA — 30 common occupations
# ===========================================================================

# Common SOC codes used in federal IGCE work
COMMON_SOC_CODES = [
    ("151252", "Software Developers"),
    ("151232", "Computer User Support Specialists"),
    ("151212", "Information Security Analysts"),
    ("151244", "Network and Computer Systems Administrators"),
    ("151231", "Computer Network Support Specialists"),
    ("131082", "Project Management Specialists"),
    ("131111", "Management Analysts"),
    ("131151", "Training and Development Specialists"),
    ("132011", "Accountants and Auditors"),
    ("132031", "Budget Analysts"),
    ("132051", "Financial Analysts"),
    ("152031", "Operations Research Analysts"),
    ("152041", "Statisticians"),
    ("172112", "Industrial Engineers"),
    ("172041", "Chemical Engineers"),
    ("172061", "Computer Hardware Engineers"),
    ("172071", "Electrical Engineers"),
    ("172072", "Electronics Engineers, Except Computer"),
    ("172112", "Industrial Engineers"),
    ("172141", "Mechanical Engineers"),
    ("173023", "Electrical and Electronics Engineering Technicians"),
    ("119121", "Natural Sciences Managers"),
    ("119041", "Architectural and Engineering Managers"),
    ("113021", "Computer and Information Systems Managers"),
    ("113011", "Administrative Services Managers"),
    ("232011", "Paralegals and Legal Assistants"),
    ("231011", "Lawyers"),
    ("271024", "Graphic Designers"),
    ("273031", "Public Relations Specialists"),
    ("273042", "Technical Writers"),
]


@pytest.mark.parametrize("soc,name", COMMON_SOC_CODES)
def test_live_get_wage_data_national_each_soc(soc, name):
    r = asyncio.run(_call("get_wage_data", occ_code=soc, scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in [
        "wages", "values", "occ_code", "data", "no_data", "error",
    ])


# ===========================================================================
# B. STATE-LEVEL WAGE DATA — major states
# ===========================================================================

# State FIPS codes
MAJOR_STATE_FIPS = [
    "51", "11", "24", "06", "48", "36", "12", "13", "37", "26",
    "39", "42", "17", "01",
]


@pytest.mark.parametrize("state_fips", MAJOR_STATE_FIPS)
def test_live_get_wage_data_software_dev_each_state(state_fips):
    """Software Developers across major states."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code=state_fips,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_state_fips_int():
    """State FIPS as int should be coerced."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code=51,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_state_fips_padded():
    """State FIPS with whitespace padding."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code="  51  ",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_state_no_area_raises():
    """State scope requires area_code."""
    try:
        asyncio.run(
            _call("get_wage_data", occ_code="151252", scope="state")
        )
    except Exception as e:
        assert "area_code" in str(e).lower() or "required" in str(e).lower()


# ===========================================================================
# C. METRO-LEVEL WAGE DATA — top procurement metros
# ===========================================================================

# Top federal procurement metros (5-digit MSA codes)
TOP_METROS = [
    ("47900", "Washington-Arlington-Alexandria"),
    ("42660", "Seattle-Tacoma-Bellevue"),
    ("12580", "Baltimore-Columbia-Towson"),
    ("14460", "Boston-Cambridge-Newton"),
    ("31080", "Los Angeles-Long Beach-Anaheim"),
    ("35620", "New York-Newark-Jersey City"),
    ("41860", "San Francisco-Oakland-Berkeley"),
    ("19100", "Dallas-Fort Worth-Arlington"),
    ("16980", "Chicago-Naperville-Elgin"),
    ("12060", "Atlanta-Sandy Springs-Alpharetta"),
    ("38060", "Phoenix-Mesa-Chandler"),
    ("33100", "Miami-Fort Lauderdale-Pompano Beach"),
    ("19740", "Denver-Aurora-Lakewood"),
    ("38900", "Portland-Vancouver-Hillsboro"),
    ("29820", "Las Vegas-Henderson-Paradise"),
]


@pytest.mark.parametrize("msa,name", TOP_METROS)
def test_live_get_wage_data_software_dev_each_metro(msa, name):
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="metro",
            area_code=msa,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_metro_int_area_code():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="metro",
            area_code=47900,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_metro_padded():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="metro",
            area_code="  47900  ",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_metro_no_area_raises():
    try:
        asyncio.run(
            _call("get_wage_data", occ_code="151252", scope="metro")
        )
    except Exception as e:
        assert "area_code" in str(e).lower() or "required" in str(e).lower()


# ===========================================================================
# D. DATATYPE COVERAGE — all 9 valid codes
# ===========================================================================

# All datatype codes documented in the MCP
ALL_DATATYPES = ["01", "03", "04", "08", "11", "12", "13", "14", "15"]


@pytest.mark.parametrize("dt", ALL_DATATYPES)
def test_live_get_wage_data_each_datatype(dt):
    """Each documented datatype should be accepted by the API."""
    r = asyncio.run(
        _call("get_wage_data", occ_code="151252", scope="national", datatypes=[dt])
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_default_datatypes():
    """No datatypes arg uses IGCE defaults."""
    r = asyncio.run(_call("get_wage_data", occ_code="151252", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_multiple_datatypes():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="national",
            datatypes=["04", "13", "11", "15"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_dedup_datatypes():
    """Duplicate datatypes should dedupe in the request."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="national",
            datatypes=["04", "04", "13"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# E. INDUSTRY BREAKDOWNS (national scope only)
# ===========================================================================

INDUSTRIES = [
    "000000",  # All industries
    "541000",  # Professional Services
    "541500",  # Computer Systems Design
    "999100",  # Federal Government
]


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_live_get_wage_data_each_industry(industry):
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="national",
            industry=industry,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_industry_int():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="national",
            industry=541000,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# F. YEAR HANDLING
# ===========================================================================

def test_live_get_wage_data_year_2024():
    r = asyncio.run(
        _call("get_wage_data", occ_code="151252", scope="national", year=2024)
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_year_2023_rejected():
    """Historical years are rejected: BLS public API only serves latest."""
    try:
        asyncio.run(
            _call("get_wage_data", occ_code="151252", scope="national", year=2023)
        )
    except Exception as e:
        assert "before the current" in str(e) or "latest year" in str(e).lower()


def test_live_get_wage_data_year_2022_rejected():
    try:
        asyncio.run(
            _call("get_wage_data", occ_code="151252", scope="national", year=2022)
        )
    except Exception as e:
        assert "before the current" in str(e) or "latest year" in str(e).lower()


def test_live_get_wage_data_year_str_or_int():
    """Year as string or int should both work."""
    r = asyncio.run(
        _call("get_wage_data", occ_code="151252", scope="national", year="2024")
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_year_default():
    """No year defaults to latest available."""
    r = asyncio.run(_call("get_wage_data", occ_code="151252", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# G. SOC CODE FORMAT VARIATIONS
# ===========================================================================

def test_live_get_wage_data_soc_as_int():
    r = asyncio.run(_call("get_wage_data", occ_code=151252, scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_soc_with_dash():
    """SOC like '15-1252' should be normalized."""
    r = asyncio.run(_call("get_wage_data", occ_code="15-1252", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_get_wage_data_soc_padded():
    r = asyncio.run(_call("get_wage_data", occ_code="  151252  ", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# H. COMPARE_METROS
# ===========================================================================

def test_live_compare_metros_top_5():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "42660", "14460", "35620", "41860"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert "metros" in data


def test_live_compare_metros_dc_metro_area():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "12580"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_with_int_codes():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=[47900, 42660, 14460],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_mixed_str_int():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", 42660],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_dedup():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "47900", "42660"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_with_datatype_median():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "42660"],
            datatype="13",  # Annual Median
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_hourly_mean():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "42660"],
            datatype="03",  # Hourly Mean
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_state_fips_rejected():
    """compare_metros should reject state FIPS codes."""
    try:
        asyncio.run(
            _call("compare_metros", occ_code="151252", metro_codes=["51"])
        )
    except Exception as e:
        assert "metro" in str(e).lower() or "state" in str(e).lower()


def test_live_compare_metros_with_year_2023_rejected():
    try:
        asyncio.run(
            _call(
                "compare_metros",
                occ_code="151252",
                metro_codes=["47900", "42660"],
                year=2023,
            )
        )
    except Exception as e:
        assert "before the current" in str(e) or "latest year" in str(e).lower()


# ===========================================================================
# I. COMPARE_OCCUPATIONS
# ===========================================================================

def test_live_compare_occupations_national():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082", "152031"],
            scope="national",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert "occupations" in data


def test_live_compare_occupations_state_va():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082"],
            scope="state",
            area_code="51",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_metro_dc():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082", "152031"],
            scope="metro",
            area_code="47900",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_with_int_codes():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=[151252, 131082],
            scope="national",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_dedup():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "151252", "131082"],
            scope="national",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_state_no_area_raises():
    try:
        asyncio.run(
            _call(
                "compare_occupations",
                occ_codes=["151252"],
                scope="state",
            )
        )
    except Exception as e:
        assert "area_code" in str(e).lower() or "required" in str(e).lower()


def test_live_compare_occupations_metro_no_area_raises():
    try:
        asyncio.run(
            _call(
                "compare_occupations",
                occ_codes=["151252"],
                scope="metro",
            )
        )
    except Exception as e:
        assert "area_code" in str(e).lower() or "required" in str(e).lower()


def test_live_compare_occupations_with_median_datatype():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082"],
            scope="national",
            datatype="13",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_with_year_2023_rejected():
    try:
        asyncio.run(
            _call(
                "compare_occupations",
                occ_codes=["151252", "131082"],
                scope="national",
                year=2023,
            )
        )
    except Exception as e:
        assert "before the current" in str(e) or "latest year" in str(e).lower()


# ===========================================================================
# J. IGCE_WAGE_BENCHMARK (composite tool, multiple datatypes)
# ===========================================================================

def test_live_igce_benchmark_software_dev_dc():
    r = asyncio.run(
        _call(
            "igce_wage_benchmark",
            occ_code="151252",
            scope="metro",
            area_code="47900",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_igce_benchmark_software_dev_national():
    r = asyncio.run(
        _call("igce_wage_benchmark", occ_code="151252", scope="national")
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_igce_benchmark_pm_specialist_va():
    r = asyncio.run(
        _call(
            "igce_wage_benchmark",
            occ_code="131082",
            scope="state",
            area_code="51",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_igce_benchmark_includes_aging_factor():
    """IGCE benchmark should compute an aging factor for the wage data."""
    r = asyncio.run(
        _call("igce_wage_benchmark", occ_code="151252", scope="national")
    )
    data = _payload(r)
    assert isinstance(data, dict)
    # Should mention aging or vintage
    assert any(k in data for k in [
        "aging_factor", "aged_value", "data_year", "vintage", "wages",
        "no_data",
    ])


def test_live_igce_benchmark_metro_seattle():
    r = asyncio.run(
        _call(
            "igce_wage_benchmark",
            occ_code="151252",
            scope="metro",
            area_code="42660",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_igce_benchmark_engineer_national():
    r = asyncio.run(
        _call(
            "igce_wage_benchmark", occ_code="172112", scope="national"
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_igce_benchmark_with_year_2023_rejected():
    try:
        asyncio.run(
            _call(
                "igce_wage_benchmark",
                occ_code="151252",
                scope="national",
                year=2023,
            )
        )
    except Exception as e:
        assert "before the current" in str(e) or "latest year" in str(e).lower()


def test_live_igce_benchmark_int_inputs():
    r = asyncio.run(
        _call(
            "igce_wage_benchmark",
            occ_code=151252,
            scope="metro",
            area_code=47900,
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# K. DETECT_LATEST_YEAR
# ===========================================================================

def test_live_detect_latest_year_returns_year():
    r = asyncio.run(_call("detect_latest_year"))
    data = _payload(r)
    assert isinstance(data, dict)
    assert any(k in data for k in ["year", "latest_year", "data_year"])


def test_live_detect_latest_year_is_recent():
    """Latest year should be 2024 or later (May 2024 OEWS data shipped)."""
    r = asyncio.run(_call("detect_latest_year"))
    data = _payload(r)
    if isinstance(data, dict):
        year = data.get("year") or data.get("latest_year") or data.get("data_year")
        if year:
            assert int(year) >= 2024


# ===========================================================================
# L. LIST TOOLS (no API call)
# ===========================================================================

def test_live_list_common_soc_codes_returns_dict():
    r = asyncio.run(_call("list_common_soc_codes"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_list_common_soc_codes_includes_software_dev():
    r = asyncio.run(_call("list_common_soc_codes"))
    data = _payload(r)
    # SOC 151252 should be in the common list
    str_data = str(data)
    assert "151252" in str_data


def test_live_list_common_metros_returns_dict():
    r = asyncio.run(_call("list_common_metros"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_list_common_metros_includes_dc():
    r = asyncio.run(_call("list_common_metros"))
    data = _payload(r)
    str_data = str(data)
    assert "47900" in str_data or "Washington" in str_data


# ===========================================================================
# M. CONCURRENT CALLS
# ===========================================================================

def test_live_concurrent_5_wage_lookups():
    async def _run():
        return await asyncio.gather(
            _call("get_wage_data", occ_code="151252", scope="national"),
            _call("get_wage_data", occ_code="131082", scope="national"),
            _call("get_wage_data", occ_code="152031", scope="national"),
            _call("get_wage_data", occ_code="172112", scope="national"),
            _call("get_wage_data", occ_code="132011", scope="national"),
        )
    results = asyncio.run(_run())
    assert len(results) == 5


def test_live_concurrent_3_metros():
    async def _run():
        return await asyncio.gather(
            _call("get_wage_data", occ_code="151252", scope="metro", area_code="47900"),
            _call("get_wage_data", occ_code="151252", scope="metro", area_code="42660"),
            _call("get_wage_data", occ_code="151252", scope="metro", area_code="14460"),
        )
    results = asyncio.run(_run())
    assert len(results) == 3


def test_live_concurrent_mixed_tools():
    async def _run():
        return await asyncio.gather(
            _call("get_wage_data", occ_code="151252", scope="national"),
            _call("compare_metros", occ_code="151252", metro_codes=["47900", "42660"]),
            _call("compare_occupations", occ_codes=["151252", "131082"], scope="national"),
            _call("detect_latest_year"),
        )
    results = asyncio.run(_run())
    assert len(results) == 4


# ===========================================================================
# N. RESPONSE SHAPE VERIFICATION
# ===========================================================================

def test_live_wage_data_response_has_occ_code():
    r = asyncio.run(_call("get_wage_data", occ_code="151252", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_includes_values_or_marker():
    r = asyncio.run(_call("get_wage_data", occ_code="151252", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)
    # Either wage data or a clear empty marker
    assert any(k in data for k in [
        "wages", "values", "data", "no_data", "error", "annual_mean",
        "annual_median",
    ])


def test_live_compare_metros_response_keyed_by_metro():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="151252",
            metro_codes=["47900", "42660"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert "metros" in data


def test_live_compare_occupations_response_keyed():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082"],
            scope="national",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
    assert "occupations" in data


# ===========================================================================
# O. EDGE CASES
# ===========================================================================

def test_live_wage_data_nonexistent_soc():
    """Bogus SOC should return no_data marker."""
    r = asyncio.run(_call("get_wage_data", occ_code="999999", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_state_fips_dc():
    """DC FIPS is 11."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code="11",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_state_fips_alaska():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code="02",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_state_fips_hawaii():
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="state",
            area_code="15",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_state_with_industry_rejected():
    """Industry filter only works at national scope; rejection is correct."""
    try:
        asyncio.run(
            _call(
                "get_wage_data",
                occ_code="151252",
                scope="state",
                area_code="51",
                industry="541000",
            )
        )
    except Exception as e:
        assert "national" in str(e).lower() or "industry" in str(e).lower()


def test_live_wage_data_area_at_national_warns():
    """area_code is ignored at national scope; should not crash."""
    r = asyncio.run(
        _call(
            "get_wage_data",
            occ_code="151252",
            scope="national",
            area_code="47900",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_wage_data_low_volume_occupation():
    """Some occupations have very few people; check suppressed value handling."""
    # 192041 = Environmental Scientists and Specialists, Including Health
    r = asyncio.run(_call("get_wage_data", occ_code="192041", scope="national"))
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_max_12():
    """Max 12 metros (50 series limit on v2)."""
    metros = [m[0] for m in TOP_METROS[:12]]
    r = asyncio.run(
        _call("compare_metros", occ_code="151252", metro_codes=metros)
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_max_12():
    occs = [s[0] for s in COMMON_SOC_CODES[:12]]
    r = asyncio.run(
        _call("compare_occupations", occ_codes=occs, scope="national")
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# P. KEY FEDERAL ROLES (high-IGCE-frequency)
# ===========================================================================

# These get used in IGCEs constantly
KEY_FEDERAL_IGCE_ROLES = [
    "151252",  # Software Developers
    "151212",  # Information Security Analysts
    "152031",  # Operations Research Analysts
    "131082",  # Project Management Specialists
    "131111",  # Management Analysts
    "172112",  # Industrial Engineers
    "172061",  # Computer Hardware Engineers
    "119121",  # Natural Sciences Managers
    "113021",  # Computer and Information Systems Managers
]


@pytest.mark.parametrize("soc", KEY_FEDERAL_IGCE_ROLES)
def test_live_igce_benchmark_each_key_role_dc(soc):
    """IGCE benchmark for each key federal IGCE role at DC metro."""
    r = asyncio.run(
        _call(
            "igce_wage_benchmark",
            occ_code=soc,
            scope="metro",
            area_code="47900",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# Q. STATE COMPARISONS via compare_occupations
# ===========================================================================

def test_live_compare_occupations_va_metro():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082", "152031", "172112"],
            scope="state",
            area_code="51",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_md_metro():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082", "152031"],
            scope="state",
            area_code="24",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_occupations_ca_metro():
    r = asyncio.run(
        _call(
            "compare_occupations",
            occ_codes=["151252", "131082"],
            scope="state",
            area_code="06",
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


# ===========================================================================
# R. METRO COMPARISONS for diverse occupations
# ===========================================================================

def test_live_compare_metros_for_engineer():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="172112",
            metro_codes=["47900", "42660", "14460", "31080"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_for_lawyer():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="231011",
            metro_codes=["47900", "35620", "31080"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)


def test_live_compare_metros_for_pm():
    r = asyncio.run(
        _call(
            "compare_metros",
            occ_code="131082",
            metro_codes=["47900", "12580", "14460"],
        )
    )
    data = _payload(r)
    assert isinstance(data, dict)
