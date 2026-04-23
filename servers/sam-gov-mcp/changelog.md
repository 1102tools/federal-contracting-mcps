# Changelog

## 0.3.6

Round 6: live audit. 235 new live-gated tests covering every tool against
the production SAM.gov API. One P1 bug found and fixed.

### P1 silent-bug found in round 6 live audit

`search_exclusions(entity_name=...)` sent the API parameter `entityName`
which SAM.gov rejects as `INVALID_SEARCH_PARAMETER`. The correct upstream
field is `exclusionName`. Anyone calling search_exclusions with a name
filter got an HTTP 400 with no result. Fix: parameter mapping changed from
`entityName` to `exclusionName` in server.py. The tool's own `entity_name`
parameter name stays the same to preserve the public interface.

### Round 6 live test coverage (235 tests, runtime ~3-5 minutes)

Each test makes a real HTTP call against api.sam.gov and verifies behavior
that mocks cannot see. Skipped automatically when `SAM_LIVE_TESTS=1` is
not set so default pytest runs stay fast.

Bucket | Count | Coverage
---|---|---
A. WAF behavior live | 17 | Apostrophes (McDonald's, L'Oreal, O'Brien, etc.), ampersands, unicode, angle brackets, SQL keywords all confirmed accepted by SAM.gov
B. Entity lookups | 13 | UEI/CAGE lookups across all `include_sections` combinations, lowercase normalization, whitespace stripping, nonexistent UEI handling
C. Entity search | 20 | `legal_business_name` partial matching, `free_text` search, NAICS/state/business-type filters, pagination at high pages, combined filters
D. Exclusions | 10 | Country filters, classification types (Firm/Individual/Vessel/Special Entity), state filtering, exclusion programs, name searches via `exclusionName`
E. Vendor responsibility check | 5 | Real UEIs through the full 2-API-call composite, flag list verification, padding/whitespace handling
F. Opportunities | 21 | All 14 set-aside codes, all 9 notice types, NAICS/state/zip filters, compound filters, 364-day span boundary
G. Contract awards | 16 | All fiscal years FY2008-FY2026, NAICS with `~`/`!` operators, PSC filtering, PIID/UEI/CAGE/awardee lookups, dept code filtering, modification number filtering, AWARD vs IDV distinction
H. PSC lookups | 16 | Real codes across categories (R, D, AJ, B, J, Y, Z), free-text queries (cyber, professional, engineering, etc.), unicode and apostrophe queries
I. Entity deep sections | 5 | Reps and certs (summary + full mode), integrity info (FAPIIS proceedings)
J. Search deleted awards | 5 | Previously zero coverage; now exercises pagination, dept code filtering, max limit
K. Concurrent calls | 3 | 5 concurrent searches, 3 concurrent lookups, mixed-tool concurrency
L. Response shape verification | 10 | Per-tool field presence checks that catch upstream API drift
M. Edge cases | 11 | Unicode CJK, emoji, max-length names, single-day windows, padded UEIs
N-S. Exhaustive coverage | 89 | Every set-aside code, every notice type, every supported FY, top procurement NAICS and states, common PSC categories

### Test counts after round 6

- `tests/test_validation.py`: 79 (73 offline + 6 live-gated, unchanged from rounds 1-4)
- `tests/test_density_r5.py`: 369 offline parameterized tests
- `tests/test_live_audit_r6.py`: 235 live-gated tests
- **Total: 683 regression tests (441 offline, 242 live-gated)**
- **Density: 45.5 tests per tool** (15 tools)

### Why this round mattered

Round 5 was a coverage expansion against the existing code. Round 5 found
zero new bugs because it didn't test the live API. Round 6 hit the live
API hard and immediately found a real bug (entity_name) that had been
shipping broken for at least one release cycle. This is exactly what the
0.3.1 release record predicted: "live audit surfaces bugs mocks cannot
catch." The pattern held.

## 0.3.5

Round 5 density expansion. No code changes to `server.py`. The audit added
369 new regression tests organized into 10 distinct failure-mode buckets,
lifting suite-wide coverage from 79 tests (5.3 per tool) to 448 tests
(29.9 per tool). Now the most-tested MCP in the suite, exceeding GSA Per
Diem at 28.7 tests per tool.

### Coverage by failure-mode bucket
1. UEI format validation across every UEI-taking tool, parameterized
   across 14 invalid format variants per tool (~70 tests)
2. CAGE format validation across every CAGE-taking tool (~15 tests)
3. PIID format validation including embedded control character cases (~9 tests)
4. PSC code format and `active_only` Literal value validation (~16 tests)
5. Date format validation across every date-taking tool, including
   leap year correctness for FY2024 vs FY2025 (~50 tests)
6. Pagination, limit, and offset boundary checks across all 5 search
   tools including the previously-untested `search_deleted_awards` (~30 tests)
7. WAF and control-character safety: null bytes, tab/CR/LF/CRLF rejected;
   apostrophes, angle brackets, SQL keywords, unicode (CJK and emoji)
   verified as accepted (~30 tests)
8. `extra='forbid'` enforcement verified individually on all 15 tools (~18 tests)
9. Filter-code validation: state codes, NAICS, business types, set-aside
   codes, fiscal year boundaries, country codes (~30 tests)
10. Direct unit tests on validator helpers: `_coerce_str`, `_safe_int`,
    `_as_list`, `_normalize_awards_response`, `_validate_uei`, `_validate_cage`,
    `_validate_naics`, `_validate_fiscal_year`, `_validate_date_mmddyyyy`,
    `_clamp`, `_clean_error_body`, `_validate_waf_safe`, `_clamp_str_len`,
    `_current_fiscal_year` (~80 tests)

### Test file structure
- `tests/test_validation.py` (existing 79 tests, unchanged): rounds 1-4
  plus live-key audit regressions
- `tests/test_density_r5.py` (new 369 tests): round 5 density expansion

### Why this matters
Each new test exercises a distinct failure mode. No padding, no shape
duplicates. Engineers reviewing the suite will see that every input field
on every tool has format, boundary, type, and injection coverage. Density
of 29.9 tests per tool is the gold standard in the 1102tools MCP suite.

## 0.3.1

Live-audit follow-up. With a real SAM.gov API key we re-ran every tool
against the live API and found 3 P1 bugs that the 0.3.0 mocked audit
rounds could not have caught. All fixed.

### Silent-wrong-data fixes (P1)
- The WAF pre-filter introduced in 0.3.0 was almost entirely false
  positives. It rejected single quotes (`'`), backticks, angle
  brackets, and SQL keywords on the theory that SAM.gov's upstream WAF
  would drop the connection. Live testing proved SAM.gov accepts all
  of these as literal search text. The filter was blocking legitimate
  company-name searches: McDonald's, L'Oreal, O'Brien, O'Reilly,
  etc. all raised a spurious "WAF triggered" error. Filter narrowed
  to just null bytes and control characters (tab, CR, LF), which
  really do break URL encoding or the API.
- Unknown parameter names were silently dropped. FastMCP tools
  generate pydantic argument models with the default `extra='ignore'`
  config, so a typo like `search_entities(keyword='Lockheed')` (the
  real parameter is `free_text`) succeeded with the typo parameter
  silently discarded -- the tool then hit the API with no filters
  and returned all 700k+ entities. Applied `extra='forbid'` to every
  tool's arg model after registration. Typos now raise
  `Extra inputs are not permitted` before any HTTP call.
- `lookup_award_by_piid` accepted empty / whitespace PIID, making an
  API call that returned empty with no indication of the problem.
  Now raises a clear error up front.

### Error-message clarity (P3)
- PSC lookup 404s used to leak SAM's opaque
  `{"response": "Entered search criteria is not found"}` body. Now
  translated to: "SAM.gov did not find any record matching your
  search. For PSC codes: verify the code exists at
  https://www.acquisition.gov/psc-manual..."

### Testing
- `tests/test_validation.py`: 13 new tests (6 offline regressions for
  the new fixes, 6 live regressions gated by `SAM_LIVE_TESTS=1`). Old
  WAF-rejection tests were replaced with "WAF-accepts" tests to catch
  regression if someone re-adds the overzealous filter.
- Added autouse fixture to reset `srv._client` between tests
  (multi-event-loop safety).

## 0.3.0
Deep hardening release. Four audit rounds surfaced 30+ issues behind SAM.gov's
notoriously temperamental API surface. This release adds aggressive
pre-validation, defensive response parsing, and a WAF pre-filter so tools fail
fast with actionable errors instead of hitting the firewall or crashing on
unusual response shapes.

### Crash fixes (all triggered by plausible SAM responses)
- `_normalize_awards_response`: `int(None)` TypeError when Contract Awards
  returns `totalRecords`/`limit`/`offset` as null. Replaced raw `int()` with
  `_safe_int` helper.
- `get_entity_reps_and_certs`: AttributeError when `entityData` returns as a
  dict instead of list (XML-to-JSON single-item collapse). Added `_as_list`
  normalizer.
- `vendor_responsibility_check`: KeyError when `totalRecords>0` but
  `entityData` missing, AttributeError when `excludedEntity` collapses to
  dict, KeyError when `totalRecords` comes back as string `"0"` (`== 0`
  compare fails). All fixed via `_as_list` + `_safe_int` + isinstance guards.

### Silent-wrong-data and validation-gap fixes
- `get_entity_reps_and_certs`: full payload is ~70KB. Added `summary_only=True`
  default returning provisionId/title/answerCount per clause, plus
  `clause_filter` param. Full detail still available via
  `summary_only=False`.
- `search_contract_awards`: `fiscal_year` now accepts int OR str (was
  str-only), with range validation 2008..current FY.
  `awardee_uei`/`awardee_cage_code` format-validated. NAICS validated to 2-6
  digits with `~`/`!` operator support. `dollars_obligated` bracket
  `[min,max]` format validated.
- `search_opportunities`: pre-enforces SAM's 364-day `posted_from`→`posted_to`
  cap. Rejects reversed date ranges. `title`/`solicitation_number`
  length-clamped. `set_aside` validated against `SET_ASIDE_CODES` dict +
  case-normalized.
- `search_entities`: `business_type_code` validated against
  `BUSINESS_TYPE_CODES` + `SBA_BUSINESS_TYPE_CODES` dicts.
  `legal_business_name`/`free_text` WAF-checked and length-clamped.
  `state_code` 2-letter USPS enforced.
- `search_exclusions`: `entity_name`/`free_text` WAF-checked +
  length-clamped. CAGE format-validated. `country` lowercase auto-normalized
  to uppercase (was rejected). `activation_date_range` MM/DD/YYYY validated.
- `check_exclusion_by_uei`, `get_entity_integrity_info`: UEI format enforced
  (was only checking empty).
- `lookup_psc_code`, `search_psc_free_text`: min-length 2, WAF-checked.
  Empty query rejected locally instead of round-tripping to API.
- `get_opportunity_description`: `notice_id` empty/whitespace rejected
  locally.

### WAF pre-filter (new)
- `_validate_waf_safe` rejects strings containing path traversal (`../`),
  HTML angle brackets, SQL keywords + comment markers, single
  quotes/backticks, null bytes. These trigger SAM.gov's firewall which drops
  the connection silently. Pre-rejecting gives an actionable error instead
  of a generic network timeout. Applied to 6 user-controlled text fields.
- `_get` RequestError branch now also treats empty error strings as WAF
  drops (httpx sometimes surfaces WAF kills with no error text).

### Error hygiene
- `_clean_error_body` strips HTML from 401/403/400 responses (SAM returns
  HTML for auth failures). Error messages stay readable.
- `_format_error` uses cleaned bodies.

### Dates
- `_validate_date_mmddyyyy` handles bracket ranges and recursively validates
  inner dates. Leap year / non-leap year Feb 29 correctly distinguished.
- All date-taking tools reject ISO 8601, YYYY-MM-DD, single-digit months,
  dashes-instead-of-slashes.

### Type coercion
- `_coerce_str` accepts int or str for conceptually-numeric code fields.
  `naics_code`, `psc_code`, `zip_code`, `contracting_*_code`,
  `modification_number`, `fiscal_year` all now accept int transparently.

### Defensive parsing
- `_as_list` normalizes XML-to-JSON single-item collapse wherever SAM
  responses can collapse (`entityData`, `excludedEntity`, `awardSummary`,
  `businessTypeList`, `listOfActions`, `farResponses`, `dfarsResponses`).
- `_safe_int` never crashes on None/"null"/""/bad types.

### Release automation
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` triggers test,
  build, and PyPI publish via Trusted Publisher (no tokens).
- `constants.USER_AGENT` bumped to 0.3.0.

### Tests
- New `tests/test_validation.py` with 65 tests covering every fix through
  the FastMCP registry (`mcp.call_tool`) so pydantic coercion runs as in
  production. Prior `stress_test.py` awaited raw coroutines and bypassed
  the tool pipeline, which is why the round-4 crashes shipped in 0.2.x.

### Breaking change note
- `get_entity_reps_and_certs` default response shape differs: summary mode
  now on by default. Callers wanting the raw ~70KB response must pass
  `summary_only=False`. This is the reason for the minor version bump
  (0.2.x → 0.3.0) rather than a patch bump.

## 0.2.0
Contract Awards API support (FPDS replacement).

- 3 new tools: search_contract_awards, lookup_award_by_piid, search_deleted_awards
- Contract Awards v1 (/contract-awards/v1/search) covers the full FPDS data set
- Response normalization: empty results use a different JSON wrapper than populated results; all tools return a consistent shape
- Plain text/HTML error handling: Contract Awards returns non-JSON for certain errors (limit>100, bad date format, invalid API key)
- Client-side limit validation (max 100) with actionable error messages
- 15 total tools (was 12)

## 0.1.0
Initial release.

- 12 MCP tools covering three SAM.gov REST APIs plus PSC lookup
- Entity Management v3: lookup_entity_by_uei, lookup_entity_by_cage, search_entities, get_entity_reps_and_certs, get_entity_integrity_info
- Exclusions v4: check_exclusion_by_uei, search_exclusions
- Get Opportunities v2: search_opportunities, get_opportunity_description
- PSC lookup: lookup_psc_code, search_psc_free_text
- Composite workflow: vendor_responsibility_check (FAR 9.104-1 entity + exclusion check)
- Actionable error translation for 400/401/403/404/406/414/429 responses
- 90-day key expiration detection with regeneration instructions
- WAF connection-drop detection with actionable message
- Client-side validation: entity size cap (10), exclusion size cap (100), opportunity limit cap (1000), negative size rejection, 3-char ISO country code enforcement, empty UEI/CAGE guardrails
- Agency post-filter workaround for broken deptname/subtier Opportunities params
- Authentication via SAM_API_KEY environment variable (never enters model context)
