# calculator.py
import math
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
# DOMAIN MODELS
# ==============================================================================
class UserMode(Enum):
    RENTER = "Renter"
    OWNER = "Owner"

class DiscountPolicy(Enum):
    NONE = "None"
    EXECUTIVE = "within_30_days"
    PRESIDENTIAL = "within_60_days"

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
# REPOSITORY
# ==============================================================================
class MVCRepository:
    def __init__(self, raw_data: dict):
        self._raw = raw_data
        self._resort_cache: Dict[str, ResortData] = {}
        self._global_holidays = self._parse_global_holidays()

    def get_resort_list_full(self) -> List[Dict[str, Any]]:
        return self._raw.get("resorts", [])

    def _parse_global_holidays(self):
        parsed = {}
        for year, hols in self._raw.get("global_holidays", {}).items():
            parsed[year] = {}
            for name, data in hols.items():
                try:
                    parsed[year][name] = (
                        datetime.strptime(data["start_date"], "%Y-%m-%d").date(),
                        datetime.strptime(data["end_date"], "%Y-%m-%d").date(),
                    )
                except:
                    continue
        return parsed

    def get_resort(self, resort_name: str) -> Optional[ResortData]:
        if resort_name in self._resort_cache:
            return self._resort_cache[resort_name]

        raw_r = next((r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name), None)
        if not raw_r:
            return None

        years_data = {}
        for year_str, y_content in raw_r.get("years", {}).items():
            holidays = []
            for h in y_content.get("holidays", []):
                ref = h.get("global_reference")
                if ref and ref in self._global_holidays.get(year_str, {}):
                    g_dates = self._global_holidays[year_str][ref]
                    holidays.append(Holiday(
                        name=h.get("name", ref),
                        start_date=g_dates[0],
                        end_date=g_dates[1],
                        room_points=h.get("room_points", {}),
                    ))

            seasons = []
            for s in y_content.get("seasons", []):
                periods = []
                for p in s.get("periods", []):
                    try:
                        periods.append(SeasonPeriod(
                            start=datetime.strptime(p["start"], "%Y-%m-%d").date(),
                            end=datetime.strptime(p["end"], "%Y-%m-%d").date(),
                        ))
                    except:
                        continue
                day_cats = [DayCategory(days=cat.get("day_pattern", []), room_points=cat.get("room_points", {}))
                           for cat in s.get("day_categories", {}).values()]
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))

            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)

        resort_obj = ResortData(id=raw_r["id"], name=raw_r["display_name"], years=years_data)
        self._resort_cache[resort_name] = resort_obj
        return resort_obj

    def get_resort_info(self, resort_name: str) -> Dict[str, str]:
        raw_r = next((r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name), None)
        if raw_r:
            return {
                "full_name": raw_r.get("resort_name", resort_name),
                "timezone": raw_r.get("timezone", "Unknown"),
                "address": raw_r.get("address", "Address not available"),
            }
        return {"full_name": resort_name, "timezone": "Unknown", "address": "Address not available"}


