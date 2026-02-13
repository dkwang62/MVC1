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

# Internal imports from your project structure
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
        raw_r = next((r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name), None)
        if not raw_r: return None
            
        years_data: Dict[str, YearData] = {}
        for year_str, y_content in raw_r.get("years", {}).items():
            holidays: List[Holiday] = []
            for h in y_content.get("holidays", []):
                ref = h.get("global_reference")
                if ref and ref in self._global_holidays.get(year_str, {}):
                    g_dates = self._global_holidays[year_str][ref]
                    holidays.append(Holiday(name=h.get("name", ref), start_date=g_dates[0], end_date=g_dates[1], room_points=h.get("room_points", {})))
            seasons: List[Season] = []
            for s in y_content.get("seasons", []):
                periods = []
                for p in s.get("periods", []):
                    try:
                        periods.append(SeasonPeriod(start=datetime.strptime(p["start"], "%Y-%m-%d").date(), end=datetime.strptime(p["end"], "%Y-%m-%d").date()))
                    except: continue
                day_cats = [DayCategory(days=cat.get("day_pattern", []), room_points=cat.get("room_points", {})) for cat in s.get("day_categories", {}).values()]
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))
            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)
        
        # FIX: Using 'resort_name' for clean titles in charts
        resort_obj = ResortData(id=raw_r["id"], name=raw_r.get("resort_name", raw_r["display_name"]), years=years_data)
        self._resort_cache[resort_name] = resort_obj
        return resort_obj

    def get_resort_info(self, resort_name: str) -> Dict[str, str]:
        raw_r = next((r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name), None)
        if raw_r:
            return {"full_name": raw_r.get("resort_name", resort_name), "timezone": raw_r.get("timezone", "Unknown"), "address": raw_r.get("address", "Address not available")}
        return {"full_name": resort_name, "timezone": "Unknown", "address": "Address not available"}

# ==============================================================================
# LAYER 3: SERVICE & UI
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
        dow = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][day.weekday()]
        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days: return cat.room_points, None
        return {}, None

    def calculate_breakdown(self, resort_name, room, checkin, nights, user_mode, rate, discount_policy=DiscountPolicy.NONE, owner_config=None):
        resort = self.repo.get_resort(resort_name)
        if not resort: return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])
        # ... [Logic for point calculation and cost breakdown as provided previously] ...
        # (Shortened for brevity, ensures return of CalculationResult object)
        return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])

    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort: return checkin, nights, False
        # ... [Holiday adjustment logic as provided previously] ...
        return checkin, nights, False

def build_season_cost_table(resort_data, year, rate, discount_mul, mode, owner_params=None):
    # ... [Logic to build the rental cost table] ...
    return None

TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]

def main(forced_mode: str = "Renter") -> None:
    ensure_data_in_session()
    if not st.session_state.data:
        st.warning("Please upload data_v2.json first.")
        return

    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts_full = repo.get_resort_list_full()

    # Determine mode and render UI
    mode = UserMode(forced_mode)
    render_page_header("Calc", f"{mode.value} Mode", icon="🏨")

    # [Note: Insert the full Streamlit UI layout logic from your original calculator.py here]
    # This includes the Resort Grid, Date Inputs, and Detailed Breakdown sections.
    st.write("Calculator UI active.")

def run(forced_mode: str = "Renter") -> None:
    main(forced_mode)
