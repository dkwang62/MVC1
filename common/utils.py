# utils.py

import pytz
from datetime import datetime
from typing import List, Dict, Any

# ----------------------------------------------------------------------
# TIMEZONE ORDER & REGION LABELS
# ----------------------------------------------------------------------

# Logical West → East ordering for common MVC timezones.
# This list is the PRIMARY source of truth for "west to east"
# ordering within each region.
COMMON_TZ_ORDER = [
    # Hawaii / Alaska / West Coast
    "Pacific/Honolulu",      # Hawaii
    "America/Anchorage",     # Alaska
    "America/Los_Angeles",   # US / Canada West Coast

    # Mexico / Mountain / Central
    "America/Mazatlan",      # Baja California Sur (Los Cabos)
    "America/Denver",        # US Mountain
    "America/Edmonton",      # Canada Mountain
    "America/Chicago",       # US Central
    "America/Winnipeg",      # Canada Central
    "America/Cancun",        # Quintana Roo (Cancún)

    # Eastern / Atlantic / Caribbean
    "America/New_York",      # US East
    "America/Toronto",       # Canada East
    "America/Halifax",       # Atlantic Canada
    "America/Puerto_Rico",   # Caribbean (AW, BS, VI, PR, etc.)
    "America/St_Johns",      # Newfoundland

    # Europe
    "Europe/London",
    "Europe/Paris",
    "Europe/Madrid",

    # Asia / Australia
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Makassar",         # Bali region (Denpasar alias)
    "Asia/Tokyo",
    "Australia/Brisbane",    # Surfers Paradise
    "Australia/Sydney",
]

# Region priority:
#   0 = USA + Canada + Caribbean
#   1 = Mexico + Costa Rica
#   2 = Europe
#   3 = Asia + Australia
#   99 = Everything else / fallback
REGION_US_CARIBBEAN = 0
REGION_MEX_CENTRAL = 1
REGION_EUROPE = 2
REGION_ASIA_AU = 3
REGION_FALLBACK = 99

# US state and DC we treat as "USA" region
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}

# Canadian provinces (kept in same region bucket as USA for navigation)
CA_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}

# Caribbean / Atlantic codes we group with USA region
CARIBBEAN_CODES = {"AW", "BS", "VI", "PR"}  # Aruba, Bahamas, USVI, Puerto Rico

# Mexico + Central America grouping
MEX_CENTRAL_CODES = {"MX", "CR"}  # Mexico, Costa Rica

# Europe country codes we currently support
EUROPE_CODES = {"ES", "FR", "GB", "UK", "PT", "IT", "DE", "NL", "IE"}

# Asia + Australia country codes we currently support
ASIA_AU_CODES = {"TH", "ID", "SG", "JP", "CN", "MY", "PH", "VN", "AU"}

# Fixed reference date to avoid DST variability in offset calculations
_REF_DT = datetime(2025, 1, 15, 12, 0, 0)

# ----------------------------------------------------------------------
# TIMEZONE OFFSET HELPERS
# ----------------------------------------------------------------------


