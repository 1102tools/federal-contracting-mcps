# Changelog

## 0.2.0

Hardening pass. Deep audit surfaced 72 issues across five rounds (2 P0, 26 P1,
32 P2, 12 P3). All fixed.

### Crash fixes (P0)
- `search_cfr` was silently ignoring every filter: query, title, chapter,
  part, subpart, section, current_only, date filters, per_page, page. The
  tool built the query string into the URL path and then passed `params={}`
  to httpx, which strips the existing query string. Every call returned a
  random default 20-result set of all-CFR content. Fixed by passing params
  as a proper dict.
- `find_recent_changes` delegates to `search_cfr` and inherited the same
  P0. `since_date` is now actually applied.

### Crash fixes (P1)
- `_resolve_date` crashed on reserved titles (up_to_date_as_of is null).
  Returns a clear "title is reserved" error instead of building a URL
  containing the literal string "None".
- `_resolve_date` crashed on API response shape variance: titles as a
  non-list, individual entries as None or non-dict, missing `number` field,
  `number` as a string instead of int. All handled defensively now.
- `_walk_structure` crashed on `children: None`, dict children, or null/
  non-dict child entries. Defensive for each.
- `_parse_xml_to_text` crashed on non-string input (bytes, None, int).
  Handled.
- `_get_json` leaked raw `JSONDecodeError` when the API returned HTML
  (maintenance page, 404 HTML), empty body, truncated body, or binary.
  Now raises a descriptive RuntimeError with content-type and body preview.
- `_format_error` crashed on bytes body (`.lower()`). Now safely coerces.

### Silent wrong-data fixes (P1)
- `get_cfr_content` with `section=""` or whitespace previously returned
  the entire 23.2 MB title XML. Now requires at least one of section/
  subpart/part/chapter.
- `lookup_far_clause` with empty `section_id` had the same 23 MB bomb.
  Now rejects empty.
- `find_far_definition` with empty term matched every paragraph (437 KB).
  With term="the" matched 358 paragraphs (327 KB). Now requires
  minimum 3 chars and paginates with `max_matches` (default 20, cap 100).
- `get_cfr_content` with unknown `chapter` (e.g. "0", "27") silently
  returned the full title. Chapter is now validated against
  TITLE_48_CHAPTERS when title=48.
- `list_agencies` returned ~100 KB. Added `summary_only` mode (default
  True) that strips deep `children` trees and non-essential fields,
  dropping payload to ~30 KB.
- `get_corrections` returned all 283 corrections (109 KB). Added `limit`
  (default 50, max 1000) and `since_year` filters.
- `_parse_xml_to_text` didn't HTML-unescape the heading or citations.
  `&amp;`, `&lt;`, `&gt;`, numeric entities now correctly decoded
  alongside paragraphs.
- Regex matching was case-sensitive; mixed-case `<head>`, `<p>`, `<cita>`
  tags were silently dropped. Now case-insensitive. Attribute-bearing
  tags like `<HEAD class="x">` now also match.
- `_parse_xml_to_text` did not strip HTML comments (content leaked through).
  Now stripped before paragraph extraction. CDATA content preserved.

### Validation (P2)
- `date` now validated as YYYY-MM-DD with real calendar check on every
  tool that takes one: `get_cfr_content`, `get_cfr_structure`,
  `get_ancestry`, `compare_versions`, `list_sections_in_part`,
  `find_far_definition`, `find_recent_changes`, search date filters.
  Rejects `""`, whitespace, `2026/04/16`, `April 16, 2026`, ISO 8601
  timestamps, and `"current"` with actionable messages.
- `part`, `subpart`, `section` accept `int` or `str` on every tool.
  Previous pydantic str-only rejection of `part=15` was a frequent
  LLM-calls-tool pain point. Handoff-known issue for get_ancestry and
  get_cfr_structure, extended to version_history and list_sections_in_part.
- Common user mistakes like `section="FAR 15.305"`, `"48 CFR 15.305"`,
  `" 15.305 "`, `"DFARS 252.204-7012"` are now normalized to the bare
  identifier rather than hitting the API as a 404.
- `title_number` / `title` validated as int 1-50.
- `search_cfr.query` rejects empty, whitespace, null byte, and strings
  over 500 chars.
- `search_cfr.per_page` and `.page` now bounds-checked (>= 1).
- `get_corrections.limit` bounds-checked (1-1000).
- `find_far_definition.term` requires minimum 3 characters.
- `find_far_definition.max_matches` bounds-checked (1-100).
- `compare_versions` now rejects identical dates with a "nothing to
  compare" error instead of silently returning two identical blocks.
- Null byte / newline / tab rejected in all coerced identifier strings.
- Strings over 120 chars rejected in identifier fields (catches
  pathological LLM inputs).
- `get_cfr_content` requires at least one scope filter (no more
  accidental whole-title fetches).

### Polish (P3)
- `_get_client` now re-creates the client if it was closed, protecting
  against multi-event-loop test harnesses.
- `_clean_error_body` helper strips HTML title/h1 from upstream HTML
  error pages instead of including raw HTML in error messages.
- XML decl and other processing instructions stripped before parsing.
- `USER_AGENT` bumped to 0.2.0.
- Error messages on 429/5xx now include retry guidance.

### Release automation
- Added `.github/workflows/publish.yml` for PyPI publishing via GitHub
  Trusted Publisher on tag `v*.*.*`.
- Added `[dependency-groups].dev` with pytest + pytest-asyncio.

### Testing
- New `tests/test_validation.py` with 101 tests. 88 offline tests cover
  every validator, response-shape defense, and XML parser edge case,
  plus the full HTTP-layer mocked error paths. 13 live tests (guarded
  by `MCP_LIVE_TESTS=1`) verify P0 regression: search filters now reach
  the API, int parts are accepted, reserved titles return clear errors,
  and list_agencies summary is under 50 KB.
- The older `stress_test.py` / `stress_test_r2.py` / `stress_test_r3.py`
  are kept for regression reference but not run by CI. They called tools
  as raw coroutines and bypassed pydantic, which is why the round 1
  smoke test said "0 bugs found".

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
