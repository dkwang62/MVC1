import math
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
import pandas as pd
import plotly.express as px
import streamlit as st
from common.ui import render_resort_card, render_resort_grid, render_page_header
from common.charts import create_gantt_chart_from_resort_data
from common.data import ensure_data_in_session

# ==============================================================================
# LAYER 1: DOMAIN MODELS (Type-Safe Data Structures)
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

@dataclass
class ComparisonResult:
    pivot_df: pd.DataFrame
    daily_chart_df: pd.DataFrame
    holiday_chart_df: pd.DataFrame

# ==============================================================================
# LAYER 2: REPOSITORY (Data Access Layer)
# ==============================================================================
class MVCRepository:
    def __init__(self, raw_data: dict):
        self._raw = raw_data
        self._resort_cache: Dict[str, ResortData] = {}
        self._global_holidays = self._parse_global_holidays()

    def get_resort_list(self) -> List[str]:
        return sorted([r["display_name"] for r in self._raw.get("resorts", [])])

    def get_resort_list_full(self) -> List[Dict[str, Any]]:
        """Return raw resort dictionaries (used for grid rendering)."""
        return self._raw.get("resorts", [])

    def _parse_global_holidays(
        self,
    ) -> Dict[str, Dict[str, Tuple[date, date]]]:
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
        """Get additional resort information for card display."""
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
# LAYER 3: SERVICE (Pure Business Logic Engine)
# ==============================================================================
class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _get_daily_points(
        self,
        resort: ResortData,
        day: date
    ) -> Tuple[Dict[str, int], Optional[Holiday]]:
        year_str = str(day.year)
        if year_str not in resort.years:
            return {}, None
        yd = resort.years[year_str]
        # Check holiday first
        for h in yd.holidays:
            if h.start_date <= day <= h.end_date:
                return h.room_points, h
        # Then regular seasons
        dow_map = {
            0: "Mon",
            1: "Tue",
            2: "Wed",
            3: "Thu",
            4: "Fri",
            5: "Sat",
            6: "Sun",
        }
        dow = dow_map[day.weekday()]
        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days:
                            return cat.room_points, None
        return {}, None

    def calculate_breakdown(
        self,
        resort_name: str,
        room: str,
        checkin: date,
        nights: int,
        user_mode: UserMode,
        rate: float,
        discount_policy: DiscountPolicy = DiscountPolicy.NONE,
        owner_config: Optional[dict] = None,
    ) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return CalculationResult(
                breakdown_df=pd.DataFrame(),
                total_points=0,
                financial_total=0.0,
                discount_applied=False,
                discounted_days=[],
            )
        rows: List[Dict[str, Any]] = []
        tot_eff_pts = 0
        tot_financial = 0.0
        tot_m = tot_c = tot_d = 0.0
        disc_applied = False
        disc_days: List[str] = []
        is_owner = user_mode == UserMode.OWNER
        processed_holidays: set[str] = set()
        i = 0
        today = datetime.now().date()
        while i < nights:
            d = checkin + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            day_str = d.strftime("%a")
            pts_map, holiday = self._get_daily_points(resort, d)
            # Holiday block (full-period pricing once)
            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                is_disc_holiday = False
                days_out = (holiday.start_date - today).days
                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0)
                    disc_pct = (1 - disc_mul) * 100
                    thresh = 30 if disc_pct == 25 else 60 if disc_pct == 30 else 0
                    if disc_pct > 0 and days_out <= thresh:
                        eff = math.floor(raw * disc_mul)
                        is_disc_holiday = True
                else:
                    renter_disc_mul = 1.0
                    if discount_policy == DiscountPolicy.PRESIDENTIAL:
                        renter_disc_mul = 0.7
                    elif discount_policy == DiscountPolicy.EXECUTIVE:
                        renter_disc_mul = 0.75
                    if (
                        discount_policy == DiscountPolicy.PRESIDENTIAL
                        and days_out <= 60
                    ) or (
                        discount_policy == DiscountPolicy.EXECUTIVE and days_out <= 30
                    ):
                        eff = math.floor(raw * renter_disc_mul)
                        is_disc_holiday = True
                if is_disc_holiday:
                    disc_applied = True
                    for j in range(holiday_days):
                        disc_date = holiday.start_date + timedelta(days=j)
                        disc_days.append(disc_date.strftime("%Y-%m-%d"))
                # Cost computation
                holiday_cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    if owner_config.get("inc_m", False):
                        m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    holiday_cost = m + c + dp
                else:
                    holiday_cost = math.ceil(eff * rate)
                row: Dict[str, Any] = {
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d, %Y')} - "
                    f"{holiday.end_date.strftime('%b %d, %Y')})",
                    "Day": "",
                    "Points": eff,
                }
                if is_owner:
                    if owner_config and owner_config.get("inc_m", False):
                        row["Maintenance"] = m
                    if owner_config and owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config and owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = holiday_cost
                else:
                    row[room] = holiday_cost
                rows.append(row)
                tot_eff_pts += eff
                tot_financial += holiday_cost
                tot_m += m
                tot_c += c
                tot_d += dp
                i += holiday_days
            # Regular day
            elif not holiday:
                raw = pts_map.get(room, 0)
                eff = raw
                is_disc_day = False
                days_out = (d - today).days
                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0)
                    disc_pct = (1 - disc_mul) * 100
                    thresh = 30 if disc_pct == 25 else 60 if disc_pct == 30 else 0
                    if disc_pct > 0 and days_out <= thresh:
                        eff = math.floor(raw * disc_mul)
                        is_disc_day = True
                else:
                    renter_disc_mul = 1.0
                    if discount_policy == DiscountPolicy.PRESIDENTIAL:
                        renter_disc_mul = 0.7
                    elif discount_policy == DiscountPolicy.EXECUTIVE:
                        renter_disc_mul = 0.75
                    if (
                        discount_policy == DiscountPolicy.PRESIDENTIAL
                        and days_out <= 60
                    ) or (
                        discount_policy == DiscountPolicy.EXECUTIVE and days_out <= 30
                    ):
                        eff = math.floor(raw * renter_disc_mul)
                        is_disc_day = True
                if is_disc_day:
                    disc_applied = True
                    disc_days.append(d_str)
                day_cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    if owner_config.get("inc_m", False):
                        m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    day_cost = m + c + dp
                else:
                    day_cost = math.ceil(eff * rate)
                row = {
                    "Date": d_str,
                    "Day": day_str,
                    "Points": eff,
                }
                if is_owner:
                    if owner_config and owner_config.get("inc_m", False):
                        row["Maintenance"] = m
                    if owner_config and owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config and owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = day_cost
                else:
                    row[room] = day_cost
                rows.append(row)
                tot_eff_pts += eff
                tot_financial += day_cost
                tot_m += m
                tot_c += c
                tot_d += dp
                i += 1
            else:
                # Should not be hit, but keep safety
                i += 1
        df = pd.DataFrame(rows)
        # Format currency columns
        if is_owner and not df.empty:
            for col in ["Maintenance", "Capital Cost", "Depreciation", "Total Cost"]:
                if col in df.columns:
                    df[col] = df[col].apply(
                        lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x
                    )
        else:
            for col in df.columns:
                if col not in ["Date", "Day", "Points"]:
                    df[col] = df[col].apply(
                        lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x
                    )
        return CalculationResult(
            breakdown_df=df,
            total_points=tot_eff_pts,
            financial_total=tot_financial,
            discount_applied=disc_applied,
            discounted_days=list(set(disc_days)),
            m_cost=tot_m,
            c_cost=tot_c,
            d_cost=tot_d,
        )

    def compare_stays(
        self,
        resort_name: str,
        rooms: List[str],
        checkin: date,
        nights: int,
        user_mode: UserMode,
        rate: float,
        policy: DiscountPolicy,
        owner_config: Optional[dict],
    ) -> ComparisonResult:
        daily_data: List[Dict[str, Any]] = []
        holiday_data: Dict[str, Dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        is_owner = user_mode == UserMode.OWNER
        disc_mul = owner_config["disc_mul"] if owner_config else 1.0
        renter_mul = 1.0
        if not is_owner:
            if policy == DiscountPolicy.PRESIDENTIAL:
                renter_mul = 0.7
            elif policy == DiscountPolicy.EXECUTIVE:
                renter_mul = 0.75
        val_key = "TotalCostValue" if is_owner else "RentValue"
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return ComparisonResult(
                pivot_df=pd.DataFrame(),
                daily_chart_df=pd.DataFrame(),
                holiday_chart_df=pd.DataFrame(),
            )
        processed_holidays: Dict[str, set[str]] = {room: set() for room in rooms}
        today = datetime.now().date()
        for room in rooms:
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)
                # Holiday, price once per holiday per room
                if h and h.name not in processed_holidays[room]:
                    processed_holidays[room].add(h.name)
                    raw = pts_map.get(room, 0)
                    eff = raw
                    days_out = (h.start_date - today).days
                    if is_owner:
                        disc_pct = (1 - disc_mul) * 100
                        thresh = 30 if disc_pct == 25 else 60 if disc_pct == 30 else 0
                        if disc_pct > 0 and days_out <= thresh:
                            eff = math.floor(raw * disc_mul)
                        else:
                            eff = raw
                    else:
                        if (
                            policy == DiscountPolicy.PRESIDENTIAL and days_out <= 60
                        ) or (policy == DiscountPolicy.EXECUTIVE and days_out <= 30):
                            eff = math.floor(raw * renter_mul)
                    if is_owner:
                        m = c = dp = 0.0
                        if owner_config and owner_config.get("inc_m", False):
                            m = math.ceil(eff * rate)
                        if owner_config and owner_config.get("inc_c", False):
                            c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                        if owner_config and owner_config.get("inc_d", False):
                            dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                        cost = m + c + dp
                    else:
                        cost = math.ceil(eff * rate)
                    holiday_data[room][h.name] += cost
                    holiday_days = (h.end_date - h.start_date).days + 1
                    i += holiday_days
                # Regular days
                elif not h:
                    raw = pts_map.get(room, 0)
                    eff = raw
                    days_out = (d - today).days
                    if is_owner:
                        disc_pct = (1 - disc_mul) * 100
                        thresh = 30 if disc_pct == 25 else 60 if disc_pct == 30 else 0
                        if disc_pct > 0 and days_out <= thresh:
                            eff = math.floor(raw * disc_mul)
                        else:
                            eff = raw
                    else:
                        if (
                            policy == DiscountPolicy.PRESIDENTIAL
                            and days_out <= 60
                        ) or (
                            policy == DiscountPolicy.EXECUTIVE
                            and days_out <= 30
                        ):
                            eff = math.floor(raw * renter_mul)
                    if is_owner:
                        m = c = dp = 0.0
                        if owner_config and owner_config.get("inc_m", False):
                            m = math.ceil(eff * rate)
                        if owner_config and owner_config.get("inc_c", False):
                            c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                        if owner_config and owner_config.get("inc_d", False):
                            dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                        cost = m + c + dp
                    else:
                        cost = math.ceil(eff * rate)
                    daily_data.append(
                        {
                            "Day": d.strftime("%a"),
                            "Date": d,
                            "Room Type": room,
                            val_key: cost,
                            "Holiday": "No",
                        }
                    )
                    i += 1
                else:
                    i += 1
        # Build pivot table using the main breakdown of the primary room as template
        template_res = self.calculate_breakdown(
            resort_name,
            rooms[0],
            checkin,
            nights,
            user_mode,
            rate,
            policy,
            owner_config,
        )
        pivot_rows: List[Dict[str, Any]] = []
        for _, tmpl_row in template_res.breakdown_df.iterrows():
            new_row: Dict[str, Any] = {"Date": tmpl_row["Date"]}
            for room in rooms:
                # Holiday row
                if "(" in str(tmpl_row["Date"]):
                    h_name = str(tmpl_row["Date"]).split(" (")[0]
                    val = holiday_data[room].get(h_name, 0.0)
                else:
                    # Day row
                    try:
                        d_obj = datetime.strptime(
                            str(tmpl_row["Date"]), "%Y-%m-%d"
                        ).date()
                    except Exception:
                        d_obj = None
                    if d_obj is not None:
                        val = next(
                            (
                                x[val_key]
                                for x in daily_data
                                if x["Date"] == d_obj and x["Room Type"] == room
                            ),
                            0.0,
                        )
                    else:
                        val = 0.0
                new_row[room] = f"${val:,.0f}"
            pivot_rows.append(new_row)
        # Total row
        total_label = "Total Cost" if is_owner else "Total Rent"
        tot_row: Dict[str, Any] = {"Date": total_label}
        for r in rooms:
            tot_sum = sum(
                x[val_key] for x in daily_data if x["Room Type"] == r
            ) + sum(holiday_data[r].values())
            tot_row[r] = f"${tot_sum:,.0f}"
        pivot_rows.append(tot_row)
        # Holiday chart rows
        h_chart_rows: List[Dict[str, Any]] = []
        for r, h_map in holiday_data.items():
            for h_name, val in h_map.items():
                h_chart_rows.append(
                    {"Holiday": h_name, "Room Type": r, val_key: val}
                )
        daily_df = pd.DataFrame(daily_data)
        holiday_df = pd.DataFrame(h_chart_rows)
        return ComparisonResult(
            pivot_df=pd.DataFrame(pivot_rows),
            daily_chart_df=daily_df,
            holiday_chart_df=holiday_df,
        )

    def adjust_holiday(
        self, resort_name: str, checkin: date, nights: int
    ) -> Tuple[date, int, bool]:
        """If stay overlaps holidays, expand to full holiday span."""
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years:
            return checkin, nights, False
        end = checkin + timedelta(days=nights - 1)
        yd = resort.years[str(checkin.year)]
        overlapping: List[Holiday] = []
        for h in yd.holidays:
            if h.start_date <= end and h.end_date >= checkin:
                overlapping.append(h)
        if not overlapping:
            return checkin, nights, False
        earliest_start = min(h.start_date for h in overlapping)
        latest_end = max(h.end_date for h in overlapping)
        adjusted_start = min(checkin, earliest_start)
        adjusted_end = max(end, latest_end)
        adjusted_nights = (adjusted_end - adjusted_start).days + 1
        return adjusted_start, adjusted_nights, True

