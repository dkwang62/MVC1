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

        resort_obj = ResortData(id=raw_r["id"], name=raw_r["display_name"], years=years_data)
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
        return {"full_name": resort_name, "timezone": "Unknown", "address": "Address not available"}

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
        for h in yd.holidays:
            if h.start_date <= day <= h.end_date:
                return h.room_points, h
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

        if user_mode == UserMode.RENTER:
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
                    renter_mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
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
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')})",
                    "Day": "", "Points": eff
                }
                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False): row["Capital Cost"] = c
                    if owner_config.get("inc_d", False): row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost

                rows.append(row)
                tot_eff_pts += eff
                tot_financial += cost
                tot_m += m; tot_c += c; tot_d += dp
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
                    renter_mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
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

                row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff}
                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False): row["Capital Cost"] = c
                    if owner_config.get("inc_d", False): row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost

                rows.append(row)
                tot_eff_pts += eff
                tot_financial += cost
                tot_m += m; tot_c += c; tot_d += dp
                i += 1
            else:
                i += 1

        df = pd.DataFrame(rows)

        # Force total to be ceiling-rounded for consistency
        if user_mode == UserMode.RENTER:
            tot_financial = math.ceil(tot_eff_pts * rate)
        elif user_mode == UserMode.OWNER and owner_config:
            maint_total = math.ceil(tot_eff_pts * rate)
            cap_total = math.ceil(tot_eff_pts * owner_config.get("cap_rate", 0.0)) if owner_config.get("inc_c", False) else 0.0
            dep_total = math.ceil(tot_eff_pts * owner_config.get("dep_rate", 0.0)) if owner_config.get("inc_d", False) else 0.0
            tot_m = maint_total
            tot_c = cap_total
            tot_d = dep_total
            tot_financial = maint_total + cap_total + dep_total

        if not df.empty:
            fmt_cols = [c for c in df.columns if c not in ["Date", "Day", "Points"]]
            for col in fmt_cols:
                df[col] = df[col].apply(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x)

        return CalculationResult(df, tot_eff_pts, tot_financial, disc_applied, list(set(disc_days)), tot_m, tot_c, tot_d)

    def compare_stays(self, resort_name, rooms, checkin, nights, user_mode, rate, policy, owner_config):
        daily_data = []
        holiday_data = defaultdict(lambda: defaultdict(float))
        val_key = "TotalCostValue" if user_mode == UserMode.OWNER else "RentValue"

        resort = self.repo.get_resort(resort_name)
        if not resort:
            return ComparisonResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

        processed_holidays = {room: set() for room in rooms}
        disc_mul = owner_config["disc_mul"] if owner_config else 1.0
        renter_mul = 1.0
        if user_mode == UserMode.RENTER:
            if policy == DiscountPolicy.PRESIDENTIAL: renter_mul = 0.7
            elif policy == DiscountPolicy.EXECUTIVE: renter_mul = 0.75

        for room in rooms:
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)

                if h and h.name not in processed_holidays[room]:
                    processed_holidays[room].add(h.name)
                    raw = pts_map.get(room, 0)
                    eff = raw
                    if user_mode == UserMode.OWNER and disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                    elif user_mode == UserMode.RENTER and renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)

                    cost = 0.0
                    if user_mode == UserMode.OWNER and owner_config:
                        m = math.ceil(eff * rate)
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0)) if owner_config.get("inc_c") else 0
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0)) if owner_config.get("inc_d") else 0
                        cost = m + c + dp
                    else:
                        cost = math.ceil(eff * rate)

                    holiday_data[room][h.name] += cost
                    i += (h.end_date - h.start_date).days + 1

                elif not h:
                    raw = pts_map.get(room, 0)
                    eff = raw
                    if user_mode == UserMode.OWNER and disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                    elif user_mode == UserMode.RENTER and renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)

                    cost = 0.0
                    if user_mode == UserMode.OWNER and owner_config:
                        m = math.ceil(eff * rate)
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0)) if owner_config.get("inc_c") else 0
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0)) if owner_config.get("inc_d") else 0
                        cost = m + c + dp
                    else:
                        cost = math.ceil(eff * rate)

                    daily_data.append({
                        "Day": d.strftime("%a"),
                        "Date": d,
                        "Room Type": room,
                        val_key: cost,
                        "Holiday": "No"
                    })
                    i += 1
                else:
                    i += 1

        template_res = self.calculate_breakdown(resort_name, rooms[0], checkin, nights, user_mode, rate, policy, owner_config)
        final_pivot = []

        for _, tmpl_row in template_res.breakdown_df.iterrows():
            d_str = tmpl_row["Date"]
            new_row = {"Date": d_str}
            for room in rooms:
                val = 0.0
                if "(" in str(d_str):
                    h_name = str(d_str).split(" (")[0]
                    val = holiday_data[room].get(h_name, 0.0)
                else:
                    try:
                        d_obj = datetime.strptime(str(d_str), "%Y-%m-%d").date()
                        val = next((x[val_key] for x in daily_data if x["Date"] == d_obj and x["Room Type"] == room), 0.0)
                    except:
                        pass
                new_row[room] = f"${math.ceil(val):,}"
            final_pivot.append(new_row)

        tot_row = {"Date": "Total Cost" if user_mode == UserMode.OWNER else "Total Rent"}
        for r in rooms:
            room_res = self.calculate_breakdown(resort_name, r, checkin, nights, user_mode, rate, policy, owner_config)
            tot_row[r] = f"${math.ceil(room_res.financial_total):,}"
        final_pivot.append(tot_row)

        h_chart_rows = []
        for r, h_map in holiday_data.items():
            for h_name, val in h_map.items():
                h_chart_rows.append({"Holiday": h_name, "Room Type": r, val_key: val})

        return ComparisonResult(pd.DataFrame(final_pivot), pd.DataFrame(daily_data), pd.DataFrame(h_chart_rows))

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
# MAIN PAGE LOGIC (rest of your UI code below - unchanged except width fix)
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]

# ... (your existing apply_settings_from_dict and main() function remain exactly the same, just replace use_container_width=True with width="stretch")

# In your main() function, replace all:
# use_container_width=True  →  width="stretch"
# Example:
# st.dataframe(res.breakdown_df, width="stretch", hide_index=True)
# st.plotly_chart(fig, width="stretch")

def main() -> None:
    # ... (your full main() function here - unchanged except width="stretch")
    # Just make sure to replace use_container_width=True → width="stretch" in all st.dataframe, st.plotly_chart, etc.
    pass

def run() -> None:
    main()
