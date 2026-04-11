# Changelog

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
