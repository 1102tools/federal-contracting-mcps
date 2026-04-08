"""Constants and reference tables for the SAM.gov MCP server."""

BASE_URL = "https://api.sam.gov"
ENTITY_PATH = "/entity-information/v3/entities"
EXCLUSIONS_PATH = "/entity-information/v4/exclusions"
OPPORTUNITIES_PATH = "/opportunities/v2/search"
OPPORTUNITY_DESC_PATH = "/prod/opportunities/v1/noticedesc"
PSC_PATH = "/prod/locationservices/v1/api/publicpscdetails"
CONTRACT_AWARDS_PATH = "/contract-awards/v1/search"

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "sam-gov-mcp/0.2.0"

# Hard caps from the SAM.gov API (enforce client-side to give good errors)
ENTITY_MAX_SIZE = 10          # Entity Management has a hard cap of 10
OPPORTUNITY_MAX_LIMIT = 1000  # Opportunities accepts large limits
EXCLUSION_MAX_SIZE = 100      # Exclusions typical cap
CONTRACT_AWARDS_MAX_LIMIT = 100  # Contract Awards hard cap

# Notice type codes (ptype parameter on Opportunities)
NOTICE_TYPES: dict[str, str] = {
    "p": "Presolicitation",
    "o": "Solicitation",
    "k": "Combined Synopsis/Solicitation",
    "r": "Sources Sought",
    "g": "Sale of Surplus Property",
    "s": "Special Notice",
    "i": "Intent to Bundle",
    "a": "Award Notice",
    "u": "Justification (J&A)",
}

# Set-aside type codes for Opportunities
SET_ASIDE_CODES: dict[str, str] = {
    "SBA": "Total Small Business Set-Aside",
    "SBP": "Partial Small Business Set-Aside",
    "8A": "8(a) Competed",
    "8AN": "8(a) Sole Source",
    "HZC": "HUBZone Set-Aside",
    "HZS": "HUBZone Sole Source",
    "SDVOSBC": "SDVOSB Set-Aside",
    "SDVOSBS": "SDVOSB Sole Source",
    "WOSB": "WOSB Set-Aside",
    "WOSBSS": "WOSB Sole Source",
    "EDWOSB": "EDWOSB Set-Aside",
    "EDWOSBSS": "EDWOSB Sole Source",
    "VSA": "Veteran Set-Aside",
    "VSS": "Veteran Sole Source",
}

# Business type codes (validated against live SAM.gov API)
BUSINESS_TYPE_CODES: dict[str, str] = {
    "23": "Minority-Owned Business",
    "27": "Self Certified Small Disadvantaged Business",
    "2X": "For Profit Organization",
    "8W": "Women-Owned Small Business",
    "A2": "Women-Owned Business",
    "A5": "Veteran-Owned Business",
    "A8": "Non-Profit Organization",
    "LJ": "Limited Liability Company",
    "MF": "Manufacturer of Goods",
    "OY": "Black American Owned",
    "PI": "Hispanic American Owned",
    "QF": "Service-Disabled Veteran-Owned Business",
    "XS": "Subchapter S Corporation",
}

# SBA-specific business types
SBA_BUSINESS_TYPE_CODES: dict[str, str] = {
    "XX": "8(a) Certified",
    "JT": "Joint Venture",
}

# Valid includeSections values for Entity Management
ENTITY_SECTIONS = {
    "entityRegistration",
    "coreData",
    "assertions",
    "pointsOfContact",
    "repsAndCerts",
    "integrityInformation",
    "All",
}

# Exclusion classification types
EXCLUSION_CLASSIFICATIONS = [
    "Firm",
    "Individual",
    "Vessel",
    "Special Entity Designation",
]

# Registration status codes
REGISTRATION_STATUS = {
    "A": "Active",
    "E": "Expired",
    "D": "Deleted",
    "I": "Inactive",
}
