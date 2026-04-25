# usaspending-gov-mcp

MCP server for the USASpending.gov federal contract, award, subaward, recipient, agency, and federal account API.

No API key required. Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Cline, Continue, Zed, etc.).

*Tested and hardened through nine rounds of integration testing against the live USASpending.gov API. v0.3 added 38 new tools and 243 tests across the new endpoints (76 live). See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes the USASpending.gov REST API as 55 MCP tools covering:

**Search and aggregation**
- `search_awards` - Primary search for contracts, IDVs, grants, loans, direct payments
- `get_award_count` - Dimensional counts across award categories
- `spending_over_time` - Time series aggregation (fiscal year, quarter, month)
- `spending_by_category` - Top N breakdowns by agency, vendor, NAICS, PSC, state, etc.
- `spending_by_transaction` - Modification-level transaction search
- `spending_by_geography` - State, county, or congressional district breakdown
- `new_awards_over_time` - Pipeline trend for a recipient

**Award detail**
- `get_award_detail` - Full record for a single award
- `get_transactions` - Full modification history for an award
- `get_award_funding` - File C funding data (Treasury account, object class, program activity)
- `get_award_funding_rollup` - Single-line funding summary
- `get_award_subaward_count`, `get_award_federal_account_count`, `get_award_transaction_count`
- `get_idv_children` - Task/delivery orders under an IDV
- `awards_last_updated` - Data freshness check

**Subawards (FFATA)**
- `search_subawards` - Subawards under a single prime
- `spending_by_subaward_grouped` - Subaward search with full filter set

**Recipients**
- `search_recipients` - Search recipients by keyword
- `get_recipient_profile` - Full recipient record
- `get_recipient_children` - Subsidiaries of a parent recipient
- `autocomplete_recipient` - Find recipient hashes by partial name
- `list_states` - All states with FIPS codes

**Agency depth**
- `list_toptier_agencies`, `get_agency_overview`, `get_agency_awards`
- `get_agency_budgetary_resources` - Budget resources by FY
- `get_agency_sub_agencies` - Subordinate orgs with obligations
- `get_agency_federal_accounts` - Funding sources (TAS)
- `get_agency_object_classes` - Spending categories (OMB)
- `get_agency_program_activities` - Program-level breakdown
- `get_agency_obligations_by_award_category` - Contract vs grant mix

**IDV depth**
- `get_idv_amounts` - Top-line IDV rollup
- `get_idv_funding`, `get_idv_funding_rollup` - File C for IDV
- `get_idv_activity` - Child orders under an IDV

**Federal accounts (Treasury)**
- `list_federal_accounts` - Search TAS
- `get_federal_account_detail`, `get_federal_account_object_classes`,
  `get_federal_account_program_activities`, `get_federal_account_fy_snapshot`

**Autocomplete**
- `autocomplete_psc`, `autocomplete_naics`
- `autocomplete_awarding_agency`, `autocomplete_funding_agency`
- `autocomplete_cfda` (grants), `autocomplete_glossary`, `autocomplete_recipient`

**Reference data**
- `get_naics_details`, `get_psc_filter_tree`
- `get_award_types_reference` - All award type codes (A=BPA Call etc.)
- `get_def_codes_reference` - Disaster Emergency Fund codes (COVID, IIJA, IRA)
- `get_glossary` - Acquisition/spending vocabulary
- `get_submission_periods` - Agency reporting period coverage
- `get_state_profile` - State-level spending profile

**Workflow convenience**
- `lookup_piid` - Auto-detects contract vs IDV and returns the matching award

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
