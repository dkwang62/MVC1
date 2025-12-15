# utils.py

import pytz
from datetime import datetime
from typing import List, Dict, Any


# ----------------------------------------------------------------------
# TIMEZONE ORDER (West → East) — used for sorting resorts in the grid
# ----------------------------------------------------------------------
COMMON_TZ_ORDER = [
    "Pacific/Honolulu",       # Hawaii
    "America/Anchorage",      # Alaska
    "America/Los_Angeles",    # US West Coast
    "America/Mazatlan",       # Mexico Pacific
    "America/Denver",         # Mountain
    "America/Edmonton",
    "America/Chicago",        # Central
    "America/Winnipeg",
    "America/Cancun",         # Mexico Caribbean
    "America/New_York",       # East Coast
    "America/Toronto",
    "America/Halifax",
    "America/Puerto_Rico",    # Caribbean
    "America/St_Johns",
    "Europe/London",
    "Europe/Paris",
    "Europe/Madrid",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Makassar",          # Bali
    "Asia/Tokyo",
    "Australia/Brisbane",
    "Australia/Sydney",
]

# ----------------------------------------------------------------------
# REGION LABELS — used for grouping in the resort grid
# ----------------------------------------------------------------------
TZ_TO_REGION_LABEL = {
    "Pacific/Honolulu": "Hawaii",
    "America/Anchorage": "Alaska",
    "America/Los_Angeles": "US West Coast",
    "America/Mazatlan": "Mexico (Pacific)",
    "America/Denver": "US Mountain",
    "America/Edmonton": "Canada Mountain",
    "America/Chicago": "US Central",
    "America/Winnipeg": "Canada Central",
    "America/Cancun": "Mexico (Caribbean)",
    "America/New_York": "US East Coast",
    "America/Toronto": "Canada East",
    "America/Halifax": "Atlantic Canada",
    "America/Puerto_Rico": "Caribbean",
    "America/St_Johns": "Newfoundland",
    "Europe/London": "UK / Ireland",
    "Europe/Paris": "Western Europe",
    "Europe/Madrid": "Western Europe",
    "Asia/Bangkok": "SE Asia",
    "Asia/Singapore": "SE Asia",
    "Asia/Makassar": "Indonesia",
    "Asia/Tokyo": "Japan",
    "Australia/Brisbane": "Australia (QLD)",
    "Australia/Sydney": "Australia",
}


def get_region_label(tz: str) -> str:
    """Return a friendly region label for a timezone. Used in resort grid grouping."""
    if not tz:
        return "Unknown"
    return TZ_TO_REGION_LABEL.get(tz, tz.split("/")[-1] if "/" in tz else tz)


def sort_resorts_west_to_east(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort resorts west to east using timezone order. Used directly in the resort selection grid."""
    def sort_key(resort: Dict[str, Any]) -> tuple:
        tz = resort.get("timezone") or "UTC"
        try:
            tz_index = COMMON_TZ_ORDER.index(tz)
        except ValueError:
            tz_index = len(COMMON_TZ_ORDER)  # unknown timezones go to the end
        name = resort.get("display_name", "")
        return (tz_index, name.lower())

    return sorted(resorts, key=sort_key)
