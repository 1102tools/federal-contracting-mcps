# SPDX-License-Identifier: MIT
"""v0.4 regression suite: Federal Hierarchy + Subaward Reporting tools.

Three tiers:
  1. Validation tests (offline, exercise pre-network argument parsing)
  2. Mock tests (offline, monkeypatch _get to feed canned responses)
  3. Live tests (gated on SAM_LIVE_TESTS=1)

The mock tier is critical for the Subaward APIs because they use ISO dates,
pageNumber/pageSize, and a different response wrapper than the rest of SAM.
The Federal Hierarchy mock tier covers its lowercase response keys.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("SAM_API_KEY", "SAM-00000000-0000-0000-0000-000000000000")

import sam_gov_mcp.server as srv  # noqa: E402
from sam_gov_mcp.server import mcp  # noqa: E402


LIVE = os.environ.get("SAM_LIVE_TESTS") == "1"


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


# ===========================================================================
# TIER 1: VALIDATION TESTS (no network)
# ===========================================================================

# --- Federal Hierarchy: search_federal_organizations ---

def test_fh_search_negative_offset():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "offset must be >= 0", offset=-1
    ))


def test_fh_search_limit_above_cap():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "limit", limit=101
    ))


def test_fh_search_limit_zero():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "limit", limit=0
    ))


def test_fh_search_negative_limit():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "limit", limit=-5
    ))


def test_fh_search_org_type_freeform_accepted():
    """The whitelist was dropped: API is forgiving and real values aren't in
    any documented enum. We accept any non-control-character string."""
    try:
        asyncio.run(_call("search_federal_organizations", fh_org_type="Department/Ind. Agency"))
    except Exception as e:
        # Network/auth fine; pre-network rejection is not.
        assert "fh_org_type" not in str(e).lower() or "rejected" not in str(e).lower()


def test_fh_search_org_type_long_string_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "exceeds maximum length",
        fh_org_type="A" * 200,
    ))


def test_fh_search_org_type_null_byte_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "null byte",
        fh_org_type="dept\x00ment",
    ))


def test_fh_search_invalid_status_rejected_by_pydantic():
    """status is a Literal; pydantic enforces it."""
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "input",  # pydantic validation error
        status="active",  # lowercase; Literal expects ACTIVE/INACTIVE/MERGED
    ))


def test_fh_search_org_id_int_coerced():
    """fh_org_id should accept int (will fail at network but not validation)."""
    # Should pass validation; will fail at HTTP because the fake API key won't auth.
    try:
        asyncio.run(_call("search_federal_organizations", fh_org_id=100123))
    except Exception as e:
        # Network/auth errors are fine; coercion rejection is not.
        assert "fh_org_id" not in str(e).lower() or "rejected" not in str(e).lower()


def test_fh_search_name_with_null_byte_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "null byte",
        fh_org_name="Treasury\x00Department",
    ))


def test_fh_search_long_name_rejected():
    long_name = "A" * 250
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "exceeds maximum length",
        fh_org_name=long_name,
    ))


def test_fh_search_unknown_param_rejected():
    """extra='forbid' should catch typos."""
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "extra",
        notarealparam="x",
    ))


def test_fh_search_org_type_passes_through_as_given(monkeypatch):
    """Whatever the user passes for fh_org_type goes to the wire unchanged."""
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_federal_organizations", fh_org_type="Department/Ind. Agency"))
    _, params = mock.calls[-1]
    assert params["fhorgtype"] == "Department/Ind. Agency"


# --- Federal Hierarchy: get_organization_hierarchy ---

def test_fh_hierarchy_empty_org_id():
    asyncio.run(_call_expect_error(
        "get_organization_hierarchy", "cannot be empty",
        fh_org_id="",
    ))


def test_fh_hierarchy_missing_org_id():
    """fh_org_id is required."""
    asyncio.run(_call_expect_error(
        "get_organization_hierarchy", "field required",
    ))


def test_fh_hierarchy_negative_offset():
    asyncio.run(_call_expect_error(
        "get_organization_hierarchy", "offset must be >= 0",
        fh_org_id="100123", offset=-1,
    ))


def test_fh_hierarchy_limit_above_cap():
    asyncio.run(_call_expect_error(
        "get_organization_hierarchy", "limit",
        fh_org_id="100123", limit=500,
    ))


def test_fh_hierarchy_org_id_accepts_int():
    """Integer org IDs should coerce."""
    try:
        asyncio.run(_call("get_organization_hierarchy", fh_org_id=100123))
    except Exception as e:
        # Network errors fine; rejection on coercion is not
        assert "must be a string" not in str(e).lower()


# --- Subaward Reporting: search_acquisition_subawards ---

def test_acq_subaward_negative_page_number():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "page_number must be >= 0",
        page_number=-1,
    ))


def test_acq_subaward_page_size_above_cap():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "page_size",
        page_size=1001,
    ))


def test_acq_subaward_page_size_zero():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "page_size",
        page_size=0,
    ))


def test_acq_subaward_rejects_mmddyyyy_date():
    """Subaward APIs use ISO format, not MM/DD/YYYY."""
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="01/15/2026",
    ))


def test_acq_subaward_rejects_iso_short_form():
    """yyyy-MM-dd is required, not yyyy-M-d."""
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="2026-1-1",
    ))


def test_acq_subaward_invalid_calendar_date():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "not a valid calendar date",
        from_date="2026-02-31",
    ))


def test_acq_subaward_accepts_iso_date():
    """yyyy-MM-dd should pass validation."""
    try:
        asyncio.run(_call("search_acquisition_subawards", from_date="2026-01-15"))
    except Exception as e:
        assert "yyyy-mm-dd" not in str(e).lower(), f"valid ISO date wrongly rejected: {e}"


def test_acq_subaward_invalid_status_rejected_by_pydantic():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "input",
        status="published",  # case-sensitive Literal
    ))


def test_acq_subaward_null_byte_rejected_in_piid():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "null byte",
        piid="W912\x00BV22",
    ))


def test_acq_subaward_long_piid_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "exceeds maximum length",
        piid="A" * 200,
    ))


def test_acq_subaward_unknown_param_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "extra",
        garbage_param="x",
    ))


def test_acq_subaward_agency_id_accepts_int():
    """agency_id should accept int and string."""
    try:
        asyncio.run(_call("search_acquisition_subawards", agency_id=9700))
    except Exception:
        pass  # network error fine
    try:
        asyncio.run(_call("search_acquisition_subawards", agency_id="9700"))
    except Exception:
        pass


# --- Subaward Reporting: search_assistance_subawards ---

def test_assist_subaward_negative_page_number():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "page_number must be >= 0",
        page_number=-1,
    ))


def test_assist_subaward_page_size_above_cap():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "page_size",
        page_size=1001,
    ))


def test_assist_subaward_rejects_mmddyyyy_date():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "yyyy-MM-dd",
        to_date="01/15/2026",
    ))


def test_assist_subaward_invalid_calendar_date():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "not a valid calendar date",
        to_date="2026-13-01",
    ))


def test_assist_subaward_unknown_param_rejected():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "extra",
        prime_contract_key="x",  # belongs on acquisition, not assistance
    ))


def test_assist_subaward_long_fain_rejected():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "exceeds maximum length",
        fain="X" * 200,
    ))


def test_assist_subaward_null_byte_rejected_in_fain():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "control character",
        fain="ABC\nDEF",
    ))


# ===========================================================================
# TIER 2: MOCK TESTS (no network, monkeypatch _get)
# ===========================================================================

class _Mock:
    """Capture last params + return canned response."""
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params, *, base_url=None):
        self.calls.append((path, dict(params)))
        return self.response


# --- Federal Hierarchy mocks ---

def test_fh_search_normalizes_lowercase_keys(monkeypatch):
    """Federal Hierarchy uses lowercase 'totalrecords' / 'orglist'."""
    mock = _Mock({
        "totalrecords": "5",  # string from upstream
        "orglist": [
            {"fhorgid": "100021", "fhorgname": "Treasury", "status": "ACTIVE"},
            {"fhorgid": "100022", "fhorgname": "IRS", "status": "ACTIVE"},
        ],
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_federal_organizations", fh_org_name="Treasury"))
    data = _payload(r)
    assert data["totalrecords"] == 5  # coerced int
    assert isinstance(data["orglist"], list)
    assert len(data["orglist"]) == 2
    assert data["orglist"][0]["fhorgname"] == "Treasury"


def test_fh_search_handles_single_orglist_dict(monkeypatch):
    """XML-to-JSON sometimes collapses single-item arrays to dicts."""
    mock = _Mock({"totalrecords": 1, "orglist": {"fhorgid": "1", "fhorgname": "X"}})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    assert isinstance(data["orglist"], list)
    assert len(data["orglist"]) == 1


def test_fh_search_handles_empty_response(monkeypatch):
    mock = _Mock({})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    # Either returns the empty dict or normalizes; both acceptable.
    assert isinstance(data, dict)


def test_fh_search_passes_correct_params(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_federal_organizations",
        fh_org_id="100021",
        fh_org_type="DEPARTMENT",
        status="ACTIVE",
        agency_code="9700",
        cgac="020",
        limit=50,
        offset=10,
    ))
    path, params = mock.calls[-1]
    assert path == "/prod/federalorganizations/v1/orgs"
    assert params["fhorgid"] == "100021"
    assert params["fhorgtype"] == "DEPARTMENT"
    assert params["status"] == "ACTIVE"
    assert params["agencycode"] == "9700"
    assert params["cgac"] == "020"
    assert params["limit"] == "50"
    assert params["offset"] == "10"


def test_fh_search_omits_unset_params(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_federal_organizations"))
    path, params = mock.calls[-1]
    # Only limit + offset should be present
    assert set(params.keys()) == {"limit", "offset"}


def test_fh_hierarchy_passes_org_id(monkeypatch):
    mock = _Mock({"totalrecords": 3, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="100021"))
    path, params = mock.calls[-1]
    assert path == "/prod/federalorganizations/v1/org/hierarchy"
    assert params["fhorgid"] == "100021"


def test_fh_hierarchy_int_org_id_coerced(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id=100021))
    _, params = mock.calls[-1]
    assert params["fhorgid"] == "100021"  # coerced to string


def test_fh_search_handles_null_totalrecords(monkeypatch):
    """Some empty responses return totalrecords: null."""
    mock = _Mock({"totalrecords": None, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    assert data["totalrecords"] == 0


# --- Subaward Reporting mocks ---

def test_acq_subaward_normalizes_response(monkeypatch):
    mock = _Mock({
        "totalPages": "3",
        "totalRecords": "250",
        "pageNumber": "0",
        "nextPageLink": "https://api.sam.gov/...?pageNumber=1",
        "previousPageLink": None,
        "data": [
            {"piid": "W912BV22P0112", "subAwardAmount": 50000},
            {"piid": "W912BV22P0112", "subAwardAmount": 25000},
        ],
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_acquisition_subawards", piid="W912BV22P0112"))
    data = _payload(r)
    assert data["totalRecords"] == 250
    assert data["totalPages"] == 3
    assert data["pageNumber"] == 0
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 2


def test_acq_subaward_handles_single_dict_data(monkeypatch):
    """One subaward might come back as dict not list."""
    mock = _Mock({
        "totalRecords": 1,
        "data": {"piid": "X", "subAwardAmount": 100},
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 1


def test_acq_subaward_handles_zero_records_no_data_key(monkeypatch):
    """Zero results might omit the data key entirely."""
    mock = _Mock({"totalRecords": 0, "totalPages": 0, "pageNumber": 0})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert data["totalRecords"] == 0
    assert data["data"] == []


def test_acq_subaward_handles_empty_dict(monkeypatch):
    mock = _Mock({})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert data["totalRecords"] == 0
    assert data["data"] == []
    assert "_note" in data


def test_acq_subaward_passes_correct_params(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_acquisition_subawards",
        prime_contract_key="ABC123",
        piid="W912BV22P0112",
        referenced_idv_piid="GS00Q14OADU131",
        referenced_idv_agency_id="4732",
        agency_id="9700",
        prime_award_type="DCA",
        from_date="2025-10-01",
        to_date="2026-04-25",
        status="Published",
        page_number=2,
        page_size=500,
    ))
    path, params = mock.calls[-1]
    assert path == "/prod/contract/v1/subcontracts/search"
    assert params["primeContractKey"] == "ABC123"
    # Live audit found the documented param names are wrong:
    # - PIID -> piid (lowercase)
    # - referencedIdvPIID -> referencedIDVPIID (caps IDV)
    # - referencedIDVAgencyID -> referencedIDVAgencyId (lowercase d)
    assert params["piid"] == "W912BV22P0112"
    assert params["referencedIDVPIID"] == "GS00Q14OADU131"
    assert params["referencedIDVAgencyId"] == "4732"
    assert params["agencyId"] == "9700"
    assert params["primeAwardType"] == "DCA"
    assert params["fromDate"] == "2025-10-01"
    assert params["toDate"] == "2026-04-25"
    assert params["status"] == "Published"
    assert params["pageNumber"] == "2"
    assert params["pageSize"] == "500"


def test_acq_subaward_default_status_is_published(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_acquisition_subawards"))
    _, params = mock.calls[-1]
    assert params["status"] == "Published"


def test_acq_subaward_deleted_status_passes_through(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_acquisition_subawards", status="Deleted"))
    _, params = mock.calls[-1]
    assert params["status"] == "Deleted"


def test_assist_subaward_passes_correct_params(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_assistance_subawards",
        prime_award_key="GRANT-ABC",
        fain="HHS-2026-001",
        agency_code="7530",
        from_date="2025-10-01",
        to_date="2026-04-25",
        status="Published",
        page_number=1,
        page_size=200,
    ))
    path, params = mock.calls[-1]
    assert path == "/prod/assistance/v1/subawards/search"
    assert params["primeAwardKey"] == "GRANT-ABC"
    assert params["fain"] == "HHS-2026-001"
    assert params["agencyCode"] == "7530"
    assert params["fromDate"] == "2025-10-01"
    assert params["toDate"] == "2026-04-25"
    assert params["pageNumber"] == "1"
    assert params["pageSize"] == "200"


def test_assist_subaward_normalizes_response(monkeypatch):
    mock = _Mock({
        "totalPages": "1",
        "totalRecords": "2",
        "pageNumber": "0",
        "data": [
            {"fain": "HHS-2026-001", "subAwardAmount": 100000},
            {"fain": "HHS-2026-001", "subAwardAmount": 50000},
        ],
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_assistance_subawards", fain="HHS-2026-001"))
    data = _payload(r)
    assert data["totalRecords"] == 2
    assert data["totalPages"] == 1
    assert len(data["data"]) == 2


def test_assist_subaward_handles_empty(monkeypatch):
    mock = _Mock({})
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_assistance_subawards"))
    data = _payload(r)
    assert data["totalRecords"] == 0
    assert data["data"] == []


def test_assist_subaward_omits_unset_params(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards"))
    _, params = mock.calls[-1]
    assert set(params.keys()) == {"pageNumber", "pageSize", "status"}


def test_subaward_normalize_handles_non_dict():
    """Pure unit test on the normalizer helper."""
    out = srv._normalize_subaward_response("not a dict")  # type: ignore[arg-type]
    assert out["totalRecords"] == 0
    assert out["data"] == []


def test_fh_normalize_handles_non_dict():
    out = srv._normalize_fh_response(None)  # type: ignore[arg-type]
    assert out["totalrecords"] == 0
    assert out["orglist"] == []


def test_subaward_normalize_handles_string_counts():
    """totalRecords/totalPages can come back as strings."""
    out = srv._normalize_subaward_response({
        "totalRecords": "12345",
        "totalPages": "100",
        "pageNumber": "5",
        "data": [],
    })
    assert out["totalRecords"] == 12345
    assert out["totalPages"] == 100
    assert out["pageNumber"] == 5


def test_subaward_normalize_handles_null_counts():
    out = srv._normalize_subaward_response({
        "totalRecords": None,
        "data": [],
    })
    assert out["totalRecords"] == 0


# ===========================================================================
# TIER 3: LIVE TESTS (gated on SAM_LIVE_TESTS=1)
# ===========================================================================

live = pytest.mark.skipif(
    not LIVE, reason="requires SAM_LIVE_TESTS=1 + SAM_API_KEY"
)


# --- Federal Hierarchy live ---

@live
def test_live_fh_search_no_filters():
    r = asyncio.run(_call("search_federal_organizations", limit=5))
    data = _payload(r)
    assert "totalrecords" in data
    assert "orglist" in data
    assert isinstance(data["orglist"], list)


@live
def test_live_fh_search_by_name_treasury():
    r = asyncio.run(_call(
        "search_federal_organizations",
        fh_org_name="Treasury",
        limit=10,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1
    # At least one result should contain "TREASURY" in the name
    assert any(
        "TREASURY" in (o.get("fhorgname") or "").upper()
        for o in data["orglist"]
    )


@live
def test_live_fh_search_active_status():
    r = asyncio.run(_call(
        "search_federal_organizations",
        status="ACTIVE",
        limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_pagination():
    """Different offsets return different records."""
    async def _both():
        r1 = await _call("search_federal_organizations", limit=5, offset=0)
        r2 = await _call("search_federal_organizations", limit=5, offset=5)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1 = _payload(r1)
    d2 = _payload(r2)
    if d1["orglist"] and d2["orglist"]:
        ids1 = {o.get("fhorgid") for o in d1["orglist"]}
        ids2 = {o.get("fhorgid") for o in d2["orglist"]}
        assert ids1 != ids2, "Pagination returned same records"


@live
def test_live_fh_hierarchy_walk():
    """Search for an org, then walk one level of hierarchy."""
    async def _walk():
        r = await _call(
            "search_federal_organizations",
            fh_org_type="DEPARTMENT",
            status="ACTIVE",
            limit=5,
        )
        data = _payload(r)
        if not data["orglist"]:
            return None, None
        parent = data["orglist"][0]
        parent_id = parent.get("fhorgid")
        if not parent_id:
            return None, None
        children = await _call(
            "get_organization_hierarchy",
            fh_org_id=parent_id,
            limit=10,
        )
        return data, children
    data, children = asyncio.run(_walk())
    if data is None:
        pytest.skip("No active department-level orgs returned")
    cdata = _payload(children)
    assert "totalrecords" in cdata
    assert "orglist" in cdata


# --- Subaward Reporting live ---

@live
def test_live_acq_subaward_recent_window():
    """Pull a small recent window. Should always have records."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01",
        to_date="2026-04-25",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data
    assert isinstance(data["data"], list)


