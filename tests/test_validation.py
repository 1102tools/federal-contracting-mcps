# SPDX-License-Identifier: MIT
"""Validation tests for gsa-perdiem-mcp.

All tests route through mcp.call_tool. Live tests (MCP_LIVE_TESTS=1) are
gated and use the minimum number of requests to stay under DEMO_KEY's
~10 req/hr limit.
"""
from __future__ import annotations

import asyncio
import json
import os
import pytest

import gsa_perdiem_mcp.server as srv
from gsa_perdiem_mcp.server import mcp

LIVE = os.environ.get("MCP_LIVE_TESTS") == "1"


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
        assert match.lower() in str(e).lower(), f"expected {match!r}, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_current_fiscal_year_returns_int():
    fy = srv._current_fiscal_year()
    assert isinstance(fy, int)
    assert 2024 <= fy <= 2040


def test_validate_state_rejects_lowercase_non_state():
    with pytest.raises(ValueError, match="USPS"):
        srv._validate_state("zz")


def test_validate_state_accepts_lowercase():
    assert srv._validate_state("ma") == "MA"


def test_validate_state_strips_whitespace():
    assert srv._validate_state(" MA ") == "MA"


def test_validate_state_rejects_digit():
    with pytest.raises(ValueError, match="USPS"):
        srv._validate_state("M1")


def test_validate_state_rejects_none():
    with pytest.raises(ValueError, match="required"):
        srv._validate_state(None)


def test_validate_state_rejects_non_string():
    with pytest.raises(ValueError, match="2-letter"):
        srv._validate_state(42)


def test_validate_state_accepts_dc():
    assert srv._validate_state("DC") == "DC"


def test_validate_state_accepts_territory():
    assert srv._validate_state("PR") == "PR"


def test_validate_zip_accepts_5_digit():
    assert srv._validate_zip("02101") == "02101"


def test_validate_zip_accepts_zip_plus_4():
    assert srv._validate_zip("02101-1234") == "02101"


def test_validate_zip_rejects_4_digit():
    with pytest.raises(ValueError, match="5-digit"):
        srv._validate_zip("1234")


def test_validate_zip_rejects_alpha():
    with pytest.raises(ValueError, match="5-digit"):
        srv._validate_zip("ABCDE")


def test_validate_zip_rejects_empty():
    with pytest.raises(ValueError, match="5-digit"):
        srv._validate_zip("")


def test_validate_zip_rejects_none():
    with pytest.raises(ValueError, match="required"):
        srv._validate_zip(None)


def test_validate_city_rejects_null_byte():
    with pytest.raises(ValueError, match="control"):
        srv._validate_city("Boston\x00")


def test_validate_city_rejects_newline():
    with pytest.raises(ValueError, match="control"):
        srv._validate_city("Boston\n")


def test_validate_city_rejects_slash():
    with pytest.raises(ValueError, match="slash"):
        srv._validate_city("Boston/Cambridge")


def test_validate_city_rejects_backslash():
    with pytest.raises(ValueError, match="slash"):
        srv._validate_city("Boston\\x")


def test_validate_city_rejects_path_traversal():
    with pytest.raises(ValueError, match="'\\.\\.'"):
        srv._validate_city("..")


def test_validate_city_rejects_path_traversal_embedded():
    with pytest.raises(ValueError, match="'\\.\\.'"):
        srv._validate_city("Boston..")


def test_validate_city_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        srv._validate_city("")


def test_validate_city_rejects_whitespace():
    with pytest.raises(ValueError, match="empty"):
        srv._validate_city("   ")


def test_validate_city_rejects_over_100_chars():
    with pytest.raises(ValueError, match="100 chars"):
        srv._validate_city("x" * 200)


def test_validate_city_strips_whitespace():
    assert srv._validate_city("  Boston  ") == "Boston"


def test_validate_city_accepts_period():
    assert srv._validate_city("St. Louis") == "St. Louis"


def test_validate_travel_month_accepts_jan():
    assert srv._validate_travel_month("Jan") == "Jan"


def test_validate_travel_month_normalizes_lowercase():
    assert srv._validate_travel_month("jan") == "Jan"


def test_validate_travel_month_normalizes_full_name():
    assert srv._validate_travel_month("January") == "Jan"


def test_validate_travel_month_rejects_garbage():
    with pytest.raises(ValueError, match="3-letter"):
        srv._validate_travel_month("xyz")


def test_validate_travel_month_rejects_one_char():
    with pytest.raises(ValueError, match="3-letter"):
        srv._validate_travel_month("J")


def test_validate_travel_month_passes_none():
    assert srv._validate_travel_month(None) is None


def test_validate_travel_month_passes_empty_as_none():
    assert srv._validate_travel_month("") is None


def test_validate_fiscal_year_default_is_current():
    fy = srv._validate_fiscal_year(None)
    assert fy == srv._current_fiscal_year()


def test_validate_fiscal_year_rejects_negative():
    with pytest.raises(ValueError, match="out of range"):
        srv._validate_fiscal_year(-1)


