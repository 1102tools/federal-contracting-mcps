# Changelog

## 0.1.0
Initial release.

- 13 MCP tools covering the eCFR API (admin, versioner, search endpoints)
- Core: get_latest_date, get_cfr_content, get_cfr_structure, get_version_history, get_ancestry, search_cfr, list_agencies, get_corrections
- Workflows: lookup_far_clause, compare_versions, list_sections_in_part, find_far_definition, find_recent_changes
- Server-side XML parsing (Claude never sees raw XML, only clean text with headings, paragraphs, and citations)
- Automatic date resolution (prevents 404s from eCFR's 1-2 day lag)
- Search defaults to current-only (prevents historical version duplicates)
- Actionable error translation for 400/404/406 responses
- No authentication required
