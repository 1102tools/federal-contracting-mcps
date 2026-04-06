# regulationsgov-mcp

MCP server for the Regulations.gov API. Federal rulemaking dockets, proposed rules, final rules, public comments, and comment period tracking.

Optional free API key for higher rate limits.

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

## Authentication (optional)

Works with DEMO_KEY (40 req/hr). Register free at [open.gsa.gov](https://open.gsa.gov/api/regulationsgov/#getting-started) for 1,000 req/hr.

## Installation

```bash
uvx regulationsgov-mcp
```

## Claude Desktop configuration

Without key:
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

With key:
```json
{
  "mcpServers": {
    "regulationsgov": {
      "command": "uvx",
      "args": ["regulationsgov-mcp"],
      "env": {
        "REGULATIONS_GOV_API_KEY": "your-api-key"
      }
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
