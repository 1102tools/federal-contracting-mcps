# federal-contracting-mcps

Eight free and open source MCP servers for federal contracting data and policy tracking, packaged as Claude Desktop Extensions (`.mcpb`) for one-click install.

No Terminal. No `uv` install. No JSON config editing. Double-click a `.mcpb` file, Claude Desktop prompts for the API key if one is needed, and the tools register automatically.

## The eight MCPs

All source lives under `servers/<name>/`. Each server is self-contained: manifest, code, tests, per-server README.

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
3. Download each `.mcpb` file from [Releases](https://github.com/1102tools/federal-contracting-mcps/releases), double-click, and follow the prompt.

Power users: every server subdirectory has its own README with `uvx` and `pip` instructions for manual install in any MCP client (Claude Desktop, Claude Code, Cursor, Cline, Zed, Continue).

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
├── license
└── readme.md
```

Each server directory ships its own `manifest.json` (MCPB), `pyproject.toml`, source, regression tests, and testing record.

## Companion repo

[federal-contracting-skills](https://github.com/1102tools/federal-contracting-skills) — Claude Skills that orchestrate these MCPs into complete acquisition deliverables: SOW/PWS Builder, three IGCE Builders (FFP, LH/T&M, Cost-Reimbursement), OT Project Description Builder, OT Cost Analysis.

MCPs handle data. Skills handle deliverables.

## Why MCPs (and not skills for the API calls)

- **Deterministic.** MCP servers execute tested Python. Claude does not generate API-call code on the fly. Same input, same output.
- **One-click install.** `.mcpb` bundles prompt for API keys at install time and register tools automatically. Contracting officers install them the same way they install any app.
- **Low context cost.** Tool schemas are ~100 tokens each. The deprecated API-data skills cost 500-1000 lines of context per run.
- **Production-hardened.** Each MCP went through 3-6 audit rounds with live testing against its production API.
- **Cross-client.** MCP is an open standard. Same servers run in Claude Desktop, Claude Code, Cursor, Cline, Zed, Continue.

## Website

[1102tools.com](https://1102tools.com)

## License

MIT

## Author

Built by [James Jenrette](https://www.linkedin.com/in/jamesjenrette/), lead systems analyst and contracting officer. Independently developed and not endorsed by any federal agency.
