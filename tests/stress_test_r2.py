"""Round 2 stress test: adversarial inputs, injection attempts, absurd values,
concurrent calls, Unicode torture, date mangling, and API boundary probes."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from datetime import datetime, timedelta

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from sam_gov_mcp.server import (
    lookup_entity_by_uei, lookup_entity_by_cage, search_entities,
    get_entity_reps_and_certs, get_entity_integrity_info,
    check_exclusion_by_uei, search_exclusions,
    search_opportunities, get_opportunity_description,
    lookup_psc_code, search_psc_free_text,
    vendor_responsibility_check,
)

P = "\033[92mPASS\033[0m"; F = "\033[91mFAIL\033[0m"; I = "\033[94mINFO\033[0m"
results = []
LEIDOS = "QVZMH5JLF274"
today_mm = datetime.now().strftime("%m/%d/%Y")
past30_mm = (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y")

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    await asyncio.sleep(0.5)
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
            if any(x in msg for x in ["400","404","406","422","429"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("SAM.GOV MCP ROUND 2: ADVERSARIAL STRESS TEST")
    print("="*60)

    # ── 1. INJECTION ATTEMPTS ──
    print("\n━━━ 1. injection payloads ━━━")

    await t("SQL injection in UEI",
        lookup_entity_by_uei("'; DROP TABLE entities; --"),
        expect="error")

    await t("SQL injection in entity name",
        search_entities(legal_business_name="' OR 1=1 --"),
        expect="error")

    await t("XSS in entity name",
        search_entities(legal_business_name="<script>alert('xss')</script>"),
        expect="error")

    await t("XSS in free text q",
        search_entities(free_text="<img onerror=alert(1) src=x>"),
        expect="error")

    await t("SQL injection in exclusion name",
        search_exclusions(entity_name="'; DELETE FROM exclusions; --"))

    await t("XSS in exclusion free text",
        search_exclusions(free_text="<script>document.cookie</script>"))

    await t("SQL injection in opportunity title",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm,
            title="' UNION SELECT * FROM secrets --", limit=5),
        expect="error")

    await t("path traversal in opportunity description",
        get_opportunity_description("../../etc/passwd"),
        expect="error")

    await t("null bytes in UEI",
        lookup_entity_by_uei("QVZMH\x00JLF274"))

    await t("CRLF injection in entity name",
        search_entities(legal_business_name="LEIDOS\r\nX-Injected: true"))

    await t("Unicode homoglyph UEI (Cyrillic chars)",
        lookup_entity_by_uei("QVZМНJLF274"))  # М and Н are Cyrillic

    # ── 2. ABSURD VALUES ──
    print("\n━━━ 2. absurd values ━━━")

    await t("UEI 1000 chars long",
        lookup_entity_by_uei("A" * 1000))

    await t("entity name 5000 chars",
        search_entities(legal_business_name="BOOZ" * 1250),
        expect="error")

    await t("exclusion free text 2000 chars",
        search_exclusions(free_text="smith" * 400))

    await t("opportunity title 1000 chars",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm,
            title="cybersecurity " * 70, limit=5))

    await t("CAGE code 100 chars",
        lookup_entity_by_cage("A" * 100))

    await t("PSC code 100 chars",
        lookup_psc_code("R" * 100))

    await t("page=999999",
        search_entities(legal_business_name="LEIDOS", page=999999))

    await t("exclusion size=100 (max allowed)",
        search_exclusions(classification="Firm", country="USA", size=100),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    # ── 3. DATE MANGLING ──
    print("\n━━━ 3. date mangling ━━━")

    await t("opportunity date with time component",
        search_opportunities(posted_from="04/01/2026 12:00:00", posted_to="04/05/2026 23:59:59", limit=5))

    await t("opportunity date with slashes reversed (DD/MM/YYYY)",
        search_opportunities(posted_from="01/04/2026", posted_to="05/04/2026", limit=5))

    await t("exclusion activation date wrong format (ISO)",
        search_exclusions(activation_date_range="[2026-01-01,2026-04-05]"))

    await t("exclusion activation date no brackets",
        search_exclusions(activation_date_range="01/01/2026,04/05/2026"))

    await t("opportunity posted_from in year 1900",
        search_opportunities(posted_from="01/01/1900", posted_to="12/31/1900", limit=5))

    await t("opportunity dates identical (0-day range)",
        search_opportunities(posted_from=today_mm, posted_to=today_mm, notice_type="o", limit=5),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (same-day range)"))

    await t("opportunity date exactly 364 days (boundary)",
        search_opportunities(
            posted_from=(datetime.now() - timedelta(days=363)).strftime("%m/%d/%Y"),
            posted_to=today_mm, limit=5),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (364-day boundary)"))

    await t("opportunity date exactly 365 days (should fail)",
        search_opportunities(
            posted_from=(datetime.now() - timedelta(days=365)).strftime("%m/%d/%Y"),
            posted_to=today_mm, limit=5),
        expect="error")

    # ── 4. UNICODE AND ENCODING TORTURE ──
    print("\n━━━ 4. unicode torture ━━━")

    await t("emoji in entity name",
        search_entities(legal_business_name="🏢 Corp"))

    await t("CJK in entity free text",
        search_entities(free_text="网络安全公司"))

    await t("Arabic in exclusion search",
        search_exclusions(entity_name="شركة"))

    await t("RTL override character in UEI",
        lookup_entity_by_uei("\u202eABCDEFGHIJKL"))

    await t("zero-width joiner in entity name",
        search_entities(legal_business_name="LEIDOS\u200dINC"))

    await t("emoji in opportunity title",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm,
            title="🔒 security", limit=5))

    await t("PSC free text with emoji",
        search_psc_free_text("🔧 engineering"))

    # ── 5. CONCURRENT CALL STRESS ──
    print("\n━━━ 5. concurrent calls ━━━")

    async def parallel_entity(n):
        tasks = [lookup_entity_by_uei(LEIDOS) for _ in range(n)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("totalRecords",0) > 0)
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": n}

    try:
        r = await parallel_entity(5)
        rec("5 concurrent entity lookups", "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/{r['total']} succeeded, {r['errors']} errors")
    except Exception as e:
        rec("5 concurrent entity lookups", "FAIL", str(e)[:100])

    await asyncio.sleep(2)

    try:
        r = await parallel_entity(10)
        rec("10 concurrent entity lookups", "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/{r['total']} succeeded, {r['errors']} errors")
    except Exception as e:
        rec("10 concurrent entity lookups", "FAIL", str(e)[:100])

    await asyncio.sleep(2)

    # Mixed concurrent: entity + exclusion + opportunity simultaneously
    async def parallel_mixed():
        tasks = [
            lookup_entity_by_uei(LEIDOS),
            check_exclusion_by_uei(LEIDOS),
            search_opportunities(posted_from=past30_mm, posted_to=today_mm, notice_type="o", limit=5),
            lookup_psc_code("R425"),
            search_exclusions(classification="Firm", country="USA", size=5),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        return {"ok": ok, "total": len(tasks)}

    try:
        r = await parallel_mixed()
        rec("5 mixed concurrent (entity+excl+opp+psc)",
            "PASS" if r["ok"] == r["total"] else "INFO",
            f"{r['ok']}/{r['total']} succeeded")
    except Exception as e:
        rec("5 mixed concurrent", "FAIL", str(e)[:100])

    # ── 6. FORBIDDEN CHARACTER GAUNTLET ──
    print("\n━━━ 6. forbidden characters ━━━")

    forbidden = ["&", "|", "{", "}", "^", "\\"]
    for char in forbidden:
        await t(f"entity name with '{char}'",
            search_entities(legal_business_name=f"TEST{char}CORP"))

    await t("exclusion name with pipe |",
        search_exclusions(entity_name="SMITH|JONES"))

    await t("exclusion name with curly braces",
        search_exclusions(entity_name="CORP{evil}"))

    # ── 7. BOOLEAN OPERATOR ABUSE ──
    print("\n━━━ 7. boolean operator abuse ━━━")

    await t("entity multi-UEI with tilde (OR operator)",
        lookup_entity_by_uei(f"[{LEIDOS}~ZQGGHJH74DW7]"))

    await t("entity UEI with NOT operator (!)",
        lookup_entity_by_uei(f"!{LEIDOS}"))

    await t("exclusion q with AND/OR operators",
        search_exclusions(free_text="smith AND jones"))

    await t("exclusion q with wildcard at start",
        search_exclusions(free_text="*smith"))

    await t("exclusion q with only wildcard",
        search_exclusions(free_text="*"))

    # ── 8. EMPTY/NONE EDGE CASES ──
    print("\n━━━ 8. empty/none edges ━━━")

    await t("search_entities all None params",
        search_entities())

    await t("search_exclusions all None params",
        search_exclusions())

    await t("search_opportunities minimal params only",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("responsibility check with whitespace-only UEI",
        vendor_responsibility_check("   "),
        check=lambda r: ("EMPTY_UEI" in r.get("flags",[]), f"flags={r.get('flags',[])}"))

    await t("responsibility check with tab+newline UEI",
        vendor_responsibility_check("\t\n"),
        check=lambda r: ("EMPTY_UEI" in r.get("flags",[]), f"flags={r.get('flags',[])}"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"SAM.GOV R2: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