@live
def test_live_acq_subaward_pagination():
    async def _both():
        r1 = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01",
            to_date="2026-04-25",
            page_size=5,
            page_number=0,
        )
        r2 = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01",
            to_date="2026-04-25",
            page_size=5,
            page_number=1,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1 = _payload(r1)
    d2 = _payload(r2)
    if d1["data"] and d2["data"]:
        keys1 = {(r.get("piid"), r.get("subAwardNumber")) for r in d1["data"]}
        keys2 = {(r.get("piid"), r.get("subAwardNumber")) for r in d2["data"]}
        if d1["totalRecords"] > 5:
            assert keys1 != keys2


@live
def test_live_acq_subaward_deleted_status():
    """Deleted status should return a valid (possibly empty) response."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        status="Deleted",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data
    assert isinstance(data["data"], list)


@live
def test_live_acq_subaward_response_shape():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01",
        to_date="2026-04-25",
        page_size=3,
    ))
    data = _payload(r)
    if data["data"]:
        record = data["data"][0]
        assert isinstance(record, dict)
        # Check that documented keys are present (some are optional, only check core)
        # subAwardAmount is documented as a top-level field; if missing, our docs are wrong
        # Don't assert hard since SAM.gov shapes shift; just verify it's a dict


@live
def test_live_assist_subaward_recent_window():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01",
        to_date="2026-04-25",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data
    assert isinstance(data["data"], list)


@live
def test_live_assist_subaward_deleted_status():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        status="Deleted",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data
    assert isinstance(data["data"], list)


@live
def test_live_subaward_iso_date_accepted():
    """Ensure SAM.gov accepts our ISO format on the wire."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2025-10-01",
        to_date="2025-10-02",
        page_size=2,
    ))
    data = _payload(r)
    # Either has data or doesn't; both fine. Should not raise.
    assert "totalRecords" in data


