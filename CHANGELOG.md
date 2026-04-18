# Changelog

## 0.2.0
Hardening release. Five audit rounds surfaced 40+ issues; this release closes
12 crash paths and 12 silent-wrong-data bugs, plus validation gaps across every
tool.

### Crash fixes (previously crashed on unusual BLS response shapes)
- `series` or `data` returned as dict instead of list (XML-to-JSON single-item
  collapse). Added `_as_list` normalizer; all response walks now tolerate both
  shapes.
- Entry missing `value`, `year`, `periodName`, or `seriesID` keys now handled
  via `.get()` with safe defaults.
- `footnotes` returned as dict or string (instead of list) handled via
  `_safe_footnotes`.
- `data` array containing `None` entries, or `series` list with `None` items,
  now skipped defensively.
- `seriesID` returned as int now coerced to str before `[-2:]` slicing.
- BLS returning 200 OK with non-JSON body (HTML error page, empty body) now
  raises a clean `RuntimeError` instead of `JSONDecodeError`.

### Silent wrong-data fixes
- `compare_metros`, `compare_occupations`: `occ_code` now enforced to 6 ASCII
  digits. Previously dashed (`"15-1252"`) and alpha (`"ABCDEF"`) codes passed
  through, producing confusing "No data" responses.
- `_normalize_area`: enforces ASCII-digit-only area codes. Previously `"VA"`
  became `"VA00000"` and silently returned no data.
- `industry` param: same ASCII-digit enforcement.
- `DATATYPE_LABELS`: fixed semantic bug. Datatype `"08"` was labeled "Hourly
  Median" but BLS data proves it is Hourly 25th Percentile. Datatype `"09"` is
  the true Hourly Median. Added missing labels for `07`, `09`, `10`, `16`.
- Bogus datatypes (`"99"`, `"AA"`) now rejected with actionable error.
- `year` parameter: range-validated (1997 through 2100). Decimals, whitespace,
  leading zeros, and letters all rejected.
- `_parse_value`: strips whitespace before comparing against SPECIAL_VALUES.
  `"  *  "` now correctly marked suppressed instead of "Unparseable".
- `BLS_API_KEY` whitespace-only value now flagged via `_api_key_status()` helper.
- Python's `.isdigit()` accepts fullwidth Unicode digits; replaced with
  ASCII-only regex.
- `REQUEST_PARTIALLY_PROCESSED` status now surfaces `_partial: True` and
  `_warnings: [...]` in the response. Previously treated as success.
- `scope='national'` with `area_code` provided: area_code now flagged as
  ignored via `_note` field instead of being silently dropped.
- Mismatched series ID in response: defensive fallback keeps user-friendly
  labels when BLS echoes a different ID.

### Validation + UX
- `igce_wage_benchmark`: burden multipliers now validated. Rejects
  `burden_low > burden_high`, non-positive, and implausibly large (>10) values.
- `compare_metros` / `compare_occupations`: input lists deduped before building
  series IDs (saves BLS quota).
- All tools accept int or str for `occ_code`, `area_code`, `year`, `industry`,
  `datatype` (was str-only; users naturally pass `2024` as int).
- `_format_error` strips HTML from 5xx bodies via `_clean_error_body`.
- `detect_latest_year` no longer silently swallows exceptions. Probe errors
  (rate limit, auth, network) now surface in `probe_error` field.
- `USER_AGENT` bumped to 0.2.0.

### Tests and release automation
- New `tests/test_validation.py` with 52 tests, all through the FastMCP
  registry (`mcp.call_tool`) so pydantic coercion runs as in production. The
  prior `stress_test.py` awaited raw coroutines, which is why the round-3/4/5
  crash paths shipped in 0.1.x.
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` runs tests, builds,
  and publishes to PyPI via Trusted Publisher (no tokens).

## 0.1.0
Initial release.

- 7 MCP tools covering the BLS OEWS API
- Core: get_wage_data, compare_metros, compare_occupations
- Workflows: igce_wage_benchmark (with burden multiplier), detect_latest_year
- Reference: list_common_soc_codes, list_common_metros
- 25-character series ID builder with component validation
- Area code normalization (2-digit FIPS, 5-digit MSA, 7-char full)
- Special value handling (wage caps, suppressed data, small samples)
- v1/v2 API auto-selection based on key presence
- Actionable error messages for rate limits, invalid keys, bad series IDs
- Industry-scope validation (industry breakdowns national only)
- Authentication via optional BLS_API_KEY environment variable
