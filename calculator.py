import math
import json
import os
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
import pandas as pd
import plotly.express as px
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from PIL import Image
from common.ui import render_resort_card, render_resort_grid, render_page_header
from common.charts import create_gantt_chart_from_resort_data
from common.data import ensure_data_in_session

# ==============================================================================
# LAYER 1: DOMAIN MODELS
# ==============================================================================
class UserMode(Enum):
    RENTER = "Renter"
    OWNER = "Owner"

class DiscountPolicy(Enum):
    NONE = "None"
    EXECUTIVE = "within_30_days"  # 25%
    PRESIDENTIAL = "within_60_days"  # 30%

@dataclass
class Holiday:
    name: str
    start_date: date
    end_date: date
    room_points: Dict[str, int]

@dataclass
class DayCategory:
    days: List[str]
    room_points: Dict[str, int]

@dataclass
class SeasonPeriod:
    start: date
    end: date

@dataclass
class Season:
    name: str
    periods: List[SeasonPeriod]
    day_categories: List[DayCategory]

@dataclass
class ResortData:
    id: str
    name: str
    years: Dict[str, "YearData"]

@dataclass
class YearData:
    holidays: List[Holiday]
    seasons: List[Season]

@dataclass
class CalculationResult:
    breakdown_df: pd.DataFrame
    total_points: int
    financial_total: float
    discount_applied: bool
    discounted_days: List[str]
    m_cost: float = 0.0
    c_cost: float = 0.0
    d_cost: float = 0.0

# ==============================================================================
# LAYER 2: REPOSITORY
# ==============================================================================
class MVCRepository:
    def __init__(self, raw_data: dict):
        self._raw = raw_data
        self._resort_cache: Dict[str, ResortData] = {}
        self._global_holidays = self._parse_global_holidays()

    def get_resort_list_full(self) -> List[Dict[str, Any]]:
        return self._raw.get("resorts", [])

    def _parse_global_holidays(self) -> Dict[str, Dict[str, Tuple[date, date]]]:
        parsed: Dict[str, Dict[str, Tuple[date, date]]] = {}
        for year, hols in self._raw.get("global_holidays", {}).items():
            parsed[year] = {}
            for name, data in hols.items():
                try:
                    parsed[year][name] = (
                        datetime.strptime(data["start_date"], "%Y-%m-%d").date(),
                        datetime.strptime(data["end_date"], "%Y-%m-%d").date(),
                    )
                except Exception:
                    continue
        return parsed

    def get_resort(self, resort_name: str) -> Optional[ResortData]:
        if resort_name in self._resort_cache:
            return self._resort_cache[resort_name]
        raw_r = next(
            (r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name),
            None,
        )
        if not raw_r:
            return None
        years_data: Dict[str, YearData] = {}
        for year_str, y_content in raw_r.get("years", {}).items():
            holidays: List[Holiday] = []
            for h in y_content.get("holidays", []):
                ref = h.get("global_reference")
                if ref and ref in self._global_holidays.get(year_str, {}):
                    g_dates = self._global_holidays[year_str][ref]
                    holidays.append(
                        Holiday(
                            name=h.get("name", ref),
                            start_date=g_dates[0],
                            end_date=g_dates[1],
                            room_points=h.get("room_points", {}),
                        )
                    )
            seasons: List[Season] = []
            for s in y_content.get("seasons", []):
                periods: List[SeasonPeriod] = []
                for p in s.get("periods", []):
                    try:
                        periods.append(
                            SeasonPeriod(
                                start=datetime.strptime(p["start"], "%Y-%m-%d").date(),
                                end=datetime.strptime(p["end"], "%Y-%m-%d").date(),
                            )
                        )
                    except Exception:
                        continue

                day_cats: List[DayCategory] = []
                for cat in s.get("day_categories", {}).values():
                    day_cats.append(
                        DayCategory(
                            days=cat.get("day_pattern", []),
                            room_points=cat.get("room_points", {}),
                        )
                    )
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))

            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)
        resort_obj = ResortData(
            id=raw_r["id"], name=raw_r["display_name"], years=years_data
        )
        self._resort_cache[resort_name] = resort_obj
        return resort_obj

    def get_resort_info(self, resort_name: str) -> Dict[str, str]:
        raw_r = next(
            (r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name),
            None,
        )
        if raw_r:
            return {
                "full_name": raw_r.get("resort_name", resort_name),
                "timezone": raw_r.get("timezone", "Unknown"),
                "address": raw_r.get("address", "Address not available"),
            }
        return {
            "full_name": resort_name,
            "timezone": "Unknown",
            "address": "Address not available",
        }

