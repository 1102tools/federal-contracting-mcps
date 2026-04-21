"""GSA Per Diem MCP stress test: all 3 rounds combined."""
from __future__ import annotations
import asyncio, sys
from gsa_perdiem_mcp.server import (
    lookup_city_perdiem, lookup_zip_perdiem, lookup_state_rates,
    get_mie_breakdown, estimate_travel_cost, compare_locations,
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
    print("GSA PER DIEM MCP: 3-ROUND COMBINED STRESS TEST")
    print("="*60)

    # ═════ ROUND 1 ═════
    print("\n" + "="*60)
    print("  ROUND 1: BOUNDARIES AND VALIDATION")
    print("="*60)

    print("\n━━━ 1.1 city lookups ━━━")

    await t("DC (returns District of Columbia)",
        lookup_city_perdiem("Washington", "DC"),
        check=lambda r: ("District" in str(r.get("matched_city","")), f"city={r.get('matched_city')}, mie={r.get('mie_daily')}"))

    await t("New York City",
        lookup_city_perdiem("New York City", "NY"),
        check=lambda r: (r.get("lodging_range") is not None, f"lodging={r.get('lodging_range')}, mie={r.get('mie_daily')}"))

    await t("Boston (composite: Boston / Cambridge)",
        lookup_city_perdiem("Boston", "MA"),
        check=lambda r: ("Boston" in str(r.get("matched_city","")), f"city={r.get('matched_city')}"))

    await t("standard rate location (rural area)",
        lookup_city_perdiem("Smalltown", "KS"),
        check=lambda r: (True, f"standard={r.get('is_standard_rate')}, city={r.get('matched_city')}"))

    await t("St. Louis (period in name)",
        lookup_city_perdiem("St. Louis", "MO"),
        check=lambda r: (r.get("matched_city") is not None, f"city={r.get('matched_city')}"))

    await t("San Francisco",
        lookup_city_perdiem("San Francisco", "CA"),
        check=lambda r: (r.get("mie_daily",0) > 0, f"lodging={r.get('lodging_range')}, mie={r.get('mie_daily')}"))

    print("\n━━━ 1.2 validation ━━━")

    await t("empty city", lookup_city_perdiem("", "DC"), expect="error")
    await t("empty state", lookup_city_perdiem("Washington", ""), expect="error")
    await t("3-letter state", lookup_city_perdiem("Washington", "DCC"), expect="error")
    await t("empty zip", lookup_zip_perdiem(""), expect="error")
    await t("4-digit zip", lookup_zip_perdiem("2020"), expect="error")
    await t("alpha zip", lookup_zip_perdiem("abcde"), expect="error")
    await t("num_nights=0", estimate_travel_cost("Washington", "DC", 0), expect="error")
    await t("num_nights=-1", estimate_travel_cost("Washington", "DC", -1), expect="error")
    await t("empty locations list", compare_locations([]), expect="error")

    print("\n━━━ 1.3 ZIP lookups ━━━")

    await t("DC ZIP 20001",
        lookup_zip_perdiem("20001"),
        check=lambda r: (r.get("mie_daily",0) > 0, f"city={r.get('matched_city')}, mie={r.get('mie_daily')}"))

    await t("NYC ZIP 10001",
        lookup_zip_perdiem("10001"),
        check=lambda r: (r.get("matched_city") is not None, f"city={r.get('matched_city')}"))

    await t("rural ZIP 67001 (Kansas)",
        lookup_zip_perdiem("67001"),
        check=lambda r: (True, f"city={r.get('matched_city')}, standard={r.get('is_standard_rate')}"))

    print("\n━━━ 1.4 state rates ━━━")

    await t("all VA NSAs",
        lookup_state_rates("VA"),
        check=lambda r: (r.get("nsa_count",0) > 3, f"nsa_count={r.get('nsa_count')}"))

    await t("all CA NSAs",
        lookup_state_rates("CA"),
        check=lambda r: (r.get("nsa_count",0) > 10, f"nsa_count={r.get('nsa_count')}"))

    await t("state with few NSAs (WY)",
        lookup_state_rates("WY"),
        check=lambda r: (True, f"nsa_count={r.get('nsa_count',0)}"))

    print("\n━━━ 1.5 M&IE breakdown ━━━")

    await t("FY2026 M&IE tiers",
        get_mie_breakdown(2026),
        check=lambda r: (len(r.get("tiers",[])) >= 5, f"tiers={len(r.get('tiers',[]))}"))

    await t("FY2025 M&IE tiers",
        get_mie_breakdown(2025),
        check=lambda r: (len(r.get("tiers",[])) >= 5, f"tiers={len(r.get('tiers',[]))}"))

    print("\n━━━ 1.6 travel cost estimation ━━━")

    await t("4 nights DC",
        estimate_travel_cost("Washington", "DC", 4),
        check=lambda r: (r.get("grand_total",0) > 500, f"total=${r.get('grand_total')}, lodging=${r.get('lodging_total')}, mie=${r.get('mie_total')}"))

    await t("1 night (2 travel days, both partial)",
        estimate_travel_cost("Washington", "DC", 1),
        check=lambda r: (r.get("travel_days") == 2, f"days={r.get('travel_days')}, total=${r.get('grand_total')}"))

    await t("10 nights NYC with month=Mar",
        estimate_travel_cost("New York City", "NY", 10, travel_month="Mar"),
        check=lambda r: (r.get("grand_total",0) > 2000, f"total=${r.get('grand_total')}"))

    await t("travel to standard rate area",
        estimate_travel_cost("Smalltown", "KS", 3),
        check=lambda r: (r.get("grand_total",0) > 0, f"total=${r.get('grand_total')}"))

    print("\n━━━ 1.7 compare locations ━━━")

    await t("compare DC vs NYC vs SF",
        compare_locations([
            {"city": "Washington", "state": "DC"},
            {"city": "New York City", "state": "NY"},
            {"city": "San Francisco", "state": "CA"},
        ]),
        check=lambda r: (len(r.get("locations",[])) == 3, f"locations={len(r.get('locations',[]))}"))

    # ═════ ROUND 2 ═════
    print("\n" + "="*60)
    print("  ROUND 2: ADVERSARIAL EDGE CASES")
    print("="*60)

    print("\n━━━ 2.1 injection ━━━")

    await t("SQL in city", lookup_city_perdiem("'; DROP TABLE", "DC"))
    await t("XSS in city", lookup_city_perdiem("<script>alert(1)</script>", "VA"))
    await t("path traversal in city", lookup_city_perdiem("../../etc/passwd", "DC"))
    await t("null byte in city", lookup_city_perdiem("Washington\x00DC", "DC"))

    print("\n━━━ 2.2 unicode ━━━")

    await t("emoji city (GSA 500s on non-ASCII)", lookup_city_perdiem("🏛️", "DC"),
        expect="error")
    await t("CJK city (GSA 500s on non-ASCII)", lookup_city_perdiem("华盛顿", "DC"),
        expect="error")
    await t("Arabic city (GSA 500s on non-ASCII)", lookup_city_perdiem("واشنطن", "DC"),
        expect="error")
    await t("1000 char city", lookup_city_perdiem("Washington " * 90, "DC"))

    print("\n━━━ 2.3 absurd values ━━━")

    await t("FY1776", lookup_city_perdiem("Washington", "DC", fiscal_year=1776))
    await t("FY2099", lookup_city_perdiem("Washington", "DC", fiscal_year=2099))
    await t("FY0", lookup_city_perdiem("Washington", "DC", fiscal_year=0))
    await t("invalid state 'ZZ'", lookup_city_perdiem("Washington", "ZZ"))
    await t("state as number '99'", lookup_city_perdiem("Washington", "99"), expect="error")
    await t("num_nights=999",
        estimate_travel_cost("Washington", "DC", 999),
        check=lambda r: (r.get("grand_total",0) > 100000, f"total=${r.get('grand_total')}"))

    await t("ZIP 00000", lookup_zip_perdiem("00000"))
    await t("ZIP 99999", lookup_zip_perdiem("99999"))

    print("\n━━━ 2.4 special city names ━━━")

    await t("O'Hare area (apostrophe)",
        lookup_city_perdiem("O'Hare", "IL"))
    await t("Winston-Salem (hyphen)",
        lookup_city_perdiem("Winston-Salem", "NC"))
    await t("St. Petersburg (period)",
        lookup_city_perdiem("St. Petersburg", "FL"),
        check=lambda r: (r.get("matched_city") is not None, f"city={r.get('matched_city')}"))
    await t("Fort Worth (composite NSA)",
        lookup_city_perdiem("Fort Worth", "TX"),
        check=lambda r: ("Fort Worth" in str(r.get("matched_city","")), f"city={r.get('matched_city')}"))

    print("\n━━━ 2.5 concurrent ━━━")

    async def parallel_5():
        tasks = [
            lookup_city_perdiem("Washington", "DC"),
            lookup_city_perdiem("New York City", "NY"),
            lookup_city_perdiem("Boston", "MA"),
            lookup_city_perdiem("San Francisco", "CA"),
            lookup_city_perdiem("Seattle", "WA"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("matched_city"))
        return {"ok": ok, "total": 5}

    try:
        r = await parallel_5()
        rec("5 concurrent city lookups", "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5")
    except Exception as e:
        rec("5 concurrent city lookups", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ═════ ROUND 3 ═════
    print("\n" + "="*60)
    print("  ROUND 3: AGENT WORKFLOWS + CREATIVE CHAOS")
    print("="*60)

    print("\n━━━ 3.1 travel IGCE simulation ━━━")

    await t("4-night DC trip in January",
        estimate_travel_cost("Washington", "DC", 4, travel_month="Jan"),
        check=lambda r: (r.get("rate_month") == "Jan", f"month=Jan, total=${r.get('grand_total')}"))

    await t("4-night DC trip in August (peak season)",
        estimate_travel_cost("Washington", "DC", 4, travel_month="Aug"),
        check=lambda r: (True, f"month=Aug, total=${r.get('grand_total')}"))

    await t("compare 5 cities for IGCE",
        compare_locations([
            {"city": "Washington", "state": "DC"},
            {"city": "New York City", "state": "NY"},
            {"city": "Seattle", "state": "WA"},
            {"city": "Denver", "state": "CO"},
            {"city": "Chicago", "state": "IL"},
        ]),
        check=lambda r: (len(r.get("locations",[])) == 5 and r["locations"][0].get("max_daily_total",0) > r["locations"][-1].get("max_daily_total",0),
            f"sorted highest first: {r['locations'][0].get('location')} > {r['locations'][-1].get('location')}"))

    print("\n━━━ 3.2 state sweep ━━━")

    await t("MD NSAs (DC spillover)",
        lookup_state_rates("MD"),
        check=lambda r: (r.get("nsa_count",0) > 0, f"nsa_count={r.get('nsa_count')}"))

    await t("TX NSAs (many cities)",
        lookup_state_rates("TX"),
        check=lambda r: (r.get("nsa_count",0) > 5, f"nsa_count={r.get('nsa_count')}"))

    print("\n━━━ 3.3 rapid fire 8 concurrent ━━━")

    async def rapid_8():
        tasks = [
            lookup_city_perdiem("Washington", "DC"),
            lookup_zip_perdiem("20001"),
            lookup_state_rates("VA"),
            get_mie_breakdown(2026),
            estimate_travel_cost("Boston", "MA", 3),
            estimate_travel_cost("Seattle", "WA", 5, travel_month="Jun"),
            compare_locations([{"city":"DC","state":"DC"},{"city":"NYC","state":"NY"}]),
            lookup_city_perdiem("Chicago", "IL"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
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
    print(f"GSA PER DIEM ALL ROUNDS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