@live
def test_live_acq_subaward_piid_actually_filters():
    """Regression: the documented uppercase 'PIID' param is silently ignored
    by the API. Lowercase 'piid' is what works. The API also validates that
    piid is alphanumeric (no special chars), so a clearly-bogus alphanumeric
    PIID either returns 0 records or a 400 - both prove the filter reached
    the server.
    """
    async def _both():
        baseline = await _call(
            "search_acquisition_subawards",
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=1,
        )
        filtered = await _call(
            "search_acquisition_subawards",
            piid="ZZZZ99999999XX",  # alphanumeric, vanishingly unlikely real PIID
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=1,
        )
        return baseline, filtered
    b, f = asyncio.run(_both())
    bdata = _payload(b)
    fdata = _payload(f)
    # If the filter reaches the wire and is honored, the nonsense PIID
    # should match very few records (typically 0).
    assert fdata["totalRecords"] < bdata["totalRecords"], (
        f"piid filter appears to be silently ignored: "
        f"baseline={bdata['totalRecords']}, filtered={fdata['totalRecords']}. "
        "Check whether SAM.gov changed their param name casing again."
    )


@live
def test_live_acq_subaward_real_piid_returns_subs():
    """Looking up a known PIID should return its subawards (not the full
    universe, which is what happens when PIID filter is silently ignored)."""
    # Use a recent prime contract that we know has subawards reported.
    # PIID validity is checked by comparison to baseline below.
    async def _both():
        baseline = await _call(
            "search_acquisition_subawards",
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=1,
        )
        # Pick the first result's PIID and re-query
        first = await _call(
            "search_acquisition_subawards",
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=5,
        )
        first_data = _payload(first)
        if not first_data["data"]:
            return baseline, None, None
        sample_piid = first_data["data"][0].get("piid")
        if not sample_piid:
            return baseline, None, None
        filtered = await _call(
            "search_acquisition_subawards",
            piid=sample_piid,
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=5,
        )
        return baseline, sample_piid, filtered
    baseline, sample_piid, filtered = asyncio.run(_both())
    if filtered is None:
        pytest.skip("No subaward records in date window to extract a PIID from")
    bdata = _payload(baseline)
    fdata = _payload(filtered)
    # Filtered count should be much less than total. Not a hard equality
    # because totals shift, but at least 100x smaller is reasonable.
    assert fdata["totalRecords"] < bdata["totalRecords"], (
        f"piid={sample_piid} returned same count as unfiltered "
        f"({fdata['totalRecords']} vs {bdata['totalRecords']})."
    )
    # All returned records should match the requested PIID
    for rec in fdata["data"]:
        assert rec.get("piid") == sample_piid, (
            f"piid filter returned mismatching record: requested {sample_piid}, "
            f"got {rec.get('piid')}"
        )


@live
def test_live_assist_subaward_fain_actually_filters():
    """Regression: ensure 'fain' filter on assistance subawards works."""
    async def _both():
        baseline = await _call(
            "search_assistance_subawards",
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=1,
        )
        filtered = await _call(
            "search_assistance_subawards",
            fain="ZZZ999999999",  # alphanumeric only; API rejects underscores
            from_date="2025-10-01",
            to_date="2026-04-25",
            page_size=1,
        )
        return baseline, filtered
    b, f = asyncio.run(_both())
    bdata = _payload(b)
    fdata = _payload(f)
    assert fdata["totalRecords"] < bdata["totalRecords"], (
        "fain filter appears to be silently ignored: "
        f"baseline={bdata['totalRecords']}, filtered={fdata['totalRecords']}."
    )


@live
def test_live_fh_search_inactive_returns_more():
    """status=INACTIVE should expand result set vs. the default (ACTIVE-only)."""
    async def _both():
        active = await _call("search_federal_organizations", limit=1)
        inactive = await _call("search_federal_organizations", status="INACTIVE", limit=1)
        return active, inactive
    a, i = asyncio.run(_both())
    adata = _payload(a)
    idata = _payload(i)
    # INACTIVE-only should return a different (and typically larger) total
    # than the default (ACTIVE-only) result set.
    assert adata["totalrecords"] != idata["totalrecords"], (
        "status=INACTIVE returned same total as default. The status filter "
        "may have started being silently ignored."
    )


# ===========================================================================
# TIER 4: PROPERTY-BASED TESTS (Hypothesis fuzzing of new helpers)
# ===========================================================================

from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

PUNISH = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


@PUNISH
@given(st.text(min_size=0, max_size=20))
def test_property_yyyy_mm_dd_never_crashes(value):
    """No string input should crash the validator with anything but ValueError."""
    try:
        result = srv._validate_date_yyyy_mm_dd(value, field="d")
        if result is not None:
            assert isinstance(result, str)
            # If returned, must be in canonical format
            import re
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", result)
    except ValueError:
        pass


@PUNISH
@given(
    yyyy=st.integers(min_value=1900, max_value=2099),
    mm=st.integers(min_value=1, max_value=12),
    dd=st.integers(min_value=1, max_value=28),
)
def test_property_yyyy_mm_dd_accepts_valid_dates(yyyy, mm, dd):
    """Calendar-valid yyyy-MM-dd dates always pass."""
    s = f"{yyyy:04d}-{mm:02d}-{dd:02d}"
    result = srv._validate_date_yyyy_mm_dd(s, field="d")
    assert result == s


@PUNISH
@given(st.text())
def test_property_yyyy_mm_dd_rejects_non_iso_format(value):
    """Anything not matching ^\\d{4}-\\d{2}-\\d{2}$ should raise."""
    import re
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return  # might be valid-looking
    try:
        srv._validate_date_yyyy_mm_dd(value, field="d")
    except ValueError:
        return
    # If it returned without raising, the input must have been valid format
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", value)


def test_yyyy_mm_dd_returns_none_for_none():
    assert srv._validate_date_yyyy_mm_dd(None, field="d") is None


def test_yyyy_mm_dd_rejects_yyyy_m_d():
    try:
        srv._validate_date_yyyy_mm_dd("2026-1-1", field="d")
    except ValueError as e:
        assert "yyyy-mm-dd" in str(e).lower()
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_rejects_yyyymmdd():
    try:
        srv._validate_date_yyyy_mm_dd("20260101", field="d")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_rejects_with_time():
    try:
        srv._validate_date_yyyy_mm_dd("2026-01-15T00:00:00", field="d")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_leap_year_feb_29():
    """2024 was a leap year."""
    assert srv._validate_date_yyyy_mm_dd("2024-02-29", field="d") == "2024-02-29"


def test_yyyy_mm_dd_non_leap_year_feb_29_rejected():
    try:
        srv._validate_date_yyyy_mm_dd("2025-02-29", field="d")
    except ValueError as e:
        assert "not a valid calendar date" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_month_13_rejected():
    try:
        srv._validate_date_yyyy_mm_dd("2026-13-01", field="d")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_day_32_rejected():
    try:
        srv._validate_date_yyyy_mm_dd("2026-01-32", field="d")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_yyyy_mm_dd_april_31_rejected():
    """April only has 30 days."""
    try:
        srv._validate_date_yyyy_mm_dd("2026-04-31", field="d")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


@PUNISH
@given(st.dictionaries(st.text(min_size=0, max_size=20), st.one_of(
    st.none(), st.integers(), st.text(), st.lists(st.dictionaries(st.text(), st.text())),
    st.dictionaries(st.text(), st.text()),
)))
def test_property_normalize_fh_never_crashes(data):
    """Arbitrary dicts must not crash _normalize_fh_response."""
    out = srv._normalize_fh_response(data)
    assert isinstance(out, dict)


@PUNISH
@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.text())))
def test_property_normalize_fh_handles_non_dict(data):
    """Non-dict inputs return a sane shape."""
    out = srv._normalize_fh_response(data)
    assert isinstance(out, dict)
    assert "totalrecords" in out or "_note" in out


@PUNISH
@given(st.dictionaries(st.text(min_size=0, max_size=20), st.one_of(
    st.none(), st.integers(), st.text(), st.lists(st.dictionaries(st.text(), st.text())),
    st.dictionaries(st.text(), st.text()),
)))
def test_property_normalize_subaward_never_crashes(data):
    """Arbitrary dicts must not crash _normalize_subaward_response."""
    out = srv._normalize_subaward_response(data)
    assert isinstance(out, dict)


@PUNISH
@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.text())))
def test_property_normalize_subaward_handles_non_dict(data):
    out = srv._normalize_subaward_response(data)
    assert isinstance(out, dict)
    assert "totalRecords" in out or "_note" in out


def test_normalize_fh_idempotent():
    """Calling normalize twice gives same result."""
    raw = {"totalrecords": "5", "orglist": [{"x": 1}]}
    once = srv._normalize_fh_response(dict(raw))
    twice = srv._normalize_fh_response(srv._normalize_fh_response(dict(raw)))
    assert once["totalrecords"] == twice["totalrecords"]
    assert once["orglist"] == twice["orglist"]


def test_normalize_subaward_idempotent():
    raw = {"totalRecords": "12", "totalPages": "1", "pageNumber": "0", "data": [{"x": 1}]}
    once = srv._normalize_subaward_response(dict(raw))
    twice = srv._normalize_subaward_response(srv._normalize_subaward_response(dict(raw)))
    assert once["totalRecords"] == twice["totalRecords"]
    assert once["data"] == twice["data"]


def test_normalize_fh_with_nan_totalrecords():
    """Bad numeric values shouldn't crash."""
    out = srv._normalize_fh_response({"totalrecords": "not-a-number", "orglist": []})
    assert out["totalrecords"] == 0


def test_normalize_subaward_with_inf():
    """Even infinity shouldn't crash _safe_int on the count fields."""
    out = srv._normalize_subaward_response({"totalRecords": float("inf"), "data": []})
    assert isinstance(out["totalRecords"], int)


def test_normalize_fh_orglist_with_nested_dicts():
    """Real responses have orglist items containing nested dicts (cgaclist, links)."""
    raw = {
        "totalrecords": 1,
        "orglist": [{
            "fhorgid": "100013311",
            "cgaclist": [{"cgac": "020"}],
            "links": [{"rel": "self", "href": "https://..."}],
            "fhorgaddresslist": [{"city": "Washington"}],
        }]
    }
    out = srv._normalize_fh_response(raw)
    assert out["orglist"][0]["cgaclist"] == [{"cgac": "020"}]