# ==============================================================================
# LAYER 3: SERVICE
# ==============================================================================
class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _get_daily_points(self, resort: ResortData, day: date) -> Tuple[Dict[str, int], Optional[Holiday]]:
        year_str = str(day.year)
        if year_str not in resort.years:
            return {}, None

        yd = resort.years[year_str]

        # Check Holidays
        for h in yd.holidays:
            if h.start_date <= day <= h.end_date:
                return h.room_points, h

        # Check Seasons
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[day.weekday()]

        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days:
                            return cat.room_points, None
        return {}, None

    def calculate_breakdown(
        self, resort_name: str, room: str, checkin: date, nights: int,
        user_mode: UserMode, rate: float, discount_policy: DiscountPolicy = DiscountPolicy.NONE,
        owner_config: Optional[dict] = None,
    ) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])

        rate = round(float(rate), 2)
        rows: List[Dict[str, Any]] = []
        tot_eff_pts = 0
        tot_financial = 0.0
        tot_m = tot_c = tot_d = 0.0
        disc_applied = False
        disc_days: List[str] = []
        is_owner = user_mode == UserMode.OWNER
        processed_holidays: set[str] = set()
        i = 0

        while i < nights:
            d = checkin + timedelta(days=i)
            pts_map, holiday = self._get_daily_points(resort, d)

            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                is_disc = False

                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                    if disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                        is_disc = True
                else:
                    renter_mul = (
                        0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL
                        else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE
                        else 1.0
                    )
                    if renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)
                        is_disc = True
                if is_disc:
                    disc_applied = True
                    for j in range(holiday_days):
                        disc_days.append((holiday.start_date + timedelta(days=j)).strftime("%Y-%m-%d"))

                cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else:
                    cost = math.ceil(eff * rate)

                row = {
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')}) [{holiday_days} nights]",
                    "Points": eff
                }

                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost

                rows.append(row)
                tot_eff_pts += eff
                i += holiday_days

            elif not holiday:
                raw = pts_map.get(room, 0)
                eff = raw
                is_disc = False

                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                    if disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                        is_disc = True
                else:
                    renter_mul = (
                        0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL
                        else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE
                        else 1.0
                    )
                    if renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)
                        is_disc = True
                if is_disc:
                    disc_applied = True
                    disc_days.append(d.strftime("%Y-%m-%d"))

                cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else:
                    cost = math.ceil(eff * rate)

                row = {"Date": d.strftime("%Y-%m-%d (%a)"), "Points": eff}

                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost
                rows.append(row)
                tot_eff_pts += eff
                i += 1
            else:
                i += 1

        df = pd.DataFrame(rows)

        if user_mode == UserMode.RENTER:
            tot_financial = math.ceil(tot_eff_pts * rate)

        elif user_mode == UserMode.OWNER and owner_config:
            raw_maint = tot_eff_pts * rate
            raw_cap = 0.0
            if owner_config.get("inc_c", False):
                raw_cap = tot_eff_pts * owner_config.get("cap_rate", 0.0)
            raw_dep = 0.0
            if owner_config.get("inc_d", False):
                raw_dep = tot_eff_pts * owner_config.get("dep_rate", 0.0)
            tot_financial = math.ceil(raw_maint + raw_cap + raw_dep)

            tot_m = math.ceil(raw_maint)
            tot_c = math.ceil(raw_cap)
            tot_d = math.ceil(raw_dep)

        if not df.empty:
            fmt_cols = [c for c in df.columns if c not in ["Date", "Points"]]
            for col in fmt_cols:
                df[col] = df[col].apply(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x)

        return CalculationResult(df, tot_eff_pts, tot_financial, disc_applied, list(set(disc_days)), tot_m, tot_c, tot_d)

    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years:
            return checkin, nights, False

        end = checkin + timedelta(days=nights - 1)
        yd = resort.years[str(checkin.year)]
        overlapping = [h for h in yd.holidays if h.start_date <= end and h.end_date >= checkin]

        if not overlapping:
            return checkin, nights, False
        s = min(h.start_date for h in overlapping)
        e = max(h.end_date for h in overlapping)
        adj_s = min(checkin, s)
        adj_e = max(end, e)
        return adj_s, (adj_e - adj_s).days + 1, True

