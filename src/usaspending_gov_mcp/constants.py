"""Constants and reference data for the USASpending API."""

BASE_URL = "https://api.usaspending.gov"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "usaspending-gov-mcp/0.1.1"

# Award type code groups. These MUST NOT be mixed in a single request
# (the API returns HTTP 422 otherwise).
AWARD_TYPE_GROUPS: dict[str, list[str]] = {
    "contracts": ["A", "B", "C", "D"],
    "idvs": [
        "IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B",
        "IDV_B_C", "IDV_C", "IDV_D", "IDV_E",
    ],
    "grants": ["02", "03", "04", "05"],
    "loans": ["07", "08"],
    "direct_payments": ["06", "10"],
    "other": ["09", "11", "-1"],
}

# Default field sets for different award types
DEFAULT_CONTRACT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Award Amount",
    "Total Outlays",
    "Contract Award Type",
    "Start Date",
    "End Date",
    "NAICS",
    "PSC",
    "generated_internal_id",
    "Last Modified Date",
]

DEFAULT_IDV_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Award Amount",
    "Start Date",
    "Last Date to Order",
    "NAICS",
    "PSC",
    "generated_internal_id",
    "Last Modified Date",
]

DEFAULT_LOAN_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Loan Value",
    "Subsidy Cost",
    "Awarding Agency",
    "Awarding Sub Agency",
    "generated_internal_id",
    "Last Modified Date",
]

DEFAULT_GRANT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Description",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Start Date",
    "End Date",
    "CFDA Number",
    "generated_internal_id",
]

# Categories accepted by spending_by_category endpoint
SPENDING_CATEGORIES = [
    "awarding_agency",
    "awarding_subagency",
    "funding_agency",
    "funding_subagency",
    "recipient",
    "cfda",
    "naics",
    "psc",
    "country",
    "county",
    "district",
    "state_territory",
    "federal_account",
    "defc",
]

# Filter value groupings
COMPETED_CODES = ["A", "D", "F", "CDO"]
NOT_COMPETED_CODES = ["B", "C", "E", "G", "NDO"]

ALL_SB_SET_ASIDE_CODES = [
    "SBA", "SBP", "8A", "8AN", "HZC", "HZS",
    "SDVOSBS", "SDVOSBC", "WOSB", "WOSBSS",
    "EDWOSB", "EDWOSBSS", "VSA",
]
