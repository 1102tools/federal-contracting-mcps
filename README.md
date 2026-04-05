# sam-gov-mcp

MCP server for SAM.gov entity registration, exclusion/debarment, and contract opportunity data.

Requires a free SAM.gov API key. Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Cline, Continue, Zed, etc.).

## What it does

Exposes three SAM.gov REST APIs plus the PSC lookup as 13 MCP tools:

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
git clone https://github.com/1102tools/sam-gov-mcp.git
cd sam-gov-mcp
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
- **Composite workflow.** `vendor_responsibility_check` collapses a typical FAR 9.104-1 check (entity registration + exclusion lookup) into one tool call, returning a structured flags list for downstream reasoning.

## Companion skill

This MCP mirrors the `sam-gov-api` skill from [1102tools.com](https://1102tools.com). The skill is markdown-based and runs in any Claude surface; the MCP wraps the same API surface as deterministic tool calls for agent workflows, automation, and Claude.ai web client use.

## License

MIT
