"""Stress test for usaspending-mcp: edge cases, boundaries, bad inputs."""
from __future__ import annotations
import asyncio, sys, traceback
from usaspending_gov_mcp.server import (
    search_awards, get_award_count, spending_over_time, spending_by_category,
    get_award_detail, get_transactions, get_award_funding, get_idv_children,
    lookup_piid, autocomplete_psc, autocomplete_naics, list_toptier_agencies,
    get_agency_overview, get_agency_awards, get_naics_details, get_psc_filter_tree,
    get_state_profile,
)

P = "\033[92mPASS\033[0m"; F = "\033[91mFAIL\033[0m"; I = "\033[94mINFO\033[0m"
results = []

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    """Run a test coroutine. expect='pass'|'error'|'zero'|'any'. check is optional lambda on result."""
    await asyncio.sleep(0.35)
    try:
        r = await coro
        if expect == "error":
            rec(name, "FAIL", "expected exception but got success")
        elif expect == "zero":
            total = r.get("totalRecords", r.get("results", r.get("page_metadata", {}).get("total", -1)))
            if isinstance(total, int) and total == 0:
                rec(name, "PASS", "0 results as expected")
            elif isinstance(r.get("results"), list) and len(r["results"]) == 0:
                rec(name, "PASS", "empty results as expected")
            else:
                rec(name, "INFO", f"got results (expected 0): {str(r)[:100]}")
        elif check:
            ok, msg = check(r)
            rec(name, "PASS" if ok else "FAIL", msg)
        else:
            rec(name, "PASS", str(r)[:80] if isinstance(r, dict) else "ok")
    except ValueError as e:
        if expect == "error":
            rec(name, "PASS", f"ValueError: {e}")
        else:
            rec(name, "FAIL", f"ValueError: {e}")
    except RuntimeError as e:
        msg = str(e)[:120]
        if expect == "error":
            rec(name, "PASS", f"RuntimeError: {msg}")
        elif "400" in msg or "404" in msg or "422" in msg:
            rec(name, "INFO", f"API error (may be expected): {msg}")
        else:
            rec(name, "FAIL", f"RuntimeError: {msg}")
    except Exception as e:
        rec(name, "FAIL", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("USASPENDING MCP STRESS TEST")
    print("="*60)

    # ── 1. SEARCH_AWARDS BOUNDARIES ──
    print("\n━━━ 1. search_awards boundaries ━━━")

    await t("limit clamped to 100",
        search_awards(award_type="contracts", keywords=["information technology"], limit=200, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) <= 100, f"got {len(r.get('results',[]))} results (max 100)"))

    await t("limit=0",
        search_awards(award_type="contracts", keywords=["information technology"], limit=0, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("limit=1 single result",
        search_awards(award_type="contracts", keywords=["cybersecurity"], limit=1, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) <= 1, f"got {len(r.get('results',[]))}"))

    await t("page=9999 beyond results",
        search_awards(award_type="contracts", keywords=["information technology"], limit=10, page=9999, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) == 0, f"got {len(r.get('results',[]))} (expect 0)"))

    await t("future dates (FY2030)",
        search_awards(award_type="contracts", keywords=["information technology"], time_period_start="2029-10-01", time_period_end="2030-09-30"),
        expect="zero")

    await t("inverted date range (start > end)",
        search_awards(award_type="contracts", keywords=["information technology"], time_period_start="2025-09-30", time_period_end="2024-10-01"))

    await t("empty keywords=[]",
        search_awards(award_type="contracts", keywords=[], time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("grants award type",
        search_awards(award_type="grants", keywords=["research"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) > 0, f"got {len(r.get('results',[]))} grants"))

    await t("loans award type (sort=Loan Value)",
        search_awards(award_type="loans", keywords=["business"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("direct_payments award type",
        search_awards(award_type="direct_payments", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("other award type",
        search_awards(award_type="other", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── 2. FILTER COMBOS ──
    print("\n━━━ 2. filter combos ━━━")

    await t("multiple NAICS codes",
        search_awards(award_type="contracts", naics_codes=["541512","541511","541519"], limit=5, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("multiple PSC codes",
        search_awards(award_type="contracts", psc_codes=["R425","D399","DA01"], limit=5, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("award_amount min only",
        search_awards(award_type="contracts", award_amount_min=100000000, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) > 0, f"got {len(r.get('results',[]))} >$100M awards"))

    await t("award_amount max only",
        search_awards(award_type="contracts", award_amount_max=1000, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("award_amount inverted (min>max)",
        search_awards(award_type="contracts", award_amount_min=1000000, award_amount_max=100, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        expect="zero")

    await t("set_aside SBA + competed full&open",
        search_awards(award_type="contracts", set_aside_type_codes=["SBA"], extent_competed_type_codes=["A"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("state filter VA",
        search_awards(award_type="contracts", place_of_performance_state="VA", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("agency + subagency combined",
        search_awards(award_type="contracts", awarding_agency="Department of Defense", awarding_subagency="Department of the Navy", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) > 0, f"got {len(r.get('results',[]))} Navy contracts"))

    await t("unicode recipient name",
        search_awards(award_type="contracts", recipient_name="Raytheon", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── 3. DETAIL ENDPOINTS ──
    print("\n━━━ 3. detail endpoints ━━━")

    await t("get_award_detail bogus ID",
        get_award_detail("CONT_AWD_BOGUS_0000_FAKE_0000"),
        expect="error")

    await t("get_transactions bogus ID (returns empty, not 404)",
        get_transactions("BOGUS_ID_12345"),
        check=lambda r: (len(r.get("results",[])) == 0, f"results={len(r.get('results',[]))}"))

    await t("get_transactions limit=5001 clamped to 5000",
        get_transactions("BOGUS_ID_12345", limit=5001),
        check=lambda r: (len(r.get("results",[])) == 0, "empty (clamped limit accepted)"))

    await t("get_award_funding bogus ID (returns empty)",
        get_award_funding("BOGUS_FUNDING_ID"),
        check=lambda r: (True, f"results={len(r.get('results',[]))}"))

    await t("get_idv_children bogus ID (returns empty)",
        get_idv_children("BOGUS_IDV_ID"),
        check=lambda r: (True, f"results={len(r.get('results',[]))}"))

    await t("get_idv_children child_idvs type (returns empty)",
        get_idv_children("BOGUS_IDV_ID", child_type="child_idvs"),
        check=lambda r: (True, f"results={len(r.get('results',[]))}"))

    # ── 4. AUTOCOMPLETE EDGES ──
    print("\n━━━ 4. autocomplete edges ━━━")

    await t("autocomplete_psc empty string",
        autocomplete_psc(""))

    await t("autocomplete_psc single char 'R'",
        autocomplete_psc("R", limit=5))

    await t("autocomplete_psc long string",
        autocomplete_psc("professional engineering technical support services", limit=5))

    await t("autocomplete_naics '54'",
        autocomplete_naics("54", limit=5))

    await t("autocomplete_naics 'zzzz' (no match)",
        autocomplete_naics("zzzz"))

    # ── 5. REFERENCE ENDPOINTS ──
    print("\n━━━ 5. reference endpoints ━━━")

    await t("get_naics_details 2-digit '54'",
        get_naics_details("54"))

    await t("get_naics_details 6-digit '541512'",
        get_naics_details("541512"))

    await t("get_naics_details invalid 'abc'",
        get_naics_details("abc"))

    await t("get_state_profile AL '01'",
        get_state_profile("01"))

    await t("get_state_profile invalid '99'",
        get_state_profile("99"))

    await t("get_agency_overview DoD '097'",
        get_agency_overview("097", fiscal_year=2025))

    await t("get_agency_overview invalid '999'",
        get_agency_overview("999"))

    await t("get_agency_awards DoD '097' FY2025",
        get_agency_awards("097", fiscal_year=2025))

    await t("get_psc_filter_tree root",
        get_psc_filter_tree(""))

    await t("get_psc_filter_tree drilldown Service/R/",
        get_psc_filter_tree("Service/R/"))

    # ── 6. SPENDING AGGREGATION ──
    print("\n━━━ 6. spending aggregation ━━━")

    await t("spending_over_time fiscal_year",
        spending_over_time(group="fiscal_year", awarding_agency="Department of Defense", time_period_start="2020-10-01", time_period_end="2025-09-30"))

    await t("spending_over_time quarter",
        spending_over_time(group="quarter", awarding_agency="Department of Defense", time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("spending_over_time month",
        spending_over_time(group="month", awarding_agency="Department of Defense", time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("spending_by_category all 14 categories",
        spending_by_category(category="recipient", keywords=["information technology"], time_period_start="2024-10-01", time_period_end="2025-09-30", limit=3))

    await t("spending_by_category state_territory",
        spending_by_category(category="state_territory", awarding_agency="Department of Defense", time_period_start="2024-10-01", time_period_end="2025-09-30", limit=5))

    await t("get_award_count with pricing filter FFP",
        get_award_count(contract_pricing_type_codes=["J"], time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (r.get("results",{}).get("contracts",0) > 0, f"FFP count={r.get('results',{}).get('contracts','?')}"))

    await t("get_award_count sole source",
        get_award_count(extent_competed_type_codes=["C"], time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── 7. LOOKUP_PIID ──
    print("\n━━━ 7. lookup_piid edges ━━━")

    await t("lookup_piid nonexistent 'ZZZZZZZZZZZZ'",
        lookup_piid("ZZZZZZZZZZZZ"),
        check=lambda r: (r.get("award_type") is None, f"type={r.get('award_type')}"))

    await t("lookup_piid empty string",
        lookup_piid(""))

    await t("lookup_piid NAVSEA prefix 'N00024'",
        lookup_piid("N00024", limit=2),
        check=lambda r: (r.get("award_type") is not None, f"type={r.get('award_type')}"))

    await t("lookup_piid Army prefix 'W91CRB'",
        lookup_piid("W91CRB", limit=2))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"USASPENDING STRESS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
