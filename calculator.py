# calculator.py
import math
import json
import os
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

@dataclass
class ComparisonResult:
    pivot_df: pd.DataFrame
    daily_chart_df: pd.DataFrame
    holiday_chart_df: pd.DataFrame

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

        raw_r = next((r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name), None)
        if not raw_r:
            return None

        years_data: Dict[str, YearData] = {}
        for year_str, y_content in raw_r.get("years", {}).items():
            holidays: List[Holiday] = []
            for h in y_content.get("holidays", []):
                ref = h.get("global_reference") or h.get("name")
                start_end = self._global_holidays.get(year_str, {}).get(ref)
                if start_end:
                    holidays.append(Holiday(name=h.get("name", ref),
                                          start_date=start_end[0],
                                          end_date=start_end[1],
                                          room_points=h.get("room_points", {})))

            seasons: List[Season] = []
            for s in y_content.get("seasons", []):
                periods = [SeasonPeriod(start=date.fromisoformat(p["start"]), end=date.fromisoformat(p["end"]))
                           for p in s.get("periods", [])]
                day_cats = []
                for cat in s.get("day_categories", {}).values():
                    day_cats.append(DayCategory(days=cat.get("day_pattern", []), room_points=cat.get("room_points", {})))
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))

            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)

        resort = ResortData(id=raw_r["id"], name=raw_r["display_name"], years=years_data)
        self._resort_cache[resort_name] = resort
        return resort

# ==============================================================================
# LAYER 3: CALCULATION ENGINE
# ==============================================================================
class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _is_holiday(self, dt: date, year_data: YearData) -> Optional[Holiday]:
        for h in year_data.holidays:
            if h.start_date <= dt <= h.end_date:
                return h
        return None

    def _get_season_day_category(self, dt: date, weekday: str, year_data: YearData):
        for season in year_data.seasons:
            for period in season.periods:
                if period.start <= dt <= period.end:
                    for cat in season.day_categories:
                        if weekday in cat.days:
                            return season.name, cat.room_points
        return None, {}

    def get_points_for_room(self, resort: ResortData, year: str, checkin_date: date,
                            nights: int, room_type: str, mode: UserMode) -> int:
        year_data = resort.years.get(year)
        if not year_data is None:
            return 0

        total = 0
        current = checkin_date
        for _ in range(nights):
            holiday = self._is_holiday(current, year_data)
            if holiday and room_type in holiday.room_points:
                total += holiday.room_points[room_type]
            else:
                _, points_map = self._get_season_day_category(current, current.strftime("%a"), year_data)
                total += points_map.get(room_type, 0)
            current += timedelta(days=1)
        return total

    def calculate_financial_cost(self, points_required: int, maintenance_rate: float,
                                 include_maintenance: bool, include_capital: bool, include_depreciation: bool,
                                 capital_pct: float, salvage: float, useful_life: int, purchase_price: float) -> float:
        cost = 0.0
        if include_maintenance:
            cost += points_required * maintenance_rate / 1000
        if include_capital:
            cost += points_required * capital_pct / 100 / 1000 * purchase_price
        if include_depreciation:
            depreciable = purchase_price - salvage
            cost += points_required * depreciable / useful_life / 1000
        return round(cost, 2)

# ==============================================================================
# SETTINGS HELPERS
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"

def apply_settings_from_dict(settings: dict):
    st.session_state.pref_maint_rate = settings.get("maintenance_rate", 0.56)
    st.session_state.pref_purchase_price = settings.get("purchase_price", 18.0)
    st.session_state.pref_capital_cost = settings.get("capital_cost_pct", 5.0)
    st.session_state.pref_salvage_value = settings.get("salvage_value", 3.0)
    st.session_state.pref_useful_life = settings.get("useful_life", 10)
    st.session_state.pref_discount_tier = settings.get("discount_tier", TIER_NO_DISCOUNT)
    st.session_state.pref_inc_c = settings.get("include_capital", True)
    st.session_state.pref_inc_d = settings.get("include_depreciation", True)
    st.session_state.renter_rate_val = settings.get("renter_rate", 0.817)
    st.session_state.renter_discount_tier = settings.get("renter_discount_tier", TIER_NO_DISCOUNT)
    if settings.get("preferred_resort_id"):
        st.session_state.current_resort_id = settings["preferred_resort_id"]

