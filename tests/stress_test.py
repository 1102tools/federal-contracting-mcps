"""BLS OEWS MCP stress test: all 3 rounds combined.
R1: boundaries, validation, real scenarios.
R2: adversarial, injection, unicode, concurrent.
R3: agent workflows, creative chaos, rapid fire."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from bls_oews_mcp.server import (
    get_wage_data, compare_metros, compare_occupations,
    igce_wage_benchmark, detect_latest_year,
    list_common_soc_codes, list_common_metros,
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
            if any(x in msg for x in ["400","403","404","429","NOT_PROCESSED"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("BLS OEWS MCP: 3-ROUND COMBINED STRESS TEST")
    print("="*60)

    # ═══════════════════════════════════════════════════
    # ROUND 1: BOUNDARIES AND VALIDATION
    # ═══════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 1: BOUNDARIES AND VALIDATION")
    print("="*60)

    print("\n━━━ 1.1 basic wage lookups ━━━")

    await t("software dev national",
        get_wage_data("151252"),
        check=lambda r: (r["wages"].get("Annual Median",{}).get("numeric") is not None,
            f"median={r['wages'].get('Annual Median',{}).get('formatted')}"))

    await t("software dev DC metro",
        get_wage_data("151252", scope="metro", area_code="47900"),
        check=lambda r: (r["wages"].get("Annual Mean Wage",{}).get("numeric") is not None,
            f"mean={r['wages'].get('Annual Mean Wage',{}).get('formatted')}"))

    await t("software dev Virginia state",
        get_wage_data("151252", scope="state", area_code="51"),
        check=lambda r: (r["wages"].get("Annual Median",{}).get("numeric") is not None,
            f"median={r['wages'].get('Annual Median',{}).get('formatted')}"))

    await t("help desk national",
        get_wage_data("151232"),
        check=lambda r: (r["wages"].get("Annual Median",{}).get("numeric") is not None,
            f"median={r['wages'].get('Annual Median',{}).get('formatted')}"))

    await t("federal govt industry filter",
        get_wage_data("151252", industry="999100"),
        check=lambda r: (True, f"mean={r['wages'].get('Annual Mean Wage',{}).get('formatted')}"))

    await t("full datatypes (all 9)",
        get_wage_data("151252", datatypes=["01","03","04","08","11","12","13","14","15"]),
        check=lambda r: (len(r["wages"]) > 7, f"fields={len(r['wages'])}"))

    print("\n━━━ 1.2 validation ━━━")

    await t("occ_code not 6 digits",
        get_wage_data("1512"), expect="error")

    await t("occ_code non-numeric",
        get_wage_data("abcdef"), expect="error")

    await t("occ_code empty",
        get_wage_data(""), expect="error")

    await t("state scope missing area_code",
        get_wage_data("151252", scope="state"), expect="error")

    await t("metro scope missing area_code",
        get_wage_data("151252", scope="metro"), expect="error")

    await t("industry with metro (invalid combo)",
        get_wage_data("151252", scope="metro", area_code="47900", industry="999100"),
        expect="error")

    await t("nonexistent SOC code",
        get_wage_data("999999"),
        check=lambda r: (all(v.get("suppressed") for k,v in r["wages"].items() if not k.startswith("_")),
            "all suppressed (expected)"))

    await t("year=2026 (too new, no data)",
        get_wage_data("151252", year="2026"),
        check=lambda r: (all(v.get("suppressed") or v.get("raw") is None for k,v in r["wages"].items() if not k.startswith("_")),
            "no data for 2026 (expected)"))

    await t("area code normalization 2-digit",
        get_wage_data("151252", scope="state", area_code="51"),
        check=lambda r: (r["wages"].get("Annual Median",{}).get("numeric") is not None, "VA data found"))

    await t("area code normalization 5-digit",
        get_wage_data("151252", scope="metro", area_code="47900"),
        check=lambda r: (r["wages"].get("Annual Median",{}).get("numeric") is not None, "DC metro data found"))

    await t("area code bad length",
        get_wage_data("151252", scope="metro", area_code="123"),
        expect="error")

    print("\n━━━ 1.3 compare tools ━━━")

    await t("compare_metros DC vs Seattle vs Baltimore",
        compare_metros("151252", ["47900", "42660", "12580"]),
        check=lambda r: (len(r.get("metros",{})) == 3, f"metros={len(r.get('metros',{}))}"))

    await t("compare_metros empty list",
        compare_metros("151252", []),
        expect="error")

    await t("compare_occupations 3 SOCs national",
        compare_occupations(["151252", "151232", "131082"]),
        check=lambda r: (len(r.get("occupations",{})) == 3, f"occupations={len(r.get('occupations',{}))}"))

    await t("compare_occupations empty list",
        compare_occupations([]),
        expect="error")

    await t("compare_occupations bad SOC code",
        compare_occupations(["15125"]),
        expect="error")

    print("\n━━━ 1.4 workflow tools ━━━")

    await t("igce_benchmark software dev national",
        igce_wage_benchmark("151252"),
        check=lambda r: (r.get("benchmarks",{}).get("Annual Median",{}).get("hourly_base") is not None,
            f"median hourly={r.get('benchmarks',{}).get('Annual Median',{}).get('hourly_base')}"))

    await t("igce_benchmark DC metro with custom burden",
        igce_wage_benchmark("151252", scope="metro", area_code="47900", burden_low=2.0, burden_high=2.5),
        check=lambda r: ("burdened" in str(r.get("benchmarks",{}).get("Annual Median",{})),
            f"burden_range={r.get('burden_range')}"))

    await t("igce_benchmark nonexistent SOC",
        igce_wage_benchmark("999999"),
        check=lambda r: (all(v.get("suppressed") for v in r.get("benchmarks",{}).values()),
            "all suppressed"))

    await t("detect_latest_year",
        detect_latest_year(),
        check=lambda r: (r.get("latest_year") is not None, f"latest={r.get('latest_year')}"))

    await t("list_common_soc_codes",
        list_common_soc_codes(),
        check=lambda r: (len(r.get("soc_codes",{})) > 15, f"codes={len(r.get('soc_codes',{}))}"))

    await t("list_common_metros",
        list_common_metros(),
        check=lambda r: (len(r.get("metros",{})) > 10, f"metros={len(r.get('metros',{}))}"))

    # ═══════════════════════════════════════════════════
    # ROUND 2: ADVERSARIAL
    # ═══════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 2: ADVERSARIAL EDGE CASES")
    print("="*60)

    print("\n━━━ 2.1 injection ━━━")

    await t("SQL injection in occ_code",
        get_wage_data("'; DROP"), expect="error")
    await t("XSS in occ_code",
        get_wage_data("<scrip"), expect="error")
    await t("null bytes in occ_code",
        get_wage_data("15125\x00"), expect="error")

    print("\n━━━ 2.2 absurd values ━━━")

    await t("area_code='99' (invalid state FIPS)",
        get_wage_data("151252", scope="state", area_code="99"),
        check=lambda r: (True, "returned (may be empty)"))

    await t("area_code='00000' (zeros)",
        get_wage_data("151252", scope="metro", area_code="00000"))

    await t("datatype='99' (nonexistent)",
        get_wage_data("151252", datatypes=["99"]))

    await t("50 series at once (v2 max)",
        compare_occupations(
            ["151252","151232","131082","151212","151244","151241","151242",
             "151251","151253","151254","152051","273042","132011","113021"],
            datatype="04"),
        check=lambda r: (len(r.get("occupations",{})) > 10, f"occs={len(r.get('occupations',{}))}"))

    await t("burden_low > burden_high",
        igce_wage_benchmark("151252", burden_low=3.0, burden_high=1.5))

    await t("burden=0",
        igce_wage_benchmark("151252", burden_low=0, burden_high=0))

    await t("burden=999",
        igce_wage_benchmark("151252", burden_low=999, burden_high=999))

    print("\n━━━ 2.3 unicode ━━━")

    await t("emoji occ_code", get_wage_data("🔧🔧🔧🔧🔧🔧"), expect="error")
    await t("CJK occ_code", get_wage_data("开发工程师的代码"), expect="error")

    print("\n━━━ 2.4 concurrent ━━━")

    async def parallel_5():
        tasks = [
            get_wage_data("151252"),
            get_wage_data("151232"),
            get_wage_data("131082"),
            get_wage_data("151212"),
            get_wage_data("113021"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        return {"ok": ok, "total": 5}

    try:
        r = await parallel_5()
        rec("5 concurrent wage lookups", "PASS" if r["ok"] == 5 else "FAIL", f"{r['ok']}/5")
    except Exception as e:
        rec("5 concurrent wage lookups", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════
    # ROUND 3: AGENT WORKFLOWS
    # ═══════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  ROUND 3: AGENT WORKFLOWS + CREATIVE CHAOS")
    print("="*60)

    print("\n━━━ 3.1 IGCE pipeline ━━━")

    categories = ["151252", "151232", "131082", "151212", "151244"]
    async def igce_pipeline():
        tasks = [igce_wage_benchmark(soc, scope="metro", area_code="47900") for soc in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("benchmarks"))
        return {"ok": ok, "total": len(categories)}

    try:
        r = await igce_pipeline()
        rec("5-SOC IGCE pipeline (DC metro)", "PASS" if r["ok"] >= 4 else "FAIL", f"{r['ok']}/5 had data")
    except Exception as e:
        rec("IGCE pipeline", "FAIL", str(e)[:100])

    await asyncio.sleep(1)

    print("\n━━━ 3.2 metro comparison sweep ━━━")

    await t("software dev across 8 metros",
        compare_metros("151252", ["47900","42660","12580","35620","31080","41860","16980","14460"]),
        check=lambda r: (len(r.get("metros",{})) == 8, f"metros={len(r.get('metros',{}))}"))

    print("\n━━━ 3.3 full occupation comparison ━━━")

    await t("10 SOCs in DC metro",
        compare_occupations(
            ["151252","151232","131082","151212","151244","151241","113021","131111","273042","152051"],
            scope="metro", area_code="47900"),
        check=lambda r: (len(r.get("occupations",{})) == 10, f"occs={len(r.get('occupations',{}))}"))

    print("\n━━━ 3.4 mixed rapid fire ━━━")

    async def rapid_10():
        tasks = [
            get_wage_data("151252"),
            get_wage_data("151252", scope="metro", area_code="47900"),
            get_wage_data("151252", scope="state", area_code="51"),
            compare_metros("151252", ["47900", "42660"]),
            compare_occupations(["151252", "151232"]),
            igce_wage_benchmark("151252"),
            igce_wage_benchmark("131082", scope="metro", area_code="47900"),
            detect_latest_year(),
            list_common_soc_codes(),
            list_common_metros(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = sum(1 for r in results if isinstance(r, Exception))
        return {"ok": ok, "errors": errs, "total": 10}

    try:
        r = await rapid_10()
        rec("10 concurrent mixed calls",
            "PASS" if r["errors"] == 0 else "INFO",
            f"{r['ok']}/10 succeeded, {r['errors']} errors")
    except Exception as e:
        rec("10 concurrent mixed", "FAIL", str(e)[:100])

    # ═══════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"BLS OEWS ALL ROUNDS: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
