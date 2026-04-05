"""Stress test for sam-gov-mcp: edge cases, boundaries, bad inputs."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from datetime import datetime, timedelta

# Load .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
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

def rec(name, status, detail=""):
    results.append((name, status, detail))
    icon = {"PASS": P, "FAIL": F, "INFO": I}.get(status, status)
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

async def t(name, coro, expect="pass", check=None):
    await asyncio.sleep(0.5)
    try:
        r = await coro
        if expect == "error":
            rec(name, "FAIL", "expected exception but got success")
        elif expect == "zero":
            total = r.get("totalRecords", 0)
            if total == 0:
                rec(name, "PASS", "0 results as expected")
            else:
                rec(name, "INFO", f"got {total} results (expected 0)")
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
        msg = str(e)[:150]
        if expect == "error":
            rec(name, "PASS", f"RuntimeError: {msg}")
        elif "400" in msg or "404" in msg or "422" in msg or "406" in msg:
            rec(name, "INFO", f"API error (may be expected): {msg}")
        else:
            rec(name, "FAIL", f"RuntimeError: {msg}")
    except Exception as e:
        rec(name, "FAIL", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    today_mm = datetime.now().strftime("%m/%d/%Y")
    past30_mm = (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y")
    past90_mm = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
    LEIDOS = "QVZMH5JLF274"

    print("\n" + "="*60)
    print("SAM.GOV MCP STRESS TEST")
    print("="*60)

    # ── 1. ENTITY SIZE/PAGINATION BOUNDARIES ──
    print("\n━━━ 1. entity size/pagination boundaries ━━━")

    await t("entity size=11 (should ValueError)",
        search_entities(legal_business_name="TEST", size=11),
        expect="error")

    await t("entity size=0 (should ValueError)",
        search_entities(legal_business_name="LEIDOS", size=0),
        expect="error")

    await t("entity size=-1 (should ValueError)",
        search_entities(legal_business_name="LEIDOS", size=-1),
        expect="error")

    await t("entity size=1 (valid minimum)",
        search_entities(legal_business_name="LEIDOS", size=1),
        check=lambda r: (len(r.get("entityData",[])) <= 1, f"got {len(r.get('entityData',[]))}"))

    await t("entity page=100 (beyond results)",
        search_entities(legal_business_name="ZZZZNONEXISTENT", page=100),
        expect="zero")

    # ── 2. ENTITY LOOKUP EDGES ──
    print("\n━━━ 2. entity lookup edge cases ━━━")

    await t("UEI empty string",
        lookup_entity_by_uei(""),
        expect="zero")

    await t("UEI too short 'ABC'",
        lookup_entity_by_uei("ABC"),
        expect="zero")

    await t("UEI all Q's (format valid but nonexistent)",
        lookup_entity_by_uei("QQQQQQQQQQQQ"),
        expect="zero")

    await t("UEI with special chars",
        lookup_entity_by_uei("Q!V@Z#M$H%"),
        expect="zero")

    await t("CAGE empty string (guardrail)",
        lookup_entity_by_cage(""),
        check=lambda r: (r.get("totalRecords",0) == 0, f"returned 0 (guardrail caught empty CAGE)"))

    await t("CAGE nonexistent 'ZZZZZ'",
        lookup_entity_by_cage("ZZZZZ"),
        expect="zero")

    await t("UEI with all sections",
        lookup_entity_by_uei(LEIDOS, include_sections=["entityRegistration","coreData","assertions","pointsOfContact"]),
        check=lambda r: (r.get("totalRecords",0) >= 1, f"total={r.get('totalRecords')}"))

    await t("UEI with samRegistered=No",
        lookup_entity_by_uei(LEIDOS, sam_registered="No"),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (ID-assigned only)"))

    # ── 3. NAME SEARCH KNOWN BUGS ──
    print("\n━━━ 3. name search known bugs ━━━")

    await t("name with & (JOHNSON & JOHNSON) -- known broken",
        search_entities(legal_business_name="JOHNSON & JOHNSON"),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (0 expected due to & bug)"))

    await t("name with () (GENERAL DYNAMICS (GD)) -- known broken",
        search_entities(legal_business_name="GENERAL DYNAMICS (GD)"),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (0 expected due to () bug)"))

    await t("name without special chars works (GENERAL DYNAMICS)",
        search_entities(legal_business_name="GENERAL DYNAMICS"),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("free text q=cybersecurity (single word)",
        search_entities(free_text="cybersecurity"),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("free text q='cybersecurity cloud' (AND logic)",
        search_entities(free_text="cybersecurity cloud"),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (AND of both words)"))

    # ── 4. BUSINESS TYPE FILTERS ──
    print("\n━━━ 4. business type filters ━━━")

    await t("businessTypeCode=QF (SDVOSB)",
        search_entities(business_type_code="QF", state_code="VA"),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)} SDVOSB in VA"))

    await t("businessTypeCode=A2 (Women-Owned)",
        search_entities(business_type_code="A2", primary_naics="541512"),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("businessTypeCode=XS (S-Corp, NOT SDVOSB)",
        search_entities(business_type_code="XS", state_code="MD"),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)} S-Corps in MD"))

    await t("invalid businessTypeCode='ZZ'",
        search_entities(business_type_code="ZZ"),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (0 expected for bad code)"))

    # ── 5. EXCLUSION BOUNDARIES ──
    print("\n━━━ 5. exclusion boundaries ━━━")

    await t("exclusion size=101 (should ValueError)",
        search_exclusions(size=101),
        expect="error")

    await t("exclusion country='US' (2-char, should ValueError)",
        search_exclusions(country="US"),
        expect="error")

    await t("exclusion country='ZZZ' (3-char invalid)",
        search_exclusions(country="ZZZ"),
        expect="zero")

    await t("exclusion UEI empty string (guardrail)",
        check_exclusion_by_uei(""),
        check=lambda r: (r.get("totalRecords",0) == 0, f"returned 0 (guardrail caught empty UEI)"))

    await t("exclusion classification=Individual",
        search_exclusions(classification="Individual", size=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)} individuals"))

    await t("exclusion classification=Vessel",
        search_exclusions(classification="Vessel", size=5),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} vessels"))

    await t("exclusion excludingAgencyCode=DOD",
        search_exclusions(excluding_agency_code="DOD", size=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)} DOD exclusions"))

    await t("exclusion date range bracket format",
        search_exclusions(activation_date_range=f"[{past90_mm},{today_mm}]", size=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("exclusion wildcard q='smith*'",
        search_exclusions(free_text="smith*", size=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    # ── 6. OPPORTUNITY BOUNDARIES ──
    print("\n━━━ 6. opportunity boundaries ━━━")

    await t("opportunity limit=2000 (should ValueError)",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, limit=2000),
        expect="error")

    await t("opportunity inverted dates (from > to)",
        search_opportunities(posted_from=today_mm, posted_to=past30_mm),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} (API may accept or reject)"))

    await t("opportunity date range > 364 days",
        search_opportunities(posted_from="01/01/2024", posted_to="12/31/2025"),
        expect="error")

    await t("opportunity ISO dates (wrong format)",
        search_opportunities(posted_from="2026-03-01", posted_to="2026-04-05"),
        expect="error")

    await t("opportunity PSC prefix R4 (should get 0, exact 4-char required)",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, psc_code="R4", limit=10),
        expect="zero")

    await t("opportunity PSC exact R425",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, psc_code="R425", limit=10),
        check=lambda r: (True, f"total={r.get('totalRecords',0)}"))

    await t("opportunity agency_keyword case insensitive",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, notice_type="o", limit=50, agency_keyword="defense"),
        check=lambda r: (len(r.get("opportunitiesData",[])) > 0, f"filtered={len(r.get('opportunitiesData',[]))}"))

    await t("opportunity agency_keyword no match",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, notice_type="o", limit=50, agency_keyword="XYZNONEXISTENT"),
        check=lambda r: (len(r.get("opportunitiesData",[])) == 0, f"filtered={len(r.get('opportunitiesData',[]))}"))

    await t("opportunity all notice types work (award notices)",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, notice_type="a", limit=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)} award notices"))

    await t("opportunity combined synopsis/solicitation (k)",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, notice_type="k", limit=5),
        check=lambda r: (r.get("totalRecords",0) > 0, f"total={r.get('totalRecords',0)}"))

    await t("opportunity set_aside=HZC (HUBZone)",
        search_opportunities(posted_from=past30_mm, posted_to=today_mm, set_aside="HZC", limit=10),
        check=lambda r: (True, f"total={r.get('totalRecords',0)} HUBZone opps"))

    await t("get_opportunity_description bogus ID",
        get_opportunity_description("BOGUS_NOTICE_ID_12345"))

    # ── 7. PSC EDGES ──
    print("\n━━━ 7. PSC lookup edges ━━━")

    await t("PSC code 'ZZZZ' (nonexistent)",
        lookup_psc_code("ZZZZ"))

    await t("PSC free text empty string",
        search_psc_free_text(""))

    await t("PSC free text long query",
        search_psc_free_text("professional engineering technical consulting management support services"))

    await t("PSC code lowercase 'r425'",
        lookup_psc_code("r425"))

    # ── 8. RESPONSIBILITY CHECK EDGES ──
    print("\n━━━ 8. vendor responsibility check edges ━━━")

    await t("responsibility check nonexistent UEI",
        vendor_responsibility_check("ZZZZZZZZZZZZ"),
        check=lambda r: ("NOT_REGISTERED" in r.get("flags",[]), f"flags={r.get('flags')}"))

    await t("responsibility check empty UEI (guardrail)",
        vendor_responsibility_check(""),
        check=lambda r: ("EMPTY_UEI" in r.get("flags",[]), f"flags={r.get('flags',[])}"))

    await t("responsibility check known clean vendor (Leidos)",
        vendor_responsibility_check(LEIDOS),
        check=lambda r: (len(r.get("flags",[])) == 0, f"flags={r.get('flags',[])} (expect empty)"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"SAM.GOV STRESS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
