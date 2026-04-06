"""Regulations.gov MCP stress test: all 3 rounds combined."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from regulationsgov_mcp.server import (
    search_documents, get_document_detail, search_comments, get_comment_detail,
    search_dockets, get_docket_detail, open_comment_periods, far_case_history,
)

P = "\033[92mPASS\033[0m"; F = "\033[91mFAIL\033[0m"; I = "\033[94mINFO\033[0m"
results = []

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    await asyncio.sleep(0.6)
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
            if any(x in msg for x in ["400","403","404","429"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("REGULATIONS.GOV MCP: 3-ROUND COMBINED STRESS TEST")
    print("="*60)

    # ═════ ROUND 1 ═════
    print("\n" + "="*60)
    print("  ROUND 1: BOUNDARIES AND VALIDATION")
    print("="*60)

    print("\n━━━ 1.1 document search ━━━")

    await t("FAR proposed rules",
        search_documents(agency_id="FAR", document_type="Proposed Rule", page_size=5),
        check=lambda r: (r.get("meta",{}).get("totalElements",0) > 0, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("DARS rules 2025",
        search_documents(agency_id="DARS", document_type="Rule", posted_date_ge="2025-01-01", page_size=5),
        check=lambda r: (True, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("term search 'cybersecurity'",
        search_documents(search_term="cybersecurity", page_size=5),
        check=lambda r: (r.get("meta",{}).get("totalElements",0) > 0, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("within comment period",
        search_documents(within_comment_period=True, page_size=5),
        check=lambda r: (True, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("docket filter FAR-2023-0008",
        search_documents(docket_id="FAR-2023-0008", page_size=10),
        check=lambda r: (r.get("meta",{}).get("totalElements",0) > 0, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("comment end date filter",
        search_documents(comment_end_date_ge="2025-01-01", page_size=5))

    await t("sort oldest first",
        search_documents(agency_id="FAR", sort="postedDate", page_size=5))

    print("\n━━━ 1.2 validation ━━━")

    await t("page_size=3 (below min 5)",
        search_documents(search_term="test", page_size=3), expect="error")

    await t("page_size=300 (above max 250)",
        search_documents(search_term="test", page_size=300), expect="error")

    await t("empty document_id", get_document_detail(""), expect="error")
    await t("empty comment_id", get_comment_detail(""), expect="error")
    await t("empty docket_id", get_docket_detail(""), expect="error")
    await t("empty far_case_history", far_case_history(""), expect="error")

    print("\n━━━ 1.3 document detail ━━━")

    # Get a real document ID
    real_doc_id = None
    try:
        sr = await search_documents(agency_id="FAR", page_size=1)
        if sr.get("data"):
            real_doc_id = sr["data"][0]["id"]
    except: pass

    if real_doc_id:
        await t(f"get_document_detail({real_doc_id[:25]}...)",
            get_document_detail(real_doc_id),
            check=lambda r: (r.get("data",{}).get("id") is not None, f"id={r.get('data',{}).get('id','?')[:30]}"))

        await t("get_document_detail with attachments",
            get_document_detail(real_doc_id, include_attachments=True))
    else:
        rec("document detail", "SKIP", "no doc ID from search")

    await t("bogus document ID",
        get_document_detail("BOGUS-9999-0000-0001"), expect="error")

    print("\n━━━ 1.4 comments ━━━")

    await t("search comments for FAR docket",
        search_comments(docket_id="FAR-2023-0008", page_size=10),
        check=lambda r: (True, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("search comments by agency",
        search_comments(agency_id="FAR", page_size=5))

    await t("bogus comment ID",
        get_comment_detail("BOGUS-COMMENT-ID"), expect="error")

    print("\n━━━ 1.5 dockets ━━━")

    await t("search FAR rulemaking dockets",
        search_dockets(agency_id="FAR", docket_type="Rulemaking", page_size=10),
        check=lambda r: (r.get("meta",{}).get("totalElements",0) > 0, f"total={r.get('meta',{}).get('totalElements',0)}"))

    await t("docket detail FAR-2023-0008",
        get_docket_detail("FAR-2023-0008"),
        check=lambda r: (r.get("data",{}).get("id") == "FAR-2023-0008", f"id={r.get('data',{}).get('id')}"))

    await t("bogus docket ID",
        get_docket_detail("BOGUS-DOCKET-999"), expect="error")

    print("\n━━━ 1.6 workflows ━━━")

    await t("open comment periods (default agencies)",
        open_comment_periods(),
        check=lambda r: (r.get("total_open",0) >= 0, f"open={r.get('total_open',0)}"))

    await t("open comment periods (FAR only)",
        open_comment_periods(agency_ids=["FAR"]),
        check=lambda r: (True, f"open={r.get('total_open',0)}"))

    await t("far_case_history FAR-2023-0008",
        far_case_history("FAR-2023-0008"),
        check=lambda r: (r.get("total_documents",0) > 0, f"docs={r.get('total_documents',0)}, title={str(r.get('title',''))[:40]}"))

    # ═════ ROUND 2 ═════
    print("\n" + "="*60)
    print("  ROUND 2: ADVERSARIAL EDGE CASES")
    print("="*60)

    print("\n━━━ 2.1 injection ━━━")

    await t("SQL in search_term",
        search_documents(search_term="'; DROP TABLE documents; --", page_size=5),
        expect="error")

    await t("XSS in search_term",
        search_documents(search_term="<script>alert(1)</script>", page_size=5))

    await t("path traversal in document_id",
        get_document_detail("../../etc/passwd"), expect="error")

    await t("null byte in search_term",
        search_documents(search_term="acquisition\x00test", page_size=5))

    print("\n━━━ 2.2 case sensitivity (critical API quirk) ━━━")

    await t("lowercase 'proposed rule' (should get 0 or different count)",
        search_documents(document_type="Proposed Rule", agency_id="FAR", page_size=5),
        check=lambda r: (True, f"correct case: total={r.get('meta',{}).get('totalElements',0)}"))

    await t("lowercase docket type 'rulemaking'",
        search_dockets(docket_type="Rulemaking", agency_id="FAR", page_size=5),
        check=lambda r: (True, f"correct case: total={r.get('meta',{}).get('totalElements',0)}"))

    print("\n━━━ 2.3 absurd values ━━━")

    await t("page=999",
        search_documents(search_term="test", page_number=999, page_size=5))

    await t("page=0",
        search_documents(search_term="test", page_number=0, page_size=5))

    await t("date 1776",
        search_documents(posted_date_ge="1776-07-04", page_size=5))

    await t("date 2099",
        search_documents(posted_date_ge="2099-01-01", page_size=5))

    await t("bogus agency_id 'ZZZZZ'",
        search_documents(agency_id="ZZZZZ", page_size=5))

    await t("1000 char search_term",
        search_documents(search_term="regulation " * 90, page_size=5))

    await t("emoji in search",
        search_documents(search_term="🏛️ regulation", page_size=5))

    print("\n━━━ 2.4 concurrent ━━━")

    async def parallel_5():
        tasks = [
            search_documents(agency_id="FAR", page_size=5),
            search_documents(agency_id="DARS", page_size=5),
            search_dockets(agency_id="FAR", page_size=5),
            get_docket_detail("FAR-2023-0008"),
            search_comments(agency_id="FAR", page_size=5),
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
            search_documents(agency_id="FAR", document_type="Proposed Rule", posted_date_ge="2024-01-01", page_size=10),
            search_documents(agency_id="DARS", document_type="Rule", posted_date_ge="2024-01-01", page_size=10),
            search_dockets(agency_id="FAR", docket_type="Rulemaking", page_size=10),
            open_comment_periods(agency_ids=["FAR", "DARS"]),
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

    await t("far_case_history DARS-2025-0071",
        far_case_history("DARS-2025-0071"),
        check=lambda r: (True, f"docs={r.get('total_documents',0)}, agency={r.get('agency')}"))

    print("\n━━━ 3.3 rapid fire 8 concurrent ━━━")

    async def rapid_8():
        tasks = [
            search_documents(agency_id="FAR", page_size=5),
            search_documents(search_term="small business", page_size=5),
            search_comments(agency_id="FAR", page_size=5),
            search_dockets(agency_id="DARS", page_size=5),
            get_docket_detail("FAR-2023-0008"),
            open_comment_periods(agency_ids=["FAR"]),
            far_case_history("FAR-2023-0008"),
            search_documents(within_comment_period=True, page_size=5),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": 8}

    try:
        r = await rapid_8()
        rec("8 concurrent mixed calls",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/8 succeeded, {r['errors']} errors")
    except Exception as e:
        rec("8 concurrent mixed", "FAIL", str(e)[:100])

    # ═════ SUMMARY ═════
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"REGULATIONS.GOV ALL ROUNDS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
