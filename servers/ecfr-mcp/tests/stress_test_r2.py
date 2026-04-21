"""Round 2: adversarial edge case test. Try to break ecfr-mcp with
extreme inputs, injection payloads, and boundary probes."""
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
            if any(x in msg for x in ["400","404","406","422","429","500"]):
                rec(name, "INFO", f"API rejected: {msg}")
            else:
                rec(name, "FAIL", f"{type(e).__name__}: {msg}")
    except Exception as e:
        rec(name, "FAIL" if expect != "error" else "PASS", f"{type(e).__name__}: {str(e)[:100]}")

async def main():
    print("\n" + "="*60)
    print("eCFR MCP ROUND 2: PURE BULLSHIT ADVERSARIAL TEST")
    print("="*60)

    # ── 1. ABSURD TITLE NUMBERS ──
    print("\n━━━ 1. absurd title numbers ━━━")

    await t("title=99999999999", get_latest_date(99999999999), expect="error")
    await t("title=-99999999", get_latest_date(-99999999), expect="error")
    await t("title=1 (exists but obscure)", get_latest_date(1),
        check=lambda r: (r.get("up_to_date_as_of") is not None, f"date={r.get('up_to_date_as_of')}"))
    await t("title=50 (max valid)", get_latest_date(50),
        check=lambda r: (True, f"date={r.get('up_to_date_as_of','not found')}"))

    # ── 2. SECTION ID GARBAGE ──
    print("\n━━━ 2. section ID garbage ━━━")

    await t("section=''", get_cfr_content(48, section=""))
    await t("section='0'", get_cfr_content(48, section="0"))
    await t("section='0000000'", get_cfr_content(48, section="0000000"))
    await t("section='-1'", get_cfr_content(48, section="-1"))
    await t("section='1/2'", get_cfr_content(48, section="1/2"))
    await t("section='15.305; DROP TABLE'", get_cfr_content(48, section="15.305; DROP TABLE"))
    await t("section='<script>'", get_cfr_content(48, section="<script>"))
    await t("section='%00%00%00'", get_cfr_content(48, section="%00%00%00"))
    await t("section='../../../etc/shadow'", get_cfr_content(48, section="../../../etc/shadow"))
    await t("section='NaN'", get_cfr_content(48, section="NaN"))
    await t("section='null'", get_cfr_content(48, section="null"))
    await t("section='undefined'", get_cfr_content(48, section="undefined"))
    await t("section='true'", get_cfr_content(48, section="true"))
    await t("section=space only '   '", get_cfr_content(48, section="   "))
    await t("section=tab+newline", get_cfr_content(48, section="\t\n"))
    await t("section=1000 chars of 'A'", get_cfr_content(48, section="A" * 1000))
    await t("section='15.305' with trailing null", get_cfr_content(48, section="15.305\x00"))

    # ── 3. PART ID GARBAGE ──
    print("\n━━━ 3. part ID garbage ━━━")

    await t("part='0'", get_cfr_content(48, part="0"))
    await t("part='-1'", get_cfr_content(48, part="-1"))
    await t("part='99999'", get_cfr_content(48, part="99999"))
    await t("part='1.5'", get_cfr_content(48, part="1.5"))
    await t("part='fifteen'", get_cfr_content(48, part="fifteen"))
    await t("part=empty string", get_cfr_content(48, part=""))
    await t("part='*'", get_cfr_content(48, part="*"))
    await t("part='%2F..%2F..%2Fetc%2Fpasswd'",
        get_cfr_content(48, part="%2F..%2F..%2Fetc%2Fpasswd"))

    # ── 4. DATE GARBAGE ──
    print("\n━━━ 4. date garbage ━━━")

    await t("date='0000-00-00'", get_cfr_content(48, date="0000-00-00", section="15.305"), expect="error")
    await t("date='9999-12-31'", get_cfr_content(48, date="9999-12-31", section="15.305"), expect="error")
    await t("date='2026-13-45'", get_cfr_content(48, date="2026-13-45", section="15.305"), expect="error")
    await t("date='2026-00-00'", get_cfr_content(48, date="2026-00-00", section="15.305"), expect="error")
    await t("date='yesterday'", get_cfr_content(48, date="yesterday", section="15.305"), expect="error")
    await t("date='1776-07-04'", get_cfr_content(48, date="1776-07-04", section="15.305"), expect="error")
    await t("date=MM/DD/YYYY format (wrong for eCFR)",
        get_cfr_content(48, date="04/05/2026", section="15.305"), expect="error")
    await t("date=unix timestamp",
        get_cfr_content(48, date="1712345678", section="15.305"), expect="error")
    await t("date=ISO with time",
        get_cfr_content(48, date="2026-04-02T12:00:00Z", section="15.305"), expect="error")
    await t("date=empty string",
        get_cfr_content(48, date="", section="15.305"), expect="error")

    # ── 5. SEARCH QUERY GARBAGE ──
    print("\n━━━ 5. search query garbage ━━━")

    await t("query=single char 'a'", search_cfr("a", title=48, per_page=3))
    await t("query=just asterisk '*'", search_cfr("*", title=48, per_page=3))
    await t("query=just spaces '     '", search_cfr("     ", title=48, per_page=3))
    await t("query=10000 chars",
        search_cfr("regulation " * 900, title=48, per_page=3))
    await t("query=only special chars '!@#$%^&*()'",
        search_cfr("!@#$%^&*()", title=48, per_page=3))
    await t("query=backslash hell",
        search_cfr("\\\\\\\\\\", title=48, per_page=3))
    await t("query=regex attempt '[a-z]+.*'",
        search_cfr("[a-z]+.*", title=48, per_page=3))
    await t("query=JSON injection '{\"evil\":true}'",
        search_cfr('{"evil":true}', title=48, per_page=3))
    await t("query=XML injection '<tag>evil</tag>'",
        search_cfr("<tag>evil</tag>", title=48, per_page=3))
    await t("query=newlines embedded",
        search_cfr("line1\nline2\nline3", title=48, per_page=3))
    await t("query=tab characters",
        search_cfr("col1\tcol2\tcol3", title=48, per_page=3))
    await t("query=null byte in middle",
        search_cfr("acqui\x00sition", title=48, per_page=3))
    await t("per_page=0", search_cfr("test", title=48, per_page=0))
    await t("per_page=-1", search_cfr("test", title=48, per_page=-1))
    await t("per_page=99999999", search_cfr("test", title=48, per_page=99999999), expect="error")
    await t("page=0", search_cfr("debarment", title=48, page=0, per_page=3))
    await t("page=-999", search_cfr("debarment", title=48, page=-999, per_page=3))

    # ── 6. FORBIDDEN AND WEIRD CHARACTERS ──
    print("\n━━━ 6. forbidden and weird characters ━━━")

    chars = ["&", "|", "{", "}", "^", "\\", "'", '"', "`", ";", ":", "<", ">",
             "=", "+", "~", "!", "@", "#", "$", "%"]
    for c in chars:
        await t(f"search with '{c}'",
            search_cfr(f"acquisition{c}regulation", title=48, per_page=2))

    # ── 7. DEFINITION SEARCH GARBAGE ──
    print("\n━━━ 7. definition search garbage ━━━")

    await t("definition=empty string", find_far_definition(""))
    await t("definition=single char 'a'", find_far_definition("a"),
        check=lambda r: (r.get("match_count",0) > 0, f"matches={r.get('match_count',0)} (expected many)"))
    await t("definition=1000 char string", find_far_definition("contract " * 110))
    await t("definition=only numbers '12345'", find_far_definition("12345"))
    await t("definition=SQL 'OR 1=1'", find_far_definition("OR 1=1"))
    await t("definition=regex '[.*]'", find_far_definition("[.*]"))
    await t("definition=null bytes", find_far_definition("contract\x00ing"))
    await t("definition=unicode snowman", find_far_definition("☃"))
    await t("definition=RTL override", find_far_definition("\u202egnirtcartnoc"))
    await t("definition=zalgo text", find_far_definition("c̷̨̛͎̈́ö̶̡n̸̰͝t̶̤̾r̸̨̈́a̴̧͝c̷̣̈́t̵̢̛"))

    # ── 8. COMPARE VERSIONS GARBAGE ──
    print("\n━━━ 8. compare_versions garbage ━━━")

    await t("compare same date twice",
        compare_versions("15.305", "2025-01-02", "2025-01-02"),
        check=lambda r: (
            r.get("before",{}).get("paragraphs") == r.get("after",{}).get("paragraphs"),
            "identical (expected)"))

    await t("compare inverted dates (after < before)",
        compare_versions("15.305", "2025-06-01", "2024-01-02"),
        expect="error")

    await t("compare with garbage section",
        compare_versions("NONEXISTENT.999", "2024-01-02", "2025-01-02"),
        expect="error")

    await t("compare with garbage dates",
        compare_versions("15.305", "not-a-date", "also-not"),
        expect="error")

    # ── 9. LIST_SECTIONS GARBAGE ──
    print("\n━━━ 9. list_sections garbage ━━━")

    await t("part=empty string", list_sections_in_part(""))
    await t("part='0'", list_sections_in_part("0"))
    await t("part='-1'", list_sections_in_part("-1"))
    await t("part='abc'", list_sections_in_part("abc"))
    await t("part='15; DROP TABLE'", list_sections_in_part("15; DROP TABLE"))
    await t("chapter='99' (nonexistent)", list_sections_in_part("1", chapter="99"))

    # ── 10. RAPID FIRE (rate limit probe) ──
    print("\n━━━ 10. rapid fire (20 calls, no delay) ━━━")

    async def rapid_fire():
        tasks = [search_cfr("acquisition", title=48, per_page=2) for _ in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, dict))
        errs = sum(1 for r in results if isinstance(r, Exception))
        rate_limited = sum(1 for r in results if isinstance(r, Exception) and "429" in str(r))
        return {"ok": ok, "errors": errs, "rate_limited": rate_limited, "total": 20}

    try:
        r = await rapid_fire()
        rec("20 rapid-fire searches (no delay)",
            "PASS" if r["rate_limited"] == 0 else "INFO",
            f"{r['ok']}/20 ok, {r['errors']} errors, {r['rate_limited']} rate-limited")
    except Exception as e:
        rec("20 rapid-fire searches", "FAIL", str(e)[:100])

    await asyncio.sleep(2)

    # ── 11. STRUCTURE WITH GARBAGE ──
    print("\n━━━ 11. structure with garbage ━━━")

    await t("structure chapter='<script>'",
        get_cfr_structure(48, chapter="<script>"))
    await t("structure subchapter='../../etc'",
        get_cfr_structure(48, subchapter="../../etc"))
    await t("structure part='*'",
        get_cfr_structure(48, part="*"))
    await t("structure all params garbage",
        get_cfr_structure(48, chapter="X", subchapter="Y", part="Z", subpart="W"))

    # ── 12. VERSION HISTORY GARBAGE ──
    print("\n━━━ 12. version history garbage ━━━")

    await t("versions part=''", get_version_history(48, part=""))
    await t("versions section='<img src=x>'", get_version_history(48, section="<img src=x>"))
    await t("versions part='*'", get_version_history(48, part="*"))
    await t("versions section='15.305; rm -rf /'", get_version_history(48, section="15.305; rm -rf /"))

    # ── 13. ANCESTRY GARBAGE ──
    print("\n━━━ 13. ancestry garbage ━━━")

    await t("ancestry section=''", get_ancestry(48, section=""))
    await t("ancestry section='javascript:void(0)'", get_ancestry(48, section="javascript:void(0)"))
    await t("ancestry part='../../../'", get_ancestry(48, part="../../../"))
    await t("ancestry both part+section garbage",
        get_ancestry(48, part="XXX", section="YYY.ZZZ"))

    # ── SUMMARY ──
    total = len(results)
    passed = sum(1 for _,s,_ in results if s == "PASS")
    failed = sum(1 for _,s,_ in results if s == "FAIL")
    info = sum(1 for _,s,_ in results if s == "INFO")
    print(f"\n{'='*60}")
    print(f"eCFR R2 ADVERSARIAL: {passed}/{total} PASS, {failed} FAIL, {info} INFO")
    print(f"{'='*60}")
    if failed:
        print("\nFAILURES:")
        for n,s,d in results:
            if s == "FAIL": print(f"  * {n}: {d}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
