# calculator.py
import math
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
import pandas as pd
import plotly.express as px
import streamlit as st
from common.ui import render_resort_card, render_resort_grid, render_page_header
# FIX: Updated import name to match charts.py
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
        
        # FIX: Ensure 'name' uses plain resort_name for clean chart titles
        resort_obj = ResortData(
            id=raw_r["id"], 
            name=raw_r.get("resort_name", raw_r["display_name"]), 
            years=years_data
        )
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
# LAYER 3: SERVICE
# ==============================================================================
class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _get_daily_points(self, resort: ResortData, day: date) -> Tuple[Dict[str, int], Optional[Holiday]]:
        year_str = str(day.year)
        if year_str not in resort.years: return {}, None
        yd = resort.years[year_str]
        for h in yd.holidays:
            if h.start_date <= day <= h.end_date: return h.room_points, h
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[day.weekday()]
        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days: return cat.room_points, None
        return {}, None

    def calculate_breakdown(
        self, resort_name: str, room: str, checkin: date, nights: int,
        user_mode: UserMode, rate: float, discount_policy: DiscountPolicy = DiscountPolicy.NONE,
        owner_config: Optional[dict] = None,
    ) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort: return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])

        rate = round(float(rate), 2)
        rows, tot_eff_pts, tot_financial = [], 0, 0.0
        tot_m = tot_c = tot_d = 0.0
        disc_applied, disc_days = False, []
        is_owner = user_mode == UserMode.OWNER
        processed_holidays, i = set(), 0

        while i < nights:
            d = checkin + timedelta(days=i)
            pts_map, holiday = self._get_daily_points(resort, d)

            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff, is_disc = raw, False

                mul = 1.0
                if is_owner: mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                else: mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
                
                if mul < 1.0:
                    eff, is_disc = math.floor(raw * mul), True
                    disc_applied = True
                    holiday_days = (holiday.end_date - holiday.start_date).days + 1
                    for j in range(holiday_days): disc_days.append((holiday.start_date + timedelta(days=j)).strftime("%Y-%m-%d"))

                cost, m, c, dp = 0.0, 0.0, 0.0, 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c"): c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d"): dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else: cost = math.ceil(eff * rate)

                row = {"Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')})", "Points": eff}
                if is_owner:
                    row.update({"Maintenance": m, "Total Cost": cost})
                    if owner_config.get("inc_c"): row["Capital Cost"] = c
                    if owner_config.get("inc_d"): row["Depreciation"] = dp
                else: row[room] = cost
                rows.append(row); tot_eff_pts += eff
                i += (holiday.end_date - holiday.start_date).days + 1

            else:
                raw = pts_map.get(room, 0)
                eff, is_disc = raw, False
                mul = 1.0
                if is_owner: mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                else: mul = 0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE else 1.0
                
                if mul < 1.0:
                    eff, is_disc = math.floor(raw * mul), True
                    disc_applied = True; disc_days.append(d.strftime("%Y-%m-%d"))

                cost, m, c, dp = 0.0, 0.0, 0.0, 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c"): c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d"): dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else: cost = math.ceil(eff * rate)

                row = {"Date": d.strftime("%Y-%m-%d (%a)"), "Points": eff}
                if is_owner:
                    row.update({"Maintenance": m, "Total Cost": cost})
                    if owner_config.get("inc_c"): row["Capital Cost"] = c
                    if owner_config.get("inc_d"): row["Depreciation"] = dp
                else: row[room] = cost
                rows.append(row); tot_eff_pts += eff; i += 1

        df = pd.DataFrame(rows)
        if not df.empty:
            for col in [c for c in df.columns if c not in ["Date", "Points"]]:
                df[col] = df[col].apply(lambda x: f"${x:,.0f}")

        # Final Financial Totals
        if is_owner and owner_config:
            tot_m, tot_c, tot_d = math.ceil(tot_eff_pts * rate), 0.0, 0.0
            if owner_config.get("inc_c"): tot_c = math.ceil(tot_eff_pts * owner_config.get("cap_rate", 0.0))
            if owner_config.get("inc_d"): tot_d = math.ceil(tot_eff_pts * owner_config.get("dep_rate", 0.0))
            tot_financial = tot_m + tot_c + tot_d
        else: tot_financial = math.ceil(tot_eff_pts * rate)

        return CalculationResult(df, tot_eff_pts, tot_financial, disc_applied, list(set(disc_days)), tot_m, tot_c, tot_d)

    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years: return checkin, nights, False
        end = checkin + timedelta(days=nights - 1)
        overlapping = [h for h in resort.years[str(checkin.year)].holidays if h.start_date <= end and h.end_date >= checkin]
        if not overlapping: return checkin, nights, False
        s, e = min(h.start_date for h in overlapping), max(h.end_date for h in overlapping)
        adj_s, adj_e = min(checkin, s), max(end, e)
        return adj_s, (adj_e - adj_s).days + 1, True

# ... [Include get_all_room_types_for_resort, build_season_cost_table, and main/run from your previous file here] ...
