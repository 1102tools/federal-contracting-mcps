# SPDX-License-Identifier: MIT
"""Regression tests for 0.2.0 hardening fixes.

Goes through the FastMCP registry (mcp.call_tool) so pydantic type coercion
runs exactly as in production. The prior stress_test.py awaited raw coroutines
and bypassed the tool pipeline, missing most of the crash and silent-wrong-data
paths fixed here.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from bls_oews_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("BLS_LIVE_TESTS") == "1"


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
# SOC code validation (consistent across all tools)
# ---------------------------------------------------------------------------

def test_get_wage_data_soc_with_dash():
    asyncio.run(_call_expect_error("get_wage_data", "only ASCII digits", occ_code="15-1252"))


def test_compare_metros_soc_with_dash():
    asyncio.run(_call_expect_error(
        "compare_metros", "only ASCII digits",
        occ_code="15-125", metro_codes=["47900"]
    ))


def test_compare_occupations_soc_with_dash():
    asyncio.run(_call_expect_error(
        "compare_occupations", "only ASCII digits",
        occ_codes=["15-125", "13-108"]
    ))


def test_soc_letters_rejected():
    asyncio.run(_call_expect_error("get_wage_data", "only ASCII digits", occ_code="ABCDEF"))


def test_soc_fullwidth_digits_rejected():
    """Python .isdigit() accepts fullwidth digits; our regex doesn't."""
    asyncio.run(_call_expect_error("get_wage_data", "only ASCII digits", occ_code="1512\uff15\u0032"))


def test_soc_too_short_rejected():
    asyncio.run(_call_expect_error("get_wage_data", "exactly 6 digits", occ_code="12345"))


def test_soc_accepts_int():
    """Users naturally pass SOC as int; we coerce."""
    try:
        asyncio.run(_call("get_wage_data", occ_code=151252))
    except Exception as e:
        assert "only ASCII digits" not in str(e), f"int SOC wrongly rejected: {e}"


# ---------------------------------------------------------------------------
# Area code validation
# ---------------------------------------------------------------------------

def test_area_code_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", scope="state", area_code="VA"
    ))


def test_area_code_7char_non_digit_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", scope="state", area_code="abcdefg"
    ))


def test_area_code_accepts_int():
    """User passes area_code=51 as int."""
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", scope="state", area_code=51))
    except Exception as e:
        assert "only ASCII digits" not in str(e)
        assert "type" not in str(e).lower() or "bool" in str(e).lower()


def test_area_code_empty_string():
    asyncio.run(_call_expect_error(
        "get_wage_data", "required",
        occ_code="151252", scope="state", area_code=""
    ))


# ---------------------------------------------------------------------------
# Industry validation
# ---------------------------------------------------------------------------

def test_industry_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", industry="54100A"
    ))


def test_industry_whitespace_stripped():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", industry="   000000   "))
    except Exception as e:
        assert "only ASCII digits" not in str(e), f"whitespace not stripped: {e}"


# ---------------------------------------------------------------------------
# Datatype validation
# ---------------------------------------------------------------------------

def test_bogus_datatype_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "not a known OEWS datatype",
        occ_code="151252", datatypes=["99"]
    ))


def test_datatype_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "only ASCII digits",
        occ_code="151252", datatypes=["AA"]
    ))


def test_compare_metros_bogus_datatype():
    asyncio.run(_call_expect_error(
        "compare_metros", "not a known OEWS datatype",
        occ_code="151252", metro_codes=["47900"], datatype="99"
    ))


def test_empty_datatypes_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "datatypes cannot be empty",
        occ_code="151252", datatypes=[]
    ))


def test_datatype_accepts_int():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", datatypes=[4]))
    except Exception as e:
        assert "not a known" not in str(e) and "only ASCII" not in str(e)


# ---------------------------------------------------------------------------
# Year validation
# ---------------------------------------------------------------------------

def test_year_decimal_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="2024.5"
    ))


