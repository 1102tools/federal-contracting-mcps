# sam-gov-mcp

<!-- mcp-name: io.github.1102tools/sam-gov-mcp -->

MCP server for SAM.gov entity registration, exclusion/debarment, contract opportunity, contract award, federal hierarchy, and FFATA subaward data.

Requires a free SAM.gov API key. Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Cline, Continue, Zed, etc.).

*Tested and hardened through eight audit rounds plus live audits with a real SAM.gov key. 1,094 regression tests. v0.4 added 278 tests for Federal Hierarchy + FFATA Subaward endpoints (123 live), catching three silently-ignored Subaward API parameter casings during live audit. Birthplace of the `extra='forbid'` cross-fix applied to all 8 MCPs in the suite. See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes seven SAM.gov REST APIs as 19 MCP tools:

**Entity Management (v3)**
- `lookup_entity_by_uei` - Single UEI lookup with configurable response sections
- `lookup_entity_by_cage` - CAGE code lookup
- `search_entities` - Flexible entity search (NAICS, PSC, business type, state, name, etc.)
- `get_entity_reps_and_certs` - FAR/DFARS reps and certs (must be requested explicitly)
- `get_entity_integrity_info` - FAPIIS proceedings data

**Exclusions (v4)**
- `check_exclusion_by_uei` - Single-UEI debarment check
- `search_exclusions` - Broader exclusion search by name, classification, program, agency, date

**Contract Opportunities (v2)**
- `search_opportunities` - Search contract opportunities with full working filter set
- `get_opportunity_description` - Fetch the HTML description by notice ID

**Contract Awards (v1) -- FPDS replacement**
- `search_contract_awards` - Search contract award records (vendor, agency, NAICS, dates, dollars, set-aside, etc.)
- `lookup_award_by_piid` - Look up all modifications for a single PIID
- `search_deleted_awards` - Search deleted award records for audit trails

**Federal Hierarchy (v1)**
- `search_federal_organizations` - Search the FH for departments, agencies, sub-agencies, offices (filter by FH org id, name, type, status, agency code, CGAC)
- `get_organization_hierarchy` - Walk the children of a federal organization

**Acquisition Subaward Reporting (FFATA subcontracts)**
- `search_acquisition_subawards` - Search FFATA subcontract reports (prime/sub relationships, agency, dates, status)

**Assistance Subaward Reporting (FFATA grant subawards)**
- `search_assistance_subawards` - Search FFATA grant subaward reports (FAIN, prime award key, agency, dates)

**PSC Lookup**
- `lookup_psc_code` - Resolve a PSC code to its full record
- `search_psc_free_text` - Free-text PSC discovery

**Composite workflow**
- `vendor_responsibility_check` - One-shot FAR 9.104-1 check (entity + exclusions in a single tool call)

## Authentication

Requires a SAM.gov API key set via the `SAM_API_KEY` environment variable.