# ==============================================================================
# HELPER: SEASON COST TABLE
# ==============================================================================
def get_all_room_types_for_resort(resort_data: ResortData) -> List[str]:
    rooms = set()
    for year_obj in resort_data.years.values():
        for season in year_obj.seasons:
            for cat in season.day_categories:
                rooms.update(cat.room_points.keys())
        for holiday in year_obj.holidays:
            rooms.update(holiday.room_points.keys())
    return sorted(rooms)

# ==============================================================================
# GANTT CHART IMAGE RENDERING (Matplotlib)
# ==============================================================================
GANTT_COLORS = {
    "Peak": "#D73027", 
    "High": "#FC8D59", 
    "Mid": "#FEE08B", 
    "Low": "#91BFDB", 
    "Holiday": "#9C27B0"
}

def season_bucket(name: str) -> str:
    """Map season name to color bucket."""
    n = (name or "").lower()
    if "peak" in n: return "Peak"
    if "high" in n: return "High"
    if "mid" in n or "shoulder" in n: return "Mid"
    if "low" in n: return "Low"
    return "Low"

@st.cache_data(ttl=3600)
def render_gantt_image(resort_data: ResortData, year_str: str, global_holidays: dict) -> Optional[Image.Image]:
    """Render Gantt chart as matplotlib image."""
    rows = []
    
    if year_str not in resort_data.years:
        return None
    
    yd = resort_data.years[year_str]
    
    # Add seasons
    for s in yd.seasons:
        name = s.name
        bucket = season_bucket(name)
        for p in s.periods:
            rows.append((name, p.start, p.end, bucket))
    
    # Add holidays
    for h in yd.holidays:
        rows.append((h.name, h.start_date, h.end_date, "Holiday"))
    
    if not rows:
        return None
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, max(3, len(rows) * 0.5)))
    
    # Draw bars
    for i, (label, start, end, typ) in enumerate(rows):
        duration = (end - start).days + 1
        ax.barh(i, duration, left=mdates.date2num(start), height=0.6, 
                color=GANTT_COLORS.get(typ, "#999"), edgecolor="black", linewidth=0.5)
    
    # Configure axes
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([label for label, _, _, _ in rows])
    ax.invert_yaxis()
    
    # Format x-axis with simple month names (no year)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    
    # Grid and styling
    ax.grid(True, axis='x', alpha=0.3)
    
    # Simple title - just resort name and year
    resort_name = resort_data.name.replace("Marriott's ", "").replace(" - Marriott Vacation Club", "")
    ax.set_title(f"{resort_name} - {year_str}", pad=12, size=12)
    
    # Legend
    legend_elements = [
        plt.Rectangle((0,0), 1, 1, facecolor=GANTT_COLORS[k], label=k) 
        for k in GANTT_COLORS if any(t == k for _, _, _, t in rows)
    ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1, 1))
    
    # Convert to image
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    
    return Image.open(buf)

def build_season_cost_table(
    resort_data: ResortData,
    year: int,
    rate: float,
    discount_mul: float,
    mode: UserMode,
    owner_params: Optional[dict] = None
) -> Optional[pd.DataFrame]:
    yd = resort_data.years.get(str(year))
    if not yd:
        return None

    room_types = get_all_room_types_for_resort(resort_data)
    if not room_types:
        return None

    rows = []

    # Seasons
    for season in yd.seasons:
        name = season.name.strip() or "Unnamed Season"
        weekly = {}
        has_data = False

        for dow in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            for cat in season.day_categories:
                if dow in cat.days:
                    rp = cat.room_points
                    for room in room_types:
                        pts = rp.get(room, 0)
                        if pts:
                            has_data = True
                        weekly[room] = weekly.get(room, 0) + pts
                    break

        if has_data:
            row = {"Season": name}
            for room in room_types:
                raw_pts = weekly.get(room, 0)
                eff_pts = math.floor(raw_pts * discount_mul) if discount_mul < 1 else raw_pts
                if mode == UserMode.RENTER:
                    cost = math.ceil(eff_pts * rate)
                else:
                    m = math.ceil(eff_pts * rate) if owner_params.get("inc_m", False) else 0
                    c = math.ceil(eff_pts * owner_params.get("cap_rate", 0.0)) if owner_params.get("inc_c", False) else 0
                    d = math.ceil(eff_pts * owner_params.get("dep_rate", 0.0)) if owner_params.get("inc_d", False) else 0
                    cost = m + c + d
                row[room] = f"${cost:,}"
            rows.append(row)

    # Holidays
    for h in yd.holidays:
        name = h.name.strip() or "Holiday"
        rp = h.room_points
        row = {"Season": f"Holiday – {name}"}
        for room in room_types:
            raw = rp.get(room, 0)
            if not raw:
                row[room] = "—"
                continue
            eff = math.floor(raw * discount_mul) if discount_mul < 1 else raw
            if mode == UserMode.RENTER:
                cost = math.ceil(eff * rate)
            else:
                m = math.ceil(eff * rate) if owner_params.get("inc_m", False) else 0
                c = math.ceil(eff * owner_params.get("cap_rate", 0.0)) if owner_params.get("inc_c", False) else 0
                d = math.ceil(eff * owner_params.get("dep_rate", 0.0)) if owner_params.get("inc_d", False) else 0
                cost = m + c + d
            row[room] = f"${cost:,}"
        rows.append(row)

    return pd.DataFrame(rows, columns=["Season"] + room_types) if rows else None

