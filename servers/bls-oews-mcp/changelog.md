# Changelog

## 0.2.2

Live audit with a real BLS API key surfaced 1 P0 usability bug and 10 P1
silent-wrong-data paths that the 0.2.0 / 0.2.1 mocked rounds never caught.

### Usability (P0)
- `occ_code` validator previously rejected the **standard BLS SOC format**
  `15-1252` with "must contain only ASCII digits." Users pasting codes
  directly from bls.gov/soc, BLS publications, or procurement documents
  hit a hard error on every lookup; only the un-dashed `151252` worked.
  Now both forms are accepted and normalized: the dash is stripped
  before validation. Verified live: `occ_code="15-1252"` returns
  Software Developers mean wage $144,570.

### Silent-wrong-data (P1)
- `year` validator allowed 1997-2100, but the BLS OEWS **public API only
  serves the current year** (2024). Asking for 2023 or 2015 returned
  empty rows that the tool reported as `"suppressed": true` -- making it
  look like BLS was censoring the cell for privacy when really the API
  just doesn't serve historical data. Year range now tightened to
  current ± 1, with a clear error pointing users to
  bls.gov/oes/tables.htm for historical data.
- Nonexistent SOC codes (e.g. `99-9999`) returned 4 wage fields all
  flagged `"suppressed": true` with no indication the SOC was fake.
  `igce_wage_benchmark` happily returned a benchmarks table with
  `occ_title: "99-9999"` as if that were the real name. Now every
  `get_wage_data` response includes `no_data: true` + `no_data_reason`
  when all wage values are null, listing the common causes (SOC typo /
  retired code / unsurveyed area + industry).
- `igce_wage_benchmark` now also carries that `no_data` flag up, and
  emits `_title_warning` when the SOC isn't in the built-in title
  lookup (so typos like `99-9999` get called out explicitly).
- Nonexistent state FIPS (`"99"`), metro MSA (`"99999"`), or NAICS
  industry (`"999999"`) all used to return silently-suppressed fields.
  Now flagged with the same `no_data` + `no_data_reason` payload.
- `compare_metros` accepted 2-digit state FIPS mixed into the
  `metro_codes` list. After normalization these became valid-looking
  7-digit series components but silently returned zero results. Now
  raises ValueError: "looks like a 2-digit state FIPS" and points at
  `compare_occupations(scope='state')` instead.

### Validation (P2)
- Single-digit state FIPS (CA=`6`, AK=`2`, etc.) now auto-pads to two
  digits. Previously rejected as "unrecognized area code (length 1)."
  Users commonly know FIPS as `6` not `06`.
- Control characters (`\n`, `\r`, `\t`, `\x00`) in `occ_code` are now
  rejected up front. Previously `strip()` ate the newline and the
  remaining digits validated fine.
- `OEWS_LATEST_FUTURE_YEAR` dropped from 2100 to `OEWS_CURRENT_YEAR+1`
  so years that will never have data are rejected at validation time.

### Release automation
- USER_AGENT bumped to `bls-oews-mcp/0.2.2`.
- 12 new regression tests covering every round-1 finding.

## 0.2.1

Cross-MCP fix discovered during the sam-gov-mcp 0.3.1 live audit.

- FastMCP tools generate pydantic argument models with the default
  `extra='ignore'` config. Unknown parameter names were silently
  dropped: a typo like `get_wage_data(ocupation_code='15-1252')` (the
  real parameter is `occ_code`) succeeded with the typo discarded,
  and the tool ran with an empty / default-filter result set. Now
  every tool has `extra='forbid'` applied after registration, so
  typos raise "Extra inputs are not permitted" before any HTTP call.
- USER_AGENT bumped to `bls-oews-mcp/0.2.1`.
- Added regression test covering the new behavior.

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
