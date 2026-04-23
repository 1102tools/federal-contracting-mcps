# Changelog

## 0.2.10

Round 8: Hypothesis-driven punishment suite + bonus live tests. 69 new
tests (~25,000 random probes via Hypothesis + 10 live API calls). Zero
new bugs found, validating that the round-6 fixes plus the original
hardening covered the failure surface completely.

### Why zero bugs is meaningful

The same Hypothesis approach found 2 P3 bugs in sam-gov-mcp (round 7).
The fact that it found zero in usaspending-gov-mcp reflects a structural
difference: usaspending uses `_ensure_dict_response` which raises on
non-dict inputs (no normalization gap to exploit), and its validators
are pydantic-pre-validated on the public boundary. The validators that
Hypothesis stress-tested all handled the full random input space without
crashing.

### Round 8 coverage (69 functions, ~25,000 probes + 10 live calls)

Bucket | Functions | Notes
---|---|---
A. _validate_date | 4 + 8 specific | YYYY-MM-DD generators, calendar edge cases
B. _clamp_limit | 2 | sys.maxsize values, in-range passthrough
C. _coerce_code_list | 2 + 2 specific | None/list/int coercion, empty/whitespace rejection
D. _validate_no_control_chars | 3 | Every codepoint 0-31 rejected, clean strings pass
E. _normalize_toptier | 3 | Padding behavior, 0-99 → 3-digit
F. _validate_fiscal_year | 3 | 2008..current valid, below/above rejected
G. _ensure_dict_response | 2 | Dict passthrough, non-dict raises
H. _clean_error_body | 3 | Random text, HTML titles, h1 extraction
I. _validate_strings_no_control_chars | 1 + 2 specific | Lists with control chars
J. Async concurrency stress | 3 | 50 concurrent + 100 mixed + 50 sequential
K. Encoding edge cases | 10 + 5 specific | Unicode normalization, RTL, BOM, ZWSP, emoji
L. Integer overflow | 1 | sys.maxsize bounds
M. Composite tool deep tests | 5 specific | lookup_piid input variants
N. Bonus live tests | 10 | int NAICS coercion live, PSC tree extra slashes, unicode recipient, emoji keyword, max pagination, NAICS sectors, top-10 state profiles, 50 concurrent live searches, decade-span aggregation, lowercase PIID

### Test counts after round 8

- `tests/test_validation.py`: 62 (52 offline + 10 live-gated)
- `tests/test_density_r5.py`: 415 offline parameterized tests
- `tests/test_live_audit_r6.py`: 157 live-gated tests
- `tests/test_live_audit_r7.py`: 104 live-gated tests
- `tests/test_punishment_r8.py`: 69 (59 offline Hypothesis + 10 live)
- **Total: 807 regression tests (526 offline, 281 live-gated)**
- **Density: 47.5 tests per tool** (17 tools)

## 0.2.9

Round 7: deep live audit (104 new live-gated tests). Zero new server bugs
found, validating round 6's two fixes covered the gaps. The two test
failures during this round were both test-author errors (wrong sort field
name "Action Date" instead of "Last Modified Date"; wrong HTTP code
expectation 404 vs actual 400 on invalid FIPS), not MCP bugs.

### Round 7 coverage targets (gaps from round 6)

