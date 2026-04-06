"""GSA CALC+ MCP stress test: all 3 rounds combined.
R1: boundaries, validation, real scenarios.
R2: adversarial, injection, unicode, concurrent.
R3: agent workflows, creative chaos, rapid fire."""
from __future__ import annotations
import asyncio, sys
from gsa_calc_mcp.server import (
    keyword_search, exact_search, suggest_contains, filtered_browse,
    igce_benchmark, price_reasonableness_check, vendor_rate_card, sin_analysis,
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
            if any(x in msg for x in ["400","404","429","500"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("GSA CALC+ MCP: 3-ROUND COMBINED STRESS TEST")
    print("="*60)

    # ═══════════════════════════════════════════════════════════
    # ROUND 1: BOUNDARIES AND VALIDATION
    # ═══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 1: BOUNDARIES AND VALIDATION")
    print("="*60)

    # ── 1.1 KEYWORD SEARCH BASICS ──
    print("\n━━━ 1.1 keyword search basics ━━━")

    await t("software developer (common query)",
        keyword_search("software developer", page_size=5),
        check=lambda r: (r.get("_stats",{}).get("total_rates",0) > 100, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("project manager with BA filter",
        keyword_search("project manager", education_level="BA", page_size=5),
        check=lambda r: (r.get("_stats",{}).get("total_rates",0) > 0, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("cybersecurity with experience 5-15",
        keyword_search("cybersecurity", experience_min=5, experience_max=15, page_size=5),
        check=lambda r: (r.get("_stats",{}).get("total_rates",0) > 0, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("help desk small business only",
        keyword_search("help desk", business_size="S", page_size=5))

    await t("security clearance yes filter",
        keyword_search("systems administrator", security_clearance="yes", page_size=5))

    await t("SIN filter 54151S",
        keyword_search("developer", sin="54151S", page_size=5))

    await t("price range $100-$200",
        keyword_search("analyst", price_min=100, price_max=200, page_size=5))

    await t("sort desc by rate",
        keyword_search("engineer", page_size=5, ordering="current_price", sort="desc"),
        check=lambda r: (True, "sorted desc"))

    await t("page 2 of results",
        keyword_search("software", page=2, page_size=10))

    # ── 1.2 PAGE SIZE BOUNDARIES ──
    print("\n━━━ 1.2 page size boundaries ━━━")

    await t("page_size=501 (over max)",
        keyword_search("test", page_size=501),
        expect="error")

    await t("page_size=0 (invalid)",
        keyword_search("test", page_size=0),
        expect="error")

    await t("page_size=-1 (invalid)",
        keyword_search("test", page_size=-1),
        expect="error")

    await t("page_size=500 (max valid)",
        keyword_search("software", page_size=500),
        check=lambda r: (len(r.get("hits",{}).get("hits",[])) > 0, "got results at max page size"))

    await t("page_size=1 (min valid)",
        keyword_search("software", page_size=1),
        check=lambda r: (len(r.get("hits",{}).get("hits",[])) == 1, f"got {len(r.get('hits',{}).get('hits',[]))}"))

    # ── 1.3 SUGGEST CONTAINS ──
    print("\n━━━ 1.3 suggest contains ━━━")

    await t("suggest vendor 'booz'",
        suggest_contains("vendor_name", "booz"),
        check=lambda r: (True, f"suggestions={len(r.get('suggestions',[])) }"))

    await t("suggest labor 'software'",
        suggest_contains("labor_category", "software"),
        check=lambda r: (len(r.get("suggestions",[])) > 0, f"suggestions={len(r.get('suggestions',[]))}"))

    await t("suggest 1-char (too short)",
        suggest_contains("vendor_name", "b"),
        expect="error")

    await t("suggest empty string",
        suggest_contains("vendor_name", ""),
        expect="error")

    await t("suggest nonexistent vendor 'zzzzzzqqqq'",
        suggest_contains("vendor_name", "zzzzzzqqqq"),
        check=lambda r: (len(r.get("suggestions",[])) == 0, "0 suggestions (expected)"))

    # ── 1.4 EXACT SEARCH ──
    print("\n━━━ 1.4 exact search ━━━")

    await t("exact search empty value",
        exact_search("vendor_name", ""),
        expect="error")

    await t("exact search whitespace value",
        exact_search("vendor_name", "   "),
        expect="error")

    # ── 1.5 WORKFLOW TOOLS ──
    print("\n━━━ 1.5 workflow tools ━━━")

    await t("igce_benchmark software developer",
        igce_benchmark("software developer"),
        check=lambda r: (r.get("total_rates",0) > 100, f"rates={r.get('total_rates',0)}, median={r.get('percentiles',{}).get('p50_median')}"))

    await t("igce_benchmark with all filters",
        igce_benchmark("project manager", education_level="MA", experience_min=10, experience_max=20, business_size="S"),
        check=lambda r: (r.get("total_rates",0) > 0, f"rates={r.get('total_rates',0)}"))

    await t("igce_benchmark nonexistent category",
        igce_benchmark("underwater basket weaving specialist"),
        check=lambda r: (r.get("total_rates",0) == 0, "0 rates (expected)"))

    await t("price_reasonableness $195/hr software developer",
        price_reasonableness_check("software developer", 195.0),
        check=lambda r: ("analysis" in r, f"z={r.get('analysis',{}).get('z_score')}, iqr={r.get('analysis',{}).get('iqr_position')}"))

    await t("price_reasonableness $50/hr (low)",
        price_reasonableness_check("software developer", 50.0),
        check=lambda r: (r.get("analysis",{}).get("iqr_position","").startswith("below"), f"iqr={r.get('analysis',{}).get('iqr_position')}"))

    await t("price_reasonableness $500/hr (high)",
        price_reasonableness_check("software developer", 500.0),
        check=lambda r: (r.get("analysis",{}).get("iqr_position","").startswith("above"), f"iqr={r.get('analysis',{}).get('iqr_position')}"))

    await t("price_reasonableness no data category",
        price_reasonableness_check("underwater basket weaving", 100.0),
        check=lambda r: (r.get("status") == "NO_DATA", "NO_DATA (expected)"))

    await t("vendor_rate_card 'leidos'",
        vendor_rate_card("leidos"),
        check=lambda r: (r.get("total_categories",0) > 0, f"vendor={r.get('vendor')}, categories={r.get('total_categories',0)}"))

    await t("vendor_rate_card nonexistent vendor",
        vendor_rate_card("zzzznonexistentcorp"),
        check=lambda r: ("error" in r, "not found (expected)"))

    await t("vendor_rate_card 1-char (too short)",
        vendor_rate_card("b"),
        expect="error")

    await t("sin_analysis 54151S (IT)",
        sin_analysis("54151S"),
        check=lambda r: (r.get("total_rates",0) > 1000, f"rates={r.get('total_rates',0)}"))

    await t("sin_analysis empty",
        sin_analysis(""),
        expect="error")

    await t("sin_analysis nonexistent SIN",
        sin_analysis("ZZZZZ"),
        check=lambda r: (r.get("total_rates",0) == 0, "0 rates (expected)"))

    # ═══════════════════════════════════════════════════════════
    # ROUND 2: ADVERSARIAL
    # ═══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 2: ADVERSARIAL EDGE CASES")
    print("="*60)

    # ── 2.1 INJECTION ──
    print("\n━━━ 2.1 injection payloads ━━━")

    await t("SQL injection in keyword",
        keyword_search("'; DROP TABLE rates; --", page_size=3),
        expect="error")

    await t("XSS in keyword",
        keyword_search("<script>alert('xss')</script>", page_size=3),
        expect="error")

    await t("SQL injection in suggest",
        suggest_contains("vendor_name", "' OR 1=1 --"),
        expect="error")

    await t("JSON injection in keyword",
        keyword_search('{"evil":true}', page_size=3))

    await t("null byte in keyword",
        keyword_search("software\x00developer", page_size=3))

    await t("CRLF in keyword",
        keyword_search("test\r\nX-Injected: true", page_size=3))

    await t("path traversal in keyword",
        keyword_search("../../etc/passwd", page_size=3),
        expect="error")

    # ── 2.2 UNICODE TORTURE ──
    print("\n━━━ 2.2 unicode torture ━━━")

    await t("emoji keyword", keyword_search("🔧 engineer", page_size=3))
    await t("CJK keyword", keyword_search("软件开发", page_size=3))
    await t("Arabic keyword", keyword_search("مهندس", page_size=3))
    await t("zalgo text", keyword_search("s̷o̶f̵t̷w̸a̵r̷e̸", page_size=3))
    await t("RTL override", keyword_search("\u202erepoleved", page_size=3))
    await t("1000 char keyword", keyword_search("developer " * 100, page_size=3),
        expect="error")
    await t("only special chars", keyword_search("!@#$%^&*()", page_size=3))
    await t("backslash hell", keyword_search("\\\\\\\\\\", page_size=3))

    # ── 2.3 ABSURD VALUES ──
    print("\n━━━ 2.3 absurd values ━━━")

    await t("experience_min=999",
        keyword_search("developer", experience_min=999, page_size=3))

    await t("experience_min=-1",
        keyword_search("developer", experience_min=-1, page_size=3))

    await t("price_min=999999999 (billion/hr)",
        keyword_search("developer", price_min=999999999, page_size=3))

    await t("price_min=0.001",
        keyword_search("developer", price_min=0.001, price_max=0.002, page_size=3))

    await t("price_min > price_max (inverted)",
        keyword_search("developer", price_min=200, price_max=50, page_size=3))

    await t("education BA|MA|PHD (pipe OR)",
        keyword_search("developer", education_level="BA|MA|PHD", page_size=5),
        check=lambda r: (r.get("_stats",{}).get("total_rates",0) > 0, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("page=99999",
        keyword_search("developer", page=99999, page_size=3),
        expect="error")

    await t("page=-1",
        keyword_search("developer", page=-1, page_size=3),
        expect="error")

    await t("ordering by invalid field",
        keyword_search("developer", ordering="nonexistent_field", page_size=3),
        expect="error")

    await t("suggest with forbidden chars",
        suggest_contains("vendor_name", "<script>"),
        expect="error")

    await t("suggest idv_piid field",
        suggest_contains("idv_piid", "GS-35"),
        check=lambda r: (True, f"suggestions={len(r.get('suggestions',[]))}"))

    await t("price_reasonableness negative rate",
        price_reasonableness_check("developer", -50.0),
        check=lambda r: ("analysis" in r, f"z={r.get('analysis',{}).get('z_score')}"))

    await t("price_reasonableness rate=0",
        price_reasonableness_check("developer", 0.0))

    await t("price_reasonableness rate=99999",
        price_reasonableness_check("developer", 99999.0),
        check=lambda r: (r.get("analysis",{}).get("iqr_position","").startswith("above"), "above P75"))

    # ── 2.4 CONCURRENT ──
    print("\n━━━ 2.4 concurrent calls ━━━")

    async def parallel_5():
        tasks = [
            keyword_search("developer", page_size=3),
            keyword_search("analyst", page_size=3),
            keyword_search("manager", page_size=3),
            keyword_search("engineer", page_size=3),
            keyword_search("administrator", page_size=3),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 5}

    try:
        r = await parallel_5()
        rec("5 concurrent keyword searches", "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5")
    except Exception as e:
        rec("5 concurrent keyword searches", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    async def parallel_mixed():
        tasks = [
            keyword_search("software developer", page_size=3),
            suggest_contains("vendor_name", "leidos"),
            igce_benchmark("project manager"),
            sin_analysis("54151S"),
            filtered_browse(education_level="MA", business_size="S", page_size=3),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 5}

    try:
        r = await parallel_mixed()
        rec("5 mixed concurrent", "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5")
    except Exception as e:
        rec("5 mixed concurrent", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════════════
    # ROUND 3: AGENT WORKFLOWS + CREATIVE CHAOS
    # ═══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 3: AGENT WORKFLOWS + CREATIVE CHAOS")
    print("="*60)

    # ── 3.1 IGCE PIPELINE ──
    print("\n━━━ 3.1 IGCE pipeline (5 labor categories) ━━━")

    categories = [
        "Program Manager", "Systems Engineer", "Software Developer",
        "Help Desk Specialist", "Network Administrator",
    ]
    async def igce_pipeline():
        tasks = [igce_benchmark(cat, education_level="BA") for cat in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("total_rates",0) > 0)
        return {"ok": ok, "total": len(categories)}

    try:
        r = await igce_pipeline()
        rec("5-category IGCE benchmark pipeline",
            "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5 had data")
    except Exception as e:
        rec("IGCE pipeline", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ── 3.2 PRICE ANALYSIS PIPELINE ──
    print("\n━━━ 3.2 price analysis (multiple rates) ━━━")

    rates_to_check = [
        ("Software Developer", 150.0),
        ("Software Developer", 250.0),
        ("Project Manager", 175.0),
        ("Help Desk", 85.0),
        ("Cybersecurity Analyst", 195.0),
    ]
    async def price_pipeline():
        tasks = [price_reasonableness_check(cat, rate) for cat, rate in rates_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and "analysis" in r)
        return {"ok": ok, "total": len(rates_to_check)}

    try:
        r = await price_pipeline()
        rec("5-rate price reasonableness pipeline",
            "PASS" if r["ok"] >= 4 else "FAIL", f"{r['ok']}/5 got analysis")
    except Exception as e:
        rec("Price pipeline", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ── 3.3 VENDOR COMPARISON ──
    print("\n━━━ 3.3 vendor comparison ━━━")

    await t("vendor_rate_card 'raytheon'",
        vendor_rate_card("raytheon"),
        check=lambda r: (r.get("total_categories",0) > 0, f"vendor={r.get('vendor')}, cats={r.get('total_categories',0)}"))

    await t("vendor_rate_card 'deloitte'",
        vendor_rate_card("deloitte"),
        check=lambda r: (r.get("total_categories",0) > 0, f"vendor={r.get('vendor')}, cats={r.get('total_categories',0)}"))

    await t("vendor_rate_card 'accenture'",
        vendor_rate_card("accenture"),
        check=lambda r: (r.get("total_categories",0) > 0 or "error" in r, f"result={'found' if r.get('total_categories',0) > 0 else 'not found'}"))

    # ── 3.4 SIN COMPARISON ──
    print("\n━━━ 3.4 SIN comparison ━━━")

    sins = ["54151S", "541611", "541512", "541330ENG", "611430"]
    for sin_code in sins:
        await t(f"sin_analysis {sin_code}",
            sin_analysis(sin_code),
            check=lambda r: (True, f"rates={r.get('total_rates',0)}, median={r.get('percentiles',{}).get('p50_median')}"))

    # ── 3.5 FILTERED BROWSE COMBOS ──
    print("\n━━━ 3.5 filtered browse combos ━━━")

    await t("MA + clearance + small business",
        filtered_browse(education_level="MA", security_clearance="yes", business_size="S", page_size=5),
        check=lambda r: (r.get("_stats",{}).get("total_rates",0) > 0, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("PHD + experience 15-30",
        filtered_browse(education_level="PHD", experience_min=15, experience_max=30, page_size=5),
        check=lambda r: (True, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    await t("HS + price under $75",
        filtered_browse(education_level="HS", price_max=75, page_size=5))

    await t("all filters at once",
        filtered_browse(
            education_level="BA", experience_min=5, experience_max=15,
            price_min=100, price_max=250, business_size="S",
            security_clearance="no", sin="54151S", worksite="Customer",
            page_size=5),
        check=lambda r: (True, f"rates={r.get('_stats',{}).get('total_rates',0)}"))

    # ── 3.6 RAPID FIRE 12 CONCURRENT ──
    print("\n━━━ 3.6 rapid fire 12 concurrent ━━━")

    async def rapid_12():
        tasks = [
            keyword_search("developer", page_size=2),
            keyword_search("manager", page_size=2),
            keyword_search("analyst", page_size=2),
            suggest_contains("vendor_name", "north"),
            suggest_contains("labor_category", "cyber"),
            igce_benchmark("Software Developer"),
            igce_benchmark("Project Manager"),
            price_reasonableness_check("Engineer", 175.0),
            vendor_rate_card("lockheed"),
            sin_analysis("54151S"),
            filtered_browse(education_level="BA", page_size=2),
            filtered_browse(business_size="S", page_size=2),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": 12}

    try:
        r = await rapid_12()
        rec("12 concurrent mixed calls",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/12 succeeded, {r['errors']} errors")
    except Exception as e:
        rec("12 concurrent mixed", "FAIL", str(e)[:100])

    # ═══════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"GSA CALC+ ALL ROUNDS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
