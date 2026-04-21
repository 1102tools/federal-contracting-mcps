# federal-contracting-mcps

Eight free and open source Model Context Protocol (MCP) servers for federal contracting data and policy tracking, packaged as Claude Desktop Extensions (`.dxt`) for one-click install.

No Terminal required. No `uv` install. No JSON config editing. Double-click a `.dxt` file, Claude Desktop prompts for the API key if needed, and the tools are registered automatically.

## What's in here

Eight MCP servers covering the federal data and policy sources a contracting officer actually uses:

**Procurement data**
- USASpending — federal contract and award data, PIIDs, vendor history, agency spending
- GSA CALC+ — awarded NTE hourly rates from GSA MAS contracts (230K+ records)
- BLS OEWS — market wage data across ~830 occupations and 530+ metros
- GSA Per Diem — federal travel lodging and M&IE rates for all CONUS
- SAM.gov — entity registration, exclusions, opportunities, contract awards (FPDS replacement)

**Regulatory and policy tracking**
- eCFR — current CFR text updated daily, FAR / DFARS clause lookup
- Federal Register — proposed rules, final rules, notices, executive orders, FAR cases
- Regulations.gov — federal rulemaking dockets, public comments, docket histories

Combined: 82 deterministic tool calls across eight servers. 719 regression tests across eight audit programs. Published to PyPI with Trusted Publisher for source installs; bundled as DXT for Claude Desktop one-click install.

## Install

Quick path (Claude Desktop):

1. Install [Claude Desktop](https://claude.ai/download).
2. Register the free API keys you need: [BLS](https://data.bls.gov/registrationEngine/), [api.data.gov](https://api.data.gov/signup/) (covers Per Diem and Regulations.gov), [SAM.gov](https://sam.gov/). USASpending, GSA CALC+, eCFR, and Federal Register need no key.
3. Download each `.dxt` file from the [Releases page](https://github.com/1102tools/federal-contracting-mcps/releases) (coming soon), double-click, and follow the install prompt.

Power users can install any MCP via `uvx` or `pip` using the individual source repos linked below.

## The eight MCPs

| MCP | Tools | Key | PyPI | Source |
|---|---|---|---|---|
| USASpending | 17 | None | `usaspending-gov-mcp` | [usaspending-gov-mcp](https://github.com/1102tools/usaspending-gov-mcp) |
| GSA CALC+ | 8 | None | `gsa-calc-mcp` | [gsa-calc-mcp](https://github.com/1102tools/gsa-calc-mcp) |
| BLS OEWS | 7 | BLS | `bls-oews-mcp` | [bls-oews-mcp](https://github.com/1102tools/bls-oews-mcp) |
| GSA Per Diem | 6 | api.data.gov | `gsa-perdiem-mcp` | [gsa-perdiem-mcp](https://github.com/1102tools/gsa-perdiem-mcp) |
| SAM.gov | 15 | SAM.gov | `sam-gov-mcp` | [sam-gov-mcp](https://github.com/1102tools/sam-gov-mcp) |
| eCFR | 13 | None | `ecfr-mcp` | [ecfr-mcp](https://github.com/1102tools/ecfr-mcp) |
| Federal Register | 8 | None | `federal-register-mcp` | [federal-register-mcp](https://github.com/1102tools/federal-register-mcp) |
| Regulations.gov | 8 | api.data.gov | `regulationsgov-mcp` | [regulationsgov-mcp](https://github.com/1102tools/regulationsgov-mcp) |

Each source repo ships a `TESTING.md` with audit rounds, bug counts, and regression test coverage.

## Companion repo

This repo is the install hub. The skill library is a separate, companion repository:

**[federal-contracting-skills](https://github.com/1102tools/federal-contracting-skills)** — Claude Skills that orchestrate these MCPs into complete acquisition deliverables:

- SOW / PWS Builder (FAR 37.102(d) compliant)
- IGCE Builder: FFP (wrap rate buildup)
- IGCE Builder: LH/T&M (burden multiplier)
- IGCE Builder: Cost-Reimbursement (CPFF / CPAF / CPIF)
- OT Project Description Builder (10 USC 4021/4022, TRL phases)
- OT Cost Analysis (milestone-based should-cost)

**How they work together:** The MCPs in this repo handle deterministic API data pulls. The skills in the companion repo handle scope decisions, cost buildup, and document generation. Contracting officers install both: MCPs for data, skills for deliverables.

## Why MCPs (and not just the skills)?

- **Deterministic tool calls.** Every call returns the same structured output. No LLM drift between runs.
- **Production-hardened.** Eight MCPs, 3-6 audit rounds each, 719 regression tests total, roughly 350 bugs fixed during hardening.
- **Low context cost.** Tool schemas are ~100 tokens each. The deprecated API skills cost 500-1000 lines of context per run.
- **Works across MCP clients.** Claude Desktop via DXT is the recommended install; the underlying PyPI packages work in Cursor, Cline, Zed, Continue, and other MCP clients via manual config.

## Why DXT (and not just `uv` config)?

DXT (Desktop Extensions) is Anthropic's one-click install format for Claude Desktop. A `.dxt` file bundles the runtime, dependencies, manifest, and credential prompts. Users without Python, `uv`, or Terminal experience can install by double-clicking. This is the path contracting officers actually take.

The traditional `uvx` + JSON config path is still supported for developers and non-Claude clients. See each MCP's source repo for manual install instructions.

## Status

**Seed repo.** DXT build artifacts, build workflow, and Releases coming soon. Each MCP's source is live and installable today via `uvx` or `pip`. See individual repos for manual install.

Track progress: [Issues](https://github.com/1102tools/federal-contracting-mcps/issues) / [Discussions](https://github.com/1102tools/federal-contracting-mcps/discussions).

## Website

[1102tools.com](https://1102tools.com) — full install guide, example prompts, architecture diagram, AI boundaries, and downloads for both this repo and the companion skills repo.

## License

MIT

## Author

Built by [James Jenrette](https://www.linkedin.com/in/jamesjenrette/), senior federal contracting officer (GS-1102-14), unlimited warrant. All skills and MCPs are independently developed and not endorsed by any federal agency.
