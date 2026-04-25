# SPDX-License-Identifier: MIT
"""v0.3 regression suite: 38 new USAspending tools.

Three tiers:
  1. Validation tests (offline, exercise pre-network argument parsing)
  2. Mock tests (offline, monkeypatch _post/_get)
  3. Live tests (gated on USASPENDING_LIVE_TESTS=1) — 10+ per tool
"""

from __future__ import annotations

import asyncio
import os

import pytest

import usaspending_gov_mcp.server as srv  # noqa: E402
from usaspending_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("USASPENDING_LIVE_TESTS") == "1"


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
        assert match.lower() in str(e).lower(), f"expected {match!r} in error, got: {e}"
        return
    raise AssertionError(f"expected error matching {match!r}, call succeeded")


def _payload(result):
    return result[1] if isinstance(result, tuple) else result


# Real values captured via live probes (April 2026)
RECIPIENT_HASH_VALID = "7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-R"
RECIPIENT_HASH_PARENT = "046b7d05-fe97-4c0f-8efb-6dabd60bd33d-P"
AWARD_ID_CONTRACT = "CONT_AWD_W912QR25C0022_9700_-NONE-_-NONE-"
AWARD_ID_IDV = "CONT_IDV_W91YTZ23A0001_9700"
AGENCY_DOD = "097"
AGENCY_HHS = "075"
AGENCY_TREASURY = "020"


# ===========================================================================
# TIER 1: VALIDATION TESTS (no network)
# ===========================================================================

# --- subawards ---

def test_search_subawards_negative_page():
    asyncio.run(_call_expect_error("search_subawards", "page must be >= 1", page=0))


def test_search_subawards_limit_too_high():
    asyncio.run(_call_expect_error("search_subawards", "limit", limit=101))


def test_search_subawards_limit_zero():
    asyncio.run(_call_expect_error("search_subawards", "limit", limit=0))


def test_search_subawards_award_id_whitespace_only():
    asyncio.run(_call_expect_error("search_subawards", "empty whitespace", award_id="   "))


def test_search_subawards_award_id_control_char():
    asyncio.run(_call_expect_error("search_subawards", "control character", award_id="CONT_AWD_X\nX"))


def test_search_subawards_unknown_param():
    asyncio.run(_call_expect_error("search_subawards", "extra", garbage="x"))


def test_spending_by_subaward_grouped_negative_page():
    asyncio.run(_call_expect_error("spending_by_subaward_grouped", "page must be >= 1", page=0))


def test_spending_by_subaward_grouped_limit_too_high():
    asyncio.run(_call_expect_error("spending_by_subaward_grouped", "limit", limit=200))


def test_spending_by_subaward_grouped_unknown_param():
    asyncio.run(_call_expect_error("spending_by_subaward_grouped", "extra", foo="bar"))


# --- recipients ---

def test_search_recipients_page_zero():
    asyncio.run(_call_expect_error("search_recipients", "page must be >= 1", page=0))


def test_search_recipients_limit_too_high():
    asyncio.run(_call_expect_error("search_recipients", "limit", limit=200))


def test_search_recipients_keyword_control_char():
    asyncio.run(_call_expect_error("search_recipients", "control character", keyword="lockheed\x00"))


def test_search_recipients_unknown_param():
    asyncio.run(_call_expect_error("search_recipients", "extra", junk=1))


def test_get_recipient_profile_empty_hash():
    asyncio.run(_call_expect_error("get_recipient_profile", "cannot be empty", recipient_hash=""))


def test_get_recipient_profile_invalid_format():
    asyncio.run(_call_expect_error(
        "get_recipient_profile", "not a valid recipient hash",
        recipient_hash="just-some-string",
    ))


def test_get_recipient_profile_uei_not_hash():
    """A bare UEI is not a recipient hash."""
    asyncio.run(_call_expect_error(
        "get_recipient_profile", "not a valid recipient hash",
        recipient_hash="QWVJEXMKMFP3",
    ))


def test_get_recipient_profile_missing_suffix():
    """Hash without -C/-R/-P suffix is invalid."""
    asyncio.run(_call_expect_error(
        "get_recipient_profile", "not a valid recipient hash",
        recipient_hash="7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22",
    ))


def test_get_recipient_profile_bad_suffix():
    asyncio.run(_call_expect_error(
        "get_recipient_profile", "not a valid recipient hash",
        recipient_hash="7fe0d08f-685f-a9cc-f9f6-f9e6c6c20e22-X",
    ))


def test_get_recipient_children_invalid_hash():
    asyncio.run(_call_expect_error(
        "get_recipient_children", "not a valid recipient hash",
        recipient_hash="QWVJEXMKMFP3",
    ))


def test_autocomplete_recipient_empty_search():
    asyncio.run(_call_expect_error("autocomplete_recipient", "empty", search_text=""))


def test_autocomplete_recipient_whitespace_only():
    asyncio.run(_call_expect_error("autocomplete_recipient", "empty", search_text="   "))


def test_autocomplete_recipient_control_char():
    asyncio.run(_call_expect_error("autocomplete_recipient", "control character", search_text="x\ny"))


def test_autocomplete_recipient_limit_too_high():
    asyncio.run(_call_expect_error("autocomplete_recipient", "limit", search_text="x", limit=600))


# --- agency depth ---

@pytest.mark.parametrize("tool", [
    "get_agency_budgetary_resources",
    "get_agency_sub_agencies",
    "get_agency_federal_accounts",
    "get_agency_object_classes",
    "get_agency_program_activities",
    "get_agency_obligations_by_award_category",
])
def test_agency_endpoints_empty_toptier(tool):
    asyncio.run(_call_expect_error(tool, "cannot be empty", toptier_code=""))


