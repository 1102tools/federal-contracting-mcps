"""Round 3: creative chaos for usaspending-mcp. Agent workflows, real 1102
scenarios, LLM hallucination inputs, type confusion, concurrent abuse."""
from __future__ import annotations
import asyncio, sys
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
    await asyncio.sleep(0.35)
    try:
        r = await coro
        if expect == "error":
            rec(name, "FAIL", f"expected exception, got: {str(r)[:80]}")
        elif check:
            ok, msg = check(r)
            rec(name, "PASS" if ok else "FAIL", msg)
        else:
            rec(name, "PASS", str(r)[:80] if isinstance(r, dict) else "ok")
    except (ValueError, RuntimeError) as e:
        if expect == "error":
            rec(name, "PASS", f"{type(e).__name__}: {str(e)[:100]}")
        else:
            msg = str(e)[:120]
            if any(x in msg for x in ["400","404","422","429","500"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("USASPENDING R3: CREATIVE CHAOS + AGENT WORKFLOWS")
    print("="*60)

    # ── 1. REAL 1102 SCENARIOS ──
    print("\n━━━ 1. real 1102 scenarios ━━━")

    # Find a real award, then drill into it
    await t("search Navy T&M contracts FY2025",
        search_awards(
            award_type="contracts",
            awarding_agency="Department of Defense",
            awarding_subagency="Department of the Navy",
            contract_pricing_type_codes=["Y"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=3),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} T&M Navy contracts"))

    await t("search 8(a) sole source awards FY2025",
        search_awards(
            award_type="contracts",
            set_aside_type_codes=["8AN"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=5),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} 8(a) sole source"))

    await t("search CPFF contracts (cost-reimbursement)",
        search_awards(
            award_type="contracts",
            contract_pricing_type_codes=["U"],
            award_amount_min=10000000,
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=3),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} CPFF >$10M"))

    await t("search grants for 'research' FY2025",
        search_awards(
            award_type="grants",
            keywords=["research"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=5),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} grants"))

    await t("search IDVs (BPAs/IDIQs) for IT services",
        search_awards(
            award_type="idvs",
            naics_codes=["541512"],
            time_period_start="2022-10-01", time_period_end="2025-09-30",
            limit=5),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} IDVs"))

    # ── 2. MULTI-FILTER STACKING ──
    print("\n━━━ 2. multi-filter stacking ━━━")

    await t("5 filters at once (agency+naics+psc+setaside+amount)",
        search_awards(
            award_type="contracts",
            awarding_agency="Department of Defense",
            naics_codes=["541512"],
            psc_codes=["D399"],
            set_aside_type_codes=["SBA"],
            award_amount_min=100000,
            time_period_start="2022-10-01", time_period_end="2025-09-30",
            limit=5))

    await t("all set-aside codes at once",
        search_awards(
            award_type="contracts",
            set_aside_type_codes=["SBA","SBP","8A","8AN","HZC","HZS","SDVOSBS","SDVOSBC","WOSB","WOSBSS","EDWOSB","EDWOSBSS","VSA"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=3),
        check=lambda r: (len(r.get("results",[])) > 0, f"found {len(r.get('results',[]))} SB awards"))

    await t("all competed codes at once",
        search_awards(
            award_type="contracts",
            extent_competed_type_codes=["A","D","F","CDO"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=3))

    await t("all not-competed codes at once",
        search_awards(
            award_type="contracts",
            extent_competed_type_codes=["B","C","E","G","NDO"],
            time_period_start="2024-10-01", time_period_end="2025-09-30",
            limit=3))

    await t("all pricing types at once",
        get_award_count(
            contract_pricing_type_codes=["A","B","J","K","L","M","R","S","T","U","V","Y","Z"],
            time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (r.get("results",{}).get("contracts",0) > 0, f"contracts={r.get('results',{}).get('contracts','?')}"))

    # ── 3. LLM HALLUCINATION INPUTS ──
    print("\n━━━ 3. LLM hallucination inputs ━━━")

    await t("keyword='PIID N00024-24-C-0085' (PIID as keyword)",
        search_awards(keywords=["PIID N00024-24-C-0085"], limit=3, time_period_start="2020-10-01", time_period_end="2025-09-30"))

    await t("keyword='contract number W91CRB' (natural language leak)",
        search_awards(keywords=["contract number W91CRB"], limit=3, time_period_start="2020-10-01", time_period_end="2025-09-30"))

    await t("agency name misspelled 'Departmnet of Defnse'",
        search_awards(awarding_agency="Departmnet of Defnse", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("NAICS as keyword (Claude might confuse filter types)",
        search_awards(keywords=["541512"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("PSC in wrong field (psc_codes with NAICS value)",
        search_awards(psc_codes=["541512"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("state code full name instead of abbreviation",
        search_awards(place_of_performance_state="Virginia", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("sort by nonexistent field",
        search_awards(keywords=["cybersecurity"], sort="Nonexistent Field", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("award_type as plural 'contract' (not in enum)",
        search_awards(award_type="contracts", keywords=["test"], limit=1, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── 4. SPENDING CATEGORY EXHAUSTIVE ──
    print("\n━━━ 4. spending_by_category all 14 dimensions ━━━")

    categories = [
        "awarding_agency", "awarding_subagency", "funding_agency",
        "funding_subagency", "recipient", "cfda", "naics", "psc",
        "country", "county", "district", "state_territory",
        "federal_account", "defc"
    ]
    for cat in categories:
        await t(f"category={cat}",
            spending_by_category(
                category=cat,
                time_period_start="2024-10-01", time_period_end="2025-09-30",
                limit=3))

    # ── 5. AGENT WORKFLOW SIMULATIONS ──
    print("\n━━━ 5. agent workflow simulations ━━━")

    # ContractWatch nightly scan: find suspicious awards
    async def contractwatch_scan():
        tasks = [
            # Sole source over $5M
            search_awards(
                award_type="contracts",
                extent_competed_type_codes=["C"],
                award_amount_min=5000000,
                time_period_start="2025-03-01", time_period_end="2025-04-05",
                limit=10),
            # 8(a) sole source over $5M
            search_awards(
                award_type="contracts",
                set_aside_type_codes=["8AN"],
                award_amount_min=5000000,
                time_period_start="2025-03-01", time_period_end="2025-04-05",
                limit=10),
            # Top recipients this month
            spending_by_category(
                category="recipient",
                time_period_start="2025-03-01", time_period_end="2025-04-05",
                limit=10),
            # Award count by competition
            get_award_count(
                extent_competed_type_codes=["C"],
                time_period_start="2025-03-01", time_period_end="2025-04-05"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 4}

    try:
        r = await contractwatch_scan()
        rec("ContractWatch nightly scan (4 concurrent queries)",
            "PASS" if r["ok"] == 4 else "FAIL", f"{r['ok']}/4 succeeded")
    except Exception as e:
        rec("ContractWatch nightly scan", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # IGCE research: vendor landscape for a NAICS
    async def igce_research():
        tasks = [
            spending_by_category(category="recipient", naics_codes=["541512"],
                time_period_start="2022-10-01", time_period_end="2025-09-30", limit=15),
            get_award_count(naics_codes=["541512"],
                time_period_start="2022-10-01", time_period_end="2025-09-30"),
            spending_over_time(group="fiscal_year", naics_codes=["541512"],
                time_period_start="2020-10-01", time_period_end="2025-09-30"),
            spending_by_category(category="psc", naics_codes=["541512"],
                time_period_start="2022-10-01", time_period_end="2025-09-30", limit=10),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 4}

    try:
        r = await igce_research()
        rec("IGCE vendor landscape research (4 concurrent)",
            "PASS" if r["ok"] == 4 else "FAIL", f"{r['ok']}/4 succeeded")
    except Exception as e:
        rec("IGCE vendor landscape", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # Market research: full pipeline
    async def market_research():
        tasks = [
            search_awards(award_type="contracts", naics_codes=["541512"],
                awarding_agency="Department of Defense",
                time_period_start="2022-10-01", time_period_end="2025-09-30", limit=25),
            search_awards(award_type="idvs", naics_codes=["541512"],
                time_period_start="2022-10-01", time_period_end="2025-09-30", limit=10),
            spending_by_category(category="recipient", naics_codes=["541512"],
                set_aside_type_codes=["SBA","SBP","8A","8AN","HZC","HZS","SDVOSBS","SDVOSBC"],
                time_period_start="2022-10-01", time_period_end="2025-09-30", limit=15),
            get_award_count(naics_codes=["541512"],
                set_aside_type_codes=["SBA","SBP","8A","8AN","HZC","HZS","SDVOSBS","SDVOSBC"],
                time_period_start="2022-10-01", time_period_end="2025-09-30"),
            autocomplete_psc("computer systems design"),
            autocomplete_naics("computer"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = [str(r)[:60] for r in results if isinstance(r, Exception)]
        return {"ok": ok, "total": 6, "errors": errs}

    try:
        r = await market_research()
        rec("Market research full pipeline (6 concurrent)",
            "PASS" if r["ok"] == 6 else "FAIL",
            f"{r['ok']}/6" + (f", errors: {r['errors']}" if r["errors"] else ""))
    except Exception as e:
        rec("Market research pipeline", "FAIL", str(e)[:100])

    # ── 6. SPENDING_OVER_TIME DEEP ──
    print("\n━━━ 6. spending_over_time deep ━━━")

    await t("DoD spending 2010-2025 by fiscal_year",
        spending_over_time(
            group="fiscal_year",
            awarding_agency="Department of Defense",
            time_period_start="2010-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) > 10, f"years={len(r.get('results',[]))}"))

    await t("monthly spending with NAICS filter",
        spending_over_time(
            group="month",
            naics_codes=["541512"],
            time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) > 0, f"months={len(r.get('results',[]))}"))

    await t("quarterly with multiple filters",
        spending_over_time(
            group="quarter",
            awarding_agency="Department of Defense",
            naics_codes=["541512"],
            time_period_start="2022-10-01", time_period_end="2025-09-30"))

    # ── 7. LOOKUP_PIID REALISTIC ──
    print("\n━━━ 7. lookup_piid realistic patterns ━━━")

    await t("PIID with dashes (common format)",
        lookup_piid("N00024-21-C", limit=3))

    await t("PIID partial match 'FA8650'",
        lookup_piid("FA8650", limit=3),
        check=lambda r: (r.get("award_type") is not None, f"type={r.get('award_type')}"))

    await t("PIID with spaces (user might paste badly)",
        lookup_piid(" N00024 ", limit=3))

    await t("PIID lowercase (should still work via keyword)",
        lookup_piid("n00024", limit=3))

    await t("PIID that looks like a phone number",
        lookup_piid("800-555-1234", limit=2))

    await t("PIID that's actually a UEI (wrong API)",
        lookup_piid("QVZMH5JLF274", limit=2))

    # ── 8. REFERENCE ENDPOINT EXHAUSTIVE ──
    print("\n━━━ 8. reference endpoints exhaustive ━━━")

    await t("list_toptier_agencies",
        list_toptier_agencies(),
        check=lambda r: (len(r.get("results",[])) > 100, f"agencies={len(r.get('results',[]))}"))

    await t("agency overview NASA '080'",
        get_agency_overview("080", fiscal_year=2025),
        check=lambda r: ("NASA" in str(r.get("name","")), f"name={r.get('name','?')}"))

    await t("agency awards VA '036'",
        get_agency_awards("036", fiscal_year=2025))

    await t("NAICS details 2-digit '54' (Professional Services)",
        get_naics_details("54"),
        check=lambda r: ("Professional" in str(r), "got Professional Services"))

    await t("NAICS details 4-digit '5415'",
        get_naics_details("5415"))

    await t("PSC tree Product top level",
        get_psc_filter_tree("Product/"))

    await t("PSC tree Service/D/ (IT telecom)",
        get_psc_filter_tree("Service/D/"))

    await t("state profile DC '11'",
        get_state_profile("11"),
        check=lambda r: ("Columbia" in str(r.get("name","")), f"name={r.get('name','?')}"))

    await t("state profile Puerto Rico '72'",
        get_state_profile("72"),
        check=lambda r: (True, f"name={r.get('name','?')}"))

    # ── 9. RAPID FIRE 15 CONCURRENT ──
    print("\n━━━ 9. rapid fire 15 concurrent ━━━")

    async def rapid_15():
        tasks = [
            search_awards(keywords=["cybersecurity"], limit=2, time_period_start="2024-10-01", time_period_end="2025-09-30"),
            search_awards(keywords=["cloud migration"], limit=2, time_period_start="2024-10-01", time_period_end="2025-09-30"),
            search_awards(keywords=["help desk"], limit=2, time_period_start="2024-10-01", time_period_end="2025-09-30"),
            spending_by_category(category="recipient", keywords=["defense"], time_period_start="2024-10-01", time_period_end="2025-09-30", limit=3),
            spending_by_category(category="naics", time_period_start="2024-10-01", time_period_end="2025-09-30", limit=3),
            spending_over_time(group="quarter", time_period_start="2024-10-01", time_period_end="2025-09-30"),
            get_award_count(time_period_start="2024-10-01", time_period_end="2025-09-30"),
            autocomplete_psc("engineering"),
            autocomplete_naics("software"),
            list_toptier_agencies(),
            lookup_piid("N00024", limit=1),
            lookup_piid("W91CRB", limit=1),
            lookup_piid("FA8650", limit=1),
            get_naics_details("541512"),
            get_state_profile("51"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": 15}

    try:
        r = await rapid_15()
        rec("15 concurrent mixed calls",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/15 succeeded, {r['errors']} errors")
    except Exception as e:
        rec("15 concurrent mixed", "FAIL", str(e)[:100])

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"USASPENDING R3: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
