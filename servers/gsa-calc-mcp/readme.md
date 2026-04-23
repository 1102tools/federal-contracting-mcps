# gsa-calc-mcp

MCP server for the GSA CALC+ Labor Ceiling Rates API. Query awarded GSA MAS schedule hourly rates for IGCE development, price reasonableness analysis, and market research.

No authentication required. Works with any MCP-compatible client.

*Tested and hardened through four retroactive live audit rounds against the GSA CALC+ API. 314 regression tests covering 49 P1 bugs (19 crashes, 30 silent-wrong-data) and 19 P2 validation gaps fixed, plus 12 retroactive deep-audit findings. See [TESTING.md](TESTING.md) for the full testing record.*

## What it does

Exposes the GSA CALC+ API as 8 MCP tools:

**Core search**
- `keyword_search` - Wildcard search across labor categories, vendors, and contract numbers
- `exact_search` - Exact field match (use suggest_contains to discover values first)
- `suggest_contains` - Autocomplete/discovery for field values (2-char minimum)
- `filtered_browse` - Browse with filters only (no keyword)

**Workflow tools**
- `igce_benchmark` - Rate statistics for IGCE development (min/max/avg/median/percentiles)
- `price_reasonableness_check` - Evaluate a proposed rate against market distribution
- `vendor_rate_card` - All rates for a vendor (auto-discovers exact name)
- `sin_analysis` - Rate distribution for a GSA SIN

## No authentication required

The GSA CALC+ API is public. 1,000 requests/hour rate limit.

## Installation

```bash
uvx gsa-calc-mcp
```

Or from source:

```bash
git clone https://github.com/1102tools/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/gsa-calc-mcp
pip install -e .
```

## Claude Desktop configuration

```json
{
  "mcpServers": {
    "gsa-calc": {
      "command": "uvx",
      "args": ["gsa-calc-mcp"]
    }
  }
}
```

## Example prompts

- "What are the GSA ceiling rates for Senior Software Developer with a BA and 10+ years experience?"
- "Is $195/hr reasonable for a Cybersecurity Analyst? Check against CALC+ rates."
- "Pull the full rate card for Booz Allen Hamilton from GSA CALC+."
- "What does the IT Professional Services SIN (54151S) rate distribution look like?"
- "Build IGCE benchmarks for these 5 labor categories: Program Manager, Systems Engineer, Software Developer, Help Desk Specialist, Network Administrator."
- "Find all small business ceiling rates for project management between $100-$200/hr."

## Important: ceiling rates, not prices paid

CALC+ data represents the maximum hourly rate a contractor can charge under their GSA MAS contract. Actual task order rates should be lower per FAR 8.405-2(d). These rates are:

- Fully burdened (includes fringe, overhead, G&A, profit)
- Worldwide (no geographic adjustment)
- Master contract-level (not task order-specific)
- From vendor Price Proposal Tables (self-reported by contractors)

Always note sample size and remind users these are ceiling rates when presenting analysis.

## License

MIT
