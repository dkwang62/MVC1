# common/utils.py
import pytz
from datetime import datetime
from typing import List, Dict, Any

# ----------------------------------------------------------------------
# TIMEZONE ORDER & REGION LABELS
# ----------------------------------------------------------------------

# Logical West → East ordering for common MVC timezones
COMMON_TZ_ORDER = [
    "Pacific/Honolulu", "America/Anchorage", "America/Los_Angeles", "America/Denver",
    "America/Chicago", "America/New_York", "America/Vancouver", "America/Edmonton",
    "America/Winnipeg", "America/Toronto", "America/Halifax", "America/St_Johns",
    "US/Hawaii", "US/Alaska", "US/Pacific", "US/Mountain", "US/Central", "US/Eastern",
    "America/Aruba", "America/St_Thomas", "Asia/Denpasar",  # Aruba, Virgin Islands, Bali
]

TZ_TO_REGION = {
    "Pacific/Honolulu": "Hawaii",
    "US/Hawaii": "Hawaii",
    "America/Anchorage": "Alaska",
    "US/Alaska": "Alaska",
    "America/Los_Angeles": "West Coast",
    "US/Pacific": "West Coast",
    "America/Denver": "Mountain",
    "US/Mountain": "Mountain",
    "America/Chicago": "Central",
    "US/Central": "Central",
    "America/New_York": "East Coast",
    "US/Eastern": "East Coast",
    "America/Aruba": "Caribbean",
    "America/St_Thomas": "Caribbean",
    "Asia/Denpasar": "Bali/Indonesia",
}


def get_timezone_offset(tz_name: str) -> float:
    """
    Return UTC offset in hours (negative for west of UTC).

    We fix a reference date (2025-01-01) to avoid DST ambiguity.
    """
    try:
        tz = pytz.timezone(tz_name)
        dt = datetime(2025, 1, 1)
        offset = tz.utcoffset(dt)
        return offset.total_seconds() / 3600 if offset is not None else 0.0
    except Exception:
        return 0.0


def get_region_label(tz: str) -> str:
    """
    Map a timezone string to a human-friendly region label.
    Falls back to the last component of the tz name.
    """
    if not tz:
        return "Unknown"
    return TZ_TO_REGION.get(tz, tz.split("/")[-1] if "/" in tz else tz)


def sort_resorts_west_to_east(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort resorts West → East using:
      1) COMMON_TZ_ORDER index (explicit priority)
      2) UTC offset (secondary)
      3) Address / name (tertiary, alphabetic)
    """
    def sort_key(r: Dict[str, Any]):
        tz = r.get("timezone", "UTC")

        if tz in COMMON_TZ_ORDER:
            priority = COMMON_TZ_ORDER.index(tz)
        else:
            priority = 1000  # unknown – push to the end

        offset = get_timezone_offset(tz)
        address = (
            r.get("address")
            or r.get("resort_name")
            or r.get("display_name")
            or ""
        ).lower()

        return (priority, offset, address)

    return sorted(resorts, key=sort_key)
