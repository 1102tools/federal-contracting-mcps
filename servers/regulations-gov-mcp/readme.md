# regulationsgov-mcp

MCP server for the Regulations.gov API. Federal rulemaking dockets, proposed rules, final rules, public comments, and comment period tracking.

Optional free API key for higher rate limits.

*Tested and hardened through three rounds of integration testing against the live Regulations.gov API. 51 regression tests covering 1 P0 catastrophic bug, 10 P1 silent-wrong-data bugs (including `agency_id=""` returning all 1,951,938 records), and 7 P2 validation gaps fixed. See [TESTING.md](TESTING.md) for the full testing record.*

## What it does

Exposes the Regulations.gov API as 8 MCP tools:

**Core**
- `search_documents` - Search proposed rules, final rules, notices with flexible filters
- `get_document_detail` - Full document details with optional attachments
- `search_comments` - Search public comments (by docket, document, or keyword)
- `get_comment_detail` - Full comment text and submitter info
- `search_dockets` - Search rulemaking and nonrulemaking dockets
- `get_docket_detail` - Docket metadata, abstract, and RIN

**Workflow**
- `open_comment_periods` - Currently open comment periods across procurement agencies
- `far_case_history` - Full lifecycle of a FAR/DFARS rulemaking case

## Get your own API key (strongly recommended)

This server hits `api.regulations.gov`, which uses api.data.gov for rate
limiting.

- **Without a key**: falls back to the shared `DEMO_KEY` which is capped at
  **40 requests per hour across everyone using it**. A single
  `open_comment_periods` scan across 8 agencies already uses 8 of those 40,
  so you'll hit 429 errors within a couple of prompts.
- **With a personal key**: 1,000 requests per hour, yours alone.

**Get a free key (takes 30 seconds):**

1. Go to [open.gsa.gov/api/regulationsgov/#getting-started](https://open.gsa.gov/api/regulationsgov/#getting-started) (or directly at [api.data.gov/signup](https://api.data.gov/signup/))
2. Enter your name and email — no approval, no wait
3. Copy the key from the confirmation page
4. Paste it into your Claude Desktop config as `REGULATIONS_GOV_API_KEY` (see below)

The same api.data.gov key works for every api.data.gov-backed API
(Regulations.gov, GSA Per Diem, NASA, FEC, FCC, etc.), so if you already
have one for another 1102tools MCP you can reuse it.

## Installation

```bash
uvx regulationsgov-mcp
```

## Claude Desktop configuration

**Recommended (with your own key):**
```json
{
  "mcpServers": {
    "regulationsgov": {
      "command": "uvx",
      "args": ["regulationsgov-mcp"],
      "env": {
        "REGULATIONS_GOV_API_KEY": "paste-your-api-data-gov-key-here"
      }
    }
  }
}
```

**Without a key** (works for a handful of calls per hour, then 429s until the hour rolls over):
```json
{
  "mcpServers": {
    "regulationsgov": {
      "command": "uvx",
      "args": ["regulationsgov-mcp"]
    }
  }
}
```

## Example prompts

- "What FAR cases have open comment periods right now?"
- "Show me the full docket history for FAR-2023-0008."
- "Find all proposed rules from DARS posted in the last 6 months."
- "How many public comments were submitted on FAR Case 2023-008?"
- "Search for rulemaking dockets related to cybersecurity at DoD."
- "Find all SBA rules about size standards from the last year."

## Important: case-sensitive filter values

Regulations.gov filter values are CASE-SENSITIVE. Use exact casing:
- Document types: `Proposed Rule`, `Rule`, `Notice` (not lowercase)
- Docket types: `Rulemaking`, `Nonrulemaking`
- Lowercase values silently return 0 results with no error

## Companion tools

- `federal-register-mcp`: what was published in the Federal Register
- `regulationsgov-mcp`: the docket structure, public comments, and comment period status
- `ecfr-mcp`: what the regulation currently says after amendments

Together these three cover the full regulatory pipeline from proposal through public comment to codified rule.

## License

MIT
