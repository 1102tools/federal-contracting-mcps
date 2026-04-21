"""Round 3: creative chaos. Real-world edge cases a 1102 would actually hit,
combined with edge cases an LLM might hallucinate as inputs."""
from __future__ import annotations
import asyncio, sys, time
from ecfr_mcp.server import (
    get_latest_date, get_cfr_content, get_cfr_structure,
    get_version_history, get_ancestry, search_cfr,
    list_agencies, get_corrections, lookup_far_clause,
    compare_versions, list_sections_in_part,
    find_far_definition, find_recent_changes,
)

P = "\033[92mPASS\033[0m"; F = "\033[91mFAIL\033[0m"; I = "\033[94mINFO\033[0m"
results = []

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    await asyncio.sleep(0.3)
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
            if any(x in msg for x in ["400","404","406","422","429","500"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("eCFR MCP ROUND 3: CREATIVE CHAOS")
    print("="*60)

    d = (await get_latest_date(48))["up_to_date_as_of"]
    print(f"  Safe date: {d}")

    # ── 1. REAL-WORLD 1102 SCENARIOS ──
    print("\n━━━ 1. real-world 1102 scenarios ━━━")

    # User types "FAR 15.305" but the MCP wants just "15.305"
    await t("section with 'FAR ' prefix (common user mistake)",
        get_cfr_content(48, section="FAR 15.305"))

    # User types the full citation format
    await t("section='48 CFR 15.305' (full citation)",
        get_cfr_content(48, section="48 CFR 15.305"))

    # Clause with dash (very common in FAR 52)
    await t("clause 52.212-4 (dash in section ID)",
        lookup_far_clause("52.212-4"),
        check=lambda r: ("Contract Terms" in r.get("heading",""), f"heading={r.get('heading','')[:50]}"))

    # Clause with double dash (DFARS 252.xxx-xxxx)
    await t("DFARS 252.204-7012 (CUI clause)",
        lookup_far_clause("252.204-7012", chapter="2"),
        check=lambda r: (len(r.get("paragraphs",[])) > 5, f"paragraphs={len(r.get('paragraphs',[]))}"))

    # The biggest FAR section by far
    await t("FAR 52.212-5 (massive clause list)",
        lookup_far_clause("52.212-5"),
        check=lambda r: (len(r.get("paragraphs",[])) > 100, f"paragraphs={len(r.get('paragraphs',[]))}"))

    # Appendix (not a section)
    await t("FAR Part 31 appendix (if exists)",
        get_cfr_content(48, part="31"))

    # Subpart that doesn't exist
    await t("subpart 15.99 (nonexistent)",
        get_cfr_content(48, subpart="15.99"))

    # The RFO deviation awareness check
    await t("search for 'deviation' in FAR",
        search_cfr("deviation", title=48, chapter="1", per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    # ── 2. LLM HALLUCINATION INPUTS ──
    print("\n━━━ 2. LLM hallucination inputs ━━━")

    # Claude might try these non-existent but plausible-sounding sections
    await t("section='15.305(a)' (subsection notation)",
        get_cfr_content(48, section="15.305(a)"))

    await t("section='15.305.1' (sub-section with extra dot)",
        get_cfr_content(48, section="15.305.1"))

    await t("section='Part 15' (word 'Part' prefix)",
        get_cfr_content(48, section="Part 15"))

    await t("section='Subpart 15.3' (word prefix)",
        get_cfr_content(48, section="Subpart 15.3"))

    await t("section='Section 15.305' (word prefix)",
        get_cfr_content(48, section="Section 15.305"))

    # Claude might pass chapter as int-like
    await t("chapter as number string '001'",
        get_cfr_content(48, chapter="001", section="1.101"))

    # Claude might try to get multiple sections in one call
    await t("section='15.305,15.306' (comma-separated)",
        get_cfr_content(48, section="15.305,15.306"))

    # Claude might pass NAICS instead of section
    await t("section='541512' (NAICS code, not section)",
        get_cfr_content(48, section="541512"))

    # ── 3. CROSS-TITLE QUERIES ──
    print("\n━━━ 3. cross-title queries ━━━")

    await t("Title 29 Labor (non-acquisition)",
        get_cfr_content(29, part="1", section="1.1"),
        check=lambda r: (len(r.get("paragraphs",[])) >= 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("Title 2 Grants (2 CFR 200)",
        search_cfr("Uniform Guidance", title=2, per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("Title 5 Administrative Personnel",
        get_latest_date(5),
        check=lambda r: (r.get("up_to_date_as_of") is not None, "got date"))

    await t("Title 41 Public Contracts",
        get_cfr_structure(41, part="101"),
        check=lambda r: (True, "got structure"))

    # ── 4. XML PARSING STRESS ──
    print("\n━━━ 4. XML parsing deep stress ━━━")

    # FAR Part 52 is enormous (all standard clauses)
    await t("entire FAR Part 52 (huge, ~2MB XML)",
        get_cfr_content(48, part="52"),
        check=lambda r: (len(r.get("paragraphs",[])) > 1000, f"paragraphs={len(r.get('paragraphs',[]))}"))

    # FAR 2.101 definitions with specific tricky terms
    await t("definition: 'micro-purchase threshold' (has dash)",
        find_far_definition("micro-purchase threshold"),
        check=lambda r: (r.get("match_count",0) > 0, f"matches={r.get('match_count',0)}"))

    await t("definition: '$250,000' (dollar sign + comma)",
        find_far_definition("$250,000"),
        check=lambda r: (True, f"matches={r.get('match_count',0)}"))

    await t("definition: case sensitivity 'CONTRACTING OFFICER' vs 'contracting officer'",
        find_far_definition("CONTRACTING OFFICER"),
        check=lambda r: (r.get("match_count",0) > 0, f"matches={r.get('match_count',0)} (case insensitive)"))

    await t("definition: parenthetical '(b)(1)(ii)'",
        find_far_definition("(b)(1)(ii)"))

    # ── 5. VERSION COMPARISON EDGE CASES ──
    print("\n━━━ 5. version comparison deep ━━━")

    await t("compare at exact boundary: 2017-01-01 (earliest) vs latest",
        compare_versions("52.212-4", "2017-01-03", d),
        check=lambda r: (
            len(r.get("before",{}).get("paragraphs",[])) > 0,
            f"before={len(r.get('before',{}).get('paragraphs',[]))} after={len(r.get('after',{}).get('paragraphs',[]))}"))

    await t("compare same section same date (no diff)",
        compare_versions("15.305", d, d),
        check=lambda r: (
            r.get("before",{}).get("paragraphs") == r.get("after",{}).get("paragraphs"),
            "identical (correct)"))

    await t("compare DFARS clause across dates",
        compare_versions("252.204-7012", "2020-01-02", d, chapter="2"),
        check=lambda r: (len(r.get("after",{}).get("paragraphs",[])) > 0, "got DFARS comparison"))

    # ── 6. STRUCTURE DEEP WALK ──
    print("\n━━━ 6. structure deep walk ━━━")

    await t("list_sections FAR Part 52 (hundreds of clauses)",
        list_sections_in_part("52"),
        check=lambda r: (r.get("section_count",0) > 200, f"sections={r.get('section_count',0)}"))

    await t("list_sections FAR Part 1 (small part)",
        list_sections_in_part("1"),
        check=lambda r: (r.get("section_count",0) > 5, f"sections={r.get('section_count',0)}"))

    await t("list_sections DFARS Part 215",
        list_sections_in_part("215", chapter="2"),
        check=lambda r: (r.get("section_count",0) > 0, f"sections={r.get('section_count',0)}"))

    await t("structure for all of Title 48 (massive tree)",
        get_cfr_structure(48),
        check=lambda r: (r.get("children") is not None or r.get("identifier") is not None, "got full tree"))

    # ── 7. SEARCH REFINEMENT PATTERNS ──
    print("\n━━━ 7. search refinement patterns ━━━")

    await t("search with exact phrase (quotes)",
        search_cfr('"organizational conflict of interest"', title=48, per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("search with Boolean AND",
        search_cfr("debarment AND suspension", title=48, per_page=5))

    await t("search with Boolean OR",
        search_cfr("debarment OR suspension", title=48, per_page=5))

    await t("search with Boolean NOT",
        search_cfr("debarment NOT suspension", title=48, per_page=5))

    await t("search with parentheses grouping",
        search_cfr("(debarment OR suspension) AND responsibility", title=48, per_page=5))

    await t("search scoped to DFARS only",
        search_cfr("cybersecurity", title=48, chapter="2", per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("search with section filter",
        search_cfr("evaluation", title=48, section="15.305", per_page=5))

    await t("find_recent_changes FAR Part 19 (set-asides, often amended)",
        find_recent_changes("2024-01-01", part="19"),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    # ── 8. RAPID MIXED WORKFLOW ──
    print("\n━━━ 8. rapid mixed workflow (simulating agent) ━━━")

    # Simulate what ContractWatch might do: look up a clause, check its
    # history, get the ancestry, search for related sections, all at once
    async def agent_investigation():
        tasks = [
            lookup_far_clause("9.406-2"),           # debarment causes
            get_version_history(48, section="9.406-2"),  # when was it last changed?
            get_ancestry(48, section="9.406-2"),     # where does it sit?
            search_cfr("debarment causes", title=48, chapter="1", per_page=5),
            find_far_definition("debarment"),        # what does the FAR define it as?
            list_sections_in_part("9"),              # what else is in Part 9?
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = [str(r)[:80] for r in results if isinstance(r, Exception)]
        return {"ok": ok, "total": 6, "errors": errs}

    try:
        r = await agent_investigation()
        rec("6-tool agent investigation (debarment deep dive)",
            "PASS" if r["ok"] == 6 else "FAIL",
            f"{r['ok']}/6 succeeded" + (f", errors: {r['errors']}" if r["errors"] else ""))
    except Exception as e:
        rec("6-tool agent investigation", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # Simulate market research workflow
    async def market_research_flow():
        tasks = [
            search_cfr("small business set-aside", title=48, chapter="1", part="19", per_page=10),
            lookup_far_clause("19.502-2"),
            find_far_definition("small business concern"),
            list_sections_in_part("19"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 4}

    try:
        r = await market_research_flow()
        rec("4-tool market research flow",
            "PASS" if r["ok"] == 4 else "FAIL",
            f"{r['ok']}/4 succeeded")
    except Exception as e:
        rec("4-tool market research flow", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # 15 rapid calls simulating an agent reading through an entire FAR part
    async def read_entire_part():
        sections = ["15.300","15.301","15.302","15.303","15.304","15.305",
                     "15.306","15.307","15.308"]
        tasks = [lookup_far_clause(s) for s in sections]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and len(r.get("paragraphs",[])) > 0)
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": len(sections)}

    try:
        r = await read_entire_part()
        rec("9 concurrent clause lookups (read Subpart 15.3)",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/{r['total']} returned content, {r['errors']} errors")
    except Exception as e:
        rec("9 concurrent clause lookups", "FAIL", str(e)[:100])

    # ── 9. CORRECTIONS DEEP ──
    print("\n━━━ 9. corrections and agencies deep ━━━")

    await t("corrections for Title 48",
        get_corrections(48),
        check=lambda r: (len(r.get("ecfr_corrections",[])) > 100, f"corrections={len(r.get('ecfr_corrections',[]))}"))

    await t("corrections for Title 2",
        get_corrections(2),
        check=lambda r: (True, f"corrections={len(r.get('ecfr_corrections',[]))}"))

    await t("agencies list has FAR council",
        list_agencies(),
        check=lambda r: (
            any("Federal Acquisition" in a.get("name","") for a in r.get("agencies",[])),
            "FAR council found"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"eCFR R3 CREATIVE CHAOS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
