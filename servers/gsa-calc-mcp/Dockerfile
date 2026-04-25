FROM python:3.12-slim

# gsa-calc-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir gsa-calc-mcp==0.2.6

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["gsa-calc-mcp"]
