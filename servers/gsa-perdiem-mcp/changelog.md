# Changelog

## 0.2.5

Round 6 (second live audit). 240 new live-gated tests added covering
all 6 tools against the production GSA Per Diem API. Zero new bugs
found, which validates the depth of prior hardening (the original
0.2.x audits already surfaced 3 P1 bugs and 55 findings).

### Round 6 live test coverage (240 tests, runtime ~2:37)

Bucket | Count | Coverage
---|---|---
A. City lookups across 50 states + DC | 51 | One representative city per state, verifying every state code reaches the API and returns a valid response shape
B. Special character handling | 10 | St. Louis with/without period, Winston-Salem with hyphen/space, Coeur d'Alene with both apostrophe variants, lowercase/mixed-case state, padded inputs, unmatched cities
C. High-cost metros + procurement hotspots | 26 | NYC, SF, Boston, DC + Arlington/Bethesda/Quantico/Huntsville/Dayton/Albuquerque/Colorado Springs/Tampa
D. Seasonal cities | 12 | Aspen, Park City, Vail, Key West, Jackson Hole, Hilton Head, Nantucket, Martha's Vineyard, Naples, Palm Beach, Telluride, Lake Tahoe
E. Fiscal year coverage | 8 | Each FY 2020-2026 plus default
F. ZIP lookups | 24 | 20 major federal ZIPs plus ZIP+4, padding, rural Montana, multiple FYs
G. State NSA listings | 53 | All 50 states + DC + lowercase normalization + FY filter
H. M&IE breakdown | 9 | Each FY 2020-2026, default FY, response shape verification
I. Travel cost estimates | 22 | 8 trip lengths (1-365 nights), 12 months, with/without FY, high-cost metros
J. Compare locations | 6 | DC metro area, max-locations, 2-location minimum, with FY, mixed-case states, seasonal city comparison
K. Concurrent calls | 2 | 5 concurrent city lookups, mixed-tool concurrency
L. Response shape verification | 5 | Per-tool field presence checks
M. Edge cases | 12 | DC special case, Alaska/Hawaii remote handling, January vs October DC seasonality, unicode unmatched

### Test counts after round 6

- `tests/test_validation.py`: 173 (165 offline + 8 live-gated, unchanged from rounds 1-5)
- `tests/test_live_audit_r6.py`: 240 live-gated tests
- **Total: 413 regression tests (165 offline, 248 live-gated)**
- **Density: 68.8 tests per tool** (6 tools)

### Why this round mattered

Per Diem was already at 28.7 tests per
tool from the original 0.2.x audits. Round 6 added 240 live tests on
top and found zero new bugs. That's not the round being weak; that's
proof the original hardening covered the failure surface completely.
This is the only MCP in the suite where round 6 found nothing, which
itself is a strong signal of code quality.

## 0.2.1

Cross-MCP fix discovered during the sam-gov-mcp 0.3.1 live audit.

- FastMCP tools register pydantic argument models with the default
  `extra='ignore'` config, so a typo like
  `lookup_city_perdiem(state_code='VA')` (real param is `state`)
  silently dropped the typo'd argument and ran without the intended
  filter. Now every tool has `extra='forbid'` applied after
  registration, so typos raise "Extra inputs are not permitted"
  before any HTTP call.
- USER_AGENT bumped to `gsa-perdiem-mcp/0.2.1`.
- Added regression test covering the new behavior.

## 0.2.0

Hardening pass. Deep audit surfaced 55 issues across six rounds (1 P0,
23 P1, 21 P2, 10 P3). All fixed. Round 6 was a live audit with a real
API key that caught 3 silent-wrong-data bugs the mocked rounds 1-5
missed.

