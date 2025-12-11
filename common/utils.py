# utils.py

import pytz
from datetime import datetime
from typing import List, Dict, Any

# =============================================
# 2. West to East Sorting – Regional groups, then West→East within region
# =============================================


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
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
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
    """UTC offset in HOURS (for completeness, not used by sorter directly)."""
    minutes = get_timezone_offset_minutes(tz_name)
    return minutes / 60.0


def _extract_country_or_region_code(resort: Dict[str, Any]) -> str:
    """
    Try to pull a 2-letter ISO-style country / state code from the resort.
    We look at several common fields to be robust against schema differences.
    """
    for key in ("country_code", "country", "code", "region_code"):
        val = resort.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    return ""


def _region_from_code_or_country(resort: Dict[str, Any]) -> int:
    """Internal helper: region inferred from any country/region code field."""
    code = _extract_country_or_region_code(resort)
    if not code:
        return REGION_FALLBACK

    # USA states / DC
    if code in US_STATE_CODES:
        return REGION_US_CARIBBEAN

    # Canada
    if code in CA_PROVINCES or code == "CA":
        return REGION_US_CARIBBEAN

    # Caribbean
    if code in CARIBBEAN_CODES:
        return REGION_US_CARIBBEAN

    # Mexico / Costa Rica
    if code in MEX_CENTRAL_CODES:
        return REGION_MEX_CENTRAL

    # Europe
    if code in EUROPE_CODES:
        return REGION_EUROPE

    # Asia / Australia
    if code in ASIA_AU_CODES:
        return REGION_ASIA_AU

    return REGION_FALLBACK


def _region_from_timezone(tz: str) -> int:
    """Fallback region inference based only on timezone."""
    if not tz:
        return REGION_FALLBACK

    # Americas, including Pacific/Honolulu
    if tz.startswith("America/") or tz.startswith("Pacific/"):
        # Explicitly treat Cancun and Mazatlan as Mexico/Central bucket
        if tz in ("America/Cancun", "America/Mazatlan"):
            return REGION_MEX_CENTRAL
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

    Region order (top→bottom in dropdown):
        0: USA + Canada + Caribbean
        1: Mexico + Costa Rica
        2: Europe
        3: Asia + Australia
        99: fallback / unknown

    FIX FOR BALI:
    - If timezone clearly says Europe or Asia/Australia, we TRUST the timezone.
      (So Bali: tz='Asia/Singapore' → Asia/AU, even though code='ID' is also a US state.)
    - Otherwise (Americas / unknown), we use the code if available.
    """
    tz = resort.get("timezone") or ""

    tz_region = _region_from_timezone(tz)
    code_region = _region_from_code_or_country(resort)

    # 1) If timezone unambiguously says Europe or Asia/Australia, trust it.
    if tz_region in (REGION_EUROPE, REGION_ASIA_AU):
        return tz_region

    # 2) Otherwise we're likely in the Americas / unknown; use code if helpful.
    if code_region != REGION_FALLBACK:
        return code_region

    # 3) If code didn't help but timezone did, use timezone.
    if tz_region != REGION_FALLBACK:
        return tz_region

    # 4) Complete fallback.
    return REGION_FALLBACK


def sort_resorts_west_to_east(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort resorts so the Streamlit dropdown flows TOP→BOTTOM as:

      [Region 0] USA + Canada + Caribbean (west→east)
      [Region 1] Mexico + Costa Rica (west→east)
      [Region 2] Europe (west→east)
      [Region 3] Asia + Australia (west→east)
      [Region 99] Unknown / fallback

    Within each region:
      1. By COMMON_TZ_ORDER index (explicit west→east list)
      2. Then by UTC offset in minutes (for timezones not in COMMON_TZ_ORDER)
      3. Then by display_name / resort_name alphabetically
    """
    def sort_key(r: Dict[str, Any]):
        region_prio = get_region_priority(r)

        tz = r.get("timezone") or "UTC"
        if tz in COMMON_TZ_ORDER:
            tz_index = COMMON_TZ_ORDER.index(tz)
        else:
            # Unknown timezones come after known ones within the region,
            # ordered by UTC offset as a rough west→east indicator.
            tz_index = len(COMMON_TZ_ORDER)

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
