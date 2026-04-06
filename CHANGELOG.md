# Changelog

## 0.1.0 (2026-04-05)

Initial release.

- 9 MCP tools covering the Regulations.gov API (documents, comments, dockets)
- Core: search_documents, get_document_detail, search_comments, get_comment_detail, search_dockets, get_docket_detail
- Workflows: open_comment_periods (multi-agency scan), far_case_history (docket + all documents)
- Page size validation (5-250 range enforced client-side)
- Case-sensitive filter value documentation in tool descriptions
- Date format asymmetry documented (postedDate vs lastModifiedDate)
- Aggregations always present in search responses for quick counts
- Actionable error messages for 400/403/404/429
- Falls back to DEMO_KEY when no API key configured
