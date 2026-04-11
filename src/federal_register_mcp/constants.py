# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""Constants for the Federal Register MCP server."""

BASE_URL = "https://www.federalregister.gov/api/v1"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "federal-register-mcp/0.1.1"

DOCUMENT_TYPES = {
    "PRORULE": "Proposed Rule",
    "RULE": "Final Rule",
    "NOTICE": "Notice",
    "PRESDOCU": "Presidential Document",
}

ORDER_OPTIONS = ["newest", "oldest", "relevance", "executive_order_number"]

FACET_NAMES = ["type", "agency", "topic"]

DEFAULT_FIELDS = [
    "title", "document_number", "publication_date", "type", "abstract",
    "agencies", "docket_ids", "regulation_id_numbers", "comment_url",
    "comments_close_on", "cfr_references", "html_url", "pdf_url",
    "citation", "dates", "effective_on", "action", "significant",
]
