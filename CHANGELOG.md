# Changelog

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
