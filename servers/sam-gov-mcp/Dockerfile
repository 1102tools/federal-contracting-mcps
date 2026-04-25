FROM python:3.12-slim

# sam-gov-mcp: stdio MCP server for federal contracting data
# Glama-compatible: container starts the server on stdio for introspection.

RUN pip install --no-cache-dir sam-gov-mcp==0.4.0

# Stdio transport: server reads JSON-RPC from stdin, writes to stdout.
CMD ["sam-gov-mcp"]
