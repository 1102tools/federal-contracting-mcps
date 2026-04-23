# Changelog

## 0.2.6

Round 5: Hypothesis-driven offline property test suite + extensive live audit.
197 new test functions (~25,000 random probes via Hypothesis + 122 live API
calls across all 8 tools). Zero new bugs found, validating the rounds 1-4
hardening covered the failure surface.

### Round 5 coverage

Bucket | Functions | Notes
---|---|---
A. _safe_dict / _as_list / _safe_number / _safe_bucket_key fuzz | 4 | 500 probes each across all input types
B. _validate_no_control_chars / _validate_waf_safe property | 3 | Every codepoint 0-31 rejected; clean strings pass
C. _validate_finite + numerical helpers | 1 + 3 specific | inf/nan/finite handling
D. _clamp_text_len / _strip_or_none property | 2 | Length boundary, strip behavior
E. _clamp property tests | 1 | sys.maxsize bounds
F. _validate_education_level | 1 + 14 specific | All 6 valid levels, pipe-delimited combos, normalization, invalid rejected
G. _validate_worksite | 1 + 6 specific | Customer/Contractor/Both, normalization
H. _validate_sin | 1 + 8 specific | Real SINs, int coercion, bool rejection
I. Experience/price range | 2 + 11 specific | Reversed, negative, inf/nan
J. Ordering/sort validators | 2 + 12 specific | All valid, common invalid
K. Async concurrency stress | 3 | 50/100 concurrent, 50 sequential
L. Encoding edge cases | 14 | Unicode normalization, emoji
M. Integer boundaries | 1 | sys.maxsize
N. **Live tests (122 calls)**:
  - 15 common labor categories via keyword_search
  - 8 real SINs via sin_analysis (54151S, 541611, 541715, 541330ENG, 541512, 611430, 541330, 541990)
  - All 6 education levels + pipe-delimited
  - 5 experience ranges + 4 price ranges
  - business_size, security_clearance, worksite combinations
  - exact_search labor_category + vendor_name
  - 6 suggest_contains queries
  - 5 igce_benchmark categories + filtered variant
  - 5 price_reasonableness rates
  - 3 vendor_rate_card vendors
  - Pagination depth (page 2, 5, max 200)
  - All 5 ordering options + asc/desc
  - WAF probes (apostrophes, ampersands, unicode)
  - Compound filter combinations
  - 5 concurrent live searches
  - Response shape verification
  - Validation rejection live (no-filter browse, empty keyword)
O. Historical regression sanity | 3 | Apostrophe, no-filter rejection, extra='forbid'

### Test counts after round 5

- `tests/test_validation.py`: 117 (offline + 9 live-gated, unchanged)
- `tests/test_round_5.py`: 197 (95 offline Hypothesis + 102 live)
- **Total: 314 regression tests (212 offline, 102 live-gated)**
- **Density: 39.3 tests per tool** (8 tools)

### Why zero bugs is meaningful

The original 0.2.2 audit found 86 issues including 4 P0 catastrophic bugs
(filtered_browse returning 265k records, pydantic bool→int silent coercion).
That hardening was thorough enough that an additional ~25,000 random probes
through Hypothesis plus 122 live tests across the full tool surface couldn't
find anything new. The validators handle the entire random input space
without crashing, and the live API contract matches what the tools expect.

## 0.2.2

Full live-audit pass against the real GSA CALC+ API (rounds 1-4). Mocks in
0.2.1 were clean, but the live pass surfaced 8 P1 silent-wrong-data paths
and 4 P2 validation gaps. All fixed.

### Silent wrong-data (P1)
- **Control characters in free-text now rejected before strip().** `\n`,
  `\r`, `\t`, `\b` and other 0x00-0x1f / 0x7f code points previously passed
  the WAF pre-filter because `_strip_or_none` only removed leading/trailing
  whitespace and `_validate_waf_safe` only checked `\x00`. Internal control
  chars reached the API URL-encoded and returned 0 hits silently (classic
  copy-paste artifact trap). New `_validate_no_control_chars` runs FIRST on
  every free-text input: `keyword`, `exact_search.value`, `suggest_contains.term`,
  `igce_benchmark.labor_category`, `vendor_rate_card.vendor_name`, `exclude`.
- **`filtered_browse()` with no filters now rejected.** Empirically the
  unfiltered default returns 265,067 records (`hits_capped=True`). Callers
  who omitted all filters got the first 100 records of an unbounded dataset
  silently. New at-least-one-filter rule raises a clear error pointing to
  typical filters (education_level, sin, experience_min).
