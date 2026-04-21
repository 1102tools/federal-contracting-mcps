# gsa-perdiem-mcp

MCP server for the GSA Per Diem Rates API. Federal travel lodging and M&IE rates for IGCEs and travel cost estimation.

Works without configuration using DEMO_KEY. Optional free API key for higher rate limits.

*Tested and hardened through six rounds of integration testing against the live GSA Per Diem API, including a round-6 live audit with a real api.data.gov key. 172 regression tests covering 1 P0 path-traversal bug, 23 P1 silent-wrong-data bugs, and 21 P2 validation gaps fixed. See [TESTING.md](TESTING.md) for the full testing record.*

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

## Get your own API key (strongly recommended)

This server hits `api.gsa.gov`, which uses api.data.gov for rate limiting.

- **Without a key**: falls back to the shared `DEMO_KEY` which is capped at
  **~10 requests per hour across everyone using it**. A couple real prompts
  will blow through that limit and you'll start seeing 429 errors.
- **With a personal key**: 1,000 requests per hour, yours alone.

**Get a free key (takes 30 seconds):**

1. Go to [api.data.gov/signup](https://api.data.gov/signup/)
2. Enter your name and email — no approval, no wait
3. Copy the key from the confirmation page
4. Paste it into your Claude Desktop config as `PERDIEM_API_KEY` (see below)

The same key works for every api.data.gov-backed API (GSA Per Diem, NASA,
FEC, FCC, etc.).

## Installation

```bash
uvx gsa-perdiem-mcp
```

## Claude Desktop configuration

**Recommended (with your own key):**
```json
{
  "mcpServers": {
    "gsa-perdiem": {
      "command": "uvx",
      "args": ["gsa-perdiem-mcp"],
      "env": {
        "PERDIEM_API_KEY": "paste-your-api-data-gov-key-here"
      }
    }
  }
}
```

**Without a key** (works for a handful of calls per hour, then 429s until the hour rolls over):
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