def test_year_whitespace_stripped():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", year="  2024  "))
    except Exception as e:
        assert "4-digit year" not in str(e)


def test_year_leading_zero_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="02024"
    ))


def test_year_too_old_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "out of OEWS range",
        occ_code="151252", year="1990"
    ))


def test_year_too_new_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "out of OEWS range",
        occ_code="151252", year=2500
    ))


def test_year_accepts_int():
    try:
        asyncio.run(_call("get_wage_data", occ_code="151252", year=2024))
    except Exception as e:
        assert "4-digit year" not in str(e)


def test_year_letters_rejected():
    asyncio.run(_call_expect_error(
        "get_wage_data", "4-digit year",
        occ_code="151252", year="abcd"
    ))


# ---------------------------------------------------------------------------
# IGCE burden validation
# ---------------------------------------------------------------------------

def test_igce_burden_low_greater_than_high():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be <= burden_high",
        occ_code="151252", burden_low=3.0, burden_high=1.5
    ))


def test_igce_burden_negative():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be positive",
        occ_code="151252", burden_low=-1.0, burden_high=2.0
    ))


def test_igce_burden_zero():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "must be positive",
        occ_code="151252", burden_low=0, burden_high=0
    ))


def test_igce_burden_extreme():
    asyncio.run(_call_expect_error(
        "igce_wage_benchmark", "implausibly large",
        occ_code="151252", burden_high=50.0
    ))


# ---------------------------------------------------------------------------
# Response-shape defensive parsing (crash regressions)
# ---------------------------------------------------------------------------

def test_as_list_helper():
    from bls_oews_mcp.server import _as_list
    assert _as_list(None) == []
    assert _as_list([]) == []
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list({"foo": "bar"}) == [{"foo": "bar"}]
    # Non-dict/list scalars return empty list (safer than wrapping)
    assert _as_list("string") == []
    assert _as_list(42) == []


def test_parse_value_handles_none():
    from bls_oews_mcp.server import _parse_value
    out = _parse_value(None, "04")
    assert out["numeric"] is None
    assert out["suppressed"] is True


def test_parse_value_strips_whitespace_special_values():
    """Round 1 finding: '  *  ' was marked Unparseable, should be Suppressed."""
    from bls_oews_mcp.server import _parse_value
    out = _parse_value("  *  ", "04")
    assert out["suppressed"] is True


def test_parse_value_empty_string_suppressed():
    from bls_oews_mcp.server import _parse_value
    out = _parse_value("", "04")
    assert out["suppressed"] is True


def test_extract_first_data_entry():
    from bls_oews_mcp.server import _extract_first_data_entry
    assert _extract_first_data_entry(None) is None
    assert _extract_first_data_entry({"data": None}) is None
    assert _extract_first_data_entry({"data": []}) is None
    assert _extract_first_data_entry({"data": [None, None]}) is None
    assert _extract_first_data_entry({"data": {"value": "1"}}) == {"value": "1"}
    assert _extract_first_data_entry({"data": [{"value": "1"}]}) == {"value": "1"}


def test_safe_footnotes_handles_weird_shapes():
    from bls_oews_mcp.server import _safe_footnotes
    assert _safe_footnotes({"footnotes": None}) == []
    assert _safe_footnotes({"footnotes": "single string"}) == ["single string"]
    assert _safe_footnotes({"footnotes": {"text": "dict-collapse"}}) == ["dict-collapse"]
    assert _safe_footnotes({"footnotes": [{"text": "a"}, {"text": ""}, {"nope": "x"}]}) == ["a"]


def test_series_id_from_handles_int():
    """Round 5: seriesID returned as int crashed on sid[-2:]."""
    from bls_oews_mcp.server import _series_id_from
    assert _series_id_from({"seriesID": 151252}) == "151252"
    assert _series_id_from({"seriesID": None}) == ""
    assert _series_id_from({}) == ""
    assert _series_id_from(None) == ""