def test_validate_fiscal_year_rejects_zero():
    with pytest.raises(ValueError, match="out of range"):
        srv._validate_fiscal_year(0)


def test_validate_fiscal_year_rejects_1900():
    with pytest.raises(ValueError, match="out of range"):
        srv._validate_fiscal_year(1900)


def test_validate_fiscal_year_rejects_far_future():
    with pytest.raises(ValueError, match="out of range"):
        srv._validate_fiscal_year(9999)


def test_validate_fiscal_year_accepts_string_int():
    fy = srv._validate_fiscal_year("2026")
    assert fy == 2026


def test_validate_fiscal_year_rejects_string_non_numeric():
    with pytest.raises(ValueError, match="year like"):
        srv._validate_fiscal_year("abc")


def test_validate_fiscal_year_rejects_bool():
    with pytest.raises(ValueError, match="not bool"):
        srv._validate_fiscal_year(True)


def test_normalize_city_for_url_encodes_slash():
    r = srv._normalize_city_for_url("Boston/Cambridge")
    # slash should be %2F after our override, but slash should not appear
    # in practice city names are validated to reject it. Direct call here
    # ensures _normalize doesn't leak the slash.
    assert "/" not in r


def test_normalize_city_for_url_encodes_path_traversal_dots():
    # Even if validate_city wasn't run, normalize should at least
    # percent-encode the dots-and-slashes so the URL router can't
    # traverse.
    r = srv._normalize_city_for_url("../../admin")
    assert "/" not in r


def test_normalize_city_replaces_apostrophe():
    r = srv._normalize_city_for_url("Martha's Vineyard")
    assert "'" not in r
    assert "%27" not in r
    assert "Martha" in r


# ---------------------------------------------------------------------------
# Tool-level validation (pydantic + handler)
# ---------------------------------------------------------------------------

def test_lookup_city_rejects_empty_city():
    asyncio.run(_call_expect_error("lookup_city_perdiem", "empty", city="", state="MA"))


def test_lookup_city_rejects_bad_state():
    asyncio.run(_call_expect_error("lookup_city_perdiem", "USPS", city="Boston", state="ZZ"))


def test_lookup_city_rejects_path_traversal():
    # '../../admin' has both slashes and '..', either error message is fine.
    asyncio.run(_call_expect_error(
        "lookup_city_perdiem", "slash", city="../../admin", state="MA"
    ))


def test_lookup_city_rejects_dot_dot():
    # Pure '..' with no slash should trip the '..' check.
    asyncio.run(_call_expect_error(
        "lookup_city_perdiem", "'..'", city="Boston..", state="MA"
    ))


def test_lookup_city_rejects_slash_in_city():
    asyncio.run(_call_expect_error(
        "lookup_city_perdiem", "slash", city="Boston/Cambridge", state="MA"
    ))


def test_lookup_city_rejects_null_byte():
    asyncio.run(_call_expect_error(
        "lookup_city_perdiem", "control", city="Boston\x00", state="MA"
    ))


def test_lookup_city_rejects_bad_fy():
    asyncio.run(_call_expect_error(
        "lookup_city_perdiem", "out of range",
        city="Boston", state="MA", fiscal_year=9999,
    ))


def test_lookup_zip_rejects_4_digit():
    asyncio.run(_call_expect_error("lookup_zip_perdiem", "5-digit", zip_code="1234"))


def test_lookup_zip_rejects_alpha():
    asyncio.run(_call_expect_error("lookup_zip_perdiem", "5-digit", zip_code="ABCDE"))


def test_lookup_state_rates_rejects_bad_state():
    asyncio.run(_call_expect_error("lookup_state_rates", "USPS", state="ZZ"))


def test_estimate_travel_cost_rejects_zero_nights():
    asyncio.run(_call_expect_error(
        "estimate_travel_cost", "must be >= 1",
        city="Boston", state="MA", num_nights=0,
    ))


def test_estimate_travel_cost_rejects_huge_nights():
    asyncio.run(_call_expect_error(
        "estimate_travel_cost", "exceeds maximum",
        city="Boston", state="MA", num_nights=10000,
    ))


def test_estimate_travel_cost_rejects_bad_month():
    asyncio.run(_call_expect_error(
        "estimate_travel_cost", "3-letter",
        city="Boston", state="MA", num_nights=3, travel_month="xyz"
    ))


def test_compare_locations_rejects_empty():
    asyncio.run(_call_expect_error("compare_locations", "non-empty", locations=[]))


def test_compare_locations_rejects_too_many():
    asyncio.run(_call_expect_error(
        "compare_locations", "up to",
        locations=[{"city": "Boston", "state": "MA"}] * 30,
    ))


def test_compare_locations_rejects_non_dict_entry():
    asyncio.run(_call_expect_error(
        "compare_locations", "dict",
        locations=["Boston, MA"],
    ))


def test_get_mie_breakdown_rejects_bad_fy():
    asyncio.run(_call_expect_error("get_mie_breakdown", "out of range", fiscal_year=1900))


