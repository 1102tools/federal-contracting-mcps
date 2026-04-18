# Changelog

## 0.2.0
Hardening release. Fixes 18 bugs across all 8 tools, including a P0 pydantic
crash on `list_agencies` that blocked the tool from ever being called.

### Crash fix
- `list_agencies`: return type declared `dict[str, Any]` but API returned a
  list, causing pydantic validation to crash on every call. Wrapped response in
  `{total_agencies, returned, query, include_detail, agencies}`.

### Silent-wrong-data and runaway payload fixes
- `list_agencies`: full dump was ~700KB. Added `query` filter (case-insensitive
  substring match on name, short_name, slug) and slim-field default
  (id/name/short_name/slug/parent_id). Full detail available via
  `include_detail=True`.
- `get_public_inspection`: added `limit` param (default 50, max 500).
  Previously could return 170KB+ unfiltered.
- `open_comment_periods`: added `limit` param (default 50, max 100).
  Previously hardcoded `per_page=100` returning ~188KB.
- `far_case_history`: requires minimum `docket_id` length of 3. Previously
  `docket_id='x'` returned 65 unrelated docs via 1-char substring match.
- `get_documents_batch`: each document number now validated against
  `YYYY-NNNNN` or `CN-YYYY-NNNNN` regex. Previously empty-string entries
  became `,,` in the URL and returned all 10,000 docs.
- `search_documents`: clamped `term`, `docket_id`, `regulation_id_number`
  length (500/200/50 chars). Previously 10k-char term triggered HTTP 414
  with raw HTML leak.
- `search_documents`: lowered `per_page` cap from 1000 to 100 to stay within
  MCP response size budgets.

### Validation gaps closed
- `search_documents` and `get_facet_counts`: pub/comment/effective date
  ranges validated to `YYYY-MM-DD`, reversed ranges rejected, empty list
  filters (`agencies=[]`, `doc_types=[]`) rejected explicitly.
- `get_facet_counts`: requires at least one filter (previously unfiltered
  queries returned all-time aggregates).
- `search_documents`: whitespace-only `term`/`docket_id`/`regulation_id_number`
  normalize to `None` instead of being sent as `"+++"` filters.
- `get_document` and `get_documents_batch`: document number format validated
  (prevents confusing 404s from `#`, `?`, `&`, `/`, spaces).
- `search_documents` + `get_facet_counts`: `pub_date_gte` before 1994-01-01
  raises with actionable message (FR API has no pre-1994 data).
- `list_agencies`: empty-string and whitespace-only `query` both normalize
  to `None`.
- `get_public_inspection`: `agency_filter=''` / `keyword_filter=''` normalize
  to `None`.

### Error hygiene
- `_format_error` wraps bodies in `_clean_error_body` which strips HTML and
  extracts title/h1 text. Added HTTP 414 handler. Rewrote 404 message to be
  endpoint-agnostic.

### Release automation
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` triggers test,
  build, and PyPI publish via Trusted Publisher (no tokens).
- `constants.USER_AGENT` bumped to 0.2.0.

### Tests
- New `tests/test_validation.py` with 43 tests, all through the FastMCP
  registry (`mcp.call_tool`). The prior `stress_test.py` awaited raw
  coroutines and bypassed pydantic, which is why the `list_agencies` crash
  shipped in 0.1.x.

## 0.1.0
Initial release.

- 9 MCP tools covering the Federal Register API
- Core: search_documents, get_document, get_documents_batch, get_facet_counts, get_public_inspection, list_agencies
- Workflows: open_comment_periods, far_case_history (with term-search fallback)
- Flexible search conditions: agency, type, term, docket ID, RIN, publication/comment/effective date ranges, correction flag, significance flag
- Public inspection client-side filtering (API does not support server-side)
- Default field set covering the most common document metadata
- Actionable error messages for 404/422/429
- No authentication required