# ==============================================================================
# LAYER 4: UI HELPERS
# ==============================================================================
def render_metrics_grid(
    result: CalculationResult,
    mode: UserMode,
    owner_params: Optional[dict],
    policy: DiscountPolicy,
) -> None:
    """Render summary metrics in a responsive grid."""
    owner_params = owner_params or {}
    if mode == UserMode.OWNER:
        num_components = sum(
            [
                owner_params.get("inc_m", False),
                owner_params.get("inc_c", False),
                owner_params.get("inc_d", False),
            ]
        )
        cols = st.columns(2 + max(num_components, 0))
        with cols[0]:
            st.metric(
                label="📊 Total Points",
                value=f"{result.total_points:,}",
                help="Total vacation points required for this stay",
            )
        with cols[1]:
            st.metric(
                label="💰 Total Cost",
                value=f"${result.financial_total:,.0f}",
                help="Total ownership cost including all selected components",
            )
        col_idx = 2
        if owner_params.get("inc_m"):
            with cols[col_idx]:
                st.metric(
                    label="🔧 Maintenance",
                    value=f"${result.m_cost:,.0f}",
                    help="Annual Maintenance attributable to this stay",
                )
            col_idx += 1
        if owner_params.get("inc_c"):
            with cols[col_idx]:
                st.metric(
                    label="💼 Capital Cost",
                    value=f"${result.c_cost:,.0f}",
                    help="Opportunity cost of capital tied up in ownership",
                )
            col_idx += 1
        if owner_params.get("inc_d"):
            with cols[col_idx]:
                st.metric(
                    label="📉 Depreciation",
                    value=f"${result.d_cost:,.0f}",
                    help="Share of asset depreciation for this usage",
                )
            col_idx += 1
    else:
        if result.discount_applied:
            cols = st.columns(3)
            pct = "30%" if policy == DiscountPolicy.PRESIDENTIAL else "25%"
            with cols[0]:
                st.metric(
                    label="📊 Total Points",
                    value=f"{result.total_points:,}",
                    help="Discounted points required",
                )
            with cols[1]:
                st.metric(
                    label="💰 Total Rent",
                    value=f"${result.financial_total:,.0f}",
                    help="Total rental cost (based on discounted points)",
                )
            with cols[2]:
                st.metric(
                    label="🎉 Discount Applied",
                    value=pct,
                    delta=f"{len(result.discounted_days)} days",
                    help="Points discount for last-minute booking",
                )
        else:
            cols = st.columns(2)
            with cols[0]:
                st.metric(
                    label="📊 Total Points",
                    value=f"{result.total_points:,}",
                    help="Total vacation points required",
                )
            with cols[1]:
                st.metric(
                    label="💰 Total Rent",
                    value=f"${result.financial_total:,.0f}",
                    help="Total rental cost (no points discount)",
                )