# ---------------------------------------------------------------------------
# Response-shape defense (offline mocking)
# ---------------------------------------------------------------------------

def _mock_get(response):
    """Replace srv._get with a fake that returns response; return the original."""
    orig = srv._get
    async def fake(path):
        return response
    srv._get = fake
    return orig


def _restore_get(orig):
    srv._get = orig


def test_parse_rate_entry_handles_none_entry():
    r = srv._parse_rate_entry(None)
    assert r["city"] is None
    assert r["county"] == "N/A"
    assert r["meals"] == 0


def test_parse_rate_entry_handles_none_months():
    r = srv._parse_rate_entry({"city": "X", "months": None, "meals": 50})
    assert r["lodging_by_month"] == {}
    assert r["has_monthly_data"] is False


def test_parse_rate_entry_handles_single_month_dict():
    """XML-to-JSON collapse: months.month is a dict, not a list."""
    r = srv._parse_rate_entry({
        "city": "X", "county": "Y", "meals": 50,
        "months": {"month": {"short": "Jan", "value": 100}},
    })
    assert r["lodging_by_month"] == {"Jan": 100}


def test_parse_rate_entry_handles_null_month_value():
    r = srv._parse_rate_entry({
        "city": "X", "county": "Y", "meals": 50,
        "months": {"month": [{"short": "Jan", "value": None}, {"short": "Feb", "value": 100}]},
    })
    assert r["lodging_by_month"]["Jan"] == 0
    assert r["lodging_by_month"]["Feb"] == 100
    assert r["lodging_min"] == 0


def test_parse_rate_entry_handles_string_meals():
    r = srv._parse_rate_entry({"city": "X", "meals": "50"})
    assert r["meals"] == 50


def test_parse_rate_entry_handles_none_meals():
    r = srv._parse_rate_entry({"city": "X", "meals": None})
    assert r["meals"] == 0


def test_parse_rate_entry_handles_missing_city():
    r = srv._parse_rate_entry({"county": "Y", "meals": 50})
    assert r["city"] is None


def test_parse_rate_entry_standard_rate_flag():
    r = srv._parse_rate_entry({"city": "Standard Rate", "meals": 50})
    assert r["is_standard_rate"] is True


def test_parse_rate_entry_non_string_city():
    r = srv._parse_rate_entry({"city": 42, "meals": 10})
    assert r["city"] == "42"


def test_select_best_rate_handles_none_response():
    assert srv._select_best_rate(None) is None


def test_select_best_rate_handles_list_response():
    assert srv._select_best_rate([]) is None


def test_select_best_rate_handles_empty_rates():
    assert srv._select_best_rate({"rates": []}) is None


def test_select_best_rate_handles_none_rate_list():
    assert srv._select_best_rate({"rates": [{"rate": None}]}) is None


def test_select_best_rate_handles_none_entry_in_list():
    r = srv._select_best_rate({"rates": [{"rate": [None, {"city": "X", "meals": 10}]}]})
    assert r["city"] == "X"


def test_select_best_rate_exact_match_wins():
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Other", "meals": 10},
            {"city": "Boston", "meals": 20},
            {"city": "Standard Rate", "meals": 5},
        ]}]},
        query_city="Boston",
    )
    assert r["city"] == "Boston"


def test_select_best_rate_composite_match():
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Boston / Cambridge", "meals": 92},
            {"city": "Standard Rate", "meals": 50},
        ]}]},
        query_city="Boston",
    )
    assert r["city"] == "Boston / Cambridge"


def test_select_best_rate_prefers_nsa_over_standard():
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Standard Rate", "meals": 68},
            {"city": "Some City", "meals": 80},
        ]}]},
    )
    assert r["city"] == "Some City"


def test_lookup_city_handles_empty_api_response():
    """Tool returns friendly error, not a crash, when API returns empty rates."""
    orig = _mock_get({"rates": [], "errors": None})
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="Xyzzyx", state="MA"))
        assert "error" in r
        assert "No rates found" in r["error"]
    finally:
        _restore_get(orig)


def test_lookup_city_handles_none_api_response():
    orig = _mock_get(None)
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="Boston", state="MA"))
        assert "error" in r
    finally:
        _restore_get(orig)


def test_lookup_city_handles_shape_variance():
    """Missing months key, None meals, unusual month values - should not crash."""
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "Boston",
            "county": "Suffolk",
            "meals": None,
            "months": None,
        }]}],
    })
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="Boston", state="MA"))
        assert r["mie_daily"] == 0
        assert "no monthly lodging data" in r["lodging_range"]
    finally:
        _restore_get(orig)


def test_lookup_state_rates_handles_none_response():
    orig = _mock_get(None)
    try:
        r = asyncio.run(srv.lookup_state_rates(state="CA"))
        assert r["nsa_count"] == 0
        assert r["rates"] == []
    finally:
        _restore_get(orig)


