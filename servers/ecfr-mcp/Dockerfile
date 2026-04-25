FROM python:3.12-slim

# ecfr-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir ecfr-mcp==0.2.5

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["ecfr-mcp"]
