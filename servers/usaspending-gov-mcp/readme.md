# usaspending-gov-mcp

MCP server for the USASpending.gov federal contract and award data API.

No API key required. Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Cline, Continue, Zed, etc.).

*Tested and hardened through four rounds of integration testing against the live USASpending.gov API. 807 regression tests covering 10 P1 silent-wrong-data bugs and 5 P2 validation gaps fixed. See [TESTING.md](TESTING.md) for the full testing record.*

## What it does

Exposes the USASpending.gov REST API as 17 MCP tools covering:

**Search and aggregation**
- `search_awards` - Primary search for contracts, IDVs, grants, loans, direct payments
- `get_award_count` - Dimensional counts across award categories
- `spending_over_time` - Time series aggregation (fiscal year, quarter, month)
- `spending_by_category` - Top N breakdowns by agency, vendor, NAICS, PSC, state, etc.

**Award detail**
- `get_award_detail` - Full record for a single award
- `get_transactions` - Full modification history for an award
- `get_award_funding` - File C funding data (Treasury account, object class, program activity)
- `get_idv_children` - Task/delivery orders under an IDV

**Workflow convenience**
- `lookup_piid` - Auto-detects contract vs IDV and returns the matching award

**Autocomplete**
- `autocomplete_psc` - Product/Service Code lookup
- `autocomplete_naics` - NAICS code lookup

**Reference data**
- `list_toptier_agencies` - All federal agencies
- `get_agency_overview` - Agency summary by toptier code and fiscal year
- `get_agency_awards` - Agency award totals by category
- `get_naics_details` - NAICS code details (2-6 digit)
- `get_psc_filter_tree` - PSC hierarchy, drillable
- `get_state_profile` - State-level spending profile by FIPS code

## Installation

### Via pip

```bash
pip install usaspending-gov-mcp
```

### Via uvx (recommended, no venv needed)

```bash
uvx usaspending-gov-mcp
```

### From source

```bash
git clone https://github.com/1102tools/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/usaspending-gov-mcp
pip install -e .
```

## Claude Desktop configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "usaspending": {
      "command": "uvx",
      "args": ["usaspending-gov-mcp"]
    }
  }
}
```

If you installed via `pip install -e .` or a regular `pip install`:

```json
{
  "mcpServers": {
    "usaspending": {
      "command": "python",
      "args": ["-m", "usaspending_gov_mcp.server"]
    }
  }
}
```

Restart Claude Desktop. The server should appear in the MCP tools panel.

## Claude Code configuration

Add to `~/.claude.json` or your project's `.claude.json`:

```json
{
  "mcpServers": {
    "usaspending": {
      "command": "uvx",
      "args": ["usaspending-gov-mcp"]
    }
  }
}
```

## Example prompts

Once configured, try:

- "Show me the top 10 NAVSEA contracts awarded in FY2025 by dollar value."
- "Find all software development contracts at NASA with sole-source justifications in the last year."
- "How much has Leidos received in federal awards since 2020? Group by fiscal year."
- "What are the top 15 recipients of HUBZone set-aside contracts at DoD?"
- "Pull the full modification history for PIID N00024-24-C-0085."
- "Compare FFP vs T&M award counts for IT services at Air Force in FY2024."

## Design notes

- **No authentication required.** USASpending.gov is a free, public API.
- **Award type groups cannot be mixed.** The `award_type` parameter takes one of: `contracts`, `idvs`, `grants`, `loans`, `direct_payments`, `other`. Use separate calls for separate categories.
- **Actionable error messages.** Common API errors (422 mixed award types, 400 sort field missing, 400 empty keywords) are translated into guidance for the calling LLM.
- **Sort field auto-handling.** The USASpending API requires the sort field to appear in the fields array; this server adds it automatically.
- **Sensible defaults.** Search limits default to 25 (API max 100). Default fields cover the most common columns for each award category.
- **Flat filter parameters.** Most common filters are surfaced as named parameters (`keywords`, `awarding_agency`, `naics_codes`, etc.) rather than a nested filter dict, for better LLM tool discovery.

## Data source

All data is sourced from [USASpending.gov](https://www.usaspending.gov), which aggregates FPDS-NG contract data, FAADC assistance data, and agency DATA Act submissions. Data freshness varies by agency: non-DoD contract data is typically available within 5 business days, DoD and USACE procurement data has a 90-day reporting delay in FPDS, and financial assistance data is available within 2 days of submission.

## License

MIT