def test_lookup_state_rates_filters_out_standard_rate():
    orig = _mock_get({"rates": [{"rate": [
        {"city": "Anchorage", "meals": 80, "months": {"month": [{"short":"Jan","value":100}]}},
        {"city": "Standard Rate", "meals": 68, "months": {"month": [{"short":"Jan","value":110}]}},
    ]}]})
    try:
        r = asyncio.run(srv.lookup_state_rates(state="AK"))
        assert r["nsa_count"] == 1
        assert r["rates"][0]["city"] == "Anchorage"
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_list_response():
    orig = _mock_get([
        {"total": 68, "breakfast": 16, "FirstLastDay": 51},
        {"total": 74, "breakfast": 18},  # missing FirstLastDay
    ])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert len(r["tiers"]) == 2
        # 2nd tier should compute first_last as total * 0.75
        assert r["tiers"][1]["first_last_day_75pct"] == round(74 * 0.75, 2)
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_none_response():
    orig = _mock_get(None)
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"] == []
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_none_tier():
    orig = _mock_get([{"total": 68}, None, {"total": 80}])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert len(r["tiers"]) == 3
        assert r["tiers"][1]["total"] == 0  # None tier coerced to zeros
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_string_total():
    orig = _mock_get([{"total": "68", "breakfast": "16"}])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"][0]["total"] == 68
        assert r["tiers"][0]["breakfast"] == 16
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_single_night():
    """1-night trip = 2 travel days = 2 * first_last_mie."""
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "Boston",
            "meals": 100,
            "months": {"month": [{"short":"Jan","value":200}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(city="Boston", state="MA", num_nights=1))
        assert r["num_nights"] == 1
        assert r["travel_days"] == 2
        # First+last = 2 days at 75% of 100 = 150 total MIE
        assert r["mie_total"] == 150
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_uses_travel_month_rate():
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "Boston",
            "meals": 100,
            "months": {"month": [{"short":"Jan","value":200},{"short":"Jul","value":400}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(
            city="Boston", state="MA", num_nights=3, travel_month="Jul"
        ))
        assert r["nightly_lodging"] == 400
        assert r["rate_month"] == "Jul"
    finally:
        _restore_get(orig)


# ---------------------------------------------------------------------------
# HTTP layer defense
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code=200, text='', content_type='application/json'):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}
    def json(self):
        return json.loads(self.text)
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)


def _install_fake_client(resp_or_exc):
    class FC:
        is_closed = False
        async def get(self, url):
            if isinstance(resp_or_exc, Exception):
                raise resp_or_exc
            return resp_or_exc
    srv._client = FC()


