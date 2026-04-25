FROM python:3.12-slim

# bls-oews-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir bls-oews-mcp==0.2.6

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["bls-oews-mcp"]