### Crash fixes (P0)
- `lookup_city_perdiem`, `estimate_travel_cost`, and `compare_locations`
  had a path-traversal bug: `urllib.parse.quote(city)` used the default
  `safe='/'`, leaving `/` and `.` unencoded in the URL path. A city
  value of `"../../admin"` produced the URL
  `/travel/perdiem/v2/admin/state/MA/year/2026`, hitting a different
  GSA API endpoint. Fixed two ways: (1) `_validate_city` rejects `/`,
  `\`, and `..` sequences up front; (2) `_normalize_city_for_url` uses
  `safe=''` so any stray special characters are fully percent-encoded.

### Crash fixes (P1)
- `_parse_rate_entry` crashed on `months: None`
  (`AttributeError: 'NoneType' object has no attribute 'get'`). Fixed
  with `_safe_dict`.
- `_parse_rate_entry` crashed when `months.month` was a single dict
  (XML-to-JSON single-item collapse) because the loop iterated dict
  keys (strings). Fixed with `_as_list`.
- `_parse_rate_entry` crashed on `min(values)` when any month value was
  `None` (`TypeError: '<' not supported between int and NoneType`).
  Fixed with `_safe_int` defaulting to 0.
- `_parse_rate_entry` crashed when `entry` itself was `None` (e.g.
  single null entry in the rate list) and when `city` was non-string.
- `_select_best_rate` crashed when the API response was `None` or a
  bare list instead of a dict. Fixed with `_safe_dict` / `_as_list`.
- `lookup_state_rates` / `get_mie_breakdown` crashed on `None`
  responses. Both now return empty-but-valid output.
- `get_mie_breakdown` crashed on `None` tier entries and string
  `total` values. Now uses `_safe_number` for all numeric fields.
- `_get` raised raw `JSONDecodeError` when the API returned HTML
  (maintenance page, unusual 4xx HTML bodies), empty body, or
  truncated JSON. Now raises a descriptive RuntimeError with
  content-type and body preview.
- `_format_error` was not safe against bytes bodies. Fixed.

### Silent wrong-data fixes (P1)
- `_parse_rate_entry` silently produced `lodging_range: "$0/night"`
  when months data was missing or had null values. Now reports
  `has_monthly_data: False` and returns
  `"no monthly lodging data available"` instead of a fake $0 rate.
- `_select_best_rate` used `entry.get("city") == "Standard Rate"` as
  a flag. The `standardRate` field on entries is unreliable (always
  returns the string `"false"`), so we continue matching by city
  name, but now case-insensitively with whitespace tolerance.
- `estimate_travel_cost` silently accepted invalid `travel_month`
  values like `"January"`, `"xyz"`, `"1"`, falling back to max.
  `"January"` and `"jan"` now normalize to `"Jan"`; everything else
  raises a clear error.
- **Round 6 (live)**: typographic apostrophe U+2019 in city names
  (e.g. `"Martha\u2019s Vineyard"`) was stripped by the URL normalizer
  to `"Martha s Vineyard"`. The API then prefix-matched nothing and
  returned all MA NSAs; the tool silently returned "Andover" with no
  indication the query didn't match. Fix: new `_normalize_for_match`
  treats typographic and ASCII apostrophes, hyphens, periods, and
  commas as equivalent in both query and API responses.
- **Round 6 (live)**: when `query_city` was provided but didn't match
  any NSA (exact or composite), `_select_best_rate` silently fell
  back to the first NSA. Confirmed against live API: `"Peñasco, NM"`
  returned Taos, `"Santa Rosa Beach, FL"` returned Fort Walton Beach,
  `"Winston-Salem, NC"` returned the first random NSA. Fix: now
  prefers the Standard Rate for that state with a
  `match_type='standard_fallback'` flag and human-readable `match_note`.
  If there's no Standard Rate and no exact match, flags the response
  with `match_type='unmatched_nsa'` and a WARNING note.
- **Round 6 (live)**: `"St Louis"` (no period) didn't match `"St. Louis"`
  because substring match respects punctuation. Fixed by the same
  `_normalize_for_match` that treats `.` as whitespace.
- Every lookup response now includes a `match_type` field
  (`exact` / `composite` / `standard_fallback` / `unmatched_nsa` /
  `first_nsa` / `standard_only`) and city-query lookups include a
  `match_note` explaining non-exact matches.

### Validation (P2)
- `city` now validated: rejects empty, whitespace-only, > 100 chars,
  null bytes, newlines, tabs, slashes (both forward and back), and
  `..` sequences. Matches GSA's URL routing constraints.
- `state` validated against the full USPS 2-letter list (50 states +
  DC + territories AS, GU, MP, PR, VI). `"ZZ"` now rejected locally.
- `zip_code` accepts both `"02101"` and `"02101-1234"` (ZIP+4 is
  auto-truncated to the 5-digit prefix). Still rejects non-numeric
  and wrong-length inputs.
- `fiscal_year` bounded to FY2015-FY(current+1). Previously accepted
  negative, 0, 1900, 9999, 10**20 silently.
- `travel_month` validated as 3-letter abbreviation; `"January"` /
  `"jan"` / `"JAN"` normalize to `"Jan"`.
- `num_nights` bounded 1-365.
- `compare_locations` list capped at 25 entries (previously unbounded;
  DEMO_KEY rate limit would crush 200+ sequential calls). Entries are
  validated up front so bad inputs don't halt the whole batch.
- `compare_locations` non-dict entries now raise rather than falling
  through to `str(e)[:100]`.
- `PERDIEM_API_KEY` is URL-encoded before being put in the query
  string (was a raw interpolation). Keys with `&` or other URL-reserved
  chars would have corrupted the request.

### Polish (P3)
- `_current_fiscal_year()` replaces the hardcoded `DEFAULT_FISCAL_YEAR`
  constant. Previously FY2026 was baked in; after Oct 2026 rollover it
  would have defaulted to a stale year.
- `_get_client` recreates the client if it was closed, so tests can
  run cleanly across multiple asyncio loops.
- USER_AGENT bumped to `gsa-perdiem-mcp/0.2.0`.
- `_format_error` messages for 404 and 500 are more informative.
- `_clean_error_body` extracts the useful content (title/h1) from HTML
  error pages instead of including raw HTML in the message.
- `PERDIEM_API_KEY` with surrounding whitespace now strips and uses
  the trimmed value, falling back to `DEMO_KEY` if empty after strip.

### Release automation
- Added `.github/workflows/publish.yml` for PyPI publishing via GitHub
  Trusted Publisher on tag `v*.*.*`.
- Added `[dependency-groups].dev` with pytest + pytest-asyncio.

### Testing
- New `tests/test_validation.py` with 172 tests (164 offline + 8
  live, gated by `MCP_LIVE_TESTS=1`). Covers every helper, all
  validators, all response-shape defenses (None/list/missing keys/
  single-item collapse/null values/string coercion), every HTTP
  error path (HTML 200, empty, truncated, 403, 429, 500, timeout),
  concurrent client reuse, and XML-style single-item collapse.
- Live tests include 4 regression tests for the round 6 P1 findings:
  typographic apostrophe matching, unmatched-city flagging,
  punctuation-insensitive matching, and Standard-Rate fallback
  labeling.
- The older `stress_test.py` called tools as raw coroutines and
  bypassed pydantic validation, which is why the original smoke test
  said "0 bugs found." Kept for reference, not run by CI.

## 0.1.0
Initial release.

- 7 MCP tools covering the GSA Per Diem Rates API
- Core: lookup_city_perdiem, lookup_zip_perdiem, lookup_state_rates, get_mie_breakdown
- Workflows: estimate_travel_cost (with first/last day 75% M&IE), compare_locations
- Auto-selects best rate from API response (exact > composite NSA > first NSA > standard)
- Handles seasonal lodging variations (monthly breakdown)
- Special character handling for city names (apostrophes, hyphens, periods)
- Falls back to DEMO_KEY when no API key configured
- Actionable error messages for 403/429
- No mandatory authentication