def test_get_handles_html_200():
    _install_fake_client(_FakeResp(200, "<html>maint</html>", "text/html"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        asyncio.run(srv._get("x"))


def test_get_handles_empty_200():
    _install_fake_client(_FakeResp(200, "", "application/json"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        asyncio.run(srv._get("x"))


def test_get_handles_truncated_json():
    _install_fake_client(_FakeResp(200, "{\"rates\":[{", "application/json"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        asyncio.run(srv._get("x"))


def test_get_handles_timeout():
    import httpx
    _install_fake_client(httpx.TimeoutException("timed out"))
    with pytest.raises(RuntimeError, match="Network error"):
        asyncio.run(srv._get("x"))


def test_get_formats_403():
    _install_fake_client(_FakeResp(403, "{}", "application/json"))
    with pytest.raises(RuntimeError, match="API key rejected"):
        asyncio.run(srv._get("x"))


def test_get_formats_429():
    _install_fake_client(_FakeResp(429, '{"error":{}}', "application/json"))
    with pytest.raises(RuntimeError, match="Rate limited"):
        asyncio.run(srv._get("x"))


def test_get_formats_500():
    _install_fake_client(_FakeResp(500, "internal error", "text/plain"))
    with pytest.raises(RuntimeError, match="server error"):
        asyncio.run(srv._get("x"))


def test_format_error_handles_bytes():
    msg = srv._format_error(500, b"<html>oops</html>")
    assert "HTTP 500" in msg


def test_format_error_handles_none():
    assert "HTTP 500" in srv._format_error(500, None)


def test_clean_error_body_strips_html():
    r = srv._clean_error_body("<html><head><title>Err 500</title></head></html>")
    assert "Err 500" in r
    assert "<html>" not in r


def test_get_api_key_uses_env(monkeypatch):
    monkeypatch.setenv("PERDIEM_API_KEY", "test-key-123")
    assert srv._get_api_key() == "test-key-123"


def test_get_api_key_falls_back_to_demo(monkeypatch):
    monkeypatch.delenv("PERDIEM_API_KEY", raising=False)
    assert srv._get_api_key() == "DEMO_KEY"


def test_get_api_key_strips_whitespace_and_falls_back(monkeypatch):
    monkeypatch.setenv("PERDIEM_API_KEY", "   ")
    assert srv._get_api_key() == "DEMO_KEY"


# ---------------------------------------------------------------------------
# LIVE tests (require real API calls; gated to stay under rate limits)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_lookup_boston():
    r = asyncio.run(_call("lookup_city_perdiem", city="Boston", state="MA"))
    data = _payload(r)
    assert "Boston" in (data.get("matched_city") or "")
    assert data.get("mie_daily", 0) > 0


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_state_rates_ma():
    r = asyncio.run(_call("lookup_state_rates", state="MA"))
    data = _payload(r)
    assert data.get("nsa_count", 0) > 5


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_mie_breakdown():
    r = asyncio.run(_call("get_mie_breakdown"))
    data = _payload(r)
    tiers = data.get("tiers", [])
    assert len(tiers) >= 5
    assert all(t.get("total", 0) > 0 for t in tiers)


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_typographic_apostrophe_matches_exact():
    """Regression from round 6 P1: U+2019 apostrophe used to silently match Andover."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Martha\u2019s Vineyard", state="MA"))
    data = _payload(r)
    assert "Martha" in (data.get("matched_city") or "")
    assert "Vineyard" in (data.get("matched_city") or "")
    assert data.get("match_type") == "exact"


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_unmatched_city_flagged():
    """Regression from round 6 P1: querying a city not in any NSA used to
    silently return the first NSA with no warning."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Santa Rosa Beach", state="FL"))
    data = _payload(r)
    assert data.get("match_type") in ("standard_fallback", "unmatched_nsa")
    assert data.get("match_note")  # must have explanatory note


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_st_louis_no_period_matches():
    """'St Louis' without period should normalize-match 'St. Louis'."""
    r = asyncio.run(_call("lookup_city_perdiem", city="St Louis", state="MO"))
    data = _payload(r)
    assert "Louis" in (data.get("matched_city") or "")
    assert data.get("match_type") == "exact"


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_winston_salem_returns_standard():
    """Winston-Salem is not a listed NSA; should return Standard Rate with
    a fallback flag rather than silently matching a random NSA."""
    r = asyncio.run(_call("lookup_city_perdiem", city="Winston-Salem", state="NC"))
    data = _payload(r)
    assert data.get("matched_city") == "Standard Rate"
    assert data.get("match_type") == "standard_fallback"


@pytest.mark.skipif(not LIVE, reason="requires MCP_LIVE_TESTS=1")
def test_live_estimate_travel_cost():
    r = asyncio.run(_call(
        "estimate_travel_cost",
        city="Boston", state="MA", num_nights=3, travel_month="Jul",
    ))
    data = _payload(r)
    assert data.get("grand_total", 0) > 100
    assert data.get("rate_month") == "Jul"


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------

def test_safe_dict_returns_empty_for_none():
    assert srv._safe_dict(None) == {}


def test_safe_dict_returns_empty_for_list():
    assert srv._safe_dict([1, 2]) == {}


def test_safe_dict_passes_dict():
    assert srv._safe_dict({"a": 1}) == {"a": 1}


def test_as_list_passes_list():
    assert srv._as_list([1, 2]) == [1, 2]


def test_as_list_wraps_dict():
    assert srv._as_list({"a": 1}) == [{"a": 1}]


def test_as_list_empty_for_none():
    assert srv._as_list(None) == []


def test_as_list_wraps_scalar():
    assert srv._as_list(42) == [42]


def test_safe_int_handles_null_string():
    assert srv._safe_int("null") == 0
    assert srv._safe_int("None") == 0
    assert srv._safe_int("") == 0


def test_safe_int_handles_string_int():
    assert srv._safe_int("42") == 42


def test_safe_int_returns_default_for_garbage():
    assert srv._safe_int("abc", default=999) == 999


def test_safe_number_filters_nan():
    assert srv._safe_number(float("nan")) == 0.0


def test_safe_number_filters_inf():
    assert srv._safe_number(float("inf")) == 0.0
    assert srv._safe_number(float("-inf")) == 0.0


def test_safe_number_passes_float():
    assert srv._safe_number(3.14) == 3.14


def test_safe_number_passes_int():
    assert srv._safe_number(5) == 5.0


def test_parse_rate_entry_skips_month_with_no_short():
    r = srv._parse_rate_entry({
        "city": "X",
        "months": {"month": [{"value": 100}, {"short": "Jan", "value": 200}]},
    })
    assert "Jan" in r["lodging_by_month"]
    assert len(r["lodging_by_month"]) == 1


def test_parse_rate_entry_skips_empty_short():
    r = srv._parse_rate_entry({
        "city": "X",
        "months": {"month": [{"short": "", "value": 100}]},
    })
    assert r["lodging_by_month"] == {}


def test_parse_rate_entry_with_null_months_dict():
    r = srv._parse_rate_entry({"city": "X", "months": {"month": None}})
    assert r["lodging_by_month"] == {}


def test_parse_rate_entry_non_dict_county():
    r = srv._parse_rate_entry({"city": "X", "county": 42, "meals": 10})
    assert r["county"] == "N/A"


def test_select_best_rate_query_city_no_match_prefers_standard():
    """When query doesn't match any NSA, prefer Standard Rate over random NSA.
    This was a P1 silent-wrong bug found during live audit (round 6)."""
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Other", "meals": 10},
            {"city": "Standard Rate", "meals": 5},
        ]}]},
        query_city="Boston",
    )
    assert r["city"] == "Standard Rate"
    assert r["match_type"] == "standard_fallback"