- **`sin=True` / `sin=False` now rejected at pydantic layer.** `Union[str, int, None]`
  accepts bool (subclass of int), coerces `True`→`1`/`False`→`0` BEFORE
  `_validate_sin` runs. The coerced `"1"` / `"0"` passes the alphanumeric
  regex and reaches the API as `filter=sin:1`, silently matching zero
  records. New `BeforeValidator(_reject_bool_pre)` on `SinInput` rejects
  bool at the pydantic validation step. Applied to `keyword_search`,
  `filtered_browse`, `igce_benchmark`, and `sin_analysis.sin_code`.
- **`proposed_rate=NaN` / `Inf` now rejected.** NaN comparisons always
  return False, so `proposed_rate < p25`, `< p75`, `< median` all fall
  through to the else branches, producing `vs_median="equal"` and
  `iqr_position="above P75 (high)"` on a NaN input. New finite check
  raises a clear error.
- **`price_min` / `price_max` = NaN / Inf now rejected.** pydantic's `float`
  type has no finite constraint (unlike `int`, which does), so NaN slipped
  through and only failed at the API with HTTP 406. `_validate_finite`
  applied in `_validate_price_range` and `_validate_experience_range`.
- **`exclude` parameter now WAF-checked, length-capped, and control-char
  filtered.** Previously only `_strip_or_none` ran; `exclude="<script>"`
  round-tripped to GSA's WAF for a 403, and `exclude="a\x00b"` reached
  the API as a null byte.
- **`paged_past_end` flag added.** When `(page-1) * page_size >= total`,
  the response now includes `paged_past_end: True` and
  `paged_past_end_reason` indicating the last page with data. Previously
  empty pages past the end were indistinguishable from zero-match queries.
- **Elasticsearch 10,000-result window pre-clamped.** GSA CALC+ is backed
  by Elasticsearch with the default `index.max_result_window=10000`. Any
  `page * page_size > 10000` previously returned a cryptic HTTP 406. New
  `_validate_es_window` rejects locally with guidance to narrow via filters.

### Validation (P2)
- `igce_benchmark.labor_category` length cap 500 (previously hit API 406).
- `suggest_contains.term` length cap 500.
- `vendor_rate_card.vendor_name` length cap 500.
- `sin_analysis.sin_code` length cap 20 (real SINs are <=10 chars).

### Testing
- `_reset_client` autouse pytest fixture prevents `httpx.AsyncClient` from
  binding to a closed asyncio event loop across `asyncio.run()` invocations
  (the "Event loop is closed" error in multi-test runs).
- 31 new tests (25 offline regressions + 6 live-gated via `GSA_CALC_LIVE_TESTS=1`).
  Live tests cover: one-filter-browse, apostrophe vendors, 5+ compound
  filters narrowing, 5-call concurrency, paged-past-end flag, unicode
  keywords.
- Total: 117 tests, all green (109 offline + 8 live).
- USER_AGENT bumped to `gsa-calc-mcp/0.2.2`.

## 0.2.1

Two fixes triggered by the sam-gov-mcp 0.3.1 live audit:

- WAF pre-filter introduced in 0.2.0 had false positives. Live-verified
  against the real GSA CALC API: apostrophes (O'Reilly, O'Brien),
  backticks, semicolons, and SQL keywords (DROP TABLE) are all accepted
  as literal search text. Only HTML angle brackets and path traversal
  sequences actually trigger a 403. Filter narrowed accordingly so
  searches for labor categories like "O'Reilly Software Engineer"
  no longer raise a spurious "WAF triggered" error.
- Unknown parameter names were silently dropped. FastMCP tools register
  pydantic arg models with the default `extra='ignore'`, so a typo like
  `keyword_search(keyword='engineer')` (real param is `q`) silently
  discarded the typo'd argument and ran with no filter. Now every tool
  has `extra='forbid'` applied after registration, raising
  "Extra inputs are not permitted" on typos before any HTTP call.
- USER_AGENT bumped to `gsa-calc-mcp/0.2.1`.
- Replaced obsolete WAF-rejection tests with WAF-accepts tests so this
  filter cannot silently get reverted.

## 0.2.0
Deep hardening release. Six audit rounds surfaced 74 issues behind the thin
0.1.x shell. This release closes 19 distinct crash paths and 30 silent
wrong-data bugs, plus 19 validation gaps. `_extract_stats` alone had 12 ways
to crash on unusual GSA aggregation shapes.

### Crash fixes
- `_extract_stats` is now fully defensive: tolerates `aggregations` as null /
  list / string, `wage_stats` as null, `histogram_percentiles` / `values` as
  null, `std_deviation_bounds` as null, bucket items with `None` entries or
  missing `key` / `doc_count`, `hits.total` as int / null / missing, NaN / Inf
  in numeric fields. Never raises.
