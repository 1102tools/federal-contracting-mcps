# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""Constants for the Regulations.gov MCP server."""

BASE_URL = "https://api.regulations.gov/v4"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "regulationsgov-mcp/0.1.1"

MIN_PAGE_SIZE = 5
MAX_PAGE_SIZE = 250
DEFAULT_PAGE_SIZE = 25

# Document types (CASE-SENSITIVE)
DOCUMENT_TYPES = ["Proposed Rule", "Rule", "Notice", "Supporting & Related Material", "Other"]

# Docket types (CASE-SENSITIVE)
DOCKET_TYPES = ["Rulemaking", "Nonrulemaking"]

# Acquisition-relevant agency IDs
PROCUREMENT_AGENCIES = ["FAR", "DARS", "GSA", "SBA", "OFPP", "DOD", "NASA", "VA"]