# ==============================================================================
# CALCULATOR SERVICE
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

        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day.weekday()]
        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days:
                            return cat.room_points, None
        return {}, None

    def calculate_breakdown(self, resort_name: str, room: str, checkin: date, nights: int,
                           user_mode: UserMode, rate: float, discount_policy: DiscountPolicy = DiscountPolicy.NONE,
                           owner_config: Optional[dict] = None) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])

        if user_mode == UserMode.RENTER:
            rate = round(rate, 2)

        rows = []
        total_points = 0
        total_cost = 0.0
        m_total = c_total = d_total = 0.0
        discount_applied = False
        discounted_days = []
        processed_holidays = set()
        i = 0

        while i < nights:
            d = checkin + timedelta(days=i)
            points_map, holiday = self._get_daily_points(resort, d)

            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw_pts = points_map.get(room, 0)
                eff_pts = raw_pts

                # Apply discount
                if user_mode == UserMode.OWNER and owner_config and owner_config.get("disc_mul", 1.0) < 1.0:
                    eff_pts = math.floor(raw_pts * owner_config["disc_mul"])
                    discount_applied = True
                elif user_mode == UserMode.RENTER:
                    mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
                    if mul < 1.0:
                        eff_pts = math.floor(raw_pts * mul)
                        discount_applied = True

                cost = math.ceil(eff_pts * rate) if user_mode == UserMode.RENTER else 0
                if user_mode == UserMode.OWNER and owner_config:
                    m = math.ceil(eff_pts * rate)
                    c = math.ceil(eff_pts * owner_config.get("cap_rate", 0)) if owner_config.get("inc_c") else 0
                    d = math.ceil(eff_pts * owner_config.get("dep_rate", 0)) if owner_config.get("inc_d") else 0
                    cost = m + c + d
                    m_total += m; c_total += c; d_total += d

                rows.append({
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')})",
                    "Day": "", "Points": eff_pts,
                    room if user_mode == UserMode.RENTER else "Total Cost": cost
                })
                total_points += eff_pts
                total_cost += cost
                i += (holiday.end_date - holiday.start_date).days + 1
            else:
                raw_pts = points_map.get(room, 0)
                eff_pts = raw_pts

                if user_mode == UserMode.OWNER and owner_config and owner_config.get("disc_mul", 1.0) < 1.0:
                    eff_pts = math.floor(raw_pts * owner_config["disc_mul"])
                    discount_applied = True
                    discounted_days.append(d.strftime("%Y-%m-%d"))
                elif user_mode == UserMode.RENTER:
                    mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
                    if mul < 1.0:
                        eff_pts = math.floor(raw_pts * mul)
                        discount_applied = True
                        discounted_days.append(d.strftime("%Y-%m-%d"))

                cost = math.ceil(eff_pts * rate) if user_mode == UserMode.RENTER else 0
                if user_mode == UserMode.OWNER and owner_config:
                    m = math.ceil(eff_pts * rate)
                    c = math.ceil(eff_pts * owner_config.get("cap_rate", 0)) if owner_config.get("inc_c") else 0
                    d = math.ceil(eff_pts * owner_config.get("dep_rate", 0)) if owner_config.get("inc_d") else 0
                    cost = m + c + d
                    m_total += m; c_total += c; d_total += d

                row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff_pts}
                if user_mode == UserMode.RENTER:
                    row[room] = cost
                else:
                    row["Total Cost"] = cost
                rows.append(row)

                total_points += eff_pts
                total_cost += cost
                i += 1

        df = pd.DataFrame(rows)

        # Final total — always ceiling-rounded
        if user_mode == UserMode.RENTER:
            total_cost = math.ceil(total_points * rate)
        elif user_mode == UserMode.OWNER and owner_config:
            total_cost = math.ceil(total_points * rate)
            if owner_config.get("inc_c"): total_cost += math.ceil(total_points * owner_config.get("cap_rate", 0))
            if owner_config.get("inc_d"): total_cost += math.ceil(total_points * owner_config.get("dep_rate", 0))

        # Format currency
        for col in df.columns:
            if col not in ["Date", "Day", "Points"]:
                df[col] = df[col].apply(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x)

        return CalculationResult(
            breakdown_df=df,
            total_points=total_points,
            financial_total=total_cost,
            discount_applied=discount_applied,
            discounted_days=discounted_days,
            m_cost=m_total, c_cost=c_total, d_cost=d_total
        )

    def compare_stays(self, resort_name, rooms, checkin, nights, user_mode, rate, policy, owner_config):
        daily_data = []
        holiday_data = defaultdict(lambda: defaultdict(float))
        val_key = "TotalCostValue" if user_mode == UserMode.OWNER else "RentValue"

        resort = self.repo.get_resort(resort_name)
        if not resort:
            return ComparisonResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

        disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
        renter_mul = 0.7 if policy == DiscountPolicy.PRESIDENTIAL else 0.75 if policy == DiscountPolicy.EXECUTIVE else 1.0

        for room in rooms:
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)

                if h:
                    raw = pts_map.get(room, 0)
                    eff = raw
                    if user_mode == UserMode.OWNER and disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                    elif user_mode == UserMode.RENTER and renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)

                    cost = math.ceil(eff * rate) if user_mode == UserMode.RENTER else (
                        math.ceil(eff * rate) +
                        (math.ceil(eff * owner_config.get("cap_rate", 0)) if owner_config.get("inc_c") else 0) +
                        (math.ceil(eff * owner_config.get("dep_rate", 0)) if owner_config.get("inc_d") else 0)
                    )

                    holiday_data[room][h.name] += cost
                    i += (h.end_date - h.start_date).days + 1
                else:
                    raw = pts_map.get(room, 0)
                    eff = raw
                    if user_mode == UserMode.OWNER and disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                    elif user_mode == UserMode.RENTER and renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)

                    cost = math.ceil(eff * rate) if user_mode == UserMode.RENTER else (
                        math.ceil(eff * rate) +
                        (math.ceil(eff * owner_config.get("cap_rate", 0)) if owner_config.get("inc_c") else 0) +
                        (math.ceil(eff * owner_config.get("dep_rate", 0)) if owner_config.get("inc_d") else 0)
                    )

                    daily_data.append({"Day": d.strftime("%a"), "Date": d, "Room Type": room, val_key: cost, "Holiday": "No"})
                    i += 1

        # Build pivot
        template = self.calculate_breakdown(resort_name, rooms[0], checkin, nights, user_mode, rate, policy, owner_config)
        pivot_rows = []

        for _, row in template.breakdown_df.iterrows():
            d_str = row["Date"]
            new_row = {"Date": d_str}
            for room in rooms:
                if "(" in str(d_str):
                    h_name = str(d_str).split(" (")[0]
                    val = holiday_data[room].get(h_name, 0)
                else:
                    try:
                        d_obj = datetime.strptime(str(d_str), "%Y-%m-%d").date()
                        val = next((x[val_key] for x in daily_data if x["Date"] == d_obj and x["Room Type"] == room), 0)
                    except:
                        val = 0
                new_row[room] = f"${math.ceil(val):,}"
            pivot_rows.append(new_row)

        # Total row
        total_row = {"Date": "Total Rent" if user_mode == UserMode.RENTER else "Total Cost"}
        for room in rooms:
            res = self.calculate_breakdown(resort_name, room, checkin, nights, user_mode, rate, policy, owner_config)
            total_row[room] = f"${math.ceil(res.financial_total):,}"
        pivot_rows.append(total_row)

        return ComparisonResult(
            pivot_df=pd.DataFrame(pivot_rows),
            daily_chart_df=pd.DataFrame(daily_data),
            holiday_chart_df=pd.DataFrame([{"Holiday": h, "Room Type": r, val_key: v}
                                          for r, hmap in holiday_data.items() for h, v in hmap.items()])
        )

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
        new_start = min(checkin, s)
        new_end = max(end, e)
        return new_start, (new_end - new_start).days + 1, True


# ==============================================================================
# MAIN UI
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]

def main():
    ensure_data_in_session()
    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)

    # ... (your full sidebar + main UI code goes here — unchanged except width="stretch")

    # Example of fixed lines:
    st.dataframe(res.breakdown_df, width="stretch", hide_index=True)
    if comp_rooms:
        st.dataframe(comp_res.pivot_df, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(px.bar(comp_res.daily_chart_df, ...), width="stretch")
        with c2:
            st.plotly_chart(px.bar(comp_res.holiday_chart_df, ...), width="stretch")

    # The rest of your main() function stays exactly as you had it

def run():
    main()

if __name__ == "__main__":
    run()