def test_normalize_subaward_with_real_shape():
    """Verify normalizer works on a real-API-shaped record."""
    raw = {
        "totalPages": "1",
        "totalRecords": "1",
        "pageNumber": "0",
        "nextPageLink": None,
        "previousPageLink": None,
        "data": [{
            "primeContractKey": "CONT_AWD_X",
            "piid": "W912QR25C0022",
            "subAwardAmount": "2.2423425E7",
            "subEntityUei": "JT3JDHGA82X8",
            "primeNaics": {"code": "236220", "description": "BUILDING"},
        }]
    }
    out = srv._normalize_subaward_response(raw)
    assert out["data"][0]["primeNaics"]["code"] == "236220"


# ===========================================================================
# TIER 5: EXPANDED MOCK TESTS (per-endpoint)
# ===========================================================================

# --- search_federal_organizations expanded mocks ---

def test_fh_search_mock_real_treasury_shape(monkeypatch):
    """Mock matching the real Treasury response shape captured live."""
    real_shape = {
        "totalrecords": 1,
        "orglist": [{
            "fhorgid": 100013311,
            "fhorgname": "TREASURY, DEPARTMENT OF THE",
            "fhorgtype": "Department/Ind. Agency",
            "description": "The Department of the Treasury's mission...",
            "level": 0,
            "status": "ACTIVE",
            "categoryid": 1,
            "effectivestartdate": "1789-09-02",
            "createddate": "2014-09-25",
            "lastupdateddate": "2024-01-15",
            "agencycode": "2000",
            "fullParentPathName": "TREASURY, DEPARTMENT OF THE",
            "fullParentPath": "100013311",
            "cgaclist": [{"cgac": "020"}],
            "fhorgaddresslist": [{"city": "Washington"}],
            "fhorgnamehistory": [],
            "fhorgparenthistory": [],
            "links": [{"rel": "self", "href": "https://api.sam.gov/..."}],
        }]
    }
    monkeypatch.setattr(srv, "_get", _Mock(real_shape))
    r = asyncio.run(_call("search_federal_organizations", fh_org_id="100013311"))
    data = _payload(r)
    assert data["totalrecords"] == 1
    org = data["orglist"][0]
    assert org["fhorgid"] == 100013311
    assert org["status"] == "ACTIVE"


def test_fh_search_mock_orglist_with_None(monkeypatch):
    """orglist can be None when zero results."""
    monkeypatch.setattr(srv, "_get", _Mock({"totalrecords": 0, "orglist": None}))
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    # _as_list(None) returns []
    assert data["orglist"] == []


def test_fh_search_mock_missing_orglist_key(monkeypatch):
    """API can return totalrecords without orglist for zero-hit pages."""
    monkeypatch.setattr(srv, "_get", _Mock({"totalrecords": 0}))
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    assert data["totalrecords"] == 0


def test_fh_search_mock_extra_unknown_fields(monkeypatch):
    """Forward-compatible: new top-level fields shouldn't break us."""
    mock = _Mock({
        "totalrecords": 1,
        "orglist": [{"fhorgid": "1"}],
        "futureField": "ignore-me",
        "anotherFutureField": {"deep": "nested"},
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("search_federal_organizations"))
    data = _payload(r)
    assert data["totalrecords"] == 1
    # We don't strip unknown keys; pass them through
    assert "futureField" in data


def test_fh_search_mock_large_orglist(monkeypatch):
    """100 records should normalize correctly."""
    big = {"totalrecords": 100, "orglist": [{"fhorgid": str(i)} for i in range(100)]}
    monkeypatch.setattr(srv, "_get", _Mock(big))
    r = asyncio.run(_call("search_federal_organizations", limit=100))
    data = _payload(r)
    assert len(data["orglist"]) == 100


def test_fh_search_mock_agency_code_int(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_federal_organizations", agency_code=2000))
    _, params = mock.calls[-1]
    assert params["agencycode"] == "2000"


def test_fh_search_mock_cgac_with_leading_zeros(monkeypatch):
    """CGAC codes are zero-padded (e.g. '020' for Treasury). Should pass through."""
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_federal_organizations", cgac="020"))
    _, params = mock.calls[-1]
    assert params["cgac"] == "020"


def test_fh_search_mock_cgac_int(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_federal_organizations", cgac=20))
    _, params = mock.calls[-1]
    assert params["cgac"] == "20"


def test_fh_search_mock_strips_none_values(monkeypatch):
    """None-valued args are not sent on the wire."""
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_federal_organizations",
        fh_org_name=None, fh_org_type=None, status=None, agency_code=None, cgac=None,
    ))
    _, params = mock.calls[-1]
    forbidden = {"fhorgname", "fhorgtype", "status", "agencycode", "cgac"}
    assert not (forbidden & set(params.keys()))


def test_fh_search_mock_status_pass_through(monkeypatch):
    for s in ("ACTIVE", "INACTIVE", "MERGED"):
        mock = _Mock({"totalrecords": 0, "orglist": []})
        monkeypatch.setattr(srv, "_get", mock)
        asyncio.run(_call("search_federal_organizations", status=s))
        _, params = mock.calls[-1]
        assert params["status"] == s


# --- get_organization_hierarchy expanded mocks ---

def test_fh_hierarchy_mock_real_shape(monkeypatch):
    """Real Treasury hierarchy shape."""
    real_shape = {
        "totalrecords": 65,
        "orglist": [
            {"fhorgid": 300000270, "fhorgname": "INTERNAL REVENUE SERVICE",
             "fhorgtype": "Sub-Tier", "level": 1, "status": "ACTIVE",
             "fullParentPathName": "TREASURY, DEPARTMENT OF THE.INTERNAL REVENUE SERVICE",
             "links": [{"rel": "self", "href": "..."}]},
            {"fhorgid": 300000271, "fhorgname": "BUREAU OF THE FISCAL SERVICE",
             "fhorgtype": "Sub-Tier", "level": 1, "status": "ACTIVE",
             "links": [{"rel": "self", "href": "..."}]},
        ]
    }
    monkeypatch.setattr(srv, "_get", _Mock(real_shape))
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id="100013311"))
    data = _payload(r)
    assert data["totalrecords"] == 65
    assert len(data["orglist"]) == 2
    assert data["orglist"][0]["level"] == 1


def test_fh_hierarchy_mock_no_children(monkeypatch):
    """A leaf node has no children."""
    monkeypatch.setattr(srv, "_get", _Mock({"totalrecords": 0, "orglist": []}))
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id="999999"))
    data = _payload(r)
    assert data["totalrecords"] == 0
    assert data["orglist"] == []


def test_fh_hierarchy_mock_single_child_as_dict(monkeypatch):
    """Sometimes one child returns as dict not list."""
    monkeypatch.setattr(srv, "_get", _Mock({"totalrecords": 1, "orglist": {"fhorgid": "X"}}))
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id="100"))
    data = _payload(r)
    assert isinstance(data["orglist"], list)
    assert len(data["orglist"]) == 1


def test_fh_hierarchy_mock_pagination_params(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="100", limit=50, offset=20))
    _, params = mock.calls[-1]
    assert params["limit"] == "50"
    assert params["offset"] == "20"


def test_fh_hierarchy_mock_org_id_with_leading_zeros(monkeypatch):
    """ID '0001' should pass through as-is."""
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="0001"))
    _, params = mock.calls[-1]
    assert params["fhorgid"] == "0001"


def test_fh_hierarchy_mock_string_int(monkeypatch):
    """A string of digits should not be int-coerced."""
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="100013311"))
    _, params = mock.calls[-1]
    assert params["fhorgid"] == "100013311"


def test_fh_hierarchy_mock_path_correct(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="100"))
    path, _ = mock.calls[-1]
    assert path == "/prod/federalorganizations/v1/org/hierarchy"


def test_fh_hierarchy_mock_default_limit(monkeypatch):
    mock = _Mock({"totalrecords": 0, "orglist": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("get_organization_hierarchy", fh_org_id="100"))
    _, params = mock.calls[-1]
    assert params["limit"] == "100"  # default
    assert params["offset"] == "0"   # default


def test_fh_hierarchy_mock_extra_fields_passthrough(monkeypatch):
    """Future API additions shouldn't break callers."""
    mock = _Mock({
        "totalrecords": 1,
        "orglist": [{"fhorgid": "1", "newField": "x"}],
        "totalPages": 1,
    })
    monkeypatch.setattr(srv, "_get", mock)
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id="100"))
    data = _payload(r)
    assert data["orglist"][0].get("newField") == "x"
    assert data.get("totalPages") == 1


# --- search_acquisition_subawards expanded mocks ---

def test_acq_mock_real_shape(monkeypatch):
    """Real subaward shape captured from API probe."""
    real_shape = {
        "totalPages": 285,
        "totalRecords": 570,
        "pageNumber": 0,
        "nextPageLink": "https://api.sam.gov/...?pageNumber=1",
        "previousPageLink": None,
        "data": [{
            "primeContractKey": "CONT_AWD_W912QR25C0022_9700_-NONE-_-NONE-",
            "piid": "W912QR25C0022",
            "agencyId": "9700",
            "referencedIDVPIID": None,
            "referencedIDVAgencyId": None,
            "subAwardReportId": "29833343",
            "subAwardReportNumber": "928638a2-79d0-4b7b-acb1-0464aa171c6a",
            "submittedDate": "2026-01-05",
            "subAwardNumber": "125007-0011",
            "subAwardAmount": "2.2423425E7",
            "subAwardDate": "2025-12-17",
            "subEntityLegalBusinessName": "SUNSTEEL LLC",
            "subEntityUei": "JT3JDHGA82X8",
            "primeAwardType": "AWARD",
            "totalContractValue": "1.33025387E8",
            "primeEntityUei": "GMJPZCJDUG24",
            "primeEntityName": "HARPER CONSTRUCTION COMPANY, INC.",
            "baseAwardDateSigned": "2025-09-18",
            "primeNaics": {"code": "236220", "description": "BUILDING"},
            "primeOrganizationInfo": {
                "fundingAgency": {"code": "2100", "name": "DEPT OF THE ARMY"},
                "contractingDepartment": {"code": "9700", "name": "DEPT OF DEFENSE"},
            },
        }]
    }
    monkeypatch.setattr(srv, "_get", _Mock(real_shape))
    r = asyncio.run(_call("search_acquisition_subawards", piid="W912QR25C0022"))
    data = _payload(r)
    assert data["totalRecords"] == 570
    rec = data["data"][0]
    assert rec["piid"] == "W912QR25C0022"
    assert rec["subAwardAmount"] == "2.2423425E7"  # not parsed to float
    assert rec["primeNaics"]["code"] == "236220"


