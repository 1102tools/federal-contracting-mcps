# Changelog

## 0.1.0
Initial release.

- 7 MCP tools covering the GSA Per Diem Rates API
- Core: lookup_city_perdiem, lookup_zip_perdiem, lookup_state_rates, get_mie_breakdown
- Workflows: estimate_travel_cost (with first/last day 75% M&IE), compare_locations
- Auto-selects best rate from API response (exact > composite NSA > first NSA > standard)
- Handles seasonal lodging variations (monthly breakdown)
- Special character handling for city names (apostrophes, hyphens, periods)
- Falls back to DEMO_KEY when no API key configured
- Actionable error messages for 403/429
- No mandatory authentication