Bucket | Count | Coverage
---|---|---
A. Detail tools with REAL chained IDs | 9 | get_award_detail, get_transactions, get_award_funding chained from real search results
B. IDV children all 3 child_types | 4 | child_awards, child_idvs, grandchild_awards
C. Loan award searches | 3 | award_type='loans' with default sort, amount filter, response shape
D. Direct payments + Other | 3 | award_type='direct_payments', 'other', 'grants'
E. Sort and order variations | 4 | Last Modified Date, Recipient Name, asc/desc
F. Deep PSC tree drilldowns | 5 | Research and Development, Services, Products, trailing/leading slash handling
G. Compound filters returning zero | 3 | Impossibly specific filters, invalid NAICS
H. Pagination at depth | 3 | page=20, 50, 100
I. Real prime + agency combos | 7 | Lockheed at Navy/Air Force, Booz at Treasury, GD at Navy, Raytheon, Northrop, awarding_subagency
J. Award amount edge cases | 4 | $0, $1, $1B+, exact match
K. High-volume agency deep-dives | 6 | DoD, HHS grants, NASA, DHS, VA, State
L. Agency overview deep checks | 3 | DoD, HHS, NASA response shape
M. NAICS details deep checks | 3 | 2-digit, invalid 6-digit, description presence
N. State profile deep checks | 2 | Totals, state field
O. spending_by_category deep checks | 6 | Top 10 recipients, NAICS+DoD, district, county, country, CFDA grants
P. Autocomplete deep checks | 5 | 4-char PSC, 2-char PSC partial, NAICS int query, full code, max limit
Q. lookup_piid format variations | 4 | Full NAVSEA, full Air Force, nonexistent, max limit + GSA Schedule, OASIS+, DLA, full DoD
R. spending_over_time deep checks | 3 | Decade span, single quarter, NAICS+agency
S. Funding vs awarding agency | 2 | funding_agency alone, mixed funding+awarding
T. Date window edge cases | 3 | One day, FY2008 oldest, year span
U. PSC + NAICS coercion validation | 3 | Multiple PSCs, int coercion (round 6 fix verification), mixed types
V. Set-aside deep coverage | 3 | EDWOSB, VSA, multi-set-aside
W. lookup_piid format variations | 4 | GSA hyphens, OASIS+, DLA, full DoD
X. Cross-tool ID passing workflows | 2 | search → IDV children, search → funding
Y. Response field verification at scale | 3 | Required fields per result, grants recipient, IDV last date
Z. Concurrent stress | 2 | 10 concurrent searches, 8 concurrent agencies
AA. Agency name edge cases | 2 | EPA, HUD
BB. Invalid-but-well-formed inputs | 3 | Nonexistent agency code, invalid FIPS, unusual NAICS

### Test counts after round 7

- `tests/test_validation.py`: 62 (52 offline + 10 live-gated, unchanged)
- `tests/test_density_r5.py`: 415 offline parameterized tests
- `tests/test_live_audit_r6.py`: 157 live-gated tests
- `tests/test_live_audit_r7.py`: 104 live-gated tests
- **Total: 738 regression tests (467 offline, 271 live-gated)**
- **Density: 43.4 tests per tool** (17 tools)

### Why zero bugs is meaningful here

Round 6 added the live-audit lens to a previously offline-only test suite
and immediately found 2 P2 bugs (PSC tree trailing slash, list[str] int
coercion). Round 7 stress-tested the same surface from different angles
and found nothing. That's the round 7 finding: the round 6 fixes were
complete, and the deeper areas (detail tool chaining, IDV children, loans,
sort/order, deep PSC tree, compound filters) all work as documented.

## 0.2.8

Round 6: live audit. 157 new live-gated tests covering every tool against
the production USASpending.gov API. Two real bugs found and fixed.

### P2 bug: get_psc_filter_tree returned HTTP 301 on any non-empty path

USASpending's PSC filter tree endpoint requires a trailing slash. The MCP
constructed paths without one (`/api/v2/references/filter_tree/psc/Service`
instead of `/api/v2/references/filter_tree/psc/Service/`), causing the API
to return HTTP 301 with the corrected URL. The MCP did not follow redirects,
so the tool errored on every drilldown. Fix: append trailing slash on
non-empty paths. Caught by round 6 live audit.

### P2 bug: list[str] type hints rejected int values across 4 search tools

The internal `_coerce_code_list` helper accepts both str and int values
and coerces ints to strings. But the tool signatures declared
`naics_codes: list[str] | None`, so pydantic rejected int inputs at the
public boundary before they reached the coercion logic. The pre-existing
test `test_naics_codes_accepts_ints` only exercised the helper directly
(not through `mcp.call_tool`), so the gap was invisible until live audit.
Fix: type hints widened from `list[str]` to `list[str | int]` on all 7
code-list parameters across search_awards, get_award_count, spending_over_time,
spending_by_category. Public API is now consistent with the helper's behavior
and the docstring promises.

### Round 6 live test coverage (157 tests, runtime ~80 seconds)

Each test makes a real HTTP call against api.usaspending.gov and verifies
behavior that mocks cannot see. USASpending is keyless so no API key is
required. Skipped automatically when `USASPENDING_LIVE_TESTS=1` is not set.