def test_get_wage_data_with_dict_series_doesnt_crash():
    """Integration: fake BLS returning series-as-dict (XML collapse)."""
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": {"seriesID": series_ids[0], "data": [{"value": "144570", "year": 2024, "periodName": "Annual"}]}}}

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
        assert "wages" in result
    finally:
        S._query_bls = orig


def test_get_wage_data_with_missing_value_key():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [{"seriesID": series_ids[0], "data": [{"year": "2024", "periodName": "Annual"}]}]}}

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        # Should not crash; value=None flows through _parse_value
        assert isinstance(result, dict)
    finally:
        S._query_bls = orig


def test_get_wage_data_with_none_series_entries():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [None, {"seriesID": series_ids[0], "data": [{"value": "100", "year": "2024", "periodName": "Annual"}]}]}}

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
    finally:
        S._query_bls = orig


def test_get_wage_data_with_footnotes_as_dict():
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": [{"seriesID": series_ids[0], "data": [{"value": "144570", "year": "2024", "periodName": "Annual", "footnotes": {"text": "cap"}}]}]}}

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert isinstance(result, dict)
    finally:
        S._query_bls = orig


def test_query_bls_handles_non_json_200():
    """Round 5: JSONDecodeError from 200 with HTML body."""
    import bls_oews_mcp.server as S
    import httpx

    class FakeClient:
        async def post(self, *args, **kw):
            return httpx.Response(200, content=b"<html>oops</html>", request=httpx.Request("POST", args[0]))

    orig = S._get_client
    S._get_client = lambda: FakeClient()
    try:
        try:
            asyncio.run(S._query_bls(["OEUN000000000000000000004"]))
            raise AssertionError("expected RuntimeError on non-JSON 200")
        except RuntimeError as e:
            assert "non-JSON" in str(e)
    finally:
        S._get_client = orig


def test_query_bls_handles_partially_processed():
    """REQUEST_PARTIALLY_PROCESSED should surface warnings."""
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {
            "status": "REQUEST_PARTIALLY_PROCESSED",
            "message": ["Series not found: X"],
            "_partial": True,
            "_warnings": ["Series not found: X"],
            "Results": {"series": [{"seriesID": series_ids[0], "data": []}]},
        }

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252"))
        assert result.get("_partial") is True
        assert result.get("_warnings") == ["Series not found: X"]
    finally:
        S._query_bls = orig


# ---------------------------------------------------------------------------
# National scope + area_code interaction
# ---------------------------------------------------------------------------

def test_national_scope_area_code_flagged():
    """area_code with scope=national should at least produce a _note."""
    import bls_oews_mcp.server as S

    async def fake_query(series_ids, start_year=None, end_year=None):
        return {"Results": {"series": []}}

    orig = S._query_bls
    S._query_bls = fake_query
    try:
        result = asyncio.run(S.get_wage_data(occ_code="151252", scope="national", area_code="51"))
        assert "_note" in result
        assert "area_code" in result["_note"]
    finally:
        S._query_bls = orig


# ---------------------------------------------------------------------------
# Dedup across compare tools
# ---------------------------------------------------------------------------

def test_compare_metros_dedup():
    """Passing the same metro twice should only produce one series query."""
    import bls_oews_mcp.server as S

    captured: list[list[str]] = []
    async def capture_query(series_ids, start_year=None, end_year=None):
        captured.append(list(series_ids))
        return {"Results": {"series": []}}

    orig = S._query_bls
    S._query_bls = capture_query
    try:
        asyncio.run(S.compare_metros(occ_code="151252", metro_codes=["47900", "47900", "47900"]))
        assert len(captured) == 1
        assert len(captured[0]) == 1, f"expected dedup to 1 series, got {len(captured[0])}"
    finally:
        S._query_bls = orig