# ==============================================================================
# MAIN PAGE LOGIC
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]

def get_unique_years_from_data(data: Dict[str, Any]) -> List[str]:
    """Helper to get years from both resorts and global holidays for date picker."""
    years = set()
    for resort in data.get("resorts", []):
        years.update(resort.get("years", {}).keys())
    if "global_holidays" in data:
        years.update(data["global_holidays"].keys())
    return sorted([y for y in years if y.isdigit() and len(y) == 4])

def apply_settings_from_dict(user_data: dict):
    try:
        if "maintenance_rate" in user_data: st.session_state.pref_maint_rate = float(user_data["maintenance_rate"])
        if "purchase_price" in user_data: st.session_state.pref_purchase_price = float(user_data["purchase_price"])
        if "capital_cost_pct" in user_data: st.session_state.pref_capital_cost = float(user_data["capital_cost_pct"])
        if "salvage_value" in user_data: st.session_state.pref_salvage_value = float(user_data["salvage_value"])
        if "useful_life" in user_data: st.session_state.pref_useful_life = int(user_data["useful_life"])

        if "discount_tier" in user_data:
            raw = str(user_data["discount_tier"])
            if "Executive" in raw: st.session_state.pref_discount_tier = TIER_EXECUTIVE
            elif "Presidential" in raw or "Chairman" in raw: st.session_state.pref_discount_tier = TIER_PRESIDENTIAL
            else: st.session_state.pref_discount_tier = TIER_NO_DISCOUNT

        if "include_capital" in user_data: st.session_state.pref_inc_c = bool(user_data["include_capital"])
        if "include_depreciation" in user_data: st.session_state.pref_inc_d = bool(user_data["include_depreciation"])

        if "renter_rate" in user_data:
            st.session_state.renter_rate_val = float(user_data["renter_rate"])

        if "renter_discount_tier" in user_data:
            raw_r = str(user_data["renter_discount_tier"])
            if "Executive" in raw_r: st.session_state.renter_discount_tier = TIER_EXECUTIVE
            elif "Presidential" in raw_r or "Chairman" in raw_r: st.session_state.renter_discount_tier = TIER_PRESIDENTIAL
            else: st.session_state.renter_discount_tier = TIER_NO_DISCOUNT

        if "preferred_resort_id" in user_data:
            rid = str(user_data["preferred_resort_id"])
            st.session_state.pref_resort_id = rid
            st.session_state.current_resort_id = rid

    except Exception as e:
        st.error(f"Error applying settings: {e}")