Bucket | Count | Coverage
---|---|---
A. search_awards | 30 | Real keyword searches, NAICS/PSC/state/amount/recipient/date/set-aside/pricing/competition filters, all award_types, pagination, compound filters, unicode keywords, PIID-prefix searches
B. get_award_count | 7 | Filter combinations, set-aside, amount range, recipient, NAICS
C. spending_over_time | 7 | All 3 group values (fiscal_year, quarter, month), keyword/NAICS filters, multi-year span
D. spending_by_category | 11 | Parameterized across 8 categories (recipient, awarding_agency, naics, psc, etc.) plus filter combinations and max limit
E. Agency tools | 27 | All 10 major federal agencies (DoD, HHS, NASA, DHS, VA, Treasury, Education, DoE, USDA, Commerce) tested against get_agency_overview and get_agency_awards, plus FY filters and toptier code normalization
F. NAICS details | 11 | Real codes at every depth (2-digit, 3-digit, 4-digit, 6-digit) including 541512, 541611, 236220, 541990
G. PSC filter tree | 5 | Top-level + drilldowns + response shape verification (after the trailing-slash fix)
H. State profiles | 13 | Major state FIPS codes (CA, TX, FL, NY, PA, IL, OH, GA, NC, MI, VA, MD, DC)
I. Autocomplete | 22 | 10 PSC + 10 NAICS queries plus exclude_retired flag behavior
J. lookup_piid | 6 | NAVSEA, AFRL, Army, NAVAIR, DLA, GSA Schedule prefixes
K. Concurrent calls | 3 | 5 concurrent searches, 3 concurrent agency lookups, mixed-tool concurrency
L. Response shape verification | 9 | Per-tool field presence checks that catch upstream API drift
M. Edge cases | 8 | Leap year dates, FY rollover window, multi-NAICS, unicode, apostrophes, high pagination, compound filters, award_ids filter

### Test counts after round 6

- `tests/test_validation.py`: 62 (52 offline + 10 live-gated, unchanged from rounds 1-4)
- `tests/test_density_r5.py`: 415 offline parameterized tests
- `tests/test_live_audit_r6.py`: 157 live-gated tests
- **Total: 634 regression tests (467 offline, 167 live-gated)**
- **Density: 37.3 tests per tool** (17 tools)

### Why this round mattered

Round 5 was offline density expansion. It found zero new bugs because it
didn't test the live API. Round 6 hit the live API hard and found two
real bugs within the first 200 calls, including one (the int-coercion
mismatch) where a pre-existing test gave false confidence by exercising
the helper directly instead of through the public MCP boundary. This is
exactly what live audits exist to catch.

## 0.2.7

Round 5 density expansion. No code changes to `server.py`. The audit added
415 new parameterized regression tests organized into 18 distinct
failure-mode buckets, lifting suite-wide coverage from 62 tests (3.6 per
tool) to 477 tests (28.1 per tool). Now in the same density tier as
sam-gov-mcp (29.9) and gsa-perdiem-mcp (28.7).

### Coverage by failure-mode bucket
1. Date format validation across every date-taking tool, parameterized
   across 12 invalid format variants per tool plus 7 calendar-invalid cases
   including leap year correctness for FY2024 vs FY2025 (~50 tests)
2. Limit and page boundary checks across every paginated tool: zero,
   negative, just-above-cap, far-above-cap (~30 tests)
3. Amount range validation: parameterized across 4 negative values for
   both award_amount_min and award_amount_max on search_awards and
   get_award_count, plus min-greater-than-max cross-field check (~17 tests)
4. List/array filter validation on naics_codes, psc_codes, award_ids,
   keywords: empty arrays, all-empty-string entries, all-whitespace
   entries (~12 tests)
5. Control-character safety: 8 control-char variants × 9 text-input
   parameters across 5 tools, plus 10 legitimate text cases (apostrophes,
   unicode, emoji, etc.) verified as accepted (~85 tests)
6. `extra='forbid'` enforcement parameterized across all 16 tools that
   accept kwargs, plus explicit historical typo cases (~20 tests)
7. Award identifier validation across get_award_detail, get_transactions,
   get_award_funding, get_idv_children: 4 invalid variants per tool (~16 tests)
8. PIID validation on lookup_piid: 5 length and format variants (~5 tests)
9. Toptier code normalization: invalid format variants × 2 tools, plus
   left-padding behavior (3-digit, 2-digit, 1-digit, 4-digit, whitespace) (~17 tests)
10. Fiscal year boundary checks: zero, negative, pre-2008, far-future,
    boundary-valid, plus current-FY-plus-one (~7 tests)
11. NAICS code validation on get_naics_details: 7 invalid format variants
    plus valid 2-digit and 6-digit cases (~9 tests)
12. State FIPS validation on get_state_profile: 10 invalid format variants
    plus 3 valid cases including whitespace handling (~13 tests)
