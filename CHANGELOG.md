# Changelog

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
