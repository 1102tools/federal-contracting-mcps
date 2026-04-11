# SPDX-License-Identifier: MIT
# Copyright (c) 2026 James Jenrette / 1102tools
"""Constants and reference data for the eCFR MCP server."""

BASE_URL = "https://www.ecfr.gov"
DEFAULT_TIMEOUT_JSON = 15.0
DEFAULT_TIMEOUT_STRUCTURE = 30.0
DEFAULT_TIMEOUT_CONTENT = 60.0
USER_AGENT = "ecfr-mcp/0.1.1"

# Search caps
SEARCH_MAX_PER_PAGE = 5000
SEARCH_MAX_TOTAL = 10000

# Title 48 chapter map (Federal Acquisition Regulations System)
TITLE_48_CHAPTERS: dict[str, str] = {
    "1": "FAR (Parts 1-99)",
    "2": "DFARS (Parts 200-299)",
    "3": "HHSAR (Parts 300-399)",
    "4": "AGAR (Parts 400-499)",
    "5": "GSAR (Parts 500-599)",
    "6": "DOSAR (Parts 600-699)",
    "7": "AIDAR (Parts 700-799)",
    "8": "VAAR (Parts 800-899)",
    "9": "DEAR (Parts 900-999)",
    "10": "DTAR (Parts 1000-1099)",
    "12": "TAR (Parts 1200-1299)",
    "13": "CAR (Parts 1300-1399)",
    "14": "DIAR (Parts 1400-1499)",
    "15": "EPAAR (Parts 1500-1599)",
    "16": "OPMAR (Parts 1600-1699)",
    "18": "NFS (Parts 1800-1899)",
    "20": "NRCAR (Parts 2000-2099)",
    "23": "SSAAR (Parts 2300-2399)",
    "24": "HUDAR (Parts 2400-2499)",
    "25": "NSFAR (Parts 2500-2599)",
    "28": "JAR (Parts 2800-2899)",
    "29": "DOLAR (Parts 2900-2999)",
    "99": "CAS (Part 9900)",
}

# Common FAR sections for quick reference in tool descriptions
COMMON_FAR_SECTIONS: dict[str, str] = {
    "2.101": "Definitions",
    "4.1102": "SAM policy",
    "6.302-1": "Only one responsible source",
    "9.104-1": "General standards of responsibility",
    "9.406-2": "Causes for debarment",
    "12.301": "Solicitation provisions (commercial)",
    "13.003": "Simplified acquisition policy",
    "15.305": "Proposal evaluation",
    "15.306": "Exchanges with offerors",
    "19.502-2": "Total small business set-asides",
    "31.205": "Selected costs (allowability)",
    "33.103": "Protests to the agency",
    "42.302": "Contract administration functions",
    "52.212-1": "Instructions to Offerors (Commercial)",
    "52.212-4": "Contract Terms and Conditions (Commercial)",
    "52.212-5": "Required Contract Terms (Commercial)",
}