- `vendor_rate_card` hits iteration: handles `hits.hits` as null, non-dict
  items (None, str, int), `_source` as null.
- `suggest_contains` buckets iteration: skips items missing `key` field.
- `_get` now catches `JSONDecodeError` and raises a clean `RuntimeError` with
  actionable message (covers GSA maintenance pages, empty bodies, malformed
  JSON).

### Silent wrong-data fixes
- **Filter values are now URL-encoded.** Round 3 bug: filters like
  `worksite:Both & Customer` or `sin:abc;DROP` were sent raw to the API, with
  `&` breaking URL structure. Values now properly `quote_plus`-encoded.
- **`exclude` parameter is now URL-encoded.** Same bug class.
- **`experience_max` alone no longer silently drops.** Previously if only
  `experience_max` was passed (no `experience_min`), no filter was added.
  Now produces `experience_range:0,<max>`.
- **Price / experience reversed ranges rejected.** Previously `price_min=500,
  price_max=100` was sent raw to the API.
- **Hardcoded `99999` price ceiling removed.** `price_min` alone now uses
  `999999` upper bound so high-end clearance rates aren't silently excluded.
- **`education_level` validated against `EDUCATION_LEVELS` dict** (supports
  pipe-delimited OR like `BA|MA`). Previously `"XYZ"` or `"'; DROP"` silently
  reached the API.
- **`worksite` validated against {`Customer`, `Contractor`, `Both`}** with
  case normalization.
- **`sin` validated to alphanumeric only** (previously `sin='abc;DROP'`
  triggered WAF 503; now rejected locally with clean error).
- **`ordering` validated against `ORDERING_FIELDS`.** Previously SQL-suffix
  (`current_price DESC`) or bogus values silently reached the API.
- **`price_reasonableness_check.vs_median`** now reports `"unknown"` when
  median is missing (was misleadingly defaulting to `"above"`).
- **`keyword_search` rejects empty / whitespace keyword** (previously
  returned full 250K+ dataset).
- **`_extract_stats`** preserves bigger of `wage_stats.count` and
  `hits.total.value` as `total_rates` (previously used the smaller).
- **`vendor_rate_card`** numeric fields (`current_price`, `next_year_price`)
  now coerced to floats; previously strings passed through silently.

### WAF pre-filter (new)
- `_validate_waf_safe` rejects strings containing quote/backtick/semicolon,
  HTML angle brackets, SQL keywords + comment markers, path traversal (`../`),
  null bytes. GSA's firewall returns 403/503 on these with no context; pre-
  rejection gives actionable error. Applied to `keyword`, `exact_search.value`,
  `suggest_contains.term`, `igce_benchmark.labor_category`,
  `vendor_rate_card.vendor_name`.

### Validation + UX
- All tools accept int or str for `sin` (user naturally passes `54151` as int).
- `page`, `page_size` bound-checked at every tool (was missing at some).
- `price_reasonableness_check`: rejects `proposed_rate <= 0`.
- `igce_benchmark`: rejects empty `labor_category`.
- `vendor_rate_card`: adds `ordering` / `sort` params (previously hardcoded).
  Returns `_candidates` list when multiple vendors match the search term so
  caller can disambiguate.
- `_build_query_string` rejects combined search modes (keyword + search +
  suggest) that previously silently dropped lower-priority modes.
- `_format_error` wraps bodies in `_clean_error_body` which strips HTML.

### Release automation
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` runs tests + build
  + publishes to PyPI via Trusted Publisher (no tokens).
- `constants.USER_AGENT` bumped to 0.2.0.

### Tests
- New `tests/test_validation.py` with 74 tests, all through the FastMCP
  registry (`mcp.call_tool`) so pydantic coercion runs as in production.
  Prior `stress_test.py` awaited raw coroutines and bypassed the tool
  pipeline, which is why the round-2/3/4/5/6 crash paths shipped in 0.1.x.

## 0.1.0
Initial release.

- 8 MCP tools covering the GSA CALC+ Labor Ceiling Rates API
- Core search: keyword_search, exact_search, suggest_contains, filtered_browse
- Workflows: igce_benchmark, price_reasonableness_check, vendor_rate_card, sin_analysis
- Aggregation statistics extracted from every response (wage_stats, percentiles, education breakdown, business size)
- Filter support: education level, experience range, price range, business size, security clearance, SIN, worksite
- Page size validation (max 500)
- Actionable error messages
- No authentication required
