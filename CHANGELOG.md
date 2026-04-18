# Changelog

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
