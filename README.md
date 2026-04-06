# ecfr-mcp

MCP server for the eCFR (Electronic Code of Federal Regulations) API. Read FAR, DFARS, and all agency FAR supplement text with no authentication required.

Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Cline, Continue, Zed, etc.).

## What it does

Exposes the eCFR API as 13 MCP tools covering regulatory text, structure, search, version history, and common acquisition workflows:

**Core endpoints**
- `get_latest_date` - Get the most recent available date for a CFR title (call before other tools)
- `get_cfr_content` - Get parsed regulatory text for a section, subpart, or part
- `get_cfr_structure` - Hierarchical table of contents
- `get_version_history` - Amendment history for a section or part
- `get_ancestry` - Breadcrumb hierarchy path
- `search_cfr` - Full-text search with hierarchy filters
- `list_agencies` - All agencies with their CFR references
- `get_corrections` - Editorial corrections for a title

**Workflow convenience**
- `lookup_far_clause` - One-call FAR/DFARS clause text lookup (auto-resolves date)
- `compare_versions` - Side-by-side text comparison at two dates
- `list_sections_in_part` - All sections in a FAR/DFARS part
- `find_far_definition` - Search FAR 2.101 for a term definition
- `find_recent_changes` - Sections modified since a given date

## No authentication required

The eCFR API is fully public. No API key, no registration, no auth headers. Just install and use.

## Installation

### Via uvx (recommended)

```bash
uvx ecfr-mcp
```

### Via pip

```bash
pip install ecfr-mcp
```

### From source

```bash
git clone https://github.com/1102tools/ecfr-mcp.git
cd ecfr-mcp
pip install -e .
```

## Claude Desktop configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ecfr": {
      "command": "uvx",
      "args": ["ecfr-mcp"]
    }
  }
}
```

Restart Claude Desktop. The `ecfr` server appears in your MCP tools panel with 13 tools.

## Example prompts

- "Pull the current text of FAR 15.305 (Proposal Evaluation) and summarize what it requires."
- "List all sections in FAR Part 19 (Small Business Programs)."
- "Look up the FAR definition of 'commercial product' in 2.101."
- "What FAR sections were amended in the last 6 months?"
- "Compare FAR 52.212-4 between 2024-01-01 and 2025-01-01 and show me what changed."
- "Get the current text of DFARS 252.227-7014 (Rights in Noncommercial Computer Software)."
- "Search Title 48 for 'organizational conflict of interest' and show me the relevant sections."
- "Which agency owns Chapter 8 in Title 48? Get their FAR supplement structure."

## Design notes

- **XML parsed server-side.** The eCFR content endpoint returns raw XML. This server parses it into clean text (headings, paragraphs, citations) before returning to Claude, saving significant context tokens.
- **Automatic date resolution.** eCFR lags 1-2 business days behind the Federal Register. Using today's date on versioner endpoints causes 404 errors. All content tools auto-resolve to the latest available date unless you specify one.
- **Search defaults to current text.** Without `date=current`, eCFR search returns ALL historical versions including superseded. Default `current_only=True` prevents duplicate results.
- **Structure endpoint limitation.** The eCFR structure endpoint does not support section-level filtering (returns 400). `list_sections_in_part` works around this by fetching the part structure and walking the tree.
- **FAR 2.101 optimization.** The definitions section is ~109KB of XML. `find_far_definition` parses the full section server-side and returns only matching paragraphs with context.

## CFR Title 48 quick reference

| Chapter | Regulation | Parts |
|---|---|---|
| 1 | FAR | 1-99 |
| 2 | DFARS | 200-299 |
| 3 | HHSAR | 300-399 |
| 4 | AGAR | 400-499 |
| 5 | GSAR | 500-599 |
| 6 | DOSAR | 600-699 |
| 7 | AIDAR | 700-799 |
| 8 | VAAR | 800-899 |
| 9 | DEAR | 900-999 |
| 18 | NFS | 1800-1899 |

## Data source

All data from [ecfr.gov](https://www.ecfr.gov), the continuously updated online Code of Federal Regulations maintained by the Office of the Federal Register. Updated daily, typically 1-2 business days after Federal Register publication. Not an official legal edition; for official citations reference the annual CFR from GPO.

## Companion skill

This MCP mirrors the `ecfr-api` skill from [1102tools.com](https://1102tools.com). The skill is markdown-based for interactive Claude use; the MCP wraps the same API as deterministic tool calls for agent workflows and automation.

## License

MIT