def main(forced_mode: str = "Renter") -> None:
    # --- 0. INIT STATE ---
    if "current_resort" not in st.session_state: st.session_state.current_resort = None
    if "current_resort_id" not in st.session_state: st.session_state.current_resort_id = None
    
    ensure_data_in_session()

    # --- 1. AUTO-LOAD LOCAL FILE ON STARTUP ---
    if "settings_auto_loaded" not in st.session_state:
        local_settings = "mvc_owner_settings.json"
        if os.path.exists(local_settings):
            try:
                with open(local_settings, "r") as f:
                    data = json.load(f)
                    apply_settings_from_dict(data)
                    st.toast("Auto-loaded local settings!", icon="Settings")
            except Exception:
                pass
        st.session_state.settings_auto_loaded = True

    # --- 2. DEFAULTS ---
    if "pref_maint_rate" not in st.session_state: st.session_state.pref_maint_rate = 0.55
    if "pref_purchase_price" not in st.session_state: st.session_state.pref_purchase_price = 18.0
    if "pref_capital_cost" not in st.session_state: st.session_state.pref_capital_cost = 5.0
    if "pref_salvage_value" not in st.session_state: st.session_state.pref_salvage_value = 3.0
    if "pref_useful_life" not in st.session_state: st.session_state.pref_useful_life = 10
    if "pref_discount_tier" not in st.session_state: st.session_state.pref_discount_tier = TIER_NO_DISCOUNT

    st.session_state.pref_inc_m = True
    if "pref_inc_c" not in st.session_state: st.session_state.pref_inc_c = True
    if "pref_inc_d" not in st.session_state: st.session_state.pref_inc_d = True

    if "renter_rate_val" not in st.session_state: st.session_state.renter_rate_val = 0.50
    if "renter_discount_tier" not in st.session_state: st.session_state.renter_discount_tier = TIER_NO_DISCOUNT

    today = datetime.now().date()
    initial_default = today + timedelta(days=1)
    if "calc_initial_default" not in st.session_state:
        st.session_state.calc_initial_default = initial_default
        st.session_state.calc_checkin = initial_default
        st.session_state.calc_checkin_user_set = False
    
    # Initialize nights default
    if "calc_nights" not in st.session_state:
        st.session_state.calc_nights = 7

    if not st.session_state.data:
        st.warning("Please open the Editor and upload/merge data_v2.json first.")
        return

    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts_full = repo.get_resort_list_full()

    # Determine mode from arg
    mode = UserMode(forced_mode)

    render_page_header("Calc", f"{mode.value} Mode", icon="🏨", badge_color="#059669" if mode == UserMode.OWNER else "#2563eb")

    # --- MAIN PAGE: CONFIGURATION EXPANDER (Moved from Sidebar) ---
    owner_params = None
    policy = DiscountPolicy.NONE
    rate_to_use = 0.50
    disc_mul = 1.0

    # --- RESORT SELECTION ---
    if resorts_full and st.session_state.current_resort_id is None:
        if "pref_resort_id" in st.session_state and any(r.get("id") == st.session_state.pref_resort_id for r in resorts_full):
            st.session_state.current_resort_id = st.session_state.pref_resort_id
        else:
            st.session_state.current_resort_id = resorts_full[0].get("id")

    render_resort_grid(resorts_full, st.session_state.current_resort_id)
    resort_obj = next((r for r in resorts_full if r.get("id") == st.session_state.current_resort_id), None)

    if not resort_obj: return

    r_name = resort_obj.get("display_name")
    
    # Clear room type selection if resort has changed
    if "last_resort_id" not in st.session_state:
        st.session_state.last_resort_id = st.session_state.current_resort_id
    
    if st.session_state.last_resort_id != st.session_state.current_resort_id:
        # Resort changed - clear room selection so ALL rooms table expands
        if "selected_room_type" in st.session_state:
            del st.session_state.selected_room_type
        st.session_state.last_resort_id = st.session_state.current_resort_id
    
    info = repo.get_resort_info(r_name)
    render_resort_card(info["full_name"], info["timezone"], info["address"])
    
    # --- CALCULATOR INPUTS: Check-in, Nights, and calculated Checkout ---
    c1, c2, c3 = st.columns([2, 1, 2])
    with c1:
        # Get available years for the date picker
        available_years = get_unique_years_from_data(st.session_state.data)
        min_date = datetime.now().date()
        max_date = datetime.now().date() + timedelta(days=365*2)
        
        if available_years:
            min_y = int(available_years[0])
            max_y = int(available_years[-1])
            min_date = date(min_y, 1, 1)
            max_date = date(max_y, 12, 31)
            
        checkin = st.date_input(
            "Check-in", 
            value=st.session_state.calc_checkin, 
            min_value=min_date,
            max_value=max_date,
            key="calc_checkin_widget"
        )
        
        # Update session state with new check-in date
        st.session_state.calc_checkin = checkin

    if not st.session_state.calc_checkin_user_set and checkin != st.session_state.calc_initial_default:
        st.session_state.calc_checkin_user_set = True
        
    with c2:
        nights = st.number_input(
            "Nights", 
            min_value=1, 
            max_value=60, 
            value=st.session_state.calc_nights,
            key="nights_input",
            step=1
        )
        
        # Update session state immediately
        st.session_state.calc_nights = nights
    
    with c3:
        # Calculate checkout date - recalculates on every render based on current inputs
        checkout_date = checkin + timedelta(days=nights)
        
        # Display as a disabled date_input
        # Using hash of date as key to force update when value changes
        st.date_input(
            "Check-out",
            value=checkout_date,
            disabled=True,
            key="checkout_display"
        )

    # Always adjust for holidays when dates overlap
    adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)

    if adj:
        # Holiday adjustment occurred - show prominent alert
        original_checkout = checkin + timedelta(days=nights - 1)
        adjusted_checkout = adj_in + timedelta(days=adj_n - 1)
        
        # Determine what changed
        date_changed = checkin != adj_in
        nights_changed = nights != adj_n
        
        # Build detailed message
        changes = []
        if date_changed:
            changes.append(f"Check-in moved from **{checkin.strftime('%b %d')}** to **{adj_in.strftime('%b %d')}**")
        if nights_changed:
            changes.append(f"Stay extended from **{nights} nights** to **{adj_n} nights**")
        
        change_text = " and ".join(changes)
        
        st.warning(
            f"🎉 **Holiday Period Detected!**\n\n"
            f"Your dates overlap with a holiday period. To get holiday pricing, your reservation has been adjusted:\n\n"
            f"{change_text}\n\n"
            f"**New stay:** {adj_in.strftime('%b %d, %Y')} - {adjusted_checkout.strftime('%b %d, %Y')} ({adj_n} nights)",
            icon="⚠️"
        )

    # Get all available room types for this resort
    pts, _ = calc._get_daily_points(calc.repo.get_resort(r_name), adj_in)
    if not pts:
        rd = calc.repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
             yd = rd.years[str(adj_in.year)]
             if yd.seasons: pts = yd.seasons[0].day_categories[0].room_points

    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("No room data available for this resort.")
        return

    st.divider()

    # --- SETTINGS EXPANDER ---
    with st.expander("⚙️ Settings", expanded=False):
        if mode == UserMode.OWNER:
            c1, c2 = st.columns(2)
            with c1:
                current_val = st.session_state.get("pref_maint_rate", 0.55)
                val_rate = st.number_input(
                    "Maintenance ($/point)",
                    value=current_val,
                    key="widget_maint_rate",
                    step=0.01, min_value=0.0
                )
                if val_rate != current_val:
                    st.session_state.pref_maint_rate = val_rate
                rate_to_use = val_rate

            with c2:
                current_tier = st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT)
                try: t_idx = TIER_OPTIONS.index(current_tier)
                except ValueError: t_idx = 0
                opt = st.radio("Discount Tier:", TIER_OPTIONS, index=t_idx, key="widget_discount_tier")
                st.session_state.pref_discount_tier = opt

            col_chk2, col_chk3 = st.columns(2)
            inc_m = True
            with col_chk2:
                inc_c = st.checkbox("Include Capital Cost", value=st.session_state.get("pref_inc_c", True), key="widget_inc_c")
                st.session_state.pref_inc_c = inc_c
            with col_chk3:
                inc_d = st.checkbox("Include Depreciation", value=st.session_state.get("pref_inc_d", True), key="widget_inc_d")
                st.session_state.pref_inc_d = inc_d

            cap, coc, life, salvage = 18.0, 0.06, 15, 3.0
            
            if inc_c or inc_d:
                st.markdown("---")
                rc1, rc2, rc3, rc4 = st.columns(4)
                with rc1:
                    val_cap = st.number_input("Purchase ($/pt)", value=st.session_state.get("pref_purchase_price", 18.0), key="widget_purchase_price", step=1.0)
                    st.session_state.pref_purchase_price = val_cap
                    cap = val_cap
                with rc2:
                    if inc_c:
                        val_coc = st.number_input("Cost of Capital (%)", value=st.session_state.get("pref_capital_cost", 5.0), key="widget_capital_cost", step=0.5)
                        st.session_state.pref_capital_cost = val_coc
                        coc = val_coc / 100.0
                with rc3:
                    if inc_d:
                        val_life = st.number_input("Useful Life (yrs)", value=st.session_state.get("pref_useful_life", 10), key="widget_useful_life", min_value=1)
                        st.session_state.pref_useful_life = val_life
                        life = val_life
                with rc4:
                    if inc_d:
                        val_salvage = st.number_input("Salvage ($/pt)", value=st.session_state.get("pref_salvage_value", 3.0), key="widget_salvage_value", step=0.5)
                        st.session_state.pref_salvage_value = val_salvage
                        salvage = val_salvage

            owner_params = {
                "disc_mul": 1.0, "inc_m": inc_m, "inc_c": inc_c, "inc_d": inc_d,
                "cap_rate": cap * coc, "dep_rate": (cap - salvage) / life if life > 0 else 0.0,
            }
            
            # Save/Load UI inside Settings Expander
            st.markdown("---")
            sl_col1, sl_col2 = st.columns([3, 1])
            with sl_col1:
                config_file = st.file_uploader("Load Saved Settings (JSON)", type="json", key="user_cfg_upload_main")
                if config_file:
                      file_sig = f"{config_file.name}_{config_file.size}"
                      if "last_loaded_cfg" not in st.session_state or st.session_state.last_loaded_cfg != file_sig:
                          config_file.seek(0)
                          data = json.load(config_file)
                          apply_settings_from_dict(data)
                          st.session_state.last_loaded_cfg = file_sig
                          st.rerun()
            with sl_col2:
                current_pref_resort = st.session_state.current_resort_id if st.session_state.current_resort_id else ""
                current_settings = {
                    "maintenance_rate": st.session_state.get("pref_maint_rate", 0.55),
                    "purchase_price": st.session_state.get("pref_purchase_price", 18.0),
                    "capital_cost_pct": st.session_state.get("pref_capital_cost", 5.0),
                    "salvage_value": st.session_state.get("pref_salvage_value", 3.0),
                    "useful_life": st.session_state.get("pref_useful_life", 10),
                    "discount_tier": st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT),
                    "include_maintenance": True,
                    "include_capital": st.session_state.get("pref_inc_c", True),
                    "include_depreciation": st.session_state.get("pref_inc_d", True),
                    "renter_rate": st.session_state.get("renter_rate_val", 0.50),
                    "renter_discount_tier": st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT),
                    "preferred_resort_id": current_pref_resort
                }
                st.download_button("💾 Save Profile", json.dumps(current_settings, indent=2), "mvc_owner_settings.json", "application/json", use_container_width=True)

        else:
            # RENTER MODE CONFIG
            c1, c2 = st.columns(2)
            with c1:
                curr_rent = st.session_state.get("renter_rate_val", 0.50)
                renter_rate_input = st.number_input("Rental Cost per Point ($)", value=curr_rent, step=0.01, key="widget_renter_rate")
                if renter_rate_input != curr_rent: st.session_state.renter_rate_val = renter_rate_input
                rate_to_use = renter_rate_input

            with c2:
                curr_r_tier = st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT)
                try: r_idx = TIER_OPTIONS.index(curr_r_tier)
                except ValueError: r_idx = 0
                opt = st.radio("Discount tier available:", TIER_OPTIONS, index=r_idx, key="widget_renter_discount_tier")
                st.session_state.renter_discount_tier = opt

            if "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL
            elif "Executive" in opt: policy = DiscountPolicy.EXECUTIVE

        # Common Logic for Discount Multiplier
        if mode == UserMode.OWNER:
             if "Executive" in opt: policy = DiscountPolicy.EXECUTIVE
             elif "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL

        disc_mul = 0.75 if "Executive" in opt else 0.7 if "Presidential" in opt or "Chairman" in opt else 1.0
        if owner_params: owner_params["disc_mul"] = disc_mul

    # --- ROOM TYPE SELECTION/DISPLAY ---
    # Determine if we should expand the ALL rooms table
    has_selection = "selected_room_type" in st.session_state and st.session_state.selected_room_type is not None
    is_single_room_resort = len(room_types) == 1
    
    # Auto-select if single room type and no selection yet
    if is_single_room_resort and not has_selection:
        st.session_state.selected_room_type = room_types[0]
        has_selection = True
    
    # Calculate costs for all room types (needed for both display modes)
    all_room_data = []
    for rm in room_types:
        room_res = calc.calculate_breakdown(r_name, rm, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
        cost_label = "Total Rent" if mode == UserMode.RENTER else "Total Cost"
        all_room_data.append({
            "Room Type": rm,
            "Points": room_res.total_points,
            cost_label: room_res.financial_total,
            "_select": rm
        })
    
    # Only show room selection UI if multiple room types exist
    if not is_single_room_resort:
        with st.expander("🏠 All Room Types", expanded=not has_selection):
            st.caption(f"Comparing all room types for {adj_n}-night stay from {adj_in.strftime('%b %d, %Y')}")
            
            # Display the table with select buttons
            for idx, row in enumerate(all_room_data):
                is_selected = has_selection and st.session_state.selected_room_type == row['Room Type']
                
                cols = st.columns([3, 2, 2, 1.5])
                with cols[0]:
                    # Add visual indicator for selected room
                    if is_selected:
                        st.write(f"**✓ {row['Room Type']}** (Selected)")
                    else:
                        st.write(f"**{row['Room Type']}**")
                with cols[1]:
                    st.write(f"{row['Points']:,} points")
                with cols[2]:
                    cost_label = "Total Rent" if mode == UserMode.RENTER else "Total Cost"
                    st.write(f"${row[cost_label]:,.0f}")
                with cols[3]:
                    # Button with calendar icon and "Dates" text
                    if is_selected:
                        st.button("📅 Dates", key=f"select_{row['_select']}", use_container_width=True, type="primary", disabled=True)
                    else:
                        if st.button("📅 Dates", key=f"select_{row['_select']}", use_container_width=True, type="secondary"):
                            st.session_state.selected_room_type = row['Room Type']
                            st.rerun()
    
    # --- DETAILED BREAKDOWN (Only shown when room type is selected) ---
    if has_selection:
        room_sel = st.session_state.selected_room_type
        
        # Header with calendar icon and room type description, Change Room button on right
        col_header, col_clear = st.columns([4, 1])
        with col_header:
            # Show info note for single room resorts
            if is_single_room_resort:
                st.markdown(f"### 📅 {room_sel}")
                st.caption("ℹ️ This resort has only one room type")
            else:
                st.markdown(f"### 📅 {room_sel}")
        with col_clear:
            # Only show Change Room button if multiple room types exist
            if not is_single_room_resort:
                if st.button("↩️ Change Room", use_container_width=True):
                    del st.session_state.selected_room_type
                    st.rerun()
        
        # Calculate the breakdown for selected room
        res = calc.calculate_breakdown(r_name, room_sel, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
        
        # Build enhanced settings caption
        discount_display = "None"
        if disc_mul < 1.0:
            pct = int((1.0 - disc_mul) * 100)
            policy_label = "Executive" if disc_mul == 0.75 else "Presidential/Chairman" if disc_mul == 0.7 else "Custom"
            discount_display = f"✅ {pct}% Off points ({policy_label})"

        rate_label = "Maintenance " if mode == UserMode.OWNER else "Rental Rate"

        settings_parts = []
        settings_parts.append(f"{rate_label}: ${rate_to_use:.2f}/pt")

        if mode == UserMode.OWNER:
            purchase_per_pt = st.session_state.get("pref_purchase_price", 18.0)
            total_purchase = purchase_per_pt * res.total_points
            useful_life = st.session_state.get("pref_useful_life", 10)

            settings_parts.append(f"Purchase USD {total_purchase:,.0f}")
            settings_parts.append(f"Useful Life: **{useful_life} yrs**")

        settings_parts.append(f"**{discount_display}**")

        st.caption(f"⚙️ Settings: " + " • ".join(settings_parts))

        # Display metrics
        if mode == UserMode.OWNER:
            cols = st.columns(5)
            cols[0].metric("Total Points", f"{res.total_points:,}")
            cols[1].metric("Total Cost", f"${res.financial_total:,.0f}")
            cols[2].metric("Maintenance", f"${res.m_cost:,.0f}")
            if inc_c: cols[3].metric("Capital Cost", f"${res.c_cost:,.0f}")
            if inc_d: cols[4].metric("Depreciation", f"${res.d_cost:,.0f}")
        else:
            cols = st.columns(2)
            cols[0].metric("Total Points", f"{res.total_points:,}")
            cols[1].metric("Total Rent", f"${res.financial_total:,.0f}")
            if res.discount_applied: st.success(f"✨ Discount Applied: {len(res.discounted_days)} nights")

        # Daily Breakdown - displayed directly without subtitle (self-explanatory)
        st.dataframe(res.breakdown_df, use_container_width=True, hide_index=True)
    
    # --- SEASON AND HOLIDAY CALENDAR (Always available, independent of selection) ---
    st.divider()
    year_str = str(adj_in.year)
    res_data = calc.repo.get_resort(r_name)
    if res_data and year_str in res_data.years:
        with st.expander("📅 Season & Holiday Calendar", expanded=False):
            # Render Gantt chart as static image
            gantt_img = render_gantt_image(res_data, year_str, st.session_state.data.get("global_holidays", {}))
            
            if gantt_img:
                st.image(gantt_img, use_column_width=True)
            else:
                st.info("No season or holiday calendar data available for this year.")

            cost_df = build_season_cost_table(res_data, int(year_str), rate_to_use, disc_mul, mode, owner_params)
            if cost_df is not None:
                title = "7-Night Rental Costs" if mode == UserMode.RENTER else "7-Night Ownership Costs"
                note = " — Discount applied" if disc_mul < 1 else ""
                st.markdown(f"**{title}** @ ${rate_to_use:.2f}/pt{note}")
                st.dataframe(cost_df, use_container_width=True, hide_index=True)
            else:
                st.info("No season or holiday pricing data for this year.")

def run(forced_mode: str = "Renter") -> None:
    main(forced_mode)