def test_select_best_rate_query_no_match_no_standard_flags_unmatched():
    """When no Standard Rate is returned AND query doesn't match, flag the
    fallback clearly so the caller doesn't silently accept wrong data."""
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Other", "meals": 10},
        ]}]},
        query_city="Boston",
    )
    assert r["city"] == "Other"
    assert r["match_type"] == "unmatched_nsa"


def test_select_best_rate_typographic_apostrophe_matches():
    """P1 fix from round 6: 'Martha\u2019s Vineyard' must match the API's
    'Martha's Vineyard' (ASCII apostrophe) after normalization."""
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Andover", "meals": 80, "months": {"month": [{"short":"Jan","value":137}]}},
            {"city": "Martha's Vineyard", "meals": 92, "months": {"month": [{"short":"Jan","value":196}]}},
        ]}]},
        query_city="Martha\u2019s Vineyard",  # typographic (U+2019)
    )
    assert r["city"] == "Martha's Vineyard"
    assert r["match_type"] == "exact"


def test_select_best_rate_punctuation_insensitive_match():
    """'St Louis' (no period) should match 'St. Louis' via normalization."""
    r = srv._select_best_rate(
        {"rates": [{"rate": [
            {"city": "Kansas City", "meals": 80, "months": {"month": [{"short":"Jan","value":135}]}},
            {"city": "St. Louis", "meals": 86, "months": {"month": [{"short":"Jan","value":150}]}},
        ]}]},
        query_city="St Louis",
    )
    assert r["city"] == "St. Louis"
    assert r["match_type"] == "exact"


def test_select_best_rate_match_types_labeled():
    """All match_type values should be populated in returned rate dict."""
    # exact
    r = srv._select_best_rate(
        {"rates": [{"rate": [{"city": "X", "meals": 10}]}]},
        query_city="X",
    )
    assert r["match_type"] == "exact"
    # composite
    r = srv._select_best_rate(
        {"rates": [{"rate": [{"city": "X / Y", "meals": 10}]}]},
        query_city="X",
    )
    assert r["match_type"] == "composite"
    # no query: first_nsa
    r = srv._select_best_rate(
        {"rates": [{"rate": [{"city": "X", "meals": 10}]}]},
    )
    assert r["match_type"] == "first_nsa"


def test_select_best_rate_only_standard_rate_returns_standard():
    r = srv._select_best_rate(
        {"rates": [{"rate": [{"city": "Standard Rate", "meals": 50}]}]},
    )
    # No NSAs, falls back to parsed[0] which IS the standard rate
    assert r["is_standard_rate"] is True


def test_select_best_rate_case_insensitive_match():
    r = srv._select_best_rate(
        {"rates": [{"rate": [{"city": "BOSTON", "meals": 20}]}]},
        query_city="boston",
    )
    assert r["city"] == "BOSTON"


def test_normalize_city_collapses_multiple_spaces():
    r = srv._normalize_city_for_url("Boston   Cambridge")
    assert r.count("%20") == 1


def test_normalize_city_handles_curly_apostrophe():
    # Typographic apostrophe U+2019
    r = srv._normalize_city_for_url("Martha\u2019s Vineyard")
    assert "%E2%80%99" not in r


def test_normalize_city_encodes_period():
    # Periods encoded with safe=''
    r = srv._normalize_city_for_url("St. Louis")
    assert r == "St.%20Louis" or r == "St%2E%20Louis"


def test_format_lodging_range_no_data():
    r = srv._format_lodging_range({
        "lodging_min": 0, "lodging_max": 0,
        "has_monthly_data": False, "has_seasonal_variation": False,
    })
    assert "no monthly" in r


def test_format_lodging_range_flat_rate():
    r = srv._format_lodging_range({
        "lodging_min": 150, "lodging_max": 150,
        "has_monthly_data": True, "has_seasonal_variation": False,
    })
    assert r == "$150/night"


def test_format_lodging_range_seasonal():
    r = srv._format_lodging_range({
        "lodging_min": 150, "lodging_max": 250,
        "has_monthly_data": True, "has_seasonal_variation": True,
    })
    assert r == "$150-$250/night"


def test_compare_locations_fails_fast_on_bad_entry_shape():
    """Non-dict entry in locations list should raise validation error from pydantic
    before any HTTP call happens."""
    async def _run():
        try:
            await mcp.call_tool("compare_locations", {"locations": ["Boston, MA"]})
        except Exception as e:
            assert "dict" in str(e).lower()
            return
        raise AssertionError("expected dict validation error")
    asyncio.run(_run())