def get_timezone_offset_minutes(tz_name: str) -> int:
    """Return offset from UTC in minutes for a given timezone.

    Used only as a tie-breaker within the same COMMON_TZ_ORDER bucket.
    We use a fixed reference date to avoid DST-vs-standard-time issues.
    """
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        return 0

    try:
        aware = tz.localize(_REF_DT)
        offset = aware.utcoffset()
        if offset is None:
            return 0
        return int(offset.total_seconds() // 60)
    except Exception:
        return 0


def get_timezone_offset(tz_name: str) -> float:
    """Backwards-compatible helper: UTC offset in HOURS.

    Old utils.py exposed get_timezone_offset() returning a float number
    of hours. We keep that signature but implement it using the new
    minute-based helper so behaviour stays consistent.
    """
    minutes = get_timezone_offset_minutes(tz_name)
    return minutes / 60.0


# ----------------------------------------------------------------------
# REGION HELPERS (CODE + TIMEZONE)
# ----------------------------------------------------------------------


def _region_from_code(code: str) -> int:
    """Internal helper: region strictly from resort.code."""
    if not code:
        return REGION_FALLBACK

    # Normalize two-letter country / state codes
    code = code.upper()

    if code in US_STATE_CODES:
        return REGION_US_CARIBBEAN

    if code in CA_PROVINCES or code == "CA":
        return REGION_US_CARIBBEAN

    if code in CARIBBEAN_CODES:
        return REGION_US_CARIBBEAN

    if code in MEX_CENTRAL_CODES:
        return REGION_MEX_CENTRAL

    if code in EUROPE_CODES:
        return REGION_EUROPE

    if code in ASIA_AU_CODES:
        return REGION_ASIA_AU

    return REGION_FALLBACK


def _region_from_timezone(tz: str) -> int:
    """Fallback region inference based only on timezone."""
    if not tz:
        return REGION_FALLBACK

    # Americas
    if tz.startswith("America/"):
        # Explicitly treat Cancun and Mazatlan as Mexico/Central bucket
        if tz in ("America/Cancun", "America/Mazatlan"):
            return REGION_MEX_CENTRAL
        # Everything else in Americas that isn't clearly Mexico/Central
        # is grouped with USA + Caribbean
        return REGION_US_CARIBBEAN

    # Europe
    if tz.startswith("Europe/"):
        return REGION_EUROPE

    # Asia / Australia
    if tz.startswith("Asia/") or tz.startswith("Australia/"):
        return REGION_ASIA_AU

    return REGION_FALLBACK


def get_region_priority(resort: Dict[str, Any]) -> int:
    """Map a resort into a logical region bucket.

    Region order:
        0: USA + Canada + Caribbean
        1: Mexico + Costa Rica
        2: Europe
        3: Asia + Australia
        99: fallback / unknown

    Primary classification is by `code`.
    If `code` is missing or not recognized, we fall back to timezone.
    """
    code = (resort.get("code") or "").upper()
    tz = resort.get("timezone") or ""

    # 1) Try code-based mapping first
    region = _region_from_code(code)
    if region != REGION_FALLBACK:
        return region

    # 2) Fallback: use timezone to infer region
    return _region_from_timezone(tz)


# ----------------------------------------------------------------------
# REGION LABELS (BACKWARDS-COMPATIBLE get_region_label)
# ----------------------------------------------------------------------

# Legacy-style human-friendly labels keyed by timezone.
# This is used by get_region_label(tz: str) to keep the old UI contract.
TZ_TO_REGION = {
    # Hawaii / Alaska / West Coast
    "Pacific/Honolulu": "Hawaii",
    "America/Anchorage": "Alaska",
    "America/Los_Angeles": "US West Coast",

    # Mexico / Mountain / Central
    "America/Mazatlan": "Mexico (Pacific)",
    "America/Denver": "US Mountain",
    "America/Edmonton": "Canada Mountain",
    "America/Chicago": "US Central",
    "America/Winnipeg": "Canada Central",
    "America/Cancun": "Mexico (Caribbean)",

    # Eastern / Atlantic / Caribbean
    "America/New_York": "US East Coast",
    "America/Toronto": "Canada East",
    "America/Halifax": "Atlantic Canada",
    "America/Puerto_Rico": "Caribbean",
    "America/St_Johns": "Newfoundland",

    # Europe
    "Europe/London": "UK / Ireland",
    "Europe/Paris": "Western Europe",
    "Europe/Madrid": "Western Europe",

    # Asia / Australia
    "Asia/Bangkok": "SE Asia",
    "Asia/Singapore": "SE Asia",
    "Asia/Makassar": "Indonesia",
    "Asia/Tokyo": "Japan",
    "Australia/Brisbane": "Australia (QLD)",
    "Australia/Sydney": "Australia",
}


def get_region_label(tz: str) -> str:
    """Backwards-compatible timezone → region label helper.

    The old utils.py exposed get_region_label(tz: str) which is used
    by common.ui. We preserve that API here.

    If the timezone is not in TZ_TO_REGION, we fall back to the last
    component of the tz name (e.g. 'Europe/Paris' → 'Paris').
    """
    if not tz:
        return "Unknown"
    return TZ_TO_REGION.get(tz, tz.split("/")[-1] if "/" in tz else tz)


# ----------------------------------------------------------------------
# RESORT SORTING
# ----------------------------------------------------------------------


def sort_resorts_by_timezone(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort resorts first by REGION, then West → East within each region.

    Region order:
        (a) USA + Canada + Caribbean (also includes Canada & Caribbean codes)
        (b) Mexico + Costa Rica
        (c) Europe
        (d) Asia + Australia
        (e) everything else (fallback) at the end

    Within each region, sort:
        1. By COMMON_TZ_ORDER index (West → East)
        2. Then by UTC offset in minutes (tie-breaker)
        3. Then alphabetically by display_name / resort_name
    """

    def sort_key(r: Dict[str, Any]):
        region_prio = get_region_priority(r)

        tz = r.get("timezone") or "UTC"
        if tz in COMMON_TZ_ORDER:
            tz_index = COMMON_TZ_ORDER.index(tz)
        else:
            tz_index = len(COMMON_TZ_ORDER)  # unknown timezones to the end of region

        offset_minutes = get_timezone_offset_minutes(tz)
        name = r.get("display_name") or r.get("resort_name") or ""

        return (region_prio, tz_index, offset_minutes, name)

    return sorted(resorts, key=sort_key)


def sort_resorts_west_to_east(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backwards-compatible alias used by common.ui.

    Historically, utils.py exposed sort_resorts_west_to_east().
    Internally we now use sort_resorts_by_timezone(), but the external
    behaviour (West → East ordering grouped by region) is the same.
    """
    return sort_resorts_by_timezone(resorts)