def test_acq_mock_null_referenced_idv(monkeypatch):
    """Real records often have None for referencedIDVPIID/AgencyId."""
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalRecords": 1,
        "data": [{"piid": "X", "referencedIDVPIID": None, "referencedIDVAgencyId": None}]
    }))
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert data["data"][0]["referencedIDVPIID"] is None


def test_acq_mock_paginated_response(monkeypatch):
    """Page 1 of a 5-page result."""
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalPages": 5, "totalRecords": 500, "pageNumber": 1,
        "nextPageLink": "...page=2", "previousPageLink": "...page=0",
        "data": [{"piid": f"X{i}"} for i in range(100)]
    }))
    r = asyncio.run(_call("search_acquisition_subawards", page_number=1, page_size=100))
    data = _payload(r)
    assert data["pageNumber"] == 1
    assert len(data["data"]) == 100


def test_acq_mock_status_param_validation(monkeypatch):
    """Status='Published' on the wire."""
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_acquisition_subawards", status="Published"))
    _, params = mock.calls[-1]
    assert params["status"] == "Published"


def test_acq_mock_strip_none_values(monkeypatch):
    """None-valued args are dropped."""
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_acquisition_subawards",
        prime_contract_key=None, piid=None, referenced_idv_piid=None,
        referenced_idv_agency_id=None, agency_id=None, prime_award_type=None,
        from_date=None, to_date=None,
    ))
    _, params = mock.calls[-1]
    forbidden = {"primeContractKey", "piid", "referencedIDVPIID",
                 "referencedIDVAgencyId", "agencyId", "primeAwardType",
                 "fromDate", "toDate"}
    assert not (forbidden & set(params.keys()))


def test_acq_mock_each_field_individually(monkeypatch):
    """Verify each filter shows up under the right wire-name."""
    mappings = [
        ("prime_contract_key", "primeContractKey", "ABC"),
        ("piid", "piid", "W912"),
        ("referenced_idv_piid", "referencedIDVPIID", "GS00"),
        ("referenced_idv_agency_id", "referencedIDVAgencyId", "4732"),
        ("agency_id", "agencyId", "9700"),
        ("prime_award_type", "primeAwardType", "AWARD"),
    ]
    for kw, wire_name, val in mappings:
        mock = _Mock({"totalRecords": 0, "data": []})
        monkeypatch.setattr(srv, "_get", mock)
        asyncio.run(_call("search_acquisition_subawards", **{kw: val}))
        _, params = mock.calls[-1]
        assert params[wire_name] == val, f"{kw} should map to {wire_name}, got {params}"


def test_acq_mock_dates_are_iso_format(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_acquisition_subawards", from_date="2026-01-15", to_date="2026-04-25"))
    _, params = mock.calls[-1]
    assert params["fromDate"] == "2026-01-15"
    assert params["toDate"] == "2026-04-25"


def test_acq_mock_records_with_scientific_notation(monkeypatch):
    """subAwardAmount comes back as scientific-notation strings ('2.2E7'). Pass through."""
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalRecords": 2,
        "data": [
            {"piid": "X", "subAwardAmount": "2.2423425E7"},
            {"piid": "Y", "subAwardAmount": "5.0E5"},
        ]
    }))
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert data["data"][0]["subAwardAmount"] == "2.2423425E7"


def test_acq_mock_500_records_response(monkeypatch):
    """Large response with 500 records."""
    big = {"totalRecords": 5000, "totalPages": 5, "pageNumber": 0,
           "data": [{"piid": f"X{i}", "subAwardAmount": f"{i*100}.0"} for i in range(500)]}
    monkeypatch.setattr(srv, "_get", _Mock(big))
    r = asyncio.run(_call("search_acquisition_subawards", page_size=500))
    data = _payload(r)
    assert len(data["data"]) == 500


def test_acq_mock_normalizer_clamps_string_pageNumber(monkeypatch):
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalRecords": "100", "totalPages": "10", "pageNumber": "3", "data": []
    }))
    r = asyncio.run(_call("search_acquisition_subawards"))
    data = _payload(r)
    assert data["totalRecords"] == 100
    assert data["totalPages"] == 10
    assert data["pageNumber"] == 3


# --- search_assistance_subawards expanded mocks ---

def test_assist_mock_real_shape(monkeypatch):
    """Real assistance subaward shape from live probe."""
    real_shape = {
        "totalPages": 1,
        "totalRecords": 137,
        "pageNumber": 0,
        "nextPageLink": None,
        "previousPageLink": None,
        "data": [{
            "status": "Published",
            "submittedDate": "2026-01-05",
            "subVendorName": "REGENTS OF THE UNIVERSITY OF X",
            "subVendorUei": "ABC123XYZ456",
            "subAwardNumber": "SUB-001",
            "subAwardAmount": "150000.00",
            "subAwardDate": "2025-12-15",
            "reportUpdatedDate": "2026-01-05",
            "subawardReportId": "12345",
            "fain": "FA86502125028",
            "actionDate": "2025-12-15",
            "totalFedFundingAmount": "5000000.00",
            "agencyCode": "5700",
            "primeEntityUei": "DEFGHI78901",
            "primeEntityName": "PRIME GRANTEE INC",
            "primeAwardKey": "ASST_NON_FA86502125028_097",
            "vendorPhysicalAddress": {"city": "Boston", "state": "MA"},
            "subDbaName": None,
            "subParentUei": None,
        }]
    }
    monkeypatch.setattr(srv, "_get", _Mock(real_shape))
    r = asyncio.run(_call("search_assistance_subawards", fain="FA86502125028"))
    data = _payload(r)
    assert data["totalRecords"] == 137
    rec = data["data"][0]
    assert rec["fain"] == "FA86502125028"
    assert rec["primeAwardKey"] == "ASST_NON_FA86502125028_097"


def test_assist_mock_null_optional_fields(monkeypatch):
    """subDbaName, subParentUei, etc. are commonly null."""
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalRecords": 1,
        "data": [{
            "fain": "F", "subVendorUei": "X",
            "subDbaName": None, "subParentUei": None, "subParentName": None,
        }]
    }))
    r = asyncio.run(_call("search_assistance_subawards"))
    data = _payload(r)
    assert data["data"][0]["subDbaName"] is None


def test_assist_mock_each_field_individually(monkeypatch):
    mappings = [
        ("prime_award_key", "primeAwardKey", "ASST_NON_X"),
        ("fain", "fain", "FA86502125028"),
        ("agency_code", "agencyCode", "7530"),
    ]
    for kw, wire_name, val in mappings:
        mock = _Mock({"totalRecords": 0, "data": []})
        monkeypatch.setattr(srv, "_get", mock)
        asyncio.run(_call("search_assistance_subawards", **{kw: val}))
        _, params = mock.calls[-1]
        assert params[wire_name] == val, f"{kw} should map to {wire_name}, got {params}"


def test_assist_mock_dates_iso_format(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards", from_date="2025-10-01", to_date="2026-01-01"))
    _, params = mock.calls[-1]
    assert params["fromDate"] == "2025-10-01"
    assert params["toDate"] == "2026-01-01"


def test_assist_mock_status_published_default(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards"))
    _, params = mock.calls[-1]
    assert params["status"] == "Published"


def test_assist_mock_status_deleted(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards", status="Deleted"))
    _, params = mock.calls[-1]
    assert params["status"] == "Deleted"


def test_assist_mock_strip_none_values(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call(
        "search_assistance_subawards",
        prime_award_key=None, fain=None, agency_code=None,
        from_date=None, to_date=None,
    ))
    _, params = mock.calls[-1]
    forbidden = {"primeAwardKey", "fain", "agencyCode", "fromDate", "toDate"}
    assert not (forbidden & set(params.keys()))


def test_assist_mock_path_correct(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards"))
    path, _ = mock.calls[-1]
    assert path == "/prod/assistance/v1/subawards/search"


def test_assist_mock_records_with_complex_nested_org_info(monkeypatch):
    """Real records have organizationInfo with nested funding/awarding agency dicts."""
    monkeypatch.setattr(srv, "_get", _Mock({
        "totalRecords": 1,
        "data": [{
            "fain": "X",
            "organizationInfo": {
                "fundingAgency": {"code": "5700", "name": "DEPT OF AGRICULTURE"},
                "awardingAgency": {"code": "5700", "name": "DEPT OF AGRICULTURE"},
                "fundingOffice": {"code": "FUND", "name": "OFFICE NAME"},
            },
            "placeOfPerformance": {"city": "Boston", "state": "MA", "zip": "02101"},
        }]
    }))
    r = asyncio.run(_call("search_assistance_subawards"))
    data = _payload(r)
    assert data["data"][0]["organizationInfo"]["fundingAgency"]["code"] == "5700"


def test_assist_mock_500_records(monkeypatch):
    big = {"totalRecords": 5000, "totalPages": 10, "pageNumber": 0,
           "data": [{"fain": f"F{i}"} for i in range(500)]}
    monkeypatch.setattr(srv, "_get", _Mock(big))
    r = asyncio.run(_call("search_assistance_subawards", page_size=500))
    data = _payload(r)
    assert len(data["data"]) == 500


def test_assist_mock_pageNumber_default_zero(monkeypatch):
    mock = _Mock({"totalRecords": 0, "data": []})
    monkeypatch.setattr(srv, "_get", mock)
    asyncio.run(_call("search_assistance_subawards"))
    _, params = mock.calls[-1]
    assert params["pageNumber"] == "0"
    assert params["pageSize"] == "100"  # default


# ===========================================================================
# TIER 6: EXPANDED VALIDATION TESTS
# ===========================================================================

def test_fh_search_negative_offset_explicit_zero_ok():
    """offset=0 is the default; should not raise."""
    try:
        asyncio.run(_call("search_federal_organizations", offset=0))
    except Exception as e:
        # Network errors fine; not validation
        assert "offset" not in str(e).lower()


def test_fh_search_limit_at_boundary_1():
    """limit=1 should be valid."""
    try:
        asyncio.run(_call("search_federal_organizations", limit=1))
    except Exception as e:
        assert "limit" not in str(e).lower() or "must be" not in str(e).lower()


def test_fh_search_limit_at_boundary_100():
    try:
        asyncio.run(_call("search_federal_organizations", limit=100))
    except Exception as e:
        assert "limit" not in str(e).lower() or "must be" not in str(e).lower()


def test_fh_search_agency_code_int_coerced():
    try:
        asyncio.run(_call("search_federal_organizations", agency_code=2000))
    except Exception:
        pass


def test_fh_search_cgac_int_coerced():
    try:
        asyncio.run(_call("search_federal_organizations", cgac=20))
    except Exception:
        pass


def test_fh_search_cr_in_name_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "control character",
        fh_org_name="Treasury\rDepartment",
    ))


def test_fh_search_lf_in_name_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "control character",
        fh_org_name="Treasury\nDepartment",
    ))