# ==============================================================================
# MAIN PAGE LOGIC
# ==============================================================================
def main() -> None:
    # Initialise session state (calculator-specific keys)
    if "current_resort" not in st.session_state:
        st.session_state.current_resort = None
    if "current_resort_id" not in st.session_state:
        st.session_state.current_resort_id = None
    if "show_help" not in st.session_state:
        st.session_state.show_help = False

    # 1) Shared data auto-load (no uploader here)
    ensure_data_in_session()

    # 2) If no data, bail out early
    if not st.session_state.data:
        st.warning("⚠️ Please open the Editor and upload/merge data_v2.json first.")
        st.info(
            "The calculator reads the same in-memory data as the Editor. "
            "Once the Editor has loaded your JSON file, you can use the calculator here."
        )
        return

    # 3) Sidebar: user settings only
    with st.sidebar:
        st.divider()
        st.markdown("### 👤 User Settings")
        # --- User mode selection & parameters ---
        mode_sel = st.selectbox(
            "User Mode",
            [m.value for m in UserMode],
            index=0,
            help="Select whether you're renting points or own them.",
        )
        mode = UserMode(mode_sel)
        owner_params: Optional[dict] = None
        policy: DiscountPolicy = DiscountPolicy.NONE
        # Temporarily set rate; may be overridden later based on mode + year
        rate = 0.50
        opt = "No Discount"  # Default

        if mode == UserMode.OWNER:
            st.markdown("#### 💰 Ownership Parameters")
            rate = st.number_input(
                "Maintenance per Point ($)",
                value=0.50,
                step=0.01,
                min_value=0.0,
            )
            opt = st.radio(
                "Discount Option",
                [
                    "No Discount",
                    "Executive: 25% Points Discount (within 30 days)",
                    "Presidential: 30% Points Discount (within 60 days)",
                ],
                help="Select discount options.",
            )
            cap = st.number_input(
                "Purchase Price per Point ($)",
                value=18.0,
                step=1.0,
                min_value=0.0,
                help="Initial purchase price per MVC point.",
            )
            coc = (
                st.number_input(
                    "Cost of Capital (%)",
                    value=6.0,
                    step=0.5,
                    min_value=0.0,
                    help="Expected return on alternative investments.",
                )
                / 100.0
            )
            life = st.number_input(
                "Useful Life (yrs)", value=15, min_value=1
            )
            salvage = st.number_input(
                "Salvage ($/pt)",
                value=3.0,
                step=0.5,
                min_value=0.0,
            )
            inc_m = st.checkbox(
                "Include Maintenance",
                True,
                help="Annual Maintenance.",
            )
            inc_c = st.checkbox(
                "Include Capital Cost",
                True,
                help="Opportunity cost of capital invested.",
            )
            inc_d = st.checkbox(
                "Include Depreciation",
                True,
                help="Asset depreciation over time.",
            )
            owner_params = {
                "disc_mul": 1.0,  # Will be set below
                "inc_m": inc_m,
                "inc_c": inc_c,
                "inc_d": inc_d,
                "cap_rate": cap * coc,
                "dep_rate": (cap - salvage) / life if life > 0 else 0.0,
            }
        else:
            st.markdown("#### 🏨 Rental Parameters")
            rate = st.number_input(
                "Maintenance per Point ($)",
                value=0.50,
                step=0.01,
                min_value=0.0,
            )
            opt = st.radio(
                "Discount Option",
                [
                    "No Discount",
                    "Executive: 25% Points Discount (within 30 days)",
                    "Presidential: 30% Points Discount (within 60 days)",
                ],
                help="Select discount options.",
            )
            if "Presidential" in opt:
                policy = DiscountPolicy.PRESIDENTIAL
            elif "Executive" in opt:
                policy = DiscountPolicy.EXECUTIVE
            # "No Discount" uses NONE

        # Set disc_mul for owners
        disc_mul = 1.0
        if "Executive" in opt:
            disc_mul = 0.75
        elif "Presidential" in opt:
            disc_mul = 0.7

        if owner_params:  # Only for owners
            owner_params["disc_mul"] = disc_mul

    # ===== Core calculator objects =====
    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)

    # ===== Main content =====
    render_page_header(
        "Calculator",
        f"👤 {mode.value} Mode: {'Ownership' if mode == UserMode.OWNER else 'Rental'} Cost Analysis",
        icon="🏨",
        badge_color="#059669" if mode == UserMode.OWNER else "#2563eb"
    )

    # Resorts list & current selection by id
    resorts_full = repo.get_resort_list_full()  # list of resort dicts
    if resorts_full and st.session_state.current_resort_id is None:
        st.session_state.current_resort_id = resorts_full[0].get("id")
    current_resort_id = st.session_state.current_resort_id

    # Shared grid (column-first) from common.ui
    render_resort_grid(resorts_full, current_resort_id)

    # Resolve selected resort object
    resort_obj = next(
        (r for r in resorts_full if r.get("id") == current_resort_id),
        None,
    )
    if not resort_obj:
        return
    r_name = resort_obj.get("display_name")
    if not r_name:
        return

    # Resort info card
    resort_info = repo.get_resort_info(r_name)
    render_resort_card(
        resort_info["full_name"],
        resort_info["timezone"],
        resort_info["address"],
    )
    st.divider()

    # ===== Booking details =====
    st.markdown("### 📅 Booking Details")
    input_cols = st.columns([2, 1, 2, 2])
    with input_cols[0]:
        checkin = st.date_input(
            "Check-in Date",
            datetime.now().date() + timedelta(days=1),
            format="YYYY/MM/DD",
            help="Your arrival date.",
        )
    with input_cols[1]:
        nights = st.number_input(
            "Nights",
            min_value=1,
            max_value=60,
            value=7,
            help="Number of nights to stay.",
        )

    # Holiday adjustment (extend stay to full holiday span)
    adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)
    if adj:
        end_date = adj_in + timedelta(days=adj_n - 1)
        st.info(
            f"ℹ️ **Adjusted to full holiday period:** "
            f"{adj_in.strftime('%b %d, %Y')} — {end_date.strftime('%b %d, %Y')} "
            f"({adj_n} nights)"
        )

    # Derive available room types from daily points for adjusted start
    pts, _ = calc._get_daily_points(calc.repo.get_resort(r_name), adj_in)
    if not pts:
        rd = calc.repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
            yd = rd.years[str(adj_in.year)]
            if yd.seasons:
                pts = yd.seasons[0].day_categories[0].room_points
    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("❌ No room data available for selected dates.")
        return

    with input_cols[2]:
        room_sel = st.selectbox(
            "Room Type",
            room_types,
            help="Select your primary room type.",
        )
    with input_cols[3]:
        comp_rooms = st.multiselect(
            "Compare With",
            [r for r in room_types if r != room_sel],
            help="Select additional room types to compare.",
        )
    st.divider()

    # ===== Calculation =====
    res = calc.calculate_breakdown(
        r_name, room_sel, adj_in, adj_n, mode, rate, policy, owner_params
    )
    st.markdown(f"### 📊 Results: {room_sel}")
    render_metrics_grid(res, mode, owner_params, policy)

    if res.discount_applied and mode == UserMode.RENTER:
        pct = "30%" if policy == DiscountPolicy.PRESIDENTIAL else "25%"
        st.success(
            f"🎉 **Discount Applied!** {pct} off points for {len(res.discounted_days)} day(s)."
        )
    st.divider()

    # Detailed breakdown
    st.markdown("### 📋 Detailed Breakdown")
    st.dataframe(
        res.breakdown_df,
        use_container_width=True,
        hide_index=True,
        height=min(400, (len(res.breakdown_df) + 1) * 35 + 50),
    )

    # Actions
    col1, col2, _ = st.columns([1, 1, 2])
    with col1:
        csv_data = res.breakdown_df.to_csv(index=False)
        st.download_button(
            "⬇️ Download CSV",
            csv_data,
            f"{r_name}_{room_sel}_{'rental' if mode == UserMode.RENTER else 'cost'}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col2:
        if st.button("ℹ️ How it is calculated", use_container_width=True):
            st.session_state.show_help = not st.session_state.show_help

    # Comparison section
    if comp_rooms:
        st.divider()
        st.markdown("### 🔍 Room Type Comparison")
        all_rooms = [room_sel] + comp_rooms
        comp_res = calc.compare_stays(
            r_name, all_rooms, adj_in, adj_n, mode, rate, policy, owner_params
        )
        st.dataframe(
            comp_res.pivot_df,
            use_container_width=True,
            hide_index=True,
        )
        # Visual analysis
        st.markdown("#### 📈 Visual Analysis")
        chart_cols = st.columns(2)
        with chart_cols[0]:
            if not comp_res.daily_chart_df.empty:
                y_col = "TotalCostValue" if mode == UserMode.OWNER else "RentValue"
                clean_df = comp_res.daily_chart_df[
                    comp_res.daily_chart_df["Holiday"] == "No"
                ]
                if not clean_df.empty:
                    fig = px.bar(
                        clean_df,
                        x="Day",
                        y=y_col,
                        color="Room Type",
                        barmode="group",
                        text=y_col,
                        category_orders={
                            "Day": ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]
                        },
                        title="Daily Costs by Day of Week",
                        color_discrete_sequence=px.colors.qualitative.Set2,
                    )
                    fig.update_traces(
                        texttemplate="$%{text:.0f}",
                        textposition="outside",
                    )
                    fig.update_layout(
                        height=450,
                        xaxis_title="Day of Week",
                        yaxis_title="Cost ($)",
                        legend_title="Room Type",
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig, use_container_width=True)
        with chart_cols[1]:
            if not comp_res.holiday_chart_df.empty:
                y_col = "TotalCostValue" if mode == UserMode.OWNER else "RentValue"
                h_fig = px.bar(
                    comp_res.holiday_chart_df,
                    x="Holiday",
                    y=y_col,
                    color="Room Type",
                    barmode="group",
                    text=y_col,
                    title="Holiday Period Costs",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                h_fig.update_traces(
                    texttemplate="$%{text:.0f}",
                    textposition="outside",
                )
                h_fig.update_layout(
                    height=450,
                    xaxis_title="Holiday Period",
                    yaxis_title="Cost ($)",
                    legend_title="Room Type",
                    hovermode="x unified",
                )
                st.plotly_chart(h_fig, use_container_width=True)

    # Season / Holiday timeline
    year_str = str(adj_in.year)
    res_data = calc.repo.get_resort(r_name)
    if res_data and year_str in res_data.years:
        st.divider()
        with st.expander("📅 Season and Holiday Calendar", expanded=False):
            gantt_fig = create_gantt_chart_from_resort_data(
                resort_data=res_data,
                year=year_str,
                global_holidays=st.session_state.data.get("global_holidays", {}),
                height=500,
            )
            st.plotly_chart(gantt_fig, use_container_width=True)

    # Help section
    if st.session_state.show_help:
        st.divider()
        with st.expander("ℹ️ How the Calculation Works", expanded=True):
            if mode == UserMode.OWNER:
                st.markdown(
                    f"""
                    ### 💰 Owner Cost Calculation
                    **Maintenance**
                    - Formula: Maintenance per point × points used
                    - Current Maintenance: **${rate:.2f}** per point
                    - Covers: Property upkeep, utilities, staff, amenities
                    **Capital Cost**
                    - Formula: Purchase price × cost of capital rate × points used
                    - Represents: Opportunity cost of capital invested in ownership
                    **Depreciation Cost**
                    - Formula: (Purchase price − salvage value) ÷ useful life × points used
                    - Represents: Asset value decline over time
                    **Points Calculation**
                    - Effective points may be reduced by last-minute owner discounts.
                    - Holiday periods are priced as whole blocks rather than per-night averages.
                    """
                )
            else:
                if policy == DiscountPolicy.PRESIDENTIAL:
                    discount_text = (
                        "**Presidential last-minute 30% points discount:** when booked "
                        "within 60 days of check-in."
                    )
                elif policy == DiscountPolicy.EXECUTIVE:
                    discount_text = (
                        "**Executive last-minute 25% points discount:** when booked "
                        "within 30 days of check-in."
                    )
                else:
                    discount_text = "**Standard points applied (no discount).**"
                st.markdown(
                    f"""
                    ### 🏨 Rent Calculation
                    **Current Maintenance:** **${rate:.2f}** per point.
                    {discount_text}
                    - The **Points** column may show reduced points if last-minute discounts apply.
                    - 💰 Rent is always computed from the **discounted** points.
                    - Holiday periods are treated as full blocks for pricing.
                    """
                )

def run() -> None:
    main()