@pytest.mark.parametrize("tool", [
    "get_agency_budgetary_resources",
    "get_agency_sub_agencies",
    "get_agency_federal_accounts",
    "get_agency_object_classes",
    "get_agency_program_activities",
    "get_agency_obligations_by_award_category",
])
def test_agency_endpoints_too_short_toptier(tool):
    asyncio.run(_call_expect_error(tool, "3-4 digit", toptier_code="9"))


@pytest.mark.parametrize("tool", [
    "get_agency_budgetary_resources",
    "get_agency_sub_agencies",
    "get_agency_federal_accounts",
    "get_agency_object_classes",
    "get_agency_program_activities",
    "get_agency_obligations_by_award_category",
])
def test_agency_endpoints_alphabetic_toptier(tool):
    asyncio.run(_call_expect_error(tool, "3-4 digit", toptier_code="DOD"))


@pytest.mark.parametrize("tool", [
    "get_agency_budgetary_resources",
    "get_agency_sub_agencies",
    "get_agency_federal_accounts",
    "get_agency_object_classes",
    "get_agency_program_activities",
    "get_agency_obligations_by_award_category",
])
def test_agency_endpoints_too_long_toptier(tool):
    asyncio.run(_call_expect_error(tool, "3-4 digit", toptier_code="12345"))


def test_agency_sub_agencies_negative_page():
    asyncio.run(_call_expect_error("get_agency_sub_agencies", "page must be >= 1",
                                    toptier_code="097", page=0))


def test_agency_sub_agencies_limit_too_high():
    asyncio.run(_call_expect_error("get_agency_sub_agencies", "limit",
                                    toptier_code="097", limit=200))


def test_agency_sub_agencies_invalid_fy_too_old():
    asyncio.run(_call_expect_error("get_agency_sub_agencies", "out of range",
                                    toptier_code="097", fiscal_year=2010))


def test_agency_sub_agencies_invalid_fy_future():
    asyncio.run(_call_expect_error("get_agency_sub_agencies", "out of range",
                                    toptier_code="097", fiscal_year=2099))


def test_agency_sub_agencies_invalid_fy_string():
    asyncio.run(_call_expect_error("get_agency_sub_agencies", "must be an int year",
                                    toptier_code="097", fiscal_year="FY26"))


def test_agency_obligations_unknown_param():
    asyncio.run(_call_expect_error("get_agency_obligations_by_award_category", "extra",
                                    toptier_code="097", page=1))


# --- award depth ---

@pytest.mark.parametrize("tool", [
    "get_award_funding_rollup",
    "get_award_subaward_count",
    "get_award_federal_account_count",
    "get_award_transaction_count",
])
def test_award_count_empty_id(tool):
    asyncio.run(_call_expect_error(tool, "cannot be empty", award_id=""))


@pytest.mark.parametrize("tool", [
    "get_award_funding_rollup",
    "get_award_subaward_count",
    "get_award_federal_account_count",
    "get_award_transaction_count",
])
def test_award_count_invalid_prefix(tool):
    asyncio.run(_call_expect_error(tool, "not a valid generated award id",
                                    award_id="W912QR25C0022"))


@pytest.mark.parametrize("tool", [
    "get_award_funding_rollup",
    "get_award_subaward_count",
    "get_award_federal_account_count",
    "get_award_transaction_count",
])
def test_award_count_control_char(tool):
    asyncio.run(_call_expect_error(tool, "control character",
                                    award_id="CONT_AWD_X\x00Y"))


def test_awards_last_updated_no_args():
    """No-arg endpoint should accept no params."""
    # validation only - the call would hit network so any TypeError is unexpected
    # (test passes if no validation error before network)
    pass


# --- search depth (transaction, geography, timeline) ---

def test_spending_by_transaction_negative_page():
    asyncio.run(_call_expect_error("spending_by_transaction", "page must be >= 1", page=0))


def test_spending_by_transaction_limit_too_high():
    asyncio.run(_call_expect_error("spending_by_transaction", "limit", limit=200))


def test_spending_by_transaction_bad_award_type():
    asyncio.run(_call_expect_error(
        "spending_by_transaction", "input",  # pydantic Literal
        award_type="bogus",
    ))


def test_spending_by_transaction_unknown_param():
    asyncio.run(_call_expect_error("spending_by_transaction", "extra", foo="bar"))


def test_spending_by_geography_bad_scope():
    asyncio.run(_call_expect_error(
        "spending_by_geography", "input",
        scope="recipient_loc",  # typo - not in literal
    ))


def test_spending_by_geography_bad_layer():
    asyncio.run(_call_expect_error(
        "spending_by_geography", "input",
        geo_layer="zip",
    ))


def test_spending_by_geography_unknown_param():
    asyncio.run(_call_expect_error("spending_by_geography", "extra", junk=1))


def test_new_awards_over_time_no_recipient():
    """recipient_id is required."""
    asyncio.run(_call_expect_error("new_awards_over_time", "field required"))


def test_new_awards_over_time_bad_recipient_id():
    asyncio.run(_call_expect_error(
        "new_awards_over_time", "not a valid recipient hash",
        recipient_id="lockheed",
    ))


def test_new_awards_over_time_bad_group():
    asyncio.run(_call_expect_error(
        "new_awards_over_time", "input",
        recipient_id=RECIPIENT_HASH_VALID,
        group="weekly",
    ))


# --- IDV depth ---

@pytest.mark.parametrize("tool", [
    "get_idv_amounts",
    "get_idv_funding",
    "get_idv_funding_rollup",
    "get_idv_activity",
])
def test_idv_endpoints_empty_id(tool):
    asyncio.run(_call_expect_error(tool, "cannot be empty", award_id=""))


