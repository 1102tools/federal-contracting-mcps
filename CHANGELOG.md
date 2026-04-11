# Changelog

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