def test_compare_locations_records_invalid_items_not_raises():
    """One invalid city entry should produce a result row with error, not halt."""
    orig = _mock_get({"rates": [{"rate": [{"city": "Boston / Cambridge", "meals": 92,
                                           "months": {"month": [{"short":"Jan","value":200}]}}]}]})
    try:
        r = asyncio.run(srv.compare_locations(locations=[
            {"city": "Boston", "state": "MA"},
            {"city": "", "state": "MA"},  # will be recorded as error
            {"city": "Boston..", "state": "MA"},  # will be recorded as error
        ]))
        locs = r["locations"]
        # Bad ones become error entries
        errors = [l for l in locs if "error" in l]
        oks = [l for l in locs if "error" not in l]
        assert len(errors) == 2
        assert len(oks) == 1
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_uses_max_when_month_unknown_to_data():
    """Asking for Jul in a dataset that only has Jan should fall back to max."""
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "X", "meals": 80,
            "months": {"month": [{"short": "Jan", "value": 150}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(
            city="X", state="MA", num_nights=5, travel_month="Jul",
        ))
        # Falls back to lodging_max since Jul not in data
        assert r["nightly_lodging"] == 150
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_two_nights_math():
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "X", "meals": 100,
            "months": {"month": [{"short":"Jan","value":200}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(city="X", state="MA", num_nights=2))
        # 2 nights = 3 travel days = 1 full + 2 first/last
        # Full MIE 100 + 2 * (100*0.75) = 100 + 150 = 250
        assert r["mie_total"] == 250
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_365_nights_ok():
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "X", "meals": 50,
            "months": {"month": [{"short":"Jan","value":100}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(
            city="X", state="MA", num_nights=365,
        ))
        assert r["num_nights"] == 365
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_empty_list():
    orig = _mock_get([])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"] == []
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_missing_first_last():
    orig = _mock_get([{"total": 100, "breakfast": 20, "lunch": 25, "dinner": 50, "incidental": 5}])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"][0]["first_last_day_75pct"] == 75.0
    finally:
        _restore_get(orig)


def test_mie_breakdown_handles_string_totals():
    orig = _mock_get([{"total": "68", "FirstLastDay": "51"}])
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"][0]["total"] == 68.0
        assert r["tiers"][0]["first_last_day_75pct"] == 51.0
    finally:
        _restore_get(orig)


def test_concurrent_client_reuse():
    """Multiple concurrent calls on a mocked client shouldn't collide."""
    orig = _mock_get({"rates": [{"rate": [{"city":"X","meals":50,"months":{"month":[{"short":"Jan","value":100}]}}]}]})
    try:
        async def _run():
            return await asyncio.gather(
                srv.lookup_city_perdiem(city="X", state="MA"),
                srv.lookup_city_perdiem(city="X", state="MA"),
                srv.lookup_city_perdiem(city="X", state="MA"),
            )
        results = asyncio.run(_run())
        assert all(r.get("matched_city") == "X" for r in results)
    finally:
        _restore_get(orig)


def test_lookup_zip_treats_zip_plus_4_equivalently():
    orig = _mock_get({"rates": [{"rate": [
        {"city": "Boston", "meals": 92, "months": {"month": [{"short":"Jan","value":200}]}},
    ]}]})
    try:
        r1 = asyncio.run(srv.lookup_zip_perdiem(zip_code="02101"))
        r2 = asyncio.run(srv.lookup_zip_perdiem(zip_code="02101-1234"))
        assert r1["zip_code"] == r2["zip_code"] == "02101"
    finally:
        _restore_get(orig)




def test_compare_locations_single_item():
    orig = _mock_get({"rates": [{"rate": [{"city":"Boston","meals":92,"months":{"month":[{"short":"Jan","value":200}]}}]}]})
    try:
        r = asyncio.run(srv.compare_locations(locations=[{"city":"Boston","state":"MA"}]))
        assert len(r["locations"]) == 1
        assert r["locations"][0]["lodging_max"] == 200
    finally:
        _restore_get(orig)


def test_compare_locations_sorts_by_max_daily():
    """Highest max_daily_total should come first."""
    call_count = {"n": 0}
    responses = [
        {"rates": [{"rate": [{"city":"A","meals":50,"months":{"month":[{"short":"Jan","value":100}]}}]}]},
        {"rates": [{"rate": [{"city":"B","meals":80,"months":{"month":[{"short":"Jan","value":200}]}}]}]},
    ]
    async def fake(path):
        r = responses[call_count["n"]]
        call_count["n"] += 1
        return r
    orig = srv._get
    srv._get = fake
    try:
        r = asyncio.run(srv.compare_locations(locations=[
            {"city":"A","state":"CA"},
            {"city":"B","state":"CA"},
        ]))
        # B has 200+80=280 > A's 100+50=150
        assert r["locations"][0]["max_daily_total"] == 280
        assert r["locations"][1]["max_daily_total"] == 150
    finally:
        srv._get = orig


def test_parse_rate_entry_non_string_city_stringified():
    r = srv._parse_rate_entry({"city": None, "meals": 50})
    assert r["city"] is None


def test_validate_state_accepts_vi_territory():
    assert srv._validate_state("VI") == "VI"


def test_validate_state_rejects_3_letter_country_code():
    with pytest.raises(ValueError, match="USPS"):
        srv._validate_state("USA")


def test_validate_city_accepts_hyphen():
    # Hyphens allowed; normalize_city will convert to spaces
    assert srv._validate_city("Winston-Salem") == "Winston-Salem"


def test_validate_city_accepts_apostrophe():
    assert srv._validate_city("Martha's Vineyard") == "Martha's Vineyard"


def test_normalize_city_hyphen_becomes_space():
    r = srv._normalize_city_for_url("Winston-Salem")
    assert "-" not in r
    assert "%20" in r


def test_lookup_city_handles_rate_none():
    """Verify handoff-style bug: rate list None (not [])."""
    orig = _mock_get({"rates": [{"rate": None}]})
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="MA"))
        assert "error" in r
    finally:
        _restore_get(orig)


def test_lookup_city_handles_rates_as_empty_list():
    orig = _mock_get({"rates": [], "errors": None})
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="MA"))
        assert "error" in r
    finally:
        _restore_get(orig)