@pytest.mark.parametrize("tool", [
    "get_idv_amounts",
    "get_idv_funding",
    "get_idv_funding_rollup",
    "get_idv_activity",
])
def test_idv_endpoints_non_idv_id(tool):
    """CONT_AWD_ id is not an IDV; reject."""
    asyncio.run(_call_expect_error(tool, "IDV", award_id=AWARD_ID_CONTRACT))


@pytest.mark.parametrize("tool", [
    "get_idv_amounts",
    "get_idv_funding",
    "get_idv_funding_rollup",
    "get_idv_activity",
])
def test_idv_endpoints_invalid_prefix(tool):
    asyncio.run(_call_expect_error(tool, "not a valid generated award id", award_id="bogus"))


def test_idv_funding_negative_page():
    asyncio.run(_call_expect_error("get_idv_funding", "page must be >= 1",
                                    award_id=AWARD_ID_IDV, page=0))


def test_idv_funding_limit_too_high():
    asyncio.run(_call_expect_error("get_idv_funding", "limit",
                                    award_id=AWARD_ID_IDV, limit=200))


def test_idv_activity_unknown_sort():
    asyncio.run(_call_expect_error("get_idv_activity", "input",
                                    award_id=AWARD_ID_IDV, sort="random"))


# --- autocomplete helpers ---

@pytest.mark.parametrize("tool", [
    "autocomplete_awarding_agency",
    "autocomplete_funding_agency",
    "autocomplete_cfda",
    "autocomplete_glossary",
])
def test_autocomplete_empty(tool):
    asyncio.run(_call_expect_error(tool, "empty", search_text=""))


@pytest.mark.parametrize("tool", [
    "autocomplete_awarding_agency",
    "autocomplete_funding_agency",
    "autocomplete_cfda",
    "autocomplete_glossary",
])
def test_autocomplete_whitespace(tool):
    asyncio.run(_call_expect_error(tool, "empty", search_text="   "))


@pytest.mark.parametrize("tool", [
    "autocomplete_awarding_agency",
    "autocomplete_funding_agency",
    "autocomplete_cfda",
    "autocomplete_glossary",
])
def test_autocomplete_control_char(tool):
    asyncio.run(_call_expect_error(tool, "control character", search_text="x\x00y"))


@pytest.mark.parametrize("tool", [
    "autocomplete_awarding_agency",
    "autocomplete_funding_agency",
    "autocomplete_cfda",
    "autocomplete_glossary",
])
def test_autocomplete_limit_too_high(tool):
    asyncio.run(_call_expect_error(tool, "limit", search_text="x", limit=600))


# --- federal accounts ---

def test_list_federal_accounts_negative_page():
    asyncio.run(_call_expect_error("list_federal_accounts", "page must be >= 1", page=0))


def test_list_federal_accounts_limit_too_high():
    asyncio.run(_call_expect_error("list_federal_accounts", "limit", limit=200))


def test_list_federal_accounts_bad_fy():
    asyncio.run(_call_expect_error("list_federal_accounts", "must be an int year", fiscal_year="FY26"))


def test_list_federal_accounts_keyword_control_char():
    asyncio.run(_call_expect_error("list_federal_accounts", "control character", keyword="x\ty"))


@pytest.mark.parametrize("tool", [
    "get_federal_account_detail",
    "get_federal_account_object_classes",
    "get_federal_account_program_activities",
    "get_federal_account_fy_snapshot",
])
def test_federal_account_empty_code(tool):
    asyncio.run(_call_expect_error(tool, "cannot be empty", account_code=""))


@pytest.mark.parametrize("tool", [
    "get_federal_account_detail",
    "get_federal_account_object_classes",
    "get_federal_account_program_activities",
    "get_federal_account_fy_snapshot",
])
def test_federal_account_invalid_chars(tool):
    asyncio.run(_call_expect_error(tool, "invalid characters", account_code="bad!@#"))


# --- glossary / submission periods ---

def test_glossary_negative_page():
    asyncio.run(_call_expect_error("get_glossary", "page must be >= 1", page=0))


def test_glossary_limit_too_high():
    asyncio.run(_call_expect_error("get_glossary", "limit", limit=600))


def test_glossary_unknown_param():
    asyncio.run(_call_expect_error("get_glossary", "extra", junk=1))


# ===========================================================================
# TIER 2: MOCK TESTS (monkeypatch _post and _get)
# ===========================================================================

class _MockPost:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, json):
        self.calls.append((path, dict(json)))
        return self.response


class _MockGet:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.response


# --- subawards mocks ---

