FROM python:3.12-slim

# usaspending-gov-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir usaspending-gov-mcp==0.3.1

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["usaspending-mcp"]
