"""Federal Register MCP stress test: all 3 rounds combined."""
from __future__ import annotations
import asyncio, sys
from federal_register_mcp.server import (
    search_documents, get_document, get_documents_batch,
    get_facet_counts, get_public_inspection, list_agencies,
    open_comment_periods, far_case_history,
)

P = "\033[92mPASS\033[0m"; F = "\033[91mFAIL\033[0m"; I = "\033[94mINFO\033[0m"
results = []

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    await asyncio.sleep(0.4)
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
            if any(x in msg for x in ["400","404","422","429"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("FEDERAL REGISTER MCP: 3-ROUND COMBINED STRESS TEST")
    print("="*60)

    # ═════ ROUND 1 ═════
    print("\n" + "="*60)
    print("  ROUND 1: BOUNDARIES AND VALIDATION")
    print("="*60)

    print("\n━━━ 1.1 search basics ━━━")

    await t("recent proposed rules",
        search_documents(doc_types=["PRORULE"], pub_date_gte="2025-01-01", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)}"))

    await t("DoD final rules 2025",
        search_documents(agencies=["defense-department"], doc_types=["RULE"], pub_date_gte="2025-01-01", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)}"))

    await t("term search 'cybersecurity'",
        search_documents(term="cybersecurity", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)}"))

    await t("docket_id 'FAR Case 2023'",
        search_documents(docket_id="FAR Case 2023", per_page=10),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)} FAR cases"))

    await t("GSA + SBA multi-agency",
        search_documents(agencies=["general-services-administration","small-business-administration"], pub_date_gte="2025-01-01", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)}"))

    await t("significant rules only",
        search_documents(doc_types=["RULE"], significant=True, pub_date_gte="2024-01-01", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)} significant"))

    await t("corrections filter",
        search_documents(correction=True, pub_date_gte="2024-01-01", per_page=5))

    await t("presidential documents",
        search_documents(doc_types=["PRESDOCU"], pub_date_gte="2025-01-01", per_page=5),
        check=lambda r: (r.get("count",0) > 0, f"count={r.get('count',0)}"))

    await t("order=oldest",
        search_documents(term="acquisition", pub_date_gte="2025-01-01", per_page=3, order="oldest"))

    await t("order=relevance",
        search_documents(term="acquisition", per_page=3, order="relevance"))

    print("\n━━━ 1.2 single document ━━━")

    # Get a real document number from search
    search_result = await search_documents(pub_date_gte="2026-01-01", per_page=1)
    real_doc_num = None
    if search_result.get("results"):
        real_doc_num = search_result["results"][0].get("document_number")

    if real_doc_num:
        await t(f"get_document({real_doc_num})",
            get_document(real_doc_num),
            check=lambda r: (r.get("document_number") == real_doc_num, f"doc={r.get('document_number')}"))
    else:
        rec("get_document (real)", "SKIP", "no doc number from search")

    await t("get_document empty", get_document(""), expect="error")
    await t("get_document bogus", get_document("BOGUS-99999"), expect="error")

    print("\n━━━ 1.3 batch documents ━━━")

    await t("batch empty list", get_documents_batch([]), expect="error")
    await t("batch >20 docs", get_documents_batch([f"doc-{i}" for i in range(25)]), expect="error")

    if real_doc_num:
        await t("batch with 1 real doc",
            get_documents_batch([real_doc_num]),
            check=lambda r: (True, f"results={len(r.get('results',[]))}"))

    print("\n━━━ 1.4 facets ━━━")

    await t("facet by type",
        get_facet_counts("type", pub_date_gte="2025-01-01"),
        check=lambda r: (True, f"facets returned"))

    await t("facet by agency for DoD",
        get_facet_counts("agency", agencies=["defense-department"], pub_date_gte="2025-01-01"))

    await t("facet by topic",
        get_facet_counts("topic", pub_date_gte="2025-01-01"))

    print("\n━━━ 1.5 public inspection ━━━")

    await t("public inspection current",
        get_public_inspection(),
        check=lambda r: (r.get("total_pi_documents",0) >= 0, f"total={r.get('total_pi_documents',0)}"))

    await t("public inspection with keyword filter",
        get_public_inspection(keyword_filter="acquisition"))

    await t("public inspection with agency filter",
        get_public_inspection(agency_filter="defense"))

    print("\n━━━ 1.6 agencies ━━━")

    await t("list all agencies",
        list_agencies(),
        check=lambda r: (len(r) > 400, f"agencies={len(r)}"))

    print("\n━━━ 1.7 workflow tools ━━━")

    await t("open comment periods (all agencies)",
        open_comment_periods(),
        check=lambda r: (r.get("total_open",0) >= 0, f"open={r.get('total_open',0)}"))

    await t("open comment periods (procurement agencies)",
        open_comment_periods(agencies=["federal-procurement-policy-office","defense-department","general-services-administration"]),
        check=lambda r: (True, f"open={r.get('total_open',0)}"))

    await t("far_case_history 'FAR Case 2023-008'",
        far_case_history("FAR Case 2023-008"),
        check=lambda r: (r.get("total_documents",0) > 0, f"docs={r.get('total_documents',0)}"))

    await t("far_case_history empty", far_case_history(""), expect="error")

    await t("far_case_history nonexistent",
        far_case_history("NONEXISTENT-DOCKET-XYZ-999"),
        check=lambda r: (True, f"docs={r.get('total_documents',0)} (may be 0)"))

    # ═════ ROUND 2 ═════
    print("\n" + "="*60)
    print("  ROUND 2: ADVERSARIAL EDGE CASES")
    print("="*60)

    print("\n━━━ 2.1 injection ━━━")

    await t("SQL in term", search_documents(term="'; DROP TABLE documents; --", per_page=3))
    await t("XSS in term", search_documents(term="<script>alert('xss')</script>", per_page=3))
    await t("SQL in docket_id", search_documents(docket_id="' OR 1=1 --", per_page=3))
    await t("path traversal in doc number", get_document("../../etc/passwd"), expect="error")
    await t("null bytes in term", search_documents(term="acquisition\x00test", per_page=3))
    await t("CRLF in term", search_documents(term="test\r\nX-Injected: true", per_page=3))

    print("\n━━━ 2.2 unicode ━━━")

    await t("emoji in term", search_documents(term="🏛️ regulation", per_page=3))
    await t("CJK in term", search_documents(term="联邦采购法规", per_page=3))
    await t("1000 char term", search_documents(term="regulation " * 90, per_page=3))

    print("\n━━━ 2.3 absurd values ━━━")

    await t("per_page=0", search_documents(term="test", per_page=0))
    await t("per_page=5000", search_documents(term="test", per_page=5000))
    await t("page=99999", search_documents(term="test", page=99999, per_page=3))
    await t("page=-1", search_documents(term="test", page=-1, per_page=3))
    await t("pub_date 1776", search_documents(pub_date_gte="1776-07-04", pub_date_lte="1776-12-31", per_page=3))
    await t("pub_date 2099", search_documents(pub_date_gte="2099-01-01", per_page=3))
    await t("bogus agency slug", search_documents(agencies=["totally-fake-agency-zzzzz"], per_page=3))
    await t("bogus doc type", search_documents(doc_types=["FAKETYPE"], per_page=3))
    await t("bogus facet name", get_facet_counts("nonexistent"), expect="error")
    await t("bogus RIN", search_documents(regulation_id_number="0000-ZZ99", per_page=3))

    print("\n━━━ 2.4 concurrent ━━━")

    async def parallel_5():
        tasks = [
            search_documents(term="cybersecurity", per_page=3),
            search_documents(doc_types=["PRORULE"], pub_date_gte="2025-01-01", per_page=3),
            get_facet_counts("type"),
            list_agencies(),
            open_comment_periods(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        return {"ok": ok, "total": 5}

    try:
        r = await parallel_5()
        rec("5 concurrent mixed calls", "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5")
    except Exception as e:
        rec("5 concurrent mixed", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ═════ ROUND 3 ═════
    print("\n" + "="*60)
    print("  ROUND 3: AGENT WORKFLOWS")
    print("="*60)

    print("\n━━━ 3.1 procurement regulatory scan ━━━")

    async def procurement_scan():
        tasks = [
            search_documents(agencies=["federal-procurement-policy-office"], pub_date_gte="2024-01-01", per_page=10),
            search_documents(agencies=["defense-acquisition-regulations-system"], pub_date_gte="2024-01-01", per_page=10),
            open_comment_periods(agencies=["federal-procurement-policy-office","defense-department","general-services-administration"]),
            get_facet_counts("type", agencies=["defense-department"], pub_date_gte="2024-01-01"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        return {"ok": ok, "total": 4}

    try:
        r = await procurement_scan()
        rec("4-tool procurement scan", "PASS" if r["ok"] == 4 else "FAIL", f"{r['ok']}/4")
    except Exception as e:
        rec("procurement scan", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    print("\n━━━ 3.2 FAR case deep dive ━━━")

    await t("FAR Case 2023 (all 2023 cases)",
        far_case_history("FAR Case 2023"),
        check=lambda r: (r.get("total_documents",0) > 5, f"docs={r.get('total_documents',0)}"))

    await t("DFARS docket search",
        search_documents(docket_id="DARS-2024", per_page=10),
        check=lambda r: (True, f"count={r.get('count',0)}"))

    print("\n━━━ 3.3 rapid fire 10 concurrent ━━━")

    async def rapid_10():
        tasks = [
            search_documents(term="acquisition", per_page=2),
            search_documents(term="debarment", per_page=2),
            search_documents(doc_types=["PRORULE"], per_page=2),
            search_documents(doc_types=["RULE"], per_page=2),
            get_facet_counts("type"),
            get_facet_counts("agency", term="cybersecurity"),
            list_agencies(),
            open_comment_periods(),
            far_case_history("FAR Case 2024-001"),
            get_public_inspection(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": 10}

    try:
        r = await rapid_10()
        rec("10 concurrent mixed calls",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/10 succeeded, {r['errors']} errors")
    except Exception as e:
        rec("10 concurrent mixed", "FAIL", str(e)[:100])

    # ═════ SUMMARY ═════
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"FEDERAL REGISTER ALL ROUNDS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
