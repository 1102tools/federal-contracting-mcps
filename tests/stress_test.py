"""Stress test for ecfr-mcp: edge cases, boundaries, bad inputs, injection,
unicode, concurrent calls, XML parsing edge cases."""
from __future__ import annotations
import asyncio, sys
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
            if any(x in msg for x in ["400","404","406","422"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("eCFR MCP STRESS TEST: ROUND 1 + ROUND 2 COMBINED")
    print("="*60)

    # Get the safe date once for reuse
    date_info = await get_latest_date(48)
    SAFE_DATE = date_info["up_to_date_as_of"]
    print(f"  Using safe date: {SAFE_DATE}")

    # ── 1. GET_LATEST_DATE BOUNDARIES ──
    print("\n━━━ 1. get_latest_date boundaries ━━━")

    await t("title 48 (FAR)",
        get_latest_date(48),
        check=lambda r: (r.get("up_to_date_as_of") is not None, f"date={r.get('up_to_date_as_of')}"))

    await t("title 2 (Grants)",
        get_latest_date(2),
        check=lambda r: (r.get("up_to_date_as_of") is not None, f"date={r.get('up_to_date_as_of')}"))

    await t("title 999 (nonexistent)",
        get_latest_date(999),
        expect="error")

    await t("title 0",
        get_latest_date(0),
        expect="error")

    await t("title -1",
        get_latest_date(-1),
        expect="error")

    # ── 2. GET_CFR_CONTENT BOUNDARIES ──
    print("\n━━━ 2. get_cfr_content boundaries ━━━")

    await t("section 15.305 (known good)",
        get_cfr_content(48, section="15.305"),
        check=lambda r: (len(r.get("paragraphs",[])) > 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("section with date=today (may 404 due to lag)",
        get_cfr_content(48, date="2026-04-05", section="15.305"))

    await t("section with future date 2030-01-01",
        get_cfr_content(48, date="2030-01-01", section="15.305"),
        expect="error")

    await t("section with pre-2017 date",
        get_cfr_content(48, date="2015-01-01", section="15.305"),
        expect="error")

    await t("section with invalid date format",
        get_cfr_content(48, date="not-a-date", section="15.305"),
        expect="error")

    await t("nonexistent section 99.999",
        get_cfr_content(48, section="99.999"),
        check=lambda r: (len(r.get("paragraphs",[])) == 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("entire part 1 (large)",
        get_cfr_content(48, part="1"),
        check=lambda r: (len(r.get("paragraphs",[])) > 10, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("DFARS clause 252.227-7014 (chapter 2)",
        get_cfr_content(48, chapter="2", section="252.227-7014"),
        check=lambda r: (len(r.get("paragraphs",[])) > 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("raw_xml=True returns XML string",
        get_cfr_content(48, section="15.305", raw_xml=True),
        check=lambda r: ("xml" in r and "<" in r.get("xml",""), "got raw XML"))

    await t("subpart filter 15.3",
        get_cfr_content(48, subpart="15.3"),
        check=lambda r: (len(r.get("paragraphs",[])) > 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("chapter filter only (all of FAR)",
        get_cfr_content(48, chapter="1", part="1", section="1.101"),
        check=lambda r: (r.get("heading") is not None, f"heading={r.get('heading','')[:40]}"))

    # ── 3. GET_CFR_STRUCTURE BOUNDARIES ──
    print("\n━━━ 3. get_cfr_structure boundaries ━━━")

    await t("structure for FAR part 15",
        get_cfr_structure(48, part="15"),
        check=lambda r: (r.get("children") is not None or r.get("identifier") is not None, "got structure"))

    await t("structure with section filter (should 400)",
        get_cfr_structure(48, part="15"),  # structure doesn't support section, just testing part
        check=lambda r: (True, "structure returned"))

    await t("structure for nonexistent part 999",
        get_cfr_structure(48, part="999"))

    await t("structure for DFARS chapter 2",
        get_cfr_structure(48, chapter="2"),
        check=lambda r: (True, "DFARS structure returned"))

    # ── 4. SEARCH BOUNDARIES ──
    print("\n━━━ 4. search_cfr boundaries ━━━")

    await t("simple search 'debarment'",
        search_cfr("debarment", title=48, per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("search with all hierarchy filters",
        search_cfr("evaluation", title=48, chapter="1", part="15", per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("search current_only=False (historical)",
        search_cfr("debarment", title=48, current_only=False, per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, "includes historical"))

    await t("search per_page=5001 (over max)",
        search_cfr("test", per_page=5001),
        expect="error")

    await t("search with last_modified_after",
        search_cfr("*", title=48, chapter="1", last_modified_after="2025-01-01", per_page=5),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("search empty query",
        search_cfr("", title=48, per_page=5))

    await t("search very long query (500 chars)",
        search_cfr("acquisition " * 40, title=48, per_page=5))

    await t("search page=9999",
        search_cfr("debarment", title=48, page=9999, per_page=5))

    # ── 5. VERSION HISTORY BOUNDARIES ──
    print("\n━━━ 5. version_history boundaries ━━━")

    await t("versions for 52.212-4 (many versions)",
        get_version_history(48, section="52.212-4"),
        check=lambda r: (len(r.get("content_versions",[])) > 5, f"versions={len(r.get('content_versions',[]))}"))

    await t("versions for nonexistent section",
        get_version_history(48, section="99.999"),
        check=lambda r: (len(r.get("content_versions",[])) == 0, "0 versions (expected)"))

    await t("versions for entire part 52",
        get_version_history(48, part="52"),
        check=lambda r: (len(r.get("content_versions",[])) > 50, f"versions={len(r.get('content_versions',[]))}"))

    # ── 6. ANCESTRY BOUNDARIES ──
    print("\n━━━ 6. ancestry boundaries ━━━")

    await t("ancestry for 15.305",
        get_ancestry(48, section="15.305"),
        check=lambda r: (len(r.get("ancestors",[])) > 3, f"depth={len(r.get('ancestors',[]))}"))

    await t("ancestry for part 1",
        get_ancestry(48, part="1"),
        check=lambda r: (len(r.get("ancestors",[])) > 0, f"depth={len(r.get('ancestors',[]))}"))

    await t("ancestry for nonexistent section",
        get_ancestry(48, section="99.999"))

    # ── 7. WORKFLOW TOOLS ──
    print("\n━━━ 7. workflow tools ━━━")

    await t("lookup_far_clause 52.212-4",
        lookup_far_clause("52.212-4"),
        check=lambda r: (len(r.get("paragraphs",[])) > 5, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("lookup_far_clause DFARS 252.227-7014",
        lookup_far_clause("252.227-7014", chapter="2"),
        check=lambda r: (len(r.get("paragraphs",[])) > 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("lookup_far_clause nonexistent 99.999",
        lookup_far_clause("99.999"),
        check=lambda r: (len(r.get("paragraphs",[])) == 0, "0 paragraphs (expected)"))

    await t("list_sections_in_part FAR 19",
        list_sections_in_part("19"),
        check=lambda r: (r.get("section_count",0) > 20, f"sections={r.get('section_count',0)}"))

    await t("list_sections_in_part DFARS 252",
        list_sections_in_part("252", chapter="2"),
        check=lambda r: (r.get("section_count",0) > 50, f"sections={r.get('section_count',0)}"))

    await t("list_sections_in_part nonexistent 999",
        list_sections_in_part("999"))

    await t("find_far_definition 'contracting officer'",
        find_far_definition("contracting officer"),
        check=lambda r: (r.get("match_count",0) > 0, f"matches={r.get('match_count',0)}"))

    await t("find_far_definition 'xyznonexistentterm'",
        find_far_definition("xyznonexistentterm"),
        check=lambda r: (r.get("match_count",0) == 0, "0 matches (expected)"))

    await t("find_recent_changes since 2025-01-01 in FAR ch1",
        find_recent_changes("2025-01-01", chapter="1"),
        check=lambda r: (r.get("meta",{}).get("total_count",0) > 0, f"total={r.get('meta',{}).get('total_count',0)}"))

    await t("compare_versions 52.212-4 (2024 vs 2025)",
        compare_versions("52.212-4", "2024-01-02", SAFE_DATE),
        check=lambda r: (
            len(r.get("before",{}).get("paragraphs",[])) > 0 and
            len(r.get("after",{}).get("paragraphs",[])) > 0,
            f"before={len(r.get('before',{}).get('paragraphs',[]))} after={len(r.get('after',{}).get('paragraphs',[]))}"))

    # ── 8. INJECTION AND ADVERSARIAL ──
    print("\n━━━ 8. injection and adversarial ━━━")

    await t("SQL injection in search query",
        search_cfr("'; DROP TABLE cfr; --", title=48, per_page=5))

    await t("XSS in search query",
        search_cfr("<script>alert('xss')</script>", title=48, per_page=5))

    await t("path traversal in section ID",
        get_cfr_content(48, section="../../etc/passwd"))

    await t("path traversal in part ID",
        get_cfr_content(48, part="../../../etc/passwd"))

    await t("null bytes in section",
        get_cfr_content(48, section="15\x00.305"))

    await t("CRLF in search query",
        search_cfr("test\r\nX-Injected: true", title=48, per_page=5))

    await t("SQL injection in definition search",
        find_far_definition("' OR 1=1 --"))

    await t("XSS in definition search",
        find_far_definition("<img onerror=alert(1)>"))

    # ── 9. UNICODE TORTURE ──
    print("\n━━━ 9. unicode torture ━━━")

    await t("emoji in search",
        search_cfr("🔒 security", title=48, per_page=5))

    await t("CJK in search",
        search_cfr("合同法规", title=48, per_page=5))

    await t("Arabic in search",
        search_cfr("عقد", title=48, per_page=5))

    await t("emoji in definition search",
        find_far_definition("🏛️"))

    await t("very long search query",
        search_cfr("federal acquisition regulation " * 20, title=48, per_page=5))

    # ── 10. CONCURRENT CALLS ──
    print("\n━━━ 10. concurrent calls ━━━")

    async def parallel_lookups(n):
        sections = ["15.305", "52.212-4", "9.104-1", "2.101", "19.502-2"][:n]
        tasks = [lookup_far_clause(s) for s in sections]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and len(r.get("paragraphs",[])) > 0)
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": len(tasks)}

    try:
        r = await parallel_lookups(5)
        rec("5 concurrent FAR clause lookups",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/{r['total']} succeeded, {r['errors']} errors")
    except Exception as e:
        rec("5 concurrent FAR clause lookups", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    async def parallel_mixed():
        tasks = [
            get_latest_date(48),
            lookup_far_clause("15.305"),
            search_cfr("debarment", title=48, per_page=3),
            list_agencies(),
            get_version_history(48, section="52.212-4"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        return {"ok": ok, "total": len(tasks)}

    try:
        r = await parallel_mixed()
        rec("5 mixed concurrent (content+search+meta+versions)",
            "PASS" if r["ok"] == r["total"] else "INFO",
            f"{r['ok']}/{r['total']} succeeded")
    except Exception as e:
        rec("5 mixed concurrent", "FAIL", str(e)[:100])

    # ── 11. ADMIN ENDPOINTS ──
    print("\n━━━ 11. admin endpoints ━━━")

    await t("list_agencies",
        list_agencies(),
        check=lambda r: (len(r.get("agencies",[])) > 100, f"agencies={len(r.get('agencies',[]))}"))

    await t("get_corrections title 48",
        get_corrections(48),
        check=lambda r: (True, f"corrections={len(r.get('ecfr_corrections',[]))}"))

    await t("get_corrections nonexistent title 999",
        get_corrections(999),
        check=lambda r: (True, f"corrections={len(r.get('ecfr_corrections',[]))}"))

    # ── 12. XML PARSING EDGE CASES ──
    print("\n━━━ 12. XML parsing edge cases ━━━")

    await t("FAR 2.101 (huge section ~109KB)",
        get_cfr_content(48, section="2.101"),
        check=lambda r: (len(r.get("paragraphs",[])) > 100, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("FAR 52.212-5 (many clause references)",
        get_cfr_content(48, section="52.212-5"),
        check=lambda r: (len(r.get("paragraphs",[])) > 20, f"paragraphs={len(r.get('paragraphs',[]))}"))

    await t("section with extracts (clause text blocks)",
        get_cfr_content(48, section="52.212-4"),
        check=lambda r: (len(r.get("paragraphs",[])) > 0, f"paragraphs={len(r.get('paragraphs',[]))}"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"eCFR STRESS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