Get a free key at [sam.gov/profile/details](https://sam.gov/profile/details) under "Public API Key."

| Account Type | Daily Limit |
|---|---|
| Non-federal, no SAM role | 10/day |
| Non-federal with SAM role | 1,000/day |
| Federal personal | 1,000/day |
| Federal system account | 10,000/day |

**Important: SAM.gov API keys expire every 90 days.** Regenerate at the same profile page and update your env var. This server returns a clear actionable error on 401/403 with regeneration instructions.

## Installation

### Via uvx (recommended)

```bash
uvx sam-gov-mcp
```

### Via pip

```bash
pip install sam-gov-mcp
```

### From source

```bash
git clone https://github.com/1102tools/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/sam-gov-mcp
pip install -e .
```

## Claude Desktop configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "sam-gov": {
      "command": "uvx",
      "args": ["sam-gov-mcp"],
      "env": {
        "SAM_API_KEY": "SAM-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Claude Desktop. The server appears in your MCP tools panel.

## Example prompts

Once configured:

- "Look up Leidos Inc in SAM.gov by UEI QVZMH5JLF274. Check registration status, business types, and whether they have any active exclusions."
- "Find active SDVOSB firms in Virginia with primary NAICS 541512 that are currently registered in SAM."
- "Do a full responsibility check on UEI E1K4E4A29SU5 and tell me whether I can award."
- "Search for all sources sought notices posted in the last 30 days with NAICS 541512."
- "Show me SDVOSB set-aside solicitations for IT services posted this quarter."
- "Get the full description of notice ID [paste ID] and summarize the SOW."
- "Search active exclusions where the excluded party name starts with 'acme'."
- "Search contract awards for Booz Allen Hamilton in fiscal year 2026."
- "Look up all modifications for PIID W912BV22P0112."
- "Find all SDVOSB set-aside contract awards signed this year with NAICS 541512."
- "Show me deleted contract award records for Department of Defense."
- "Find the Federal Hierarchy ID for the Department of the Treasury and walk one level of children."
- "What sub-tier organizations roll up under DoD (FH org id 100000000)?"
- "Show me FFATA subcontracts on prime PIID W912QR25C0022."
- "Pull all subawards reported under grant FAIN FA86502125028."
- "List the agency-level orgs in CGAC 075 (HHS)."

## Design notes

- **Authentication via env var only.** `SAM_API_KEY` is read from the environment on every call. The key never enters Claude's conversation context.
- **90-day expiration awareness.** 401/403 errors are translated into an actionable "regenerate at sam.gov/profile/details" message with full context.
- **API quirks baked in as safety rails.**
  - Entity Management hard cap of size=10 is enforced client-side with a clear error
  - Exclusions uses `size` not `limit` (different from other SAM endpoints)
  - Country codes are validated as 3-character ISO alpha-3 (2-char codes return 0 silently)
  - No `Accept: application/json` header is set (Exclusions returns 406 if present)
  - Bracket/tilde/exclamation characters are preserved in query strings for multi-value params
- **Post-filtering for broken parameters.** The Opportunities API silently ignores `deptname` and `subtier` filters. `search_opportunities` exposes an `agency_keyword` parameter that post-filters results by matching `fullParentPathName` substring.
- **includeSections defaults.** Entity lookups default to `entityRegistration,coreData`. Always include `entityRegistration` alongside any other section or the response has no identification. `repsAndCerts` and `integrityInformation` require explicit tool calls (`get_entity_reps_and_certs`, `get_entity_integrity_info`) because even `includeSections=All` doesn't include them.
- **Contract Awards response normalization.** The Contract Awards API returns different JSON wrapper shapes for populated vs. empty results. All tools normalize this to a consistent `{"awardSummary": [...], "totalRecords": int}` shape. Error responses are plain text (not JSON), detected and raised as actionable errors.
- **Contract Awards pagination.** Uses `limit`/`offset` (NOT `page`/`size` like Entity Management). Max limit is 100. Dates must be MM/dd/yyyy format with bracket ranges `[MM/dd/yyyy,MM/dd/yyyy]`.
- **Composite workflow.** `vendor_responsibility_check` collapses a typical FAR 9.104-1 check (entity registration + exclusion lookup) into one tool call, returning a structured flags list for downstream reasoning.
- **Federal Hierarchy quirks baked in.**
  - Lowercase `totalrecords` and `orglist` keys (rest of SAM.gov uses camelCase); normalizer preserves both
  - Default response is ACTIVE-only; passing `status=ACTIVE` is a no-op vs. the unfiltered call. Pass `INACTIVE` to expand to retired orgs
  - Real `fhorgtype` values look like `Department/Ind. Agency`, but the API also accepts shorthand (DEPARTMENT, AGENCY) with case-insensitive matching
- **Subaward Reporting quirks baked in.**
  - Dates use ISO `yyyy-MM-dd` (NOT `MM/dd/yyyy` like Contract Awards). Mixing them raises a clear pre-network validation error
  - Pagination uses `pageNumber`/`pageSize` (NOT `page`/`size` or `limit`/`offset`)
  - Live audit (April 2026) found three documented parameter casings are silently ignored: `PIID` is dropped (use lowercase `piid`), `referencedIdvPIID` is dropped (use `referencedIDVPIID`), and `referencedIDVAgencyID` is dropped (use `referencedIDVAgencyId`). Wire-level names are now correct in the server

## Part of

[federal-contracting-mcps](https://github.com/1102tools/federal-contracting-mcps) — monorepo of 8 MCP servers for federal contracting data. Companion to [federal-contracting-skills](https://github.com/1102tools/federal-contracting-skills).

## License

MIT
