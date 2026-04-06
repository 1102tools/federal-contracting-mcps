"""Round 2 stress test: adversarial inputs, SQL injection attempts, XSS payloads,
absurd values, type coercion tricks, concurrent calls, and API abuse patterns."""
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
            if any(x in msg for x in ["400","404","422","429"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("USASPENDING MCP ROUND 2: ADVERSARIAL STRESS TEST")
    print("="*60)

    # ── 1. INJECTION ATTEMPTS ──
    print("\n━━━ 1. injection payloads ━━━")

    await t("SQL injection in keywords",
        search_awards(keywords=["'; DROP TABLE awards; --"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("SQL injection in recipient_name",
        search_awards(recipient_name="' OR 1=1 --", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("XSS in keywords",
        search_awards(keywords=["<script>alert('xss')</script>"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("XSS in agency name",
        search_awards(awarding_agency="<img onerror=alert(1) src=x>", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("path traversal in award detail",
        get_award_detail("../../etc/passwd"),
        expect="error")

    await t("path traversal in PSC filter tree",
        get_psc_filter_tree("../../../etc/passwd"))

    await t("null bytes in keywords",
        search_awards(keywords=["cyber\x00security"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("CRLF injection in agency",
        search_awards(awarding_agency="DoD\r\nX-Injected: true", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── 2. ABSURD VALUES ──
    print("\n━━━ 2. absurd values ━━━")

    await t("limit=999999999",
        search_awards(keywords=["cybersecurity"], limit=999999999, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) <= 100, f"got {len(r.get('results',[]))} (clamped)"))

    await t("page=-1 negative",
        search_awards(keywords=["cybersecurity"], page=-1, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("award_amount_min=negative",
        search_awards(award_amount_min=-1000000, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("award_amount very large (999 trillion)",
        search_awards(award_amount_min=999000000000000, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        check=lambda r: (len(r.get("results",[])) == 0, f"results={len(r.get('results',[]))}"))

    await t("award_amount float precision",
        search_awards(award_amount_min=0.001, award_amount_max=0.002, limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("date far in past (1776-07-04)",
        search_awards(keywords=["defense"], time_period_start="1776-07-04", time_period_end="1776-12-31", limit=3))

    await t("date far in future (2099-01-01)",
        search_awards(keywords=["defense"], time_period_start="2099-01-01", time_period_end="2099-12-31", limit=3))

    await t("malformed date (not a date)",
        search_awards(keywords=["defense"], time_period_start="not-a-date", time_period_end="also-not", limit=3))

    # ── 3. UNICODE AND ENCODING STRESS ──
    print("\n━━━ 3. unicode and encoding ━━━")

    await t("emoji in keywords",
        search_awards(keywords=["🚀 cybersecurity"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("CJK characters in keywords",
        search_awards(keywords=["网络安全合同"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("Arabic text in keywords",
        search_awards(keywords=["عقد أمن سيبراني"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("very long keyword (500 chars)",
        search_awards(keywords=["cybersecurity " * 35], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("keyword with only spaces",
        search_awards(keywords=["   "], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("autocomplete with emoji",
        autocomplete_psc("🔧"))

    await t("NAICS autocomplete with unicode",
        autocomplete_naics("café"))

    # ── 4. CONCURRENT CALL STRESS ──
    print("\n━━━ 4. concurrent calls ━━━")

    async def parallel_search(n):
        tasks = [
            search_awards(keywords=["cybersecurity"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30")
            for _ in range(n)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successes = sum(1 for r in results if isinstance(r, dict))
        errors = sum(1 for r in results if isinstance(r, Exception))
        return {"successes": successes, "errors": errors, "total": n}

    try:
        r = await parallel_search(5)
        rec("5 concurrent searches", "PASS" if r["errors"] == 0 else "INFO",
            f"{r['successes']}/{r['total']} succeeded")
    except Exception as e:
        rec("5 concurrent searches", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    try:
        r = await parallel_search(10)
        rec("10 concurrent searches", "PASS" if r["errors"] == 0 else "INFO",
            f"{r['successes']}/{r['total']} succeeded")
    except Exception as e:
        rec("10 concurrent searches", "FAIL", str(e)[:100])

    # ── 5. TYPE COERCION TRICKS ──
    print("\n━━━ 5. type coercion edge cases ━━━")

    await t("NAICS codes as integers-in-strings",
        search_awards(naics_codes=["541512", "000000"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("PSC codes with leading spaces",
        search_awards(psc_codes=[" R425 ", " D399"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("state code lowercase 'va'",
        search_awards(place_of_performance_state="va", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("state code 3-letter 'VAR'",
        search_awards(place_of_performance_state="VAR", limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("empty string award_type_codes via raw keywords",
        search_awards(award_type="contracts", keywords=[""], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        expect="error")

    # ── 6. ENDPOINT ABUSE ──
    print("\n━━━ 6. endpoint abuse ━━━")

    await t("get_award_detail with URL as ID",
        get_award_detail("https://evil.com/steal?data=true"),
        expect="error")

    await t("get_state_profile with JS payload (validation catches)",
        get_state_profile("javascript:alert(1)"),
        expect="error")

    await t("get_agency_overview with boolean-like (validation catches)",
        get_agency_overview("true"),
        expect="error")

    await t("get_naics_details with float (validation catches)",
        get_naics_details("541.512"),
        expect="error")

    await t("lookup_piid with SQL union",
        lookup_piid("N00024' UNION SELECT * FROM users--", limit=2))

    await t("spending_by_category with huge limit",
        spending_by_category(category="recipient", keywords=["cybersecurity"], limit=99999, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("spending_over_time no filters at all",
        spending_over_time())

    await t("get_award_count no filters",
        get_award_count(),
        check=lambda r: (r.get("results",{}).get("contracts",0) > 0, f"contracts={r.get('results',{}).get('contracts','?')}"))

    # ── 7. KEYWORD VALIDATION BYPASS ATTEMPTS ──
    print("\n━━━ 7. keyword validation bypass ━━━")

    await t("keyword exactly 3 chars 'abc'",
        search_awards(keywords=["abc"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    await t("keyword 2 chars 'ab' (should fail)",
        search_awards(keywords=["ab"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        expect="error")

    await t("keyword mix valid+invalid ['cybersecurity','ab']",
        search_awards(keywords=["cybersecurity","ab"], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"),
        expect="error")

    await t("keyword all whitespace '   ' (3 spaces, 3 chars)",
        search_awards(keywords=["   "], limit=3, time_period_start="2024-10-01", time_period_end="2025-09-30"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"USASPENDING R2: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