def test_compare_occupations_dedup():
    import bls_oews_mcp.server as S

    captured: list[list[str]] = []
    async def capture_query(series_ids, start_year=None, end_year=None):
        captured.append(list(series_ids))
        return {"Results": {"series": []}}

    orig = S._query_bls
    S._query_bls = capture_query
    try:
        asyncio.run(S.compare_occupations(occ_codes=["151252", "151252", "151252"]))
        assert len(captured[0]) == 1, f"expected dedup, got {len(captured[0])}"
    finally:
        S._query_bls = orig


# ---------------------------------------------------------------------------
# Error hygiene
# ---------------------------------------------------------------------------

def test_clean_error_body_strips_html():
    from bls_oews_mcp.server import _clean_error_body
    html = '<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body><h1>API_KEY_INVALID</h1></body></html>'
    result = _clean_error_body(html)
    assert "<" not in result
    assert "403 Forbidden" in result or "API_KEY_INVALID" in result


def test_clean_error_body_passthrough_non_html():
    from bls_oews_mcp.server import _clean_error_body
    assert _clean_error_body('{"error":"nope"}') == '{"error":"nope"}'


# ---------------------------------------------------------------------------
# USER_AGENT
# ---------------------------------------------------------------------------

def test_user_agent_matches_version():
    from bls_oews_mcp.constants import USER_AGENT
    assert "0.2.1" in USER_AGENT, f"USER_AGENT stale: {USER_AGENT}"


def test_api_key_status_whitespace_flagged():
    from bls_oews_mcp.server import _api_key_status
    import os
    os.environ["BLS_API_KEY"] = "   "
    try:
        status = _api_key_status()
        assert status["set"] is True
        assert status["mode"] == "v1"
        assert "whitespace" in status["note"].lower() or "empty" in status["note"].lower()
    finally:
        del os.environ["BLS_API_KEY"]


# ---------------------------------------------------------------------------
# Datatype label semantic fix (round 1 finding)
# ---------------------------------------------------------------------------

def test_datatype_08_labeled_as_25th():
    """Empirical BLS data: dt 08 returns Hourly 25th Pct, not Hourly Median."""
    from bls_oews_mcp.constants import DATATYPE_LABELS
    assert DATATYPE_LABELS["08"] == "Hourly 25th Percentile"


def test_datatype_09_labeled_as_hourly_median():
    from bls_oews_mcp.constants import DATATYPE_LABELS
    assert DATATYPE_LABELS["09"] == "Hourly Median"


def test_datatype_labels_have_missing_codes():
    from bls_oews_mcp.constants import DATATYPE_LABELS
    for code in ["07", "09", "10"]:
        assert code in DATATYPE_LABELS, f"missing label for datatype {code}"


# ---------------------------------------------------------------------------
# Live tests (opt-in)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set BLS_LIVE_TESTS=1 to run live API calls")
def test_live_software_developers_national():
    result = asyncio.run(_call("get_wage_data", occ_code="151252"))
    payload = _payload(result)
    assert "wages" in payload
    mean = payload["wages"].get("Annual Mean Wage", {})
    assert mean.get("numeric") and mean["numeric"] > 50000


@pytest.mark.skipif(not LIVE, reason="Set BLS_LIVE_TESTS=1 to run live API calls")
def test_live_igce_benchmark_software_devs():
    result = asyncio.run(_call("igce_wage_benchmark", occ_code="151252"))
    payload = _payload(result)
    assert "benchmarks" in payload


# ---------------------------------------------------------------------------
# 0.2.1: extra='forbid' applied to every tool
# ---------------------------------------------------------------------------

def test_unknown_param_rejected():
    """Typo'd param names must raise, not silently drop.
    FastMCP default is extra='ignore' which lets silent-wrong-data through."""
    async def _run():
        try:
            await mcp.call_tool(
                "get_wage_data", {"occ_code": "15-1252", "bogus_typo": "x"}
            )
        except Exception as e:
            assert "extra inputs are not permitted" in str(e).lower()
            return
        raise AssertionError("expected extra-param rejection")
    asyncio.run(_run())
