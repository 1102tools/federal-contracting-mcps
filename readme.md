# federal-contracting-mcps

Eight free and open source MCP servers for federal contracting data and policy tracking, packaged as Claude Desktop Extensions (`.mcpb`) for one-click install.

No Terminal. No `uv` install. No JSON config editing. Double-click a `.mcpb` file, Claude Desktop prompts for the API key if one is needed, and the tools register automatically.

## What's in here

Each server lives in `servers/<name>/`, self-contained with manifest, source, tests, and README.

**Procurement data**
- [sam-gov-mcp](servers/sam-gov-mcp) — SAM.gov entity registration, exclusions, opportunities, contract awards (FPDS replacement)
- [usaspending-gov-mcp](servers/usaspending-gov-mcp) — federal contract and award data, PIIDs, vendor history, agency spending
- [gsa-calc-mcp](servers/gsa-calc-mcp) — GSA CALC+ awarded NTE hourly rates from MAS contracts (230K+ records)
- [bls-oews-mcp](servers/bls-oews-mcp) — BLS OEWS market wage data across ~830 occupations and 530+ metros
- [gsa-perdiem-mcp](servers/gsa-perdiem-mcp) — federal travel lodging and M&IE rates for all CONUS

**Regulatory and policy tracking**
- [ecfr-mcp](servers/ecfr-mcp) — current CFR text updated daily, FAR / DFARS / agency supplement lookups
- [federal-register-mcp](servers/federal-register-mcp) — proposed rules, final rules, notices, executive orders, FAR cases
- [regulations-gov-mcp](servers/regulations-gov-mcp) — federal rulemaking dockets, public comments, comment period tracking

Combined: 82 deterministic tool calls, 719 regression tests, 8 audit programs, roughly 350 bugs fixed during hardening.

## Install

1. Install [Claude Desktop](https://claude.ai/download).
2. Register the free API keys you need: [BLS](https://data.bls.gov/registrationEngine/), [api.data.gov](https://api.data.gov/signup/) (covers Per Diem and Regulations.gov), [SAM.gov](https://sam.gov/). USASpending, GSA CALC+, eCFR, and Federal Register need no key.
3. Download each `.mcpb` file from the [Releases page](https://github.com/1102tools/federal-contracting-mcps/releases) (coming soon), double-click, and follow the prompt.

Power users: each server subdirectory has its own README with `uvx` and `pip` instructions for manual install in any MCP client.

## Repo layout

```
federal-contracting-mcps/
├── servers/
│   ├── bls-oews-mcp/
│   ├── ecfr-mcp/
│   ├── federal-register-mcp/
│   ├── gsa-calc-mcp/
│   ├── gsa-perdiem-mcp/
│   ├── regulations-gov-mcp/
│   ├── sam-gov-mcp/
│   └── usaspending-gov-mcp/
├── LICENSE
└── README.md
```

Each server directory ships its own `manifest.json` (MCPB), `pyproject.toml`, source, regression tests, and testing record.

## Companion repo

[federal-contracting-skills](https://github.com/1102tools/federal-contracting-skills) — Claude Skills that orchestrate these MCPs into complete acquisition deliverables:

- SOW / PWS Builder (FAR 37.102(d) compliant)
- IGCE Builder: FFP (wrap rate buildup)
- IGCE Builder: LH/T&M (burden multiplier)
- IGCE Builder: Cost-Reimbursement (CPFF / CPAF / CPIF)
- OT Project Description Builder (10 USC 4021/4022, TRL phases)
- OT Cost Analysis (milestone-based should-cost)

MCPs handle data. Skills handle deliverables. Install both.

## Why MCPs (and not skills for the API calls)

- **Deterministic tool calls.** MCP servers execute tested Python. Claude does not generate API-call code on the fly. Same input, same output.
- **One-click install for Claude Desktop.** `.mcpb` bundles prompt for API keys at install time and register tools automatically. Contracting officers install them the same way they install any app.
- **Low context cost.** Tool schemas are ~100 tokens each. The deprecated API-data skills cost 500-1000 lines of context per run.
- **Production-hardened.** Each MCP went through 3-6 audit rounds with live testing against the production API.
- **Cross-client.** MCP is an open standard. Same servers run in Claude Desktop, Claude Code, Cursor, Cline, Zed, Continue.

## Why MCPB (and not just `uv` config)

MCPB is Anthropic's one-click install format for Claude Desktop. A `.mcpb` file bundles the runtime, dependencies, manifest, and credential prompts. Users without Python, `uv`, or Terminal experience install by double-clicking. That is the path contracting officers actually take.

The traditional `uvx` + JSON config path still works for developers and non-Claude clients. See each server's README for manual install instructions.

## Status

All eight MCPs live under `servers/`. `.mcpb` bundles and Releases coming soon.

## Website

[1102tools.com](https://1102tools.com)

## License

MIT

## Author

Built by [James Jenrette](https://www.linkedin.com/in/jamesjenrette/), lead systems analyst and contracting officer. Independently developed and not endorsed by any federal agency.
