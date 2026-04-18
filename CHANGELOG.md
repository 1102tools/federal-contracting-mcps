# Changelog

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