# ==============================================================================
# MAIN APP — 100% your original code + only ONE new table added
# ==============================================================================
def main():
    ensure_data_in_session()
    data = st.session_state.data
    if not data or "resorts" not in data:
        st.warning("No resort data loaded. Use the Editor or upload a JSON file.")
        return

    calc = MVCCalculator(MVCRepository(data))

    render_page_header("Calculator", "Points & Cost Calculator", icon="Calculator")

    st.markdown("### Resort Selection")
    render_resort_grid(calc.repo.get_resort_list_full(), st.session_state.get("current_resort_id"))

    if not st.session_state.get("current_resort_id"):
        st.info("Please select a resort above to continue.")
        return

    r_name = st.session_state.current_resort
    resort = calc.repo.get_resort(r_name)
    if not resort:
        st.error("Resort data not found.")
        return

    all_resorts = calc.repo.get_resort_list_full()
    current_resort_data = next((r for r in all_resorts if r["display_name"] == r_name), {})
    address = current_resort_data.get("address", "Address not available")
    timezone = current_resort_data.get("timezone", "UTC")
    render_resort_card(r_name, timezone, address)

    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("User Mode", [UserMode.OWNER.value, UserMode.RENTER.value], horizontal=True)
        mode = UserMode.OWNER if mode == UserMode.OWNER.value else UserMode.RENTER
    with col2:
        year = st.selectbox("Year", sorted(resort.years.keys()))

    col1, col2 = st.columns(2)
    with col1:
        checkin = st.date_input("Check-in Date", value=date(int(year), 1, 10),
                                min_value=date(int(year), 1, 1), max_value=date(int(year), 12, 31))
    with col2:
        nights = st.number_input("Nights", min_value=1, max_value=21, value=7, step=1)

    adj_in = checkin

    with st.expander("Financial Settings", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            if mode == UserMode.OWNER:
                rate_to_use = st.number_input("Maintenance Fee ($ per 1,000 pts)", value=st.session_state.get("pref_maint_rate", 0.56), step=0.01, format="%.3f")
                purchase_price = st.number_input("Purchase Price ($ per point)", value=st.session_state.get("pref_purchase_price", 18.0), step=0.5)
                capital_pct = st.number_input("Capital Reserve %", value=st.session_state.get("pref_capital_cost", 5.0), step=0.5)
                include_capital = st.checkbox("Include Capital Reserve", value=st.session_state.get("pref_inc_c", True))
                salvage = st.number_input("Salvage Value ($ per point)", value=st.session_state.get("pref_salvage_value", 3.0), step=0.5)
                useful_life = st.number_input("Useful Life (years)", value=st.session_state.get("pref_useful_life", 10), min_value=1)
                include_depreciation = st.checkbox("Include Depreciation", value=st.session_state.get("pref_inc_d", True))
            else:
                rate_to_use = st.number_input("Rental Rate ($ per point)", value=st.session_state.get("renter_rate_val", 0.817), step=0.01, format="%.3f")
                include_capital = include_depreciation = False
                purchase_price = salvage = useful_life = capital_pct = 0

    year_str = str(year)
    year_data = resort.years.get(year_str)
    if not year_data:
        st.error("No data for selected year.")
        return

    # Daily breakdown — exactly your original
    st.divider()
    st.subheader("Daily Points Breakdown")
    breakdown_rows = []
    current_date = adj_in
    for _ in range(nights):
        holiday = calc._is_holiday(current_date, year_data)
        if holiday:
            source = f"Holiday: {holiday.name}"
        else:
            season_name, _ = calc._get_season_day_category(current_date, current_date.strftime("%a"), year_data)
            source = season_name or "Unknown Season"
        breakdown_rows.append({
            "Date": current_date.strftime("%Y-%m-%d"),
            "Day": current_date.strftime("%a"),
            "Period": source,
        })
        current_date += timedelta(days=1)
    st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)

    # ONLY ADDITION: All Room Types Table
    st.divider()
    st.subheader("Cost for All Room Types")

    all_room_types = sorted({
        k for season in year_data.seasons
        for cat in season.day_categories
        for k in cat.room_points.keys()
    } | {
        k for h in year_data.holidays
        for k in h.room_points.keys()
    })

    rows = []
    for room_type in all_room_types:
        points = calc.get_points_for_room(resort, year_str, adj_in, nights, room_type, mode)
        cost = calc.calculate_financial_cost(points, rate_to_use, True, include_capital, include_depreciation,
                                            capital_pct, salvage, useful_life, purchase_price)
        rows.append({
            "Room Type": room_type,
            "Points Required": f"{points:,}",
            "Total Cost ($)": f"${cost:,.2f}"
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Gantt chart — your original
    if year_str in resort.years:
        st.divider()
        with st.expander("Season and Holiday Calendar", expanded=False):
            st.plotly_chart(create_gantt_chart_from_resort_data(resort, year_str, data.get("global_holidays", {})), use_container_width=True)

    # Your original settings sidebar — untouched
    with st.sidebar:
        with st.expander("Your Calculator Settings", expanded=False):
            st.info(
                """
                **Save time by saving your profile.**
                Store your costs, membership tier, and resort preference to a file.
                Upload it anytime to instantly restore your setup.
                """
            )
            
            st.markdown("###### Load/Save Settings")
            config_file = st.file_uploader("Load Settings (JSON)", type="json", key="user_cfg_upload")
            
            if config_file:
                 file_sig = f"{config_file.name}_{config_file.size}"
                 if "last_loaded_cfg" not in st.session_state or st.session_state.last_loaded_cfg != file_sig:
                     config_file.seek(0)
                     data = json.load(config_file)
                     apply_settings_from_dict(data)
                     st.session_state.last_loaded_cfg = file_sig
                     st.rerun()

            current_pref_resort = st.session_state.current_resort_id if st.session_state.current_resort_id else ""
            current_settings = {
                "maintenance_rate": st.session_state.get("pref_maint_rate", 0.56),
                "purchase_price": st.session_state.get("pref_purchase_price", 18.0),
                "capital_cost_pct": st.session_state.get("pref_capital_cost", 5.0),
                "salvage_value": st.session_state.get("pref_salvage_value", 3.0),
                "useful_life": st.session_state.get("pref_useful_life", 10),
                "discount_tier": st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT),
                "include_maintenance": True,
                "include_capital": st.session_state.get("pref_inc_c", True),
                "include_depreciation": st.session_state.get("pref_inc_d", True),
                "renter_rate": st.session_state.get("renter_rate_val", 0.817),
                "renter_discount_tier": st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT),
                "preferred_resort_id": current_pref_resort
            }
            st.download_button("Save Settings", json.dumps(current_settings, indent=2), "mvc_owner_settings.json", "application/json", use_container_width=True)

def run() -> None:
    main()
