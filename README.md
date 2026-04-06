# gsa-perdiem-mcp

MCP server for the GSA Per Diem Rates API. Federal travel lodging and M&IE rates for IGCEs and travel cost estimation.

Works without configuration using DEMO_KEY. Optional free API key for higher rate limits.

## What it does

Exposes the GSA Per Diem API as 6 MCP tools:

**Core lookups**
- `lookup_city_perdiem` - Rates by city/state (auto-selects best NSA match)
- `lookup_zip_perdiem` - Rates by ZIP code
- `lookup_state_rates` - All NSA rates for a state
- `get_mie_breakdown` - M&IE tier table (meal components)

**Workflow**
- `estimate_travel_cost` - Calculate trip per diem (lodging + M&IE with first/last day at 75%)
- `compare_locations` - Compare rates across multiple cities

## Authentication (optional)

Works immediately with DEMO_KEY (~10 req/hr). For 1,000 req/hr, register free at [api.data.gov/signup](https://api.data.gov/signup/) and set `PERDIEM_API_KEY` in your config.

## Installation

```bash
uvx gsa-perdiem-mcp
```

## Claude Desktop configuration

Without key (works immediately):
```json
{
  "mcpServers": {
    "gsa-perdiem": {
      "command": "uvx",
      "args": ["gsa-perdiem-mcp"]
    }
  }
}
```

With key:
```json
{
  "mcpServers": {
    "gsa-perdiem": {
      "command": "uvx",
      "args": ["gsa-perdiem-mcp"],
      "env": {
        "PERDIEM_API_KEY": "your-api-data-gov-key"
      }
    }
  }
}
```

## Example prompts

- "What's the per diem rate for Washington DC in FY2026?"
- "Estimate travel costs for 4 nights in Boston in March."
- "Compare per diem rates for DC, New York, and San Francisco."
- "What are all the NSA per diem locations in Virginia?"
- "Show me the M&IE meal breakdown for the $92 tier."
- "Build a travel estimate: 3 trips to Seattle (4 nights each) and 2 trips to DC (3 nights each)."

## Important: maximum reimbursement, not actual prices

Per diem rates are federal reimbursement ceilings per 41 CFR 301-11. They are not actual hotel prices. CONUS only. OCONUS rates are from the State Department. Lodging taxes generally not included. First/last travel day M&IE at 75%.

## Companion tools

Use alongside `bls-oews-mcp` (wage data) and `gsa-calc-mcp` (ceiling rates) for complete IGCE development. Per diem covers the travel component; BLS and CALC+ cover labor.

## License

MIT