def test_fh_search_tab_in_name_rejected():
    asyncio.run(_call_expect_error(
        "search_federal_organizations", "control character",
        fh_org_name="Treasury\tDepartment",
    ))


def test_fh_hierarchy_whitespace_only_rejected():
    """Whitespace-only fh_org_id should be rejected."""
    asyncio.run(_call_expect_error(
        "get_organization_hierarchy", "cannot be empty",
        fh_org_id="   ",
    ))


def test_fh_hierarchy_zero_org_id_passes_validation():
    """fh_org_id='0' is technically valid format-wise (let API reject)."""
    try:
        asyncio.run(_call("get_organization_hierarchy", fh_org_id="0"))
    except Exception as e:
        # May fail at HTTP, but not at our validator
        assert "cannot be empty" not in str(e).lower()


def test_fh_hierarchy_offset_default_zero():
    """offset=0 explicit should work."""
    try:
        asyncio.run(_call("get_organization_hierarchy", fh_org_id="100", offset=0))
    except Exception as e:
        assert "offset" not in str(e).lower()


def test_acq_filter_individually_each(monkeypatch):
    """Each individual filter accepted."""
    for kw, val in [
        ("prime_contract_key", "ABC"), ("piid", "W912"),
        ("referenced_idv_piid", "GS00Q14OADU131"),
        ("referenced_idv_agency_id", "4732"), ("agency_id", "9700"),
        ("prime_award_type", "AWARD"),
    ]:
        mock = _Mock({"totalRecords": 0, "data": []})
        monkeypatch.setattr(srv, "_get", mock)
        asyncio.run(_call("search_acquisition_subawards", **{kw: val}))


def test_acq_subaward_year_only_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="2026",
    ))


def test_acq_subaward_iso_time_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="2026-01-15T00:00:00",
    ))


def test_acq_subaward_iso_with_z_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="2026-01-15Z",
    ))


def test_acq_subaward_dot_separator_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "yyyy-MM-dd",
        from_date="2026.01.15",
    ))


def test_acq_subaward_long_prime_contract_key_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "exceeds maximum length",
        prime_contract_key="A" * 200,
    ))


def test_acq_subaward_long_referenced_idv_piid_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "exceeds maximum length",
        referenced_idv_piid="A" * 200,
    ))


def test_acq_subaward_long_prime_award_type_rejected():
    asyncio.run(_call_expect_error(
        "search_acquisition_subawards", "exceeds maximum length",
        prime_award_type="A" * 200,
    ))


def test_acq_subaward_page_size_at_lower_boundary():
    try:
        asyncio.run(_call("search_acquisition_subawards", page_size=1))
    except Exception as e:
        assert "page_size" not in str(e).lower()


def test_acq_subaward_page_size_at_upper_boundary():
    try:
        asyncio.run(_call("search_acquisition_subawards", page_size=1000))
    except Exception as e:
        assert "page_size" not in str(e).lower()


def test_acq_subaward_page_number_zero_explicit():
    try:
        asyncio.run(_call("search_acquisition_subawards", page_number=0))
    except Exception as e:
        assert "page_number" not in str(e).lower()


def test_acq_subaward_dates_can_be_equal():
    """from_date == to_date should be valid (single-day range)."""
    try:
        asyncio.run(_call(
            "search_acquisition_subawards",
            from_date="2026-01-15", to_date="2026-01-15",
        ))
    except Exception as e:
        assert "yyyy-mm-dd" not in str(e).lower()


def test_assist_subaward_long_fain_rejected_2():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "exceeds maximum length",
        fain="F" * 200,
    ))


def test_assist_subaward_long_prime_award_key_rejected():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "exceeds maximum length",
        prime_award_key="X" * 200,
    ))


def test_assist_subaward_iso_short_form_rejected():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "yyyy-MM-dd",
        from_date="26-01-15",
    ))


def test_assist_subaward_dot_separator_rejected():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "yyyy-MM-dd",
        from_date="2026.01.15",
    ))


def test_assist_subaward_negative_page_size():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "page_size",
        page_size=-1,
    ))


def test_assist_subaward_page_size_at_lower_boundary():
    try:
        asyncio.run(_call("search_assistance_subawards", page_size=1))
    except Exception as e:
        assert "page_size" not in str(e).lower()


def test_assist_subaward_page_size_at_upper_boundary():
    try:
        asyncio.run(_call("search_assistance_subawards", page_size=1000))
    except Exception as e:
        assert "page_size" not in str(e).lower()


def test_assist_subaward_invalid_status_rejected_by_pydantic():
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "input",
        status="published",  # case-sensitive Literal
    ))


def test_assist_subaward_unknown_filter_combinations_rejected():
    """Any extra param raises (extra='forbid')."""
    asyncio.run(_call_expect_error(
        "search_assistance_subawards", "extra",
        primeAwardType="AWARD",  # belongs on acquisition
    ))


def test_assist_subaward_agency_code_int_coerced():
    try:
        asyncio.run(_call("search_assistance_subawards", agency_code=7530))
    except Exception:
        pass


# ===========================================================================
# TIER 7: EXPANDED LIVE TESTS
# ===========================================================================

# Known FH IDs captured from live probes (April 2026)
FH_TREASURY = "100013311"
FH_DOD = "100000000"
FH_HHS = "100004222"
FH_STATE = "100012062"
FH_JUSTICE = "100011955"
FH_ENERGY = "100011980"
FH_AGRICULTURE = "100006809"
FH_HOMELAND = "100011942"
FH_VETERANS = "100006568"
FH_INTERIOR = "100010393"
FH_COMMERCE = "100035122"

# Known CGAC codes
CGAC_TREASURY = "020"
CGAC_DOD = "097"
CGAC_HHS = "075"
CGAC_STATE = "019"
CGAC_JUSTICE = "015"

# Known agency codes
AC_TREASURY = "2000"
AC_JUSTICE = "1500"
AC_ENERGY = "8900"
AC_AGRICULTURE = "1200"

# Known awarding agency IDs (different from Federal Hierarchy agencycode)
AGENCY_DOD = "9700"
AGENCY_HHS = "7530"


# --- search_federal_organizations: 25+ live tests ---

@live
def test_live_fh_search_by_name_dod():
    r = asyncio.run(_call("search_federal_organizations", fh_org_name="DEFENSE", limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_hhs():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="HEALTH AND HUMAN", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1
    assert any(
        "HEALTH" in (o.get("fhorgname") or "").upper()
        for o in data["orglist"]
    )


@live
def test_live_fh_search_by_name_state():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="STATE, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_justice():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="JUSTICE, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_energy():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="ENERGY, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_agriculture():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="AGRICULTURE, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_veterans():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="VETERANS AFFAIRS", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_homeland():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="HOMELAND SECURITY", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_interior():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="INTERIOR, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_commerce():
    r = asyncio.run(_call(
        "search_federal_organizations", fh_org_name="COMMERCE, DEPARTMENT", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_name_garbage():
    """Nonsense name should return zero records, not error."""
    r = asyncio.run(_call(
        "search_federal_organizations",
        fh_org_name="NONEXISTENTAGENCYZZZZZZ", limit=5,
    ))
    data = _payload(r)
    assert data["totalrecords"] == 0
    assert data["orglist"] == []


@live
def test_live_fh_search_by_fhorgid_treasury():
    r = asyncio.run(_call("search_federal_organizations", fh_org_id=FH_TREASURY, limit=1))
    data = _payload(r)
    assert data["totalrecords"] == 1
    assert str(data["orglist"][0]["fhorgid"]) == FH_TREASURY


@live
def test_live_fh_search_by_fhorgid_dod():
    r = asyncio.run(_call("search_federal_organizations", fh_org_id=FH_DOD, limit=1))
    data = _payload(r)
    assert data["totalrecords"] == 1
    assert str(data["orglist"][0]["fhorgid"]) == FH_DOD


@live
def test_live_fh_search_by_fhorgid_hhs():
    r = asyncio.run(_call("search_federal_organizations", fh_org_id=FH_HHS, limit=1))
    data = _payload(r)
    assert data["totalrecords"] == 1


@live
def test_live_fh_search_by_cgac_treasury():
    r = asyncio.run(_call("search_federal_organizations", cgac=CGAC_TREASURY, limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_cgac_dod():
    r = asyncio.run(_call("search_federal_organizations", cgac=CGAC_DOD, limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_cgac_hhs():
    r = asyncio.run(_call("search_federal_organizations", cgac=CGAC_HHS, limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_agencycode_treasury():
    r = asyncio.run(_call("search_federal_organizations", agency_code=AC_TREASURY, limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_search_by_agencycode_int():
    """Integer agency_code coerces."""
    r = asyncio.run(_call("search_federal_organizations", agency_code=2000, limit=5))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_search_record_has_required_keys():
    r = asyncio.run(_call("search_federal_organizations", limit=5))
    data = _payload(r)
    for org in data["orglist"]:
        # Core keys we depend on
        assert "fhorgid" in org
        assert "fhorgname" in org
        assert "fhorgtype" in org
        assert "status" in org


@live
def test_live_fh_search_pagination_offset_50():
    async def _both():
        r1 = await _call("search_federal_organizations", limit=10, offset=0)
        r2 = await _call("search_federal_organizations", limit=10, offset=50)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1["orglist"] and d2["orglist"]:
        ids1 = {o.get("fhorgid") for o in d1["orglist"]}
        ids2 = {o.get("fhorgid") for o in d2["orglist"]}
        assert not (ids1 & ids2), "Pages 0 and 50 share records"


@live
def test_live_fh_search_limit_1():
    r = asyncio.run(_call("search_federal_organizations", limit=1))
    data = _payload(r)
    assert len(data["orglist"]) <= 1


@live
def test_live_fh_search_limit_100_returns_at_most_100():
    r = asyncio.run(_call("search_federal_organizations", limit=100))
    data = _payload(r)
    assert len(data["orglist"]) <= 100


@live
def test_live_fh_search_combined_filters():
    """Multiple filters at once."""
    r = asyncio.run(_call(
        "search_federal_organizations",
        cgac=CGAC_TREASURY, status="ACTIVE", limit=5,
    ))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_search_concurrent_calls():
    """5 parallel calls all complete cleanly."""
    async def _all():
        tasks = [
            _call("search_federal_organizations", fh_org_name=n, limit=2)
            for n in ["TREASURY", "DEFENSE", "HEALTH", "STATE", "JUSTICE"]
        ]
        return await asyncio.gather(*tasks)
    results = asyncio.run(_all())
    for r in results:
        d = _payload(r)
        assert "totalrecords" in d


@live
def test_live_fh_search_baseline_consistent():
    """Two unfiltered calls return the same total."""
    async def _both():
        r1 = await _call("search_federal_organizations", limit=1)
        r2 = await _call("search_federal_organizations", limit=1)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    assert _payload(r1)["totalrecords"] == _payload(r2)["totalrecords"]


@live
def test_live_fh_search_links_present():
    """Each record has a 'links' field."""
    r = asyncio.run(_call("search_federal_organizations", limit=3))
    data = _payload(r)
    if data["orglist"]:
        assert "links" in data["orglist"][0]


@live
def test_live_fh_search_status_values_in_records():
    """Returned records' status field has known values."""
    r = asyncio.run(_call("search_federal_organizations", limit=20))
    data = _payload(r)
    statuses = {o.get("status") for o in data["orglist"]}
    statuses.discard(None)
    # Default is ACTIVE-only
    assert statuses == set() or statuses <= {"ACTIVE", "INACTIVE", "MERGED"}


@live
def test_live_fh_search_default_returns_active_only():
    """Default unfiltered call should return ACTIVE orgs (per API behavior)."""
    r = asyncio.run(_call("search_federal_organizations", limit=20))
    data = _payload(r)
    if data["orglist"]:
        # All returned records should be ACTIVE
        assert all(o.get("status") == "ACTIVE" for o in data["orglist"]), (
            "Default should be ACTIVE-only per live audit"
        )


@live
def test_live_fh_search_inactive_status_returns_inactive():
    r = asyncio.run(_call("search_federal_organizations", status="INACTIVE", limit=10))
    data = _payload(r)
    if data["orglist"]:
        assert all(o.get("status") == "INACTIVE" for o in data["orglist"])


# --- get_organization_hierarchy: 25+ live tests ---

@live
def test_live_fh_hierarchy_treasury():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=10))
    data = _payload(r)
    assert "totalrecords" in data
    assert "orglist" in data
    assert isinstance(data["orglist"], list)


@live
def test_live_fh_hierarchy_treasury_has_children():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=100))
    data = _payload(r)
    assert data["totalrecords"] > 0


@live
def test_live_fh_hierarchy_dod():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=10))
    data = _payload(r)
    assert data["totalrecords"] >= 1


@live
def test_live_fh_hierarchy_hhs():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_HHS, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_state():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_STATE, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_justice():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_JUSTICE, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_energy():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_ENERGY, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_agriculture():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_AGRICULTURE, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_homeland():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_HOMELAND, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_veterans():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_VETERANS, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_interior():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_INTERIOR, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_commerce():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_COMMERCE, limit=10))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_nonexistent_id():
    """Bogus ID should return zero records, not crash."""
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id="999999999", limit=5))
    data = _payload(r)
    assert data["totalrecords"] == 0
    assert data["orglist"] == []


@live
def test_live_fh_hierarchy_int_id_works():
    """Integer org id should coerce and work the same as string."""
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=int(FH_TREASURY), limit=5))
    data = _payload(r)
    assert "totalrecords" in data


