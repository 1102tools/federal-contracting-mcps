# Changelog

## 0.2.0

First hardening pass. Live audit with a real api.data.gov key surfaced
22 findings: 1 P0, 10 P1, 7 P2, 4 P3. All fixed.

### P0: unknown-param silent-drop (cross-fix)
- FastMCP tools register pydantic arg models with `extra='ignore'` by
  default, so a typo like `search_documents(keyword='audit')` (real
  param is `search_term`) succeeded with the typo silently discarded
  and ran with no filter. This is the same bug found during the
  sam-gov-mcp 0.3.1 live audit and patched across every other MCP.
  Now every tool has `extra='forbid'` applied after registration.

### P1 silent-wrong-data fixes
- `agency_id=""` returned **all 1,951,938 Regulations.gov documents**.
  The empty string was treated as "no filter." Now explicitly rejected
  with an error pointing out the surprise behavior.
- Unknown agency IDs (`"ZZZ"`, `"FAR DOD"`) silently returned 0 results
  with no warning. Now rejected by format validation, and agencies that
  do make it through but return 0 get a `no_data: true` +
  `no_data_reason` flag.
- Null byte and other control characters in `search_term` were passed
  through to the API. Now rejected up front.
- `<script>` in `search_term` triggered the WAF with HTTP 403, but
  the server reported "API key rejected" -- misleading auth error.
  403 handler now inspects the body to distinguish WAF blocks from
  auth failures.
- Date ranges where `ge > le` silently returned 0. Now rejected with
  "ge bound must be <= le bound."
- Dates in ISO 8601 (`2025-01-01T00:00:00Z`), slash format
  (`2025/01/01`), and invalid calendars (`2025-02-30`) reached the
  API as 400s. Now pre-validated with a real calendar check.
- `last_modified_date` quirk (`YYYY-MM-DD HH:MM:SS` space-separated)
  pre-validated so typos surface locally.
- `document_id` / `docket_id` / `comment_id` with slashes produced
  HTTP 500 or 301 redirects from the API. Now rejected up front.
- Sort fields pre-validated against known whitelists per tool
  (documents, comments, dockets) instead of round-tripping to 400.
- `_get` now defends against None / non-dict API responses and
  JSON-decode failures (ports the helper set from bls-oews / ecfr).

### P2 validation
- `page_size` now also rejects bools and non-int values up front.
- `page_number` bounds enforced locally (1-20; API caps total results
  around 5,000 = 20 pages at page_size=250).
- `search_term` length-clamped to 500 chars.
- `open_comment_periods(agency_ids=[])` rejected instead of silently
  falling through to the default list.
- `agency_ids` list pre-validated per-element.
- `_clean_error_body` strips HTML title/h1 from upstream error bodies
  instead of dumping raw HTML into the error message.

### Release automation
- Added `.github/workflows/publish.yml` for PyPI via Trusted Publisher
  on tag `v*.*.*`. Matches the pattern on the other 7 shipped MCPs.
- Added `[dependency-groups].dev` with pytest + pytest-asyncio.
- USER_AGENT bumped to `regulationsgov-mcp/0.2.0`.

### Round 3 enhancement: paged-past-end differentiation
- A subsequent deep-stress live round (40+ probes) found that callers
  who paginate past the last page (e.g. `page_number=20` at
  `page_size=250` against a 2,152-record collection) got an empty
  `data: []` with no flag. Now emits `paged_past_end: true` + a
  `paged_past_end_reason` that tells the caller exactly which page was
  the last with data. The `no_data` flag continues to fire only when
  `totalElements` is 0 (truly no matches).

### Testing
- `tests/test_validation.py` with 51 tests (46 offline + 5 live gated
  by `REGULATIONS_LIVE_TESTS=1`). Covers every validator, all response-
  shape defense paths, the paged-past-end vs no-data differentiation,
  and regression tests for every round-1 and round-3 finding.
- The older `stress_test.py` awaited raw coroutines and bypassed
  pydantic, which is why the 0.1.1 release looked clean. Kept for
  reference, not run by CI.

## 0.1.0
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
