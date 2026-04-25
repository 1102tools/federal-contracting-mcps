FROM python:3.12-slim

# regulationsgov-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir regulationsgov-mcp==0.2.4

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["regulationsgov-mcp"]
