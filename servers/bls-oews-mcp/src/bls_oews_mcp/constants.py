# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants for the BLS OEWS MCP server."""

BASE_URL_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BASE_URL_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "bls-oews-mcp/0.2.6"

# OEWS data lags ~2 years. Do NOT use the calendar year.
# May 2024 estimates released April 2025. Next: May 2025 estimates in ~April 2026.
OEWS_CURRENT_YEAR = "2024"

# Series ID format: PREFIX(4) + AREA(7) + INDUSTRY(6) + OCC(6) + DATATYPE(2) = 25 chars
SERIES_ID_LENGTH = 25

# Max series per request
MAX_SERIES_V1 = 25
MAX_SERIES_V2 = 50

SPECIAL_VALUES = {"-", "#", "*", "N/A"}

DATATYPE_LABELS: dict[str, str] = {
    "01": "Employment",
    "03": "Hourly Mean Wage",
    "04": "Annual Mean Wage",
    "07": "Hourly 10th Percentile",
    "08": "Hourly 25th Percentile",
    "09": "Hourly Median",
    "10": "Hourly 75th Percentile",
    "11": "Annual 10th Percentile",
    "12": "Annual 25th Percentile",
    "13": "Annual Median",
    "14": "Annual 75th Percentile",
    "15": "Annual 90th Percentile",
    "16": "Annual 90th Percentile (alt code)",
}

# The set of datatypes we route as HOURLY values in _parse_value
HOURLY_DATATYPES: set[str] = {"03", "07", "08", "09", "10"}
# Datatypes returning COUNTS (not dollars)
COUNT_DATATYPES: set[str] = {"01"}

# Datatypes used for IGCE wage profiles
IGCE_DATATYPES = ["04", "11", "13", "15"]  # mean, 10th, median, 90th
FULL_DATATYPES = ["01", "03", "04", "08", "11", "12", "13", "14", "15"]

# Common SOC codes for federal IT/professional services
COMMON_SOC_CODES: dict[str, str] = {
    "111021": "General and Operations Managers",
    "113021": "Computer and Information Systems Managers",
    "131082": "Project Management Specialists",
    "131111": "Management Analysts",
    "132011": "Accountants and Auditors",
    "151211": "Computer Systems Analysts",
    "151212": "Information Security Analysts",
    "151232": "Computer User Support Specialists (Help Desk)",
    "151241": "Computer Network Architects",
    "151242": "Database Administrators",
    "151244": "Network and Computer Systems Administrators",
    "151251": "Computer Programmers",
    "151252": "Software Developers",
    "151253": "Software Quality Assurance Analysts",
    "151254": "Web Developers",
    "152051": "Data Scientists",
    "273042": "Technical Writers",
    "436014": "Secretaries and Administrative Assistants",
}

# Common metro MSA codes
COMMON_METROS: dict[str, str] = {
    "0047900": "Washington DC",
    "0042660": "Seattle",
    "0012580": "Baltimore",
    "0037980": "Philadelphia",
    "0035620": "New York City",
    "0031080": "Los Angeles",
    "0041860": "San Francisco",
    "0038060": "Phoenix",
    "0016980": "Chicago",
    "0012420": "Austin",
    "0014460": "Boston",
    "0019100": "Dallas",
    "0026420": "Houston",
    "0041740": "San Diego",
    "0019820": "Detroit",
}

# Common state FIPS codes
COMMON_STATES: dict[str, str] = {
    "06": "CA",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "24": "MD",
    "34": "NJ",
    "36": "NY",
    "42": "PA",
    "48": "TX",
    "51": "VA",
    "53": "WA",
}