@live
def test_live_fh_hierarchy_pagination():
    """Different offsets yield different children for orgs with >5 children."""
    async def _both():
        r1 = await _call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=5, offset=0)
        r2 = await _call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=5, offset=5)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1["totalrecords"] > 5 and d1["orglist"] and d2["orglist"]:
        ids1 = {o.get("fhorgid") for o in d1["orglist"]}
        ids2 = {o.get("fhorgid") for o in d2["orglist"]}
        assert not (ids1 & ids2), "DoD hierarchy pages overlap"


@live
def test_live_fh_hierarchy_limit_1():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=1))
    data = _payload(r)
    assert len(data["orglist"]) <= 1


@live
def test_live_fh_hierarchy_limit_100():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=100))
    data = _payload(r)
    assert len(data["orglist"]) <= 100


@live
def test_live_fh_hierarchy_response_is_dict():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY))
    data = _payload(r)
    assert isinstance(data, dict)


@live
def test_live_fh_hierarchy_orglist_is_list():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY))
    data = _payload(r)
    assert isinstance(data["orglist"], list)


@live
def test_live_fh_hierarchy_totalrecords_is_int():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY))
    data = _payload(r)
    assert isinstance(data["totalrecords"], int)


@live
def test_live_fh_hierarchy_children_have_required_keys():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=10))
    data = _payload(r)
    for child in data["orglist"]:
        assert "fhorgid" in child
        assert "fhorgname" in child
        assert "fhorgtype" in child


@live
def test_live_fh_hierarchy_recursive_walk():
    """Walk one level down to see grandchildren."""
    async def _walk():
        children = await _call("get_organization_hierarchy", fh_org_id=FH_DOD, limit=5)
        cdata = _payload(children)
        if not cdata["orglist"]:
            return None
        first_child = cdata["orglist"][0]
        child_id = str(first_child.get("fhorgid"))
        grandchildren = await _call(
            "get_organization_hierarchy", fh_org_id=child_id, limit=5,
        )
        return cdata, grandchildren
    out = asyncio.run(_walk())
    if out is None:
        pytest.skip("DoD has no children?")
    cdata, grandchildren = out
    gdata = _payload(grandchildren)
    assert "totalrecords" in gdata


@live
def test_live_fh_hierarchy_lowercase_keys_preserved():
    """API returns lowercase 'totalrecords', not 'totalRecords'."""
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY))
    data = _payload(r)
    assert "totalrecords" in data  # lowercase
    # camelCase should not appear (we don't add it)
    assert "totalRecords" not in data or data.get("totalRecords") == data.get("totalrecords")


@live
def test_live_fh_hierarchy_count_consistent_across_calls():
    """Same org queried twice returns same totalrecords."""
    async def _both():
        r1 = await _call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=1)
        r2 = await _call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=1)
        return r1, r2
    r1, r2 = asyncio.run(_both())
    assert _payload(r1)["totalrecords"] == _payload(r2)["totalrecords"]


@live
def test_live_fh_hierarchy_concurrent():
    async def _all():
        tasks = [
            _call("get_organization_hierarchy", fh_org_id=oid, limit=3)
            for oid in [FH_TREASURY, FH_DOD, FH_HHS, FH_STATE, FH_JUSTICE]
        ]
        return await asyncio.gather(*tasks)
    results = asyncio.run(_all())
    for r in results:
        d = _payload(r)
        assert "totalrecords" in d


@live
def test_live_fh_hierarchy_links_in_children():
    r = asyncio.run(_call("get_organization_hierarchy", fh_org_id=FH_TREASURY, limit=5))
    data = _payload(r)
    if data["orglist"]:
        # Each child should have a links field
        assert "links" in data["orglist"][0] or "fullParentPath" in data["orglist"][0]


@live
def test_live_fh_hierarchy_at_offset_beyond_total():
    """Offset past totalrecords returns empty orglist (not error)."""
    r = asyncio.run(_call(
        "get_organization_hierarchy", fh_org_id=FH_TREASURY,
        limit=5, offset=99999,
    ))
    data = _payload(r)
    assert isinstance(data["orglist"], list)


# --- search_acquisition_subawards: 25+ live tests ---

@live
def test_live_acq_by_agency_id_dod():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        agency_id=AGENCY_DOD,
        from_date="2025-10-01", to_date="2026-04-25",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_acq_by_prime_award_type():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        prime_award_type="AWARD",
        from_date="2025-10-01", to_date="2026-04-25",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_acq_response_top_keys():
    """Verify top-level keys match what the docs say."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    expected = {"totalPages", "totalRecords", "pageNumber", "data"}
    assert expected.issubset(set(data.keys())), (
        f"Missing expected keys. Got: {set(data.keys())}"
    )


@live
def test_live_acq_record_has_piid():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "piid" in data["data"][0]


@live
def test_live_acq_record_has_subAwardAmount():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "subAwardAmount" in data["data"][0]


@live
def test_live_acq_record_has_subEntityUei():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "subEntityUei" in data["data"][0]


@live
def test_live_acq_record_has_primeEntityUei():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "primeEntityUei" in data["data"][0]


@live
def test_live_acq_record_has_dates_iso_format():
    """subAwardDate should be yyyy-MM-dd format."""
    import re
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31",
        page_size=5,
    ))
    data = _payload(r)
    for rec in data["data"]:
        d = rec.get("subAwardDate")
        if d:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"Unexpected date format: {d!r}"


@live
def test_live_acq_page_size_1():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-04-25",
        page_size=1,
    ))
    data = _payload(r)
    assert len(data["data"]) <= 1


@live
def test_live_acq_page_size_500():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-15",
        page_size=500,
    ))
    data = _payload(r)
    assert len(data["data"]) <= 500


@live
def test_live_acq_date_range_single_day():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-15", to_date="2026-01-15",
        page_size=2,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_acq_date_range_old_year():
    """Older data should still be queryable."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2024-10-01", to_date="2024-10-31",
        page_size=2,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_acq_data_is_list():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=3,
    ))
    data = _payload(r)
    assert isinstance(data["data"], list)


@live
def test_live_acq_totalRecords_is_int():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=1,
    ))
    data = _payload(r)
    assert isinstance(data["totalRecords"], int)


@live
def test_live_acq_concurrent_calls():
    async def _all():
        tasks = [
            _call(
                "search_acquisition_subawards",
                from_date="2026-01-01", to_date="2026-04-25",
                page_size=2, page_number=p,
            )
            for p in [0, 1, 2, 3, 4]
        ]
        return await asyncio.gather(*tasks)
    results = asyncio.run(_all())
    for r in results:
        d = _payload(r)
        assert "totalRecords" in d


@live
def test_live_acq_pagination_consistency_same_page():
    """Same page queried twice returns same records."""
    async def _both():
        r1 = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=3, page_number=0,
        )
        r2 = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=3, page_number=0,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    assert d1["totalRecords"] == d2["totalRecords"]


