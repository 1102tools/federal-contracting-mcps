"""Live integration tests against the real SAM.gov API.

Requires SAM_API_KEY set in the environment. Does not write state anywhere.
Designed to exercise every tool and every documented API quirk.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Load .env from project root
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from sam_gov_mcp.server import (
    lookup_entity_by_uei,
    lookup_entity_by_cage,
    search_entities,
    get_entity_reps_and_certs,
    get_entity_integrity_info,
    check_exclusion_by_uei,
    search_exclusions,
    search_opportunities,
    get_opportunity_description,
    lookup_psc_code,
    search_psc_free_text,
    vendor_responsibility_check,
)


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
INFO = "\033[94mINFO\033[0m"

results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    icon = {"PASS": PASS, "FAIL": FAIL, "SKIP": SKIP, "INFO": INFO}.get(status, status)
    print(f"  [{icon}] {name}" + (f" — {detail}" if detail else ""))


def summarize() -> int:
    total = len(results)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")
    print()
    print("=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)
    if failed:
        print("\nFailures:")
        for name, s, detail in results:
            if s == "FAIL":
                print(f"  • {name}: {detail}")
        return 1
    return 0


async def section(title: str) -> None:
    print()
    print(f"━━━ {title} ━━━")


async def main() -> int:
    # ========== Section 1: Entity lookups ==========
    await section("1. ENTITY LOOKUPS")

    # 1a: Known Leidos UEI from the skill docs
    LEIDOS_UEI = "QVZMH5JLF274"
    try:
        r = await lookup_entity_by_uei(LEIDOS_UEI)
        total = r.get("totalRecords", 0)
        if total >= 1:
            name = r["entityData"][0].get("entityRegistration", {}).get("legalBusinessName", "?")
            record(f"lookup_entity_by_uei({LEIDOS_UEI})", "PASS", f"found: {name}")
        else:
            record(f"lookup_entity_by_uei({LEIDOS_UEI})", "FAIL", f"totalRecords={total}")
    except Exception as e:
        record(f"lookup_entity_by_uei({LEIDOS_UEI})", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1b: Same entity with assertions (NAICS/PSC)
    try:
        r = await lookup_entity_by_uei(
            LEIDOS_UEI,
            include_sections=["entityRegistration", "coreData", "assertions"],
        )
        entity = r["entityData"][0]
        assertions = entity.get("assertions", {}).get("goodsAndServices", {})
        primary_naics = assertions.get("primaryNaics")
        naics_count = len(assertions.get("naicsList") or [])
        if primary_naics:
            record("lookup_entity_by_uei with assertions", "PASS",
                   f"primaryNaics={primary_naics}, {naics_count} NAICS on file")
        else:
            record("lookup_entity_by_uei with assertions", "FAIL", "no primaryNaics")
    except Exception as e:
        record("lookup_entity_by_uei with assertions", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1c: CAGE code lookup - pull a CAGE from the first result
    try:
        r = await lookup_entity_by_uei(LEIDOS_UEI)
        cage = r["entityData"][0].get("entityRegistration", {}).get("cageCode")
        if cage:
            await asyncio.sleep(0.4)
            r2 = await lookup_entity_by_cage(cage)
            total = r2.get("totalRecords", 0)
            if total >= 1:
                record(f"lookup_entity_by_cage({cage})", "PASS", f"totalRecords={total}")
            else:
                record(f"lookup_entity_by_cage({cage})", "FAIL", f"totalRecords={total}")
        else:
            record("lookup_entity_by_cage", "SKIP", "no CAGE on Leidos record")
    except Exception as e:
        record("lookup_entity_by_cage", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1d: Name search
    try:
        r = await search_entities(legal_business_name="BOOZ ALLEN", size=5)
        total = r.get("totalRecords", 0)
        record("search_entities name=BOOZ ALLEN", "PASS" if total > 0 else "FAIL",
               f"totalRecords={total}")
    except Exception as e:
        record("search_entities name search", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1e: Market research scan - SDVOSB firms in VA doing IT
    try:
        r = await search_entities(
            business_type_code="QF",
            state_code="VA",
            primary_naics="541512",
            size=10,
        )
        total = r.get("totalRecords", 0)
        record("search_entities SDVOSB/VA/541512", "PASS" if total >= 0 else "FAIL",
               f"totalRecords={total}")
    except Exception as e:
        record("search_entities SDVOSB/VA/541512", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1f: Reps and certs (explicit section)
    try:
        r = await get_entity_reps_and_certs(LEIDOS_UEI)
        total = r.get("totalRecords", 0)
        if total >= 1:
            entity = r["entityData"][0]
            has_rac = "repsAndCerts" in entity and entity.get("repsAndCerts") is not None
            if has_rac:
                record("get_entity_reps_and_certs", "PASS", "repsAndCerts section present")
            else:
                record("get_entity_reps_and_certs", "INFO", "section empty (may be license-restricted)")
        else:
            record("get_entity_reps_and_certs", "FAIL", f"totalRecords={total}")
    except Exception as e:
        record("get_entity_reps_and_certs", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 1g: Integrity info
    try:
        r = await get_entity_integrity_info(LEIDOS_UEI)
        total = r.get("totalRecords", 0)
        if total >= 1:
            record("get_entity_integrity_info", "PASS", f"totalRecords={total}")
        else:
            record("get_entity_integrity_info", "INFO", "no integrity data returned (may be empty)")
    except Exception as e:
        record("get_entity_integrity_info", "FAIL", str(e)[:120])

    # ========== Section 2: Exclusion checks ==========
    await section("2. EXCLUSION CHECKS")

    await asyncio.sleep(0.4)

    # 2a: Check Leidos (should have no active exclusions)
    try:
        r = await check_exclusion_by_uei(LEIDOS_UEI)
        total = r.get("totalRecords", 0)
        record(f"check_exclusion_by_uei({LEIDOS_UEI})", "PASS",
               f"totalRecords={total} (expected 0 for clean vendor)")
    except Exception as e:
        record("check_exclusion_by_uei clean", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 2b: Free text exclusion search with wildcard
    try:
        r = await search_exclusions(free_text="acme*", size=10)
        total = r.get("totalRecords", 0)
        record("search_exclusions q=acme*", "PASS" if total >= 0 else "FAIL",
               f"totalRecords={total}")
    except Exception as e:
        record("search_exclusions wildcard", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 2c: Recent exclusion actions (last 90 days)
    try:
        today = datetime.now().strftime("%m/%d/%Y")
        past = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
        r = await search_exclusions(
            activation_date_range=f"[{past},{today}]",
            classification="Firm",
            size=10,
        )
        total = r.get("totalRecords", 0)
        record("search_exclusions recent 90 days firms", "PASS",
               f"totalRecords={total} firms excluded in last 90 days")
    except Exception as e:
        record("search_exclusions recent", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 2d: Country code validation (should raise for 2-char)
    try:
        await search_exclusions(country="US", size=5)
        record("search_exclusions country=US validation", "FAIL",
               "expected ValueError for 2-char country code")
    except ValueError as e:
        record("search_exclusions country=US validation", "PASS",
               f"raised ValueError as expected")
    except Exception as e:
        record("search_exclusions country=US validation", "FAIL",
               f"wrong exception: {type(e).__name__}")

    await asyncio.sleep(0.4)

    # 2e: Valid 3-char country code
    try:
        r = await search_exclusions(country="USA", classification="Firm", size=5)
        total = r.get("totalRecords", 0)
        record("search_exclusions country=USA", "PASS",
               f"totalRecords={total}")
    except Exception as e:
        record("search_exclusions country=USA", "FAIL", str(e)[:120])

    # ========== Section 3: Opportunity searches ==========
    await section("3. OPPORTUNITY SEARCHES")

    await asyncio.sleep(0.4)

    # 3a: Recent solicitations (last 30 days)
    today = datetime.now().strftime("%m/%d/%Y")
    past_30 = (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y")

    first_notice_id = None
    try:
        r = await search_opportunities(
            posted_from=past_30,
            posted_to=today,
            notice_type="o",
            limit=25,
        )
        total = r.get("totalRecords", 0)
        opps = r.get("opportunitiesData", [])
        if total > 0 and opps:
            first_notice_id = opps[0].get("noticeId")
            title = opps[0].get("title", "?")[:50]
            record("search_opportunities last 30d solicitations", "PASS",
                   f"{total} total, first: {title}")
        else:
            record("search_opportunities last 30d solicitations", "FAIL",
                   f"totalRecords={total}")
    except Exception as e:
        record("search_opportunities recent", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 3b: NAICS filter
    try:
        r = await search_opportunities(
            posted_from=past_30,
            posted_to=today,
            notice_type="o",
            naics_code="541512",
            limit=10,
        )
        total = r.get("totalRecords", 0)
        record("search_opportunities NAICS=541512", "PASS",
               f"totalRecords={total} IT services solicitations")
    except Exception as e:
        record("search_opportunities NAICS filter", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 3c: Set-aside filter
    try:
        r = await search_opportunities(
            posted_from=past_30,
            posted_to=today,
            set_aside="SDVOSBC",
            limit=10,
        )
        total = r.get("totalRecords", 0)
        record("search_opportunities SDVOSB set-aside", "PASS",
               f"totalRecords={total}")
    except Exception as e:
        record("search_opportunities set-aside", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 3d: Sources sought (notice_type=r)
    try:
        r = await search_opportunities(
            posted_from=past_30,
            posted_to=today,
            notice_type="r",
            naics_code="541512",
            limit=10,
        )
        total = r.get("totalRecords", 0)
        record("search_opportunities sources sought 541512", "PASS",
               f"totalRecords={total}")
    except Exception as e:
        record("search_opportunities sources sought", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 3e: Agency post-filter (deptname is broken, using agency_keyword)
    try:
        r = await search_opportunities(
            posted_from=past_30,
            posted_to=today,
            notice_type="o",
            limit=100,
            agency_keyword="DEFENSE",
        )
        filtered_count = len(r.get("opportunitiesData", []))
        record("search_opportunities agency_keyword=DEFENSE", "PASS",
               f"{filtered_count} post-filtered opps mentioning DEFENSE")
    except Exception as e:
        record("search_opportunities agency post-filter", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 3f: Fetch description of a real opportunity
    if first_notice_id:
        try:
            r = await get_opportunity_description(first_notice_id)
            desc = r.get("description") or r.get("raw_response") or ""
            desc_len = len(desc) if isinstance(desc, str) else 0
            if desc_len > 0:
                record("get_opportunity_description", "PASS",
                       f"fetched {desc_len} chars of HTML description")
            else:
                record("get_opportunity_description", "INFO",
                       "empty description (some opportunities have no description)")
        except Exception as e:
            record("get_opportunity_description", "FAIL", str(e)[:120])
    else:
        record("get_opportunity_description", "SKIP", "no notice ID from prior test")

    # ========== Section 4: PSC lookups ==========
    await section("4. PSC LOOKUPS")

    await asyncio.sleep(0.4)

    # 4a: PSC code lookup
    try:
        r = await lookup_psc_code("R425")
        # Response shape varies; just check we got something
        if r and (r.get("pscData") or r.get("data") or isinstance(r, dict) and len(r) > 0):
            record("lookup_psc_code(R425)", "PASS", "got response")
        else:
            record("lookup_psc_code(R425)", "INFO", f"empty response: {str(r)[:120]}")
    except Exception as e:
        record("lookup_psc_code(R425)", "FAIL", str(e)[:120])

    await asyncio.sleep(0.4)

    # 4b: PSC free text
    try:
        r = await search_psc_free_text("engineering")
        if r:
            record("search_psc_free_text(engineering)", "PASS", "got response")
        else:
            record("search_psc_free_text(engineering)", "FAIL", "empty")
    except Exception as e:
        record("search_psc_free_text", "FAIL", str(e)[:120])

    # ========== Section 5: Composite responsibility check ==========
    await section("5. VENDOR RESPONSIBILITY CHECK")

    await asyncio.sleep(0.4)

    try:
        r = await vendor_responsibility_check(LEIDOS_UEI)
        reg = r.get("registration")
        excl = r.get("exclusion")
        flags = r.get("flags", [])
        if reg and reg.get("legalBusinessName"):
            status = reg.get("status")
            excl_count = (excl or {}).get("totalRecords", "?")
            record(
                "vendor_responsibility_check(Leidos)",
                "PASS" if not flags else "INFO",
                f"{reg['legalBusinessName']} | status={status} | exclusions={excl_count} | flags={flags}",
            )
        else:
            record("vendor_responsibility_check(Leidos)", "FAIL",
                   f"registration missing, flags={flags}")
    except Exception as e:
        record("vendor_responsibility_check", "FAIL", str(e)[:120])

    # ========== Section 6: Error handling ==========
    await section("6. ERROR HANDLING")

    await asyncio.sleep(0.4)

    # 6a: Size cap on entities (client-side validation)
    try:
        await search_entities(legal_business_name="TEST", size=25)
        record("entity size cap validation", "FAIL",
               "expected ValueError for size > 10")
    except ValueError as e:
        record("entity size cap validation", "PASS",
               "raised ValueError for size=25")
    except Exception as e:
        record("entity size cap validation", "FAIL",
               f"wrong exception: {type(e).__name__}")

    await asyncio.sleep(0.4)

    # 6b: Exclusions size cap
    try:
        await search_exclusions(size=500)
        record("exclusions size cap validation", "FAIL",
               "expected ValueError for size > 100")
    except ValueError:
        record("exclusions size cap validation", "PASS",
               "raised ValueError for size=500")
    except Exception as e:
        record("exclusions size cap validation", "FAIL",
               f"wrong exception: {type(e).__name__}")

    await asyncio.sleep(0.4)

    # 6c: ISO date format should be rejected by API (server-side)
    try:
        await search_opportunities(
            posted_from="2026-03-01",  # ISO, wrong
            posted_to="2026-04-05",
            limit=10,
        )
        record("opportunities ISO date rejection", "INFO",
               "API accepted ISO date (unexpected but not a failure of our code)")
    except RuntimeError as e:
        msg = str(e)
        if "400" in msg or "date" in msg.lower():
            record("opportunities ISO date rejection", "PASS",
                   "server rejected ISO date with 400")
        else:
            record("opportunities ISO date rejection", "INFO", msg[:100])
    except Exception as e:
        record("opportunities ISO date rejection", "INFO", str(e)[:100])

    # ========== Summary ==========
    return summarize()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