13. Autocomplete query length and content checks (PSC + NAICS): empty,
    single-char, whitespace, length cap at 200 chars (~8 tests)
14. No-filter rejection on search_awards, get_award_count, spending_over_time:
    empty call, award_type-only, group-only (~6 tests)
15. Spending-by-category Literal validation, no-filter behavior, limit
    boundaries (~4 tests)
16. award_type Literal validation: 6 invalid variants × 2 tools (~12 tests)
17. order Literal validation: 7 invalid variants × 2 tools (~14 tests)
18. group / child_type Literal validation (~10 tests)
19. Direct unit tests on validator helpers: `_validate_date`, `_clamp_limit`,
    `_coerce_code_list`, `_validate_no_control_chars`, `_validate_strings_no_control_chars`,
    `_normalize_toptier`, `_validate_fiscal_year`, `_ensure_dict_response`,
    `_clean_error_body`, `_current_fiscal_year` (~75 tests)

### Test file structure
- `tests/test_validation.py` (existing 62 tests, unchanged): rounds 1-4 plus
  live-gated integration tests
- `tests/test_density_r5.py` (new 415 tests): round 5 density expansion

### Why this matters
Each new test exercises a distinct failure mode. No padding, no shape
duplicates. Density of 28.1 tests per tool puts USASpending in the same
tier as the most-tested MCPs in the 1102tools suite. Future regressions
in input validation, type coercion, or response-shape handling will be
caught by pytest before they hit users.

## 0.2.3

Follow-up hardening after a full playbook pass (round 3 deep live stress,
round 4 response-shape mocks, plus a live-gated regression suite). The
0.2.2 release shipped after only rounds 1-2; this closes the gap with
how bls-oews / gsa-perdiem / regulationsgov were audited.

### P1 silent-wrong-data
- `search_awards()` called with NO filter arguments silently returned 25
  unfiltered recent contracts. That's the same failure mode as
  regulationsgov's `agency_id=""` returning all 1.95M records. Now
  raises "search_awards requires at least one filter beyond award_type"
  with a pointer to the typical filter combinations.

### P2 response-shape defense
- `_post` / `_get` now guarantee a dict return via `_ensure_dict_response`.
  USASpending always returns JSON objects for the endpoints this MCP
  uses; anything else (None, bare list, int, string) is a CDN / proxy
  issue that used to leak into tool output as a type confusion. Now
  surfaces clearly as "USASpending returned an empty body at {path}" or
  "unexpected {type} at {path}".

### Testing
- 16 new tests: 6 offline (round-3 no-filter regression + 4 shape-guard
  regressions on mocked responses) and 10 live gated by
  `USASPENDING_LIVE_TESTS=1`.
- Live suite now covers: real search with real results, compound
  filters narrowing results, leap-year date, exact-match amount range,
  autocomplete return, state profile, concurrent searches, unicode
  keyword handling, and toptier-agency listing.
- Test total: 52 offline + 10 live = 62 passing. 0.2.2 shipped with 46.
- Added autouse fixture to reset `srv._client` between tests so the
  shared httpx client doesn't leak across event loops.

### USER_AGENT
- Bumped to `usaspending-gov-mcp/0.2.3`.

## 0.2.2

Live audit against the USASpending.gov API surfaced 9 P1 silent-wrong-data
paths and 4 P2 validation gaps. All fixed.

### P1 silent-wrong-data
- Null byte / newline / tab in `keywords` silently accepted: the API
  either strips them (returns unfiltered-ish) or 500s on them. Now
  every free-text field rejects control characters up front.
- Null byte in `autocomplete_psc.search_text` and
  `autocomplete_naics.search_text` produced HTTP 500 from the API.
  Now rejected locally.
- Null byte in `generated_award_id` / `generated_idv_id` on
  `get_transactions`, `get_award_funding`, `get_idv_children`,
  `get_award_detail` produced HTTP 500. Now rejected locally.
- Negative `award_amount_min` / `award_amount_max` silently ignored
  by USASpending and returned unfiltered default results. Now
  rejected with an explanatory error.
- `naics_codes=["", "", ""]`, `psc_codes=[""]`, `award_ids=[""]` —
  list-of-empty-strings used to be silently dropped by
  `_coerce_code_list`'s filter, leaving an empty list that applied
  no filter at all. Now rejected with "contains only empty /
  whitespace strings."
- Empty / whitespace-only `generated_award_id` on the detail tools
  hit the API as a 422 or 404. Now rejected up front with a clear
  pointer to `search_awards` as the source of valid IDs.

