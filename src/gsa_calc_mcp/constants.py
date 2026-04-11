# SPDX-License-Identifier: MIT
# Copyright (c) James Jenrette / 1102tools
"""Constants for the GSA CALC+ MCP server."""

BASE_URL = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "gsa-calc-mcp/0.1.1"

MAX_PAGE_SIZE = 500
RATE_LIMIT_PER_HOUR = 1000

EDUCATION_LEVELS = {
    "AA": "Associate's",
    "BA": "Bachelor's",
    "HS": "High School",
    "MA": "Master's",
    "PHD": "Doctorate",
    "TEC": "Technical/Vocational",
}

BUSINESS_SIZES = {
    "S": "Small Business",
    "O": "Other (Large Business)",
}

ORDERING_FIELDS = [
    "current_price",
    "labor_category",
    "vendor_name",
    "education_level",
    "min_years_experience",
]

COMMON_SINS: dict[str, str] = {
    "54151S": "IT Professional Services",
    "541611": "Management and Financial Consulting",
    "541715": "Engineering Research and Development",
    "541330ENG": "Engineering Services",
    "541519": "Other Computer Related Services",
    "541690": "Other Scientific and Technical Consulting",
    "561210FAC": "Facilities Maintenance and Management",
    "541511": "Custom Computer Programming",
    "541512": "Computer Systems Design",
    "541513": "Computer Facilities Management",
    "541610": "Management Consulting",
    "611430": "Training",
}