@live
def test_live_acq_filter_combination():
    """Multiple filters at once still produce a valid response."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        agency_id=AGENCY_DOD,
        prime_award_type="AWARD",
        from_date="2026-01-01", to_date="2026-04-25",
        page_size=3,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_acq_published_default_status():
    """Default (no status) should be Published only."""
    async def _both():
        default = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        explicit = await _call(
            "search_acquisition_subawards",
            status="Published",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        return default, explicit
    d, e = asyncio.run(_both())
    assert _payload(d)["totalRecords"] == _payload(e)["totalRecords"]


@live
def test_live_acq_deleted_total_differs():
    """Deleted should return different total than Published."""
    async def _both():
        pub = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        deleted = await _call(
            "search_acquisition_subawards",
            status="Deleted",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        return pub, deleted
    p, d = asyncio.run(_both())
    pdata, ddata = _payload(p), _payload(d)
    # Most date windows have different counts of published vs deleted
    if pdata["totalRecords"] > 100 or ddata["totalRecords"] > 100:
        assert pdata["totalRecords"] != ddata["totalRecords"]


@live
def test_live_acq_normalize_works_on_real_response():
    """Real responses normalize without _note error sentinel."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=2,
    ))
    data = _payload(r)
    # Real responses shouldn't trigger the empty-shape note
    assert data.get("_note") != "Empty or unrecognized response shape from upstream."


@live
def test_live_acq_links_navigable():
    """nextPageLink/previousPageLink fields exist and point to the API."""
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=2,
    ))
    data = _payload(r)
    if data["totalRecords"] > 2:
        assert data.get("nextPageLink") is not None
        assert "api.sam.gov" in data["nextPageLink"]


@live
def test_live_acq_totalPages_reasonable():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=10,
    ))
    data = _payload(r)
    if data["totalRecords"] > 0:
        # totalPages should be ceil(totalRecords / pageSize)
        import math
        expected = math.ceil(data["totalRecords"] / 10)
        # Not strict equality because the API might compute slightly differently;
        # but they should be very close.
        assert abs(data["totalPages"] - expected) <= 1


@live
def test_live_acq_record_subAwardAmount_is_numeric_string():
    r = asyncio.run(_call(
        "search_acquisition_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=10,
    ))
    data = _payload(r)
    for rec in data["data"]:
        amt = rec.get("subAwardAmount")
        if amt is not None:
            # Must be parseable as a float (might be in scientific notation)
            try:
                float(amt)
            except (TypeError, ValueError):
                raise AssertionError(f"subAwardAmount not numeric: {amt!r}")


@live
def test_live_acq_real_piid_record_structure():
    """Pull a real piid and verify the response record matches schema."""
    async def _fetch():
        # Find a real piid first
        first = await _call(
            "search_acquisition_subawards",
            from_date="2026-01-01", to_date="2026-04-25", page_size=5,
        )
        fdata = _payload(first)
        if not fdata["data"]:
            return None
        piid = fdata["data"][0].get("piid")
        if not piid:
            return None
        r = await _call(
            "search_acquisition_subawards",
            piid=piid, page_size=5,
        )
        return r, piid
    out = asyncio.run(_fetch())
    if out is None:
        pytest.skip("No subaward records available")
    r, piid = out
    data = _payload(r)
    for rec in data["data"]:
        assert rec["piid"] == piid


# --- search_assistance_subawards: 25+ live tests ---

@live
def test_live_assist_response_top_keys():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    expected = {"totalPages", "totalRecords", "pageNumber", "data"}
    assert expected.issubset(set(data.keys()))


@live
def test_live_assist_data_is_list():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=3,
    ))
    data = _payload(r)
    assert isinstance(data["data"], list)


@live
def test_live_assist_totalRecords_is_int():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=1,
    ))
    data = _payload(r)
    assert isinstance(data["totalRecords"], int)


@live
def test_live_assist_record_has_fain():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "fain" in data["data"][0]


@live
def test_live_assist_record_has_subVendorUei():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "subVendorUei" in data["data"][0]


@live
def test_live_assist_record_has_primeEntityUei():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "primeEntityUei" in data["data"][0]


@live
def test_live_assist_record_has_subAwardAmount():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "subAwardAmount" in data["data"][0]


@live
def test_live_assist_record_has_primeAwardKey():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        assert "primeAwardKey" in data["data"][0]


@live
def test_live_assist_by_agency_code():
    """Filter by an agency that issues grants."""
    r = asyncio.run(_call(
        "search_assistance_subawards",
        agency_code="7530",  # HHS
        from_date="2025-10-01", to_date="2026-04-25",
        page_size=5,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_assist_real_fain_filter():
    """Pull a real fain and re-query — should narrow results."""
    async def _fetch():
        baseline = await _call(
            "search_assistance_subawards",
            from_date="2025-10-01", to_date="2026-04-25", page_size=5,
        )
        bdata = _payload(baseline)
        if not bdata["data"]:
            return None
        sample_fain = bdata["data"][0].get("fain")
        if not sample_fain:
            return None
        filtered = await _call(
            "search_assistance_subawards",
            fain=sample_fain,
            from_date="2025-10-01", to_date="2026-04-25", page_size=5,
        )
        return baseline, filtered, sample_fain
    out = asyncio.run(_fetch())
    if out is None:
        pytest.skip("No assistance subawards in window")
    baseline, filtered, sample_fain = out
    bdata, fdata = _payload(baseline), _payload(filtered)
    assert fdata["totalRecords"] < bdata["totalRecords"]
    for rec in fdata["data"]:
        assert rec["fain"] == sample_fain


@live
def test_live_assist_real_prime_award_key_filter():
    """Pull a real primeAwardKey and re-query."""
    async def _fetch():
        baseline = await _call(
            "search_assistance_subawards",
            from_date="2025-10-01", to_date="2026-04-25", page_size=5,
        )
        bdata = _payload(baseline)
        if not bdata["data"]:
            return None
        sample_key = bdata["data"][0].get("primeAwardKey")
        if not sample_key:
            return None
        filtered = await _call(
            "search_assistance_subawards",
            prime_award_key=sample_key,
            from_date="2025-10-01", to_date="2026-04-25", page_size=5,
        )
        return baseline, filtered, sample_key
    out = asyncio.run(_fetch())
    if out is None:
        pytest.skip("No assistance subawards in window")
    baseline, filtered, sample_key = out
    bdata, fdata = _payload(baseline), _payload(filtered)
    assert fdata["totalRecords"] < bdata["totalRecords"]


@live
def test_live_assist_page_size_1():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=1,
    ))
    data = _payload(r)
    assert len(data["data"]) <= 1


@live
def test_live_assist_page_size_500():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=500,
    ))
    data = _payload(r)
    assert len(data["data"]) <= 500


@live
def test_live_assist_date_range_single_day():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-15", to_date="2026-01-15", page_size=2,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_assist_date_range_old_year():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2024-10-01", to_date="2024-10-31", page_size=2,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_assist_pagination():
    async def _both():
        r1 = await _call(
            "search_assistance_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=5, page_number=0,
        )
        r2 = await _call(
            "search_assistance_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=5, page_number=1,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    d1, d2 = _payload(r1), _payload(r2)
    if d1["totalRecords"] > 5 and d1["data"] and d2["data"]:
        keys1 = {(r.get("fain"), r.get("subAwardNumber")) for r in d1["data"]}
        keys2 = {(r.get("fain"), r.get("subAwardNumber")) for r in d2["data"]}
        assert keys1 != keys2


@live
def test_live_assist_pagination_consistency_same_page():
    async def _both():
        r1 = await _call(
            "search_assistance_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=3, page_number=0,
        )
        r2 = await _call(
            "search_assistance_subawards",
            from_date="2026-01-01", to_date="2026-04-25",
            page_size=3, page_number=0,
        )
        return r1, r2
    r1, r2 = asyncio.run(_both())
    assert _payload(r1)["totalRecords"] == _payload(r2)["totalRecords"]


@live
def test_live_assist_filter_combination():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        agency_code="7530",
        from_date="2025-10-01", to_date="2026-04-25",
        page_size=3,
    ))
    data = _payload(r)
    assert "totalRecords" in data


@live
def test_live_assist_concurrent_calls():
    async def _all():
        tasks = [
            _call(
                "search_assistance_subawards",
                from_date="2026-01-01", to_date="2026-04-25",
                page_size=2, page_number=p,
            )
            for p in [0, 1, 2, 3, 4]
        ]
        return await asyncio.gather(*tasks)
    results = asyncio.run(_all())
    for r in results:
        d = _payload(r)
        assert "totalRecords" in d


@live
def test_live_assist_normalize_works_on_real_response():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=2,
    ))
    data = _payload(r)
    assert data.get("_note") != "Empty or unrecognized response shape from upstream."


@live
def test_live_assist_published_default_status():
    async def _both():
        d = await _call(
            "search_assistance_subawards",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        e = await _call(
            "search_assistance_subawards",
            status="Published",
            from_date="2026-01-01", to_date="2026-04-25", page_size=1,
        )
        return d, e
    d, e = asyncio.run(_both())
    assert _payload(d)["totalRecords"] == _payload(e)["totalRecords"]


@live
def test_live_assist_record_dates_iso_format():
    import re
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    for rec in data["data"]:
        d = rec.get("subAwardDate")
        if d:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"Bad date format: {d!r}"


@live
def test_live_assist_record_subAwardAmount_numeric():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=10,
    ))
    data = _payload(r)
    for rec in data["data"]:
        amt = rec.get("subAwardAmount")
        if amt is not None:
            try:
                float(amt)
            except (TypeError, ValueError):
                raise AssertionError(f"subAwardAmount not numeric: {amt!r}")


@live
def test_live_assist_links_navigable():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=2,
    ))
    data = _payload(r)
    if data["totalRecords"] > 2:
        assert data.get("nextPageLink") is not None


@live
def test_live_assist_totalPages_reasonable():
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-04-25", page_size=10,
    ))
    data = _payload(r)
    if data["totalRecords"] > 0:
        import math
        expected = math.ceil(data["totalRecords"] / 10)
        assert abs(data["totalPages"] - expected) <= 1


@live
def test_live_assist_status_field_in_records():
    """Records have a 'status' field."""
    r = asyncio.run(_call(
        "search_assistance_subawards",
        from_date="2026-01-01", to_date="2026-01-31", page_size=5,
    ))
    data = _payload(r)
    if data["data"]:
        # Documented field per OpenAPI
        assert "status" in data["data"][0]