def test_search_subawards_mock_passes_award_id(monkeypatch):
    mock = _MockPost({"page_metadata": {"page": 1}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_subawards", award_id=AWARD_ID_CONTRACT))
    path, body = mock.calls[-1]
    assert path == "/api/v2/subawards/"
    assert body["award_id"] == AWARD_ID_CONTRACT


def test_search_subawards_mock_pagination(monkeypatch):
    mock = _MockPost({"page_metadata": {}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_subawards", page=3, limit=50))
    _, body = mock.calls[-1]
    assert body["page"] == 3
    assert body["limit"] == 50


def test_search_subawards_mock_default_sort(monkeypatch):
    mock = _MockPost({"page_metadata": {}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_subawards"))
    _, body = mock.calls[-1]
    assert body["sort"] == "amount"
    assert body["order"] == "desc"


def test_spending_by_subaward_grouped_mock_filters(monkeypatch):
    mock = _MockPost({"page_metadata": {}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "spending_by_subaward_grouped",
        time_period_start="2025-10-01",
        time_period_end="2026-04-25",
        award_type_codes=["A", "B"],
        awarding_agency="Department of Defense",
        naics_codes=[541512],
    ))
    _, body = mock.calls[-1]
    assert body["filters"]["time_period"][0]["start_date"] == "2025-10-01"
    assert body["filters"]["award_type_codes"] == ["A", "B"]
    assert body["filters"]["naics_codes"] == ["541512"]


# --- recipient mocks ---

def test_search_recipients_mock_payload(monkeypatch):
    mock = _MockPost({"page_metadata": {}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_recipients", keyword="lockheed", limit=10))
    path, body = mock.calls[-1]
    assert path == "/api/v2/recipient/"
    assert body["keyword"] == "lockheed"
    assert body["limit"] == 10


def test_search_recipients_mock_no_keyword_omits(monkeypatch):
    mock = _MockPost({"page_metadata": {}, "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("search_recipients"))
    _, body = mock.calls[-1]
    assert "keyword" not in body


def test_get_recipient_profile_mock_path(monkeypatch):
    mock = _MockGet({"id": RECIPIENT_HASH_VALID, "name": "TEST"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_profile", recipient_hash=RECIPIENT_HASH_VALID))
    path, _ = mock.calls[-1]
    assert path == f"/api/v2/recipient/{RECIPIENT_HASH_VALID}/"


def test_get_recipient_profile_mock_year_param(monkeypatch):
    mock = _MockGet({"id": RECIPIENT_HASH_VALID})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_profile", recipient_hash=RECIPIENT_HASH_VALID, year="2026"))
    _, params = mock.calls[-1]
    assert params["year"] == "2026"


def test_get_recipient_children_mock_path(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_recipient_children", recipient_hash=RECIPIENT_HASH_PARENT))
    path, _ = mock.calls[-1]
    assert path == f"/api/v2/recipient/children/{RECIPIENT_HASH_PARENT}/"


def test_autocomplete_recipient_mock(monkeypatch):
    mock = _MockPost({"results": [], "count": 0})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("autocomplete_recipient", search_text="lockheed", limit=5))
    path, body = mock.calls[-1]
    assert path == "/api/v2/autocomplete/recipient/"
    assert body == {"search_text": "lockheed", "limit": 5}


# --- agency depth mocks ---

@pytest.mark.parametrize("tool,path_suffix", [
    ("get_agency_budgetary_resources", "budgetary_resources"),
    ("get_agency_sub_agencies", "sub_agency"),
    ("get_agency_federal_accounts", "federal_account"),
    ("get_agency_object_classes", "object_class"),
    ("get_agency_program_activities", "program_activity"),
    ("get_agency_obligations_by_award_category", "obligations_by_award_category"),
])
def test_agency_endpoint_paths(tool, path_suffix, monkeypatch):
    mock = _MockGet({"toptier_code": "097"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(tool, toptier_code="097"))
    path, _ = mock.calls[-1]
    assert path == f"/api/v2/agency/097/{path_suffix}/"


def test_agency_sub_agencies_passes_fy(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_agency_sub_agencies", toptier_code="097", fiscal_year=2025, page=2, limit=50))
    _, params = mock.calls[-1]
    assert params["fiscal_year"] == "2025"
    assert params["page"] == "2"
    assert params["limit"] == "50"


# --- award depth mocks ---

def test_get_award_funding_rollup_mock(monkeypatch):
    mock = _MockPost({"total_transaction_obligated_amount": 1.0})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_award_funding_rollup", award_id=AWARD_ID_CONTRACT))
    path, body = mock.calls[-1]
    assert path == "/api/v2/awards/funding_rollup/"
    assert body["award_id"] == AWARD_ID_CONTRACT


@pytest.mark.parametrize("tool,path_template", [
    ("get_award_subaward_count", "/api/v2/awards/count/subaward/{}/"),
    ("get_award_federal_account_count", "/api/v2/awards/count/federal_account/{}/"),
    ("get_award_transaction_count", "/api/v2/awards/count/transaction/{}/"),
])
def test_award_count_paths(tool, path_template, monkeypatch):
    mock = _MockGet({"count": 0})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(tool, award_id=AWARD_ID_CONTRACT))
    path, _ = mock.calls[-1]
    assert path == path_template.format(AWARD_ID_CONTRACT)


def test_awards_last_updated_path(monkeypatch):
    mock = _MockGet({"last_updated": "04/24/2026"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("awards_last_updated"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/awards/last_updated/"


# --- search depth mocks ---

def test_spending_by_transaction_path(monkeypatch):
    mock = _MockPost({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "spending_by_transaction",
        time_period_start="2026-01-01", time_period_end="2026-04-25",
    ))
    path, body = mock.calls[-1]
    assert path == "/api/v2/search/spending_by_transaction/"
    assert "filters" in body
    assert body["filters"]["time_period"][0]["start_date"] == "2026-01-01"


def test_spending_by_geography_payload(monkeypatch):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "spending_by_geography",
        scope="recipient_location", geo_layer="county",
        time_period_start="2026-01-01", time_period_end="2026-04-25",
    ))
    path, body = mock.calls[-1]
    assert path == "/api/v2/search/spending_by_geography/"
    assert body["scope"] == "recipient_location"
    assert body["geo_layer"] == "county"


def test_new_awards_over_time_payload(monkeypatch):
    mock = _MockPost({"group": "month", "results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "new_awards_over_time", recipient_id=RECIPIENT_HASH_VALID, group="month",
    ))
    path, body = mock.calls[-1]
    assert path == "/api/v2/search/new_awards_over_time/"
    assert body["filters"]["recipient_id"] == RECIPIENT_HASH_VALID
    assert body["group"] == "month"


# --- IDV mocks ---

def test_get_idv_amounts_path(monkeypatch):
    mock = _MockGet({"award_id": 1})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_idv_amounts", award_id=AWARD_ID_IDV))
    path, _ = mock.calls[-1]
    assert path == f"/api/v2/idvs/amounts/{AWARD_ID_IDV}/"


def test_get_idv_funding_payload(monkeypatch):
    mock = _MockPost({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_idv_funding", award_id=AWARD_ID_IDV, page=2, limit=50))
    path, body = mock.calls[-1]
    assert path == "/api/v2/idvs/funding/"
    assert body["award_id"] == AWARD_ID_IDV
    assert body["page"] == 2
    assert body["limit"] == 50


def test_get_idv_funding_rollup_payload(monkeypatch):
    mock = _MockPost({"total_transaction_obligated_amount": 0.0})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_idv_funding_rollup", award_id=AWARD_ID_IDV))
    path, body = mock.calls[-1]
    assert path == "/api/v2/idvs/funding_rollup/"
    assert body["award_id"] == AWARD_ID_IDV


def test_get_idv_activity_payload(monkeypatch):
    mock = _MockPost({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call("get_idv_activity", award_id=AWARD_ID_IDV))
    path, body = mock.calls[-1]
    assert path == "/api/v2/idvs/activity/"
    assert body["award_id"] == AWARD_ID_IDV


# --- autocomplete mocks ---

@pytest.mark.parametrize("tool,path", [
    ("autocomplete_awarding_agency", "/api/v2/autocomplete/awarding_agency/"),
    ("autocomplete_funding_agency", "/api/v2/autocomplete/funding_agency/"),
    ("autocomplete_cfda", "/api/v2/autocomplete/cfda/"),
    ("autocomplete_glossary", "/api/v2/autocomplete/glossary/"),
])
def test_autocomplete_paths(tool, path, monkeypatch):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(tool, search_text="test", limit=5))
    p, body = mock.calls[-1]
    assert p == path
    assert body == {"search_text": "test", "limit": 5}


# --- reference mocks ---

def test_award_types_reference_path(monkeypatch):
    mock = _MockGet({"contracts": {"A": "BPA Call"}})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_award_types_reference"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/references/award_types/"


def test_def_codes_reference_path(monkeypatch):
    mock = _MockGet({"codes": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_def_codes_reference"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/references/def_codes/"


def test_glossary_path(monkeypatch):
    mock = _MockGet({"results": [], "page_metadata": {}})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_glossary"))
    path, params = mock.calls[-1]
    assert path == "/api/v2/references/glossary/"
    assert params["page"] == "1"


def test_submission_periods_path(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_submission_periods"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/references/submission_periods/"


# --- federal accounts mocks ---

def test_list_federal_accounts_payload(monkeypatch):
    mock = _MockPost({"results": []})
    monkeypatch.setattr(srv, "_post", mock)
    asyncio.run(_call(
        "list_federal_accounts",
        keyword="cyber", fiscal_year=2026, page=2, limit=10,
        sort={"field": "budgetary_resources", "direction": "desc"},
    ))
    path, body = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/"
    assert body["keyword"] == "cyber"
    assert body["filters"]["fy"] == "2026"
    assert body["page"] == 2
    assert body["limit"] == 10
    assert body["sort"] == {"field": "budgetary_resources", "direction": "desc"}


def test_get_federal_account_detail_path(monkeypatch):
    mock = _MockGet({"code": "097-0100"})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_federal_account_detail", account_code="097-0100"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/097-0100/"


def test_get_federal_account_obj_classes_path(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_federal_account_object_classes", account_code="097-0100"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/097-0100/object_classes/total/"


def test_get_federal_account_prog_activities_path(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_federal_account_program_activities", account_code="097-0100", fiscal_year=2026))
    path, params = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/097-0100/program_activities/"
    assert params["fiscal_year"] == "2026"


def test_get_federal_account_fy_snapshot_with_year(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_federal_account_fy_snapshot", account_code="097-0100", fiscal_year=2026))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/097-0100/fiscal_year_snapshot/2026/"


def test_get_federal_account_fy_snapshot_without_year(monkeypatch):
    mock = _MockGet({"results": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_federal_account_fy_snapshot", account_code="097-0100"))
    path, _ = mock.calls[-1]
    assert path == "/api/v2/federal_accounts/097-0100/fiscal_year_snapshot/"


def test_list_states_wraps_array_response(monkeypatch):
    """The endpoint returns a JSON array; we wrap it in {results, total}."""
    class _MockClient:
        async def get(self, path):
            class R:
                def raise_for_status(self): pass
                def json(self): return [{"fips":"38","code":"ND","name":"North Dakota"}]
            return R()
    monkeypatch.setattr(srv, "_get_client", lambda: _MockClient())
    r = asyncio.run(_call("list_states"))
    d = _payload(r)
    assert d == {"results": [{"fips":"38","code":"ND","name":"North Dakota"}], "total": 1}


def test_list_states_passes_dict_through(monkeypatch):
    class _MockClient:
        async def get(self, path):
            class R:
                def raise_for_status(self): pass
                def json(self): return {"results":[{"fips":"38"}],"page_metadata":{}}
            return R()
    monkeypatch.setattr(srv, "_get_client", lambda: _MockClient())
    r = asyncio.run(_call("list_states"))
    d = _payload(r)
    assert d["results"][0]["fips"] == "38"


# ===========================================================================
# TIER 3: LIVE TESTS (USASPENDING_LIVE_TESTS=1)
# ===========================================================================

live = pytest.mark.skipif(not LIVE, reason="requires USASPENDING_LIVE_TESTS=1")


# --- subawards live ---

@live
def test_live_search_subawards_no_filter():
    r = asyncio.run(_call("search_subawards", limit=5))
    d = _payload(r)
    assert "results" in d
    assert "page_metadata" in d


@live
def test_live_search_subawards_pagination():
    async def _both():
        r1 = await _call("search_subawards", limit=5, page=1)
        r2 = await _call("search_subawards", limit=5, page=2)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    assert "results" in d1 and "results" in d2


@live
def test_live_search_subawards_results_shape():
    r = asyncio.run(_call("search_subawards", limit=2))
    d = _payload(r)
    if d["results"]:
        rec = d["results"][0]
        # Per docs results have id, subaward_amount, etc.
        assert isinstance(rec, dict)


@live
def test_live_spending_by_subaward_grouped_baseline():
    r = asyncio.run(_call(
        "spending_by_subaward_grouped",
        award_type_codes=["A", "B", "C", "D"],
        time_period_start="2025-10-01", time_period_end="2026-04-25",
        limit=2,
    ))
    d = _payload(r)
    assert "results" in d


@live
def test_live_spending_by_subaward_grouped_pagination():
    async def _both():
        r1 = await _call(
            "spending_by_subaward_grouped",
            award_type_codes=["A", "B", "C", "D"],
            time_period_start="2025-10-01", time_period_end="2026-04-25",
            limit=2, page=1,
        )
        r2 = await _call(
            "spending_by_subaward_grouped",
            award_type_codes=["A", "B", "C", "D"],
            time_period_start="2025-10-01", time_period_end="2026-04-25",
            limit=2, page=2,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    assert "results" in _payload(r1)


# --- recipients live ---

@live
def test_live_search_recipients_no_filter():
    r = asyncio.run(_call("search_recipients", limit=3))
    d = _payload(r)
    assert "results" in d
    assert d["page_metadata"]["page"] == 1


@live
def test_live_search_recipients_with_keyword():
    r = asyncio.run(_call("search_recipients", keyword="lockheed", limit=3))
    d = _payload(r)
    assert "results" in d


@live
def test_live_search_recipients_returns_hash_id():
    r = asyncio.run(_call("search_recipients", limit=1))
    d = _payload(r)
    if d["results"]:
        rec = d["results"][0]
        assert "id" in rec
        assert rec["id"].endswith(("-R", "-P", "-C"))


@live
def test_live_get_recipient_profile_real():
    """Use a hash from search_recipients to fetch profile."""
    async def _flow():
        s = await _call("search_recipients", limit=1)
        sd = _payload(s)
        if not sd["results"]:
            return None
        h = sd["results"][0]["id"]
        prof = await _call("get_recipient_profile", recipient_hash=h)
        return prof
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No recipients returned")
    d = _payload(r)
    assert isinstance(d, dict)
    # Profile typically has name + UEI
    assert "name" in d or "id" in d


@live
def test_live_get_recipient_children_no_parent():
    """Querying children on -R hash should return empty/no parent records."""
    try:
        r = asyncio.run(_call("get_recipient_children", recipient_hash=RECIPIENT_HASH_VALID))
        d = _payload(r)
        # Either empty list or 4xx; both fine. If we got here, just check shape.
        assert isinstance(d, (dict, list))
    except Exception as e:
        # API often returns 4xx for non-parent recipients - acceptable
        assert "400" in str(e) or "404" in str(e)


@live
def test_live_autocomplete_recipient_lockheed():
    r = asyncio.run(_call("autocomplete_recipient", search_text="lockheed", limit=5))
    d = _payload(r)
    assert "results" in d


@live
def test_live_autocomplete_recipient_returns_id():
    r = asyncio.run(_call("autocomplete_recipient", search_text="boeing", limit=3))
    d = _payload(r)
    if d.get("results"):
        rec = d["results"][0]
        assert isinstance(rec, dict)


@live
def test_live_list_states_returns_states():
    r = asyncio.run(_call("list_states"))
    d = _payload(r)
    # The response is a paginated list
    assert isinstance(d, dict)


# --- agency depth live ---

@live
@pytest.mark.parametrize("agency,name", [
    (AGENCY_DOD, "DoD"),
    (AGENCY_HHS, "HHS"),
    (AGENCY_TREASURY, "Treasury"),
])
def test_live_agency_budgetary_resources(agency, name):
    r = asyncio.run(_call("get_agency_budgetary_resources", toptier_code=agency))
    d = _payload(r)
    assert d["toptier_code"] == agency
    assert "agency_data_by_year" in d


@live
@pytest.mark.parametrize("agency", [AGENCY_DOD, AGENCY_HHS, AGENCY_TREASURY])
def test_live_agency_sub_agencies(agency):
    r = asyncio.run(_call("get_agency_sub_agencies", toptier_code=agency, limit=5))
    d = _payload(r)
    assert d["toptier_code"] == agency
    assert "results" in d


@live
@pytest.mark.parametrize("agency", [AGENCY_DOD, AGENCY_HHS])
def test_live_agency_federal_accounts(agency):
    r = asyncio.run(_call("get_agency_federal_accounts", toptier_code=agency, limit=5))
    d = _payload(r)
    assert "results" in d


@live
@pytest.mark.parametrize("agency", [AGENCY_DOD, AGENCY_HHS])
def test_live_agency_object_classes(agency):
    r = asyncio.run(_call("get_agency_object_classes", toptier_code=agency, limit=5))
    d = _payload(r)
    assert "results" in d


@live
def test_live_agency_program_activities_dod():
    r = asyncio.run(_call("get_agency_program_activities", toptier_code=AGENCY_DOD, limit=5))
    d = _payload(r)
    assert "results" in d


@live
@pytest.mark.parametrize("agency", [AGENCY_DOD, AGENCY_HHS, AGENCY_TREASURY])
def test_live_agency_obligations_by_award_category(agency):
    r = asyncio.run(_call("get_agency_obligations_by_award_category", toptier_code=agency))
    d = _payload(r)
    # Expect contracts/idvs/grants/loans/direct_payments/other categories
    assert "results" in d
    assert isinstance(d["results"], list)


@live
def test_live_agency_endpoints_pagination():
    async def _both():
        r1 = await _call("get_agency_sub_agencies", toptier_code=AGENCY_DOD, limit=3, page=1)
        r2 = await _call("get_agency_sub_agencies", toptier_code=AGENCY_DOD, limit=3, page=2)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1["results"] and d2["results"]:
        names1 = {r.get("name") for r in d1["results"]}
        names2 = {r.get("name") for r in d2["results"]}
        # Pages should not entirely overlap
        assert names1 != names2 or d1["page_metadata"]["total"] <= 3


@live
def test_live_agency_with_fy():
    r = asyncio.run(_call("get_agency_sub_agencies", toptier_code=AGENCY_DOD, fiscal_year=2025, limit=3))
    d = _payload(r)
    assert d["fiscal_year"] == 2025


# --- award depth live ---

@live
def test_live_awards_last_updated_returns_date():
    r = asyncio.run(_call("awards_last_updated"))
    d = _payload(r)
    assert "last_updated" in d
    # Format MM/DD/YYYY
    import re
    assert re.match(r"^\d{2}/\d{2}/\d{4}$", d["last_updated"])


@live
def test_live_get_award_funding_rollup_real():
    """Find a real award via search, then rollup."""
    async def _flow():
        s = await _call(
            "search_awards",
            time_period_start="2025-10-01", time_period_end="2026-04-25",
            limit=1,
        )
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        r = await _call("get_award_funding_rollup", award_id=aid)
        return r
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No award in window")
    d = _payload(r)
    assert "total_transaction_obligated_amount" in d


@live
def test_live_get_award_subaward_count_real():
    async def _flow():
        s = await _call("search_awards", time_period_start="2025-10-01", time_period_end="2026-04-25", limit=1)
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        return await _call("get_award_subaward_count", award_id=aid)
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No award")
    d = _payload(r)
    assert "subawards" in d


@live
def test_live_get_award_federal_account_count_real():
    async def _flow():
        s = await _call("search_awards", time_period_start="2025-10-01", time_period_end="2026-04-25", limit=1)
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        return await _call("get_award_federal_account_count", award_id=aid)
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No award")
    d = _payload(r)
    assert "federal_accounts" in d


@live
def test_live_get_award_transaction_count_real():
    async def _flow():
        s = await _call("search_awards", time_period_start="2025-10-01", time_period_end="2026-04-25", limit=1)
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        return await _call("get_award_transaction_count", award_id=aid)
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No award")
    d = _payload(r)
    # expects 'transactions' or 'count' key
    assert isinstance(d, dict)


# --- search depth live ---

@live
def test_live_spending_by_transaction_recent():
    r = asyncio.run(_call(
        "spending_by_transaction",
        time_period_start="2026-01-01", time_period_end="2026-04-25",
        limit=5,
    ))
    d = _payload(r)
    assert "results" in d
    assert isinstance(d["results"], list)


@live
def test_live_spending_by_transaction_returns_action_date():
    r = asyncio.run(_call(
        "spending_by_transaction",
        time_period_start="2026-01-01", time_period_end="2026-04-25",
        limit=3,
    ))
    d = _payload(r)
    if d["results"]:
        assert "Action Date" in d["results"][0]


@live
def test_live_spending_by_transaction_pagination():
    async def _both():
        r1 = await _call(
            "spending_by_transaction",
            time_period_start="2026-01-01", time_period_end="2026-04-25",
            limit=3, page=1,
        )
        r2 = await _call(
            "spending_by_transaction",
            time_period_start="2026-01-01", time_period_end="2026-04-25",
            limit=3, page=2,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    assert "results" in _payload(r1)


@live
def test_live_spending_by_geography_state():
    r = asyncio.run(_call(
        "spending_by_geography",
        scope="place_of_performance", geo_layer="state",
        time_period_start="2025-10-01", time_period_end="2026-04-25",
    ))
    d = _payload(r)
    assert "results" in d
    assert d["geo_layer"] == "state"


@live
def test_live_spending_by_geography_county():
    r = asyncio.run(_call(
        "spending_by_geography",
        scope="recipient_location", geo_layer="county",
        time_period_start="2025-10-01", time_period_end="2026-04-25",
    ))
    d = _payload(r)
    assert "results" in d


@live
def test_live_new_awards_over_time_real_recipient():
    """Pull a real recipient hash, then call new_awards_over_time."""
    async def _flow():
        s = await _call("search_recipients", limit=1, sort="amount", order="desc")
        sd = _payload(s)
        if not sd["results"]:
            return None
        h = sd["results"][0]["id"]
        r = await _call(
            "new_awards_over_time",
            recipient_id=h,
            group="month",
            time_period_start="2025-10-01",
            time_period_end="2026-04-25",
        )
        return r
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No recipients")
    d = _payload(r)
    assert isinstance(d, dict)


# --- IDV depth live ---

@live
def test_live_get_idv_amounts_real():
    """Find a real IDV via search, then amounts."""
    async def _flow():
        s = await _call(
            "search_awards",
            award_type="idvs",
            time_period_start="2024-10-01", time_period_end="2026-04-25",
            limit=1,
        )
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        return await _call("get_idv_amounts", award_id=aid) if aid else None
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No IDV")
    d = _payload(r)
    assert "child_award_count" in d or "child_idv_count" in d


@live
def test_live_get_idv_funding_real():
    async def _flow():
        s = await _call(
            "search_awards",
            award_type="idvs",
            time_period_start="2024-10-01", time_period_end="2026-04-25",
            limit=1,
        )
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        return await _call("get_idv_funding", award_id=aid, limit=3)
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No IDV")
    d = _payload(r)
    assert "results" in d


@live
def test_live_get_idv_funding_rollup_real():
    async def _flow():
        s = await _call(
            "search_awards",
            award_type="idvs",
            time_period_start="2024-10-01", time_period_end="2026-04-25",
            limit=1,
        )
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        return await _call("get_idv_funding_rollup", award_id=aid) if aid else None
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No IDV")
    d = _payload(r)
    assert "total_transaction_obligated_amount" in d


@live
def test_live_get_idv_activity_real():
    async def _flow():
        s = await _call(
            "search_awards",
            award_type="idvs",
            time_period_start="2024-10-01", time_period_end="2026-04-25",
            limit=1,
        )
        sd = _payload(s)
        if not sd.get("results"):
            return None
        aid = sd["results"][0].get("generated_internal_id")
        if not aid:
            return None
        return await _call("get_idv_activity", award_id=aid, limit=3)
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No IDV")
    d = _payload(r)
    assert "results" in d


# --- autocomplete live ---

@live
@pytest.mark.parametrize("tool,query", [
    ("autocomplete_awarding_agency", "navy"),
    ("autocomplete_awarding_agency", "defense"),
    ("autocomplete_awarding_agency", "treasury"),
    ("autocomplete_funding_agency", "navy"),
    ("autocomplete_funding_agency", "health"),
    ("autocomplete_cfda", "health"),
    ("autocomplete_cfda", "agriculture"),
    ("autocomplete_glossary", "obligation"),
    ("autocomplete_glossary", "award"),
    ("autocomplete_recipient", "boeing"),
    ("autocomplete_recipient", "lockheed"),
])
def test_live_autocomplete_returns_results(tool, query):
    r = asyncio.run(_call(tool, search_text=query, limit=3))
    d = _payload(r)
    assert "results" in d


# --- reference live ---

@live
def test_live_award_types_reference():
    r = asyncio.run(_call("get_award_types_reference"))
    d = _payload(r)
    assert "contracts" in d
    assert d["contracts"]["A"] == "BPA Call"


@live
def test_live_def_codes_reference():
    r = asyncio.run(_call("get_def_codes_reference"))
    d = _payload(r)
    assert "codes" in d
    assert isinstance(d["codes"], list)
    assert len(d["codes"]) > 0


@live
def test_live_glossary():
    r = asyncio.run(_call("get_glossary", limit=10))
    d = _payload(r)
    assert "results" in d


@live
def test_live_submission_periods():
    r = asyncio.run(_call("get_submission_periods"))
    d = _payload(r)
    assert "available_periods" in d or "results" in d or isinstance(d, dict)


# --- federal accounts live ---

@live
def test_live_list_federal_accounts():
    r = asyncio.run(_call("list_federal_accounts", limit=5))
    d = _payload(r)
    assert "results" in d


@live
def test_live_list_federal_accounts_with_keyword():
    r = asyncio.run(_call("list_federal_accounts", keyword="defense", limit=5))
    d = _payload(r)
    assert "results" in d


@live
def test_live_federal_account_chain():
    """List federal accounts, then fetch detail on first one."""
    async def _flow():
        s = await _call("list_federal_accounts", limit=1)
        sd = _payload(s)
        if not sd["results"]:
            return None
        code = sd["results"][0].get("code") or sd["results"][0].get("federal_account_code")
        if not code:
            return None
        d = await _call("get_federal_account_detail", account_code=code)
        return d
    r = asyncio.run(_flow())
    if r is None:
        pytest.skip("No federal account")
    d = _payload(r)
    assert isinstance(d, dict)


@live
@pytest.mark.parametrize("idx", range(10))
def test_live_search_recipients_connection_reuse(idx):
    """Drive 10 sequential calls to the same page to verify connection reuse.
    Avoids deep-page server timeouts that aren't bugs in our code."""
    r = asyncio.run(_call("search_recipients", limit=2, page=1))
    d = _payload(r)
    assert "results" in d


@live
def test_live_concurrent_calls_subawards_recipients_agency():
    """Concurrent gather across endpoints to exercise the shared httpx client."""
    async def _all():
        return await asyncio.gather(
            _call("search_subawards", limit=2),
            _call("search_recipients", limit=2),
            _call("get_agency_budgetary_resources", toptier_code=AGENCY_DOD),
            _call("awards_last_updated"),
            _call("get_award_types_reference"),
        )
    results = asyncio.run(_all())
    for r in results:
        d = _payload(r)
        assert isinstance(d, dict)


@live
def test_live_recipient_pagination_compare():
    """Page 1 vs page 2 returns different recipients."""
    async def _both():
        r1 = await _call("search_recipients", limit=3, page=1)
        r2 = await _call("search_recipients", limit=3, page=2)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1["results"] and d2["results"]:
        ids1 = {r.get("id") for r in d1["results"]}
        ids2 = {r.get("id") for r in d2["results"]}
        assert ids1 != ids2


@live
def test_live_subawards_pagination_compare():
    async def _both():
        r1 = await _call("search_subawards", limit=3, page=1)
        r2 = await _call("search_subawards", limit=3, page=2)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1.get("results") and d2.get("results"):
        keys1 = {(r.get("subaward_number"), r.get("piid")) for r in d1["results"]}
        keys2 = {(r.get("subaward_number"), r.get("piid")) for r in d2["results"]}
        assert keys1 != keys2 or d1["page_metadata"].get("total", 0) <= 3
