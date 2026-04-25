# bls-oews-mcp

<!-- mcp-name: io.github.1102tools/bls-oews-mcp -->

MCP server for the BLS Occupational Employment and Wage Statistics (OEWS) API. Market wage data for IGCE development, price analysis, and labor market research.

Optional free API key for higher rate limits. Works without a key at reduced limits.

*Tested and hardened through a 5-round retroactive live audit with a real BLS API key after the initial smoke test reported zero bugs. 60 regression tests covering 1 P0 usability-breaking bug (SOC format), 10 P1 silent-wrong-data bugs, 12 P1 response-shape crash paths, and 7 P2 validation gaps fixed. See [TESTING.md](TESTING.md) for the full testing record.*

## What it does

Exposes the BLS OEWS API as 7 MCP tools:

**Core**
- `get_wage_data` - Wage statistics for an occupation by SOC code (national, state, or metro)
- `compare_metros` - Compare wages for one occupation across multiple metro areas
- `compare_occupations` - Compare wages across multiple occupations in one location

**Workflow**
- `igce_wage_benchmark` - Wage benchmarks with burdened rate estimates for IGCE development
- `detect_latest_year` - Check if newer OEWS data has been released

**Reference**
- `list_common_soc_codes` - SOC code mappings for federal IT/professional services
- `list_common_metros` - Metro area MSA codes

## Authentication (optional)

Without a key, the server uses BLS v1 API (25 queries/day). With a key, it uses v2 (500 queries/day). Register free at [data.bls.gov/registrationEngine](https://data.bls.gov/registrationEngine/).

## Installation

```bash
uvx bls-oews-mcp
```

## Claude Desktop configuration

Without key:
```json
{
  "mcpServers": {
    "bls-oews": {
      "command": "uvx",
      "args": ["bls-oews-mcp"]
    }
  }
}
```

With key (recommended):
```json
{
  "mcpServers": {
    "bls-oews": {
      "command": "uvx",
      "args": ["bls-oews-mcp"],
      "env": {
        "BLS_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## Example prompts

- "What's the national median salary for Software Developers (SOC 151252)?"
- "Compare Systems Analyst wages in DC, Seattle, and Baltimore."
- "Build IGCE wage benchmarks for Program Manager, Software Developer, and Help Desk at the DC metro area with a 2.0x burden factor."
- "Is $195/hr reasonable for a Senior Software Developer? Show me the BLS market data."
- "What do Information Security Analysts earn in Virginia vs nationally?"

## Important: base wages, not burdened rates

BLS OEWS data represents employer-reported base wages (no fringe, overhead, G&A, or profit). To estimate fully burdened hourly rates for an IGCE, apply a burden multiplier:

- 1.5x-1.7x: lean contractor
- 1.8x-2.2x: mid-range professional services
- 2.0x-2.5x: large contractor with clearance overhead
- 2.5x-3.0x: high-overhead (SCIF, deployed)

The `igce_wage_benchmark` tool applies the multiplier automatically.

## Data year

OEWS data lags ~2 years. The server defaults to 2024 (May 2024 estimates, released April 2025). Do NOT query 2025 or 2026. Use `detect_latest_year` to check for newer releases.

## Companion tools

Use alongside `gsa-calc-mcp` (GSA CALC+ ceiling rates) for complete pricing analysis. BLS provides what the market pays; CALC+ provides what GSA contractors charge. Together they form the IGCE pricing toolkit.

## License

MIT