def test_lookup_city_handles_rates_missing_key():
    orig = _mock_get({"errors": None})  # no 'rates' key at all
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="MA"))
        assert "error" in r
    finally:
        _restore_get(orig)


def test_lookup_state_rates_handles_only_standard():
    """State with only standard rate returns empty NSA list."""
    orig = _mock_get({"rates": [{"rate": [{"city":"Standard Rate","meals":68,"months":{"month":[{"short":"Jan","value":110}]}}]}]})
    try:
        r = asyncio.run(srv.lookup_state_rates(state="WV"))
        assert r["nsa_count"] == 0
    finally:
        _restore_get(orig)


def test_get_handles_non_dict_non_list_json():
    """If API returns a JSON number or string, _get passes it through; callers should handle."""
    # This isn't caught by _get itself; downstream defensive parsing handles it.
    # Assert by mocking a bare-int response and confirming lookup_city returns error.
    orig = _mock_get(42)
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="MA"))
        assert "error" in r
    finally:
        _restore_get(orig)


def test_get_api_key_is_url_encoded(monkeypatch):
    """A hypothetical key containing '&' should not break the URL."""
    monkeypatch.setenv("PERDIEM_API_KEY", "abc&def")
    key = srv._get_api_key()
    # The key is stored as raw; URL encoding happens inside _get.
    assert key == "abc&def"
    # Verify the encoded version a _get call would use
    import urllib.parse as up
    encoded = up.quote(key, safe="-")
    assert encoded == "abc%26def"


def test_get_api_key_strips_surrounding_spaces_live(monkeypatch):
    monkeypatch.setenv("PERDIEM_API_KEY", "  abc123  ")
    assert srv._get_api_key() == "abc123"


def test_mie_breakdown_handles_dict_with_unknown_key():
    """API returns dict without mieData or rates; should return empty list."""
    orig = _mock_get({"someOtherKey": "value"})
    try:
        r = asyncio.run(srv.get_mie_breakdown())
        assert r["tiers"] == []
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_200_night_trip():
    orig = _mock_get({
        "rates": [{"rate": [{
            "city": "X", "meals": 100,
            "months": {"month": [{"short":"Jan","value":200}]},
        }]}],
    })
    try:
        r = asyncio.run(srv.estimate_travel_cost(
            city="X", state="MA", num_nights=200,
        ))
        assert r["num_nights"] == 200
        assert r["lodging_total"] == 40000
    finally:
        _restore_get(orig)


def test_estimate_travel_cost_clamps_num_nights_366():
    with pytest.raises(Exception, match="exceeds maximum"):
        asyncio.run(_call("estimate_travel_cost",
                          city="Boston", state="MA", num_nights=366))


def test_compare_locations_preserves_fiscal_year_in_output():
    orig = _mock_get({"rates": [{"rate": [{
        "city":"X","meals":50,"months":{"month":[{"short":"Jan","value":100}]},
    }]}]})
    try:
        r = asyncio.run(srv.compare_locations(
            locations=[{"city":"X","state":"MA"}], fiscal_year=2025,
        ))
        assert r["fiscal_year"] == 2025
    finally:
        _restore_get(orig)


def test_fiscal_year_default_matches_current():
    """Default FY should match the computed current fiscal year."""
    orig = _mock_get({"rates": [{"rate": [{
        "city":"X","meals":50,"months":{"month":[{"short":"Jan","value":100}]},
    }]}]})
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="MA"))
        assert r["query"]["fiscal_year"] == srv._current_fiscal_year()
    finally:
        _restore_get(orig)


def test_lookup_city_trims_and_uppercases_state():
    orig = _mock_get({"rates": [{"rate": [
        {"city":"X","meals":50,"months":{"month":[{"short":"Jan","value":100}]}},
    ]}]})
    try:
        r = asyncio.run(srv.lookup_city_perdiem(city="X", state="  ma  "))
        assert r["query"]["state"] == "MA"
    finally:
        _restore_get(orig)