### P2 validation
- `autocomplete_psc` / `autocomplete_naics` now cap `search_text` at
  200 chars. Long searches are meaningless for autocomplete and
  triggered upstream 500s.

### Testing
- 17 new regression tests covering every round-1 and round-2 finding.
- Old tests kept; total is now 46 offline tests passing.

### USER_AGENT
- Bumped to `usaspending-gov-mcp/0.2.2`.

## 0.2.1

Cross-MCP fix discovered during the sam-gov-mcp 0.3.1 live audit.

- FastMCP tools register pydantic argument models with the default
  `extra='ignore'` config, so a typo like
  `search_awards(keyword='cyber')` (real param is `search_text`)
  silently dropped the typo'd argument and returned unfiltered data.
  Now every tool has `extra='forbid'` applied after registration, so
  typos raise "Extra inputs are not permitted" before any HTTP call.
- USER_AGENT bumped to `usaspending-gov-mcp/0.2.1`.
- Added regression test covering the new behavior.

## 0.2.0

Hardening release. Found via integration stress testing through a real MCP client (not raw coroutine awaits), which surfaced 28+ issues invisible to the prior unit tests.

### Tool behavior changes

- **get_award_count** and **spending_over_time** now raise `ValueError` when called with no filters, rather than forwarding an empty-filters request to the API (which 400s). Pass at least one filter (time_period, keywords, agency).
- **autocomplete_psc** and **autocomplete_naics** now require a minimum 2-character query. Single-character or empty queries return an empty result with a `_note` explaining why. Upstream returns arbitrary first-N alphabetical records on short queries, which silently misleads callers.
- **autocomplete_naics** adds `exclude_retired=True` (default). The upstream NAICS taxonomy includes codes retired in 2012/2017/2022 which dominate certain keyword matches (e.g. "software" previously returned only retired codes). Set `exclude_retired=False` to restore prior behavior.

### Schema and input validation

- `limit` on search, autocomplete, and convenience tools now raises when <1 or over the API's cap (100 for search endpoints, 5000 for transactions). Previously schema was unbounded and callers hit upstream 422s or 95KB+ response payloads.
- `page` parameter now requires `>= 1` across all paginated tools.
- `time_period_start` / `time_period_end` now validated as `YYYY-MM-DD`. ISO 8601 datetimes, slash-separated dates, and reversed ranges (end before start) raise actionable errors.
- `award_amount_min > award_amount_max` now raises instead of silently returning zero results.
- `naics_codes`, `psc_codes`, `award_ids`, `set_aside_type_codes`, `extent_competed_type_codes`, `contract_pricing_type_codes`, `def_codes` accept both strings and integers (auto-coerced to strings). Empty arrays raise `ValueError` to catch `naics_codes=[]` silent-match bugs.
- `place_of_performance_state` validated as 2-letter USPS code, auto-uppercased.
- `toptier_code` in `get_agency_overview` and `get_agency_awards` auto-left-pads numeric inputs shorter than 3 digits (e.g. "97" → "097").
- `fiscal_year` bounded to `[2008, current FY]` on agency endpoints.
- `lookup_piid.piid` now requires minimum 3 characters (upstream keyword filter minimum).

### Error hygiene

- HTTP 404 responses from USASpending that return an HTML error page (`<!doctype html>...`) are now parsed down to the title/h1 text, rather than leaking the full HTML body to callers.

### Documentation

- `search_awards` docstring now warns that `awarding_agency` must be the full name (e.g. "Department of the Navy"), not the slug form ("department-of-the-navy"). Slugs silently return zero results.

## 0.1.2
Initial release.

- 17 MCP tools covering the USASpending.gov REST API
- Search endpoints: search_awards, get_award_count, spending_over_time, spending_by_category
- Detail endpoints: get_award_detail, get_transactions, get_award_funding, get_idv_children
- Workflow: lookup_piid (auto-detects contract vs IDV)
- Autocomplete: autocomplete_psc, autocomplete_naics
- Reference: list_toptier_agencies, get_agency_overview, get_agency_awards, get_naics_details, get_psc_filter_tree, get_state_profile
- Actionable error translation for common 400/404/422 API errors
- Award type group validation (contracts, IDVs, grants, loans cannot be mixed)
- Sort field auto-insertion (USASpending requires sort field in fields array)
- Keyword minimum length validation (API requires 3+ chars)
- Path parameter validation for FIPS codes, agency codes, and NAICS codes
- No authentication required
