# Changelog

## 0.1.0 (2026-04-05)

Initial release.

- 9 MCP tools covering the Federal Register API
- Core: search_documents, get_document, get_documents_batch, get_facet_counts, get_public_inspection, list_agencies
- Workflows: open_comment_periods, far_case_history (with term-search fallback)
- Flexible search conditions: agency, type, term, docket ID, RIN, publication/comment/effective date ranges, correction flag, significance flag
- Public inspection client-side filtering (API does not support server-side)
- Default field set covering the most common document metadata
- Actionable error messages for 404/422/429
- No authentication required
