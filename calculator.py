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
    EXECUTIVE = "within_30_days" # 25%
    PRESIDENTIAL = "within_60_days" # 30%
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
    def **init**(self, raw_data: dict):
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
    def **init**(self, repo: MVCRepository):
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
        # --- NEW: snap renter rate to 2dp so internal value matches 0.81 shown in UI ---
        if user_mode == UserMode.RENTER:
            rate = round(float(rate), 2)
        # -------------------------------------------------------------------------------
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
            pts_map, holiday = self._get_daily_points(resort, d)
           
            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                is_disc = False
               
                # --- DISCOUNT LOGIC (unchanged) ---
                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                    # Applies to all dates regardless of days_out if multiplier exists
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
                # ----------------------------------
               
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
                    # renter daily $ still rounded upwards
                    cost = math.ceil(eff * rate)
               
                row = {
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')})",
                    "Day": "", "Points": eff
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
                tot_financial += cost
                tot_m += m; tot_c += c; tot_d += dp
                i += holiday_days
            elif not holiday:
                raw = pts_map.get(room, 0)
                eff = raw
                is_disc = False
               
                # --- DISCOUNT LOGIC (unchanged) ---
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
                # ----------------------------------
               
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
                    # renter daily $ still rounded upwards
                    cost = math.ceil(eff * rate)
                row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff}
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
                tot_financial += cost
                tot_m += m; tot_c += c; tot_d += dp
                i += 1
            else:
                i += 1
        df = pd.DataFrame(rows)
        # --- NEW: totals must be driven by total discounted points × correct per-pt rate ---
        if user_mode == UserMode.RENTER:
            # renter: Total Rent = total effective points after discount × renter rate
            tot_financial = tot_eff_pts * rate
        elif user_mode == UserMode.OWNER and owner_config:
            # owner: keep your existing behaviour, or you can also snap if you want
            maint_total = tot_eff_pts * rate
            cap_total = tot_eff_pts * owner_config.get("cap_rate", 0.0) if owner_config.get("inc_c", False) else 0.0
            dep_total = tot_eff_pts * owner_config.get("dep_rate", 0.0) if owner_config.get("inc_d", False) else 0.0
            tot_m = maint_total
            tot_c = cap_total
            tot_d = dep_total
            tot_financial = maint_total + cap_total + dep_total
        # -----------------------------------------------------------------------------------
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
        if not resort: return ComparisonResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
       
        processed_holidays = {room: set() for room in rooms}
       
        # Helper configs
        disc_mul = owner_config["disc_mul"] if owner_config else 1.0
        renter_mul = 1.0
        if not user_mode == UserMode.OWNER:
            if policy == DiscountPolicy.PRESIDENTIAL: renter_mul = 0.7
            elif policy == DiscountPolicy.EXECUTIVE: renter_mul = 0.75
        for room in rooms:
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)
               
                # Holiday Logic
                if h and h.name not in processed_holidays[room]:
                    processed_holidays[room].add(h.name)
                    raw = pts_map.get(room, 0)
                    eff = raw
                   
                    # --- DISCOUNT LOGIC MODIFIED ---
                    if user_mode == UserMode.OWNER:
                        if disc_mul < 1.0: eff = math.floor(raw * disc_mul)
                    else:
                        if renter_mul < 1.0: eff = math.floor(raw * renter_mul)
                    # -------------------------------
                   
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
               
                # Regular Day Logic
                elif not h:
                    raw = pts_map.get(room, 0)
                    eff = raw
                   
                    # --- DISCOUNT LOGIC MODIFIED ---
                    if user_mode == UserMode.OWNER:
                         if disc_mul < 1.0: eff = math.floor(raw * disc_mul)
                    else:
                         if renter_mul < 1.0: eff = math.floor(raw * renter_mul)
                    # -------------------------------
                   
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
        # Build Pivot Table
        template_res = self.calculate_breakdown(resort_name, rooms[0], checkin, nights, user_mode, rate, policy, owner_config)
        final_pivot = []
       
        for _, tmpl_row in template_res.breakdown_df.iterrows():
            d_str = tmpl_row["Date"]
            new_row = {"Date": d_str}
            for room in rooms:
                val = 0.0
                if "(" in str(d_str): # Holiday
                    h_name = str(d_str).split(" (")[0]
                    val = holiday_data[room].get(h_name, 0.0)
                else: # Regular Day
                    try:
                        d_obj = datetime.strptime(str(d_str), "%Y-%m-%d").date()
                        val = next((x[val_key] for x in daily_data if x["Date"] == d_obj and x["Room Type"] == room), 0.0)
                    except: pass
                new_row[room] = f"${val:,.0f}"
            final_pivot.append(new_row)
           
        # Total row: use the same priority rule as the main calculator:
        # total $ = total effective points after discount × per-point rate
        tot_row = {"Date": "Total Cost" if user_mode == UserMode.OWNER else "Total Rent"}
        for r in rooms:
            room_res = self.calculate_breakdown(
                resort_name,
                r,
                checkin,
                nights,
                user_mode,
                rate,
                policy,
                owner_config,
            )
            tot_row[r] = f"${room_res.financial_total:,.0f}"
        final_pivot.append(tot_row)
       
        h_chart_rows = []
        for r, h_map in holiday_data.items():
            for h_name, val in h_map.items():
                h_chart_rows.append({"Holiday": h_name, "Room Type": r, val_key: val})
        return ComparisonResult(pd.DataFrame(final_pivot), pd.DataFrame(daily_data), pd.DataFrame(h_chart_rows))
    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years: return checkin, nights, False
        end = checkin + timedelta(days=nights - 1)
        yd = resort.years[str(checkin.year)]
        overlapping = [h for h in yd.holidays if h.start_date <= end and h.end_date >= checkin]
        if not overlapping: return checkin, nights, False
       
        s = min(h.start_date for h in overlapping)
        e = max(h.end_date for h in overlapping)
        adj_s = min(checkin, s)
        adj_e = max(end, e)
        return adj_s, (adj_e - adj_s).days + 1, True
# ==============================================================================
# MAIN PAGE LOGIC
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]
def apply_settings_from_dict(user_data: dict):
    """Update session state variables from a settings dictionary."""
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
       
        # Note: include_maintenance is no longer a user setting, it's always true for owners
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
        st.session_state.calculator_mode = UserMode.OWNER.value
    except Exception as e:
        st.error(f"Error applying settings: {e}")
def main() -> None:
    # --- 0. INIT STATE ---
    if "current_resort" not in st.session_state: st.session_state.current_resort = None
    if "current_resort_id" not in st.session_state: st.session_state.current_resort_id = None
    if "show_help" not in st.session_state: st.session_state.show_help = False
    ensure_data_in_session()
    # --- 1. AUTO-LOAD LOCAL FILE ON STARTUP ---
    if "settings_auto_loaded" not in st.session_state:
        local_settings = "mvc_owner_settings.json"
        if os.path.exists(local_settings):
            try:
                with open(local_settings, "r") as f:
                    data = json.load(f)
                    apply_settings_from_dict(data)
                    st.toast("✅ Auto-loaded local settings!", icon="⚙️")
            except Exception:
                pass
        st.session_state.settings_auto_loaded = True
    # --- 2. DEFAULTS (If keys missing) ---
    if "pref_maint_rate" not in st.session_state: st.session_state.pref_maint_rate = 0.55
    if "pref_purchase_price" not in st.session_state: st.session_state.pref_purchase_price = 18.0
    if "pref_capital_cost" not in st.session_state: st.session_state.pref_capital_cost = 5.0
    if "pref_salvage_value" not in st.session_state: st.session_state.pref_salvage_value = 3.0
    if "pref_useful_life" not in st.session_state: st.session_state.pref_useful_life = 10
    if "pref_discount_tier" not in st.session_state: st.session_state.pref_discount_tier = TIER_NO_DISCOUNT
   
    # Default to True for owners, and it's not toggleable anymore
    st.session_state.pref_inc_m = True
    if "pref_inc_c" not in st.session_state: st.session_state.pref_inc_c = True
    if "pref_inc_d" not in st.session_state: st.session_state.pref_inc_d = True
   
    if "calculator_mode" not in st.session_state: st.session_state.calculator_mode = UserMode.RENTER.value
    if "renter_rate_val" not in st.session_state: st.session_state.renter_rate_val = 0.50
    if "renter_discount_tier" not in st.session_state: st.session_state.renter_discount_tier = TIER_NO_DISCOUNT
    # Checkin state
    today = datetime.now().date()
    initial_default = today + timedelta(days=1)
    if "calc_initial_default" not in st.session_state:
        st.session_state.calc_initial_default = initial_default
        st.session_state.calc_checkin = initial_default
        st.session_state.calc_checkin_user_set = False
    if not st.session_state.data:
        st.warning("⚠️ Please open the Editor and upload/merge data_v2.json first.")
        return
    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts_full = repo.get_resort_list_full()
    with st.sidebar:
        st.divider()
        st.markdown("### 👤 User Profile")
       
        # MODE SELECTOR
        mode_sel = st.radio(
            "Calc mode:", # Label hidden via CSS in app.py
            [m.value for m in UserMode],
            key="calculator_mode",
            horizontal=True,
            label_visibility="collapsed"
        )
        mode = UserMode(mode_sel)
       
        owner_params = None
        policy = DiscountPolicy.NONE
        rate_to_use = 0.50
        st.divider()
       
        if mode == UserMode.OWNER:
# st.markdown("##### 💰 Basic Costs")
           
            # OWNER PROXY
            current_val = st.session_state.get("pref_maint_rate", 0.55)
            val_rate = st.number_input(
                "Annual Maintenance Fee ($/point)",
                value=current_val,
                key="widget_maint_rate",
                step=0.01, min_value=0.0
            )
            if val_rate != current_val:
                st.session_state.pref_maint_rate = val_rate
            rate_to_use = val_rate
            current_tier = st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT)
            try: t_idx = TIER_OPTIONS.index(current_tier)
            except ValueError: t_idx = 0
           
            opt = st.radio("Discount Tier:", TIER_OPTIONS, index=t_idx, key="widget_discount_tier")
            st.session_state.pref_discount_tier = opt
           
            # --- CONDENSED ADVANCED OPTIONS ---
            st.divider()
           
            # Checkboxes on one row - REMOVED MAINTENANCE CHEKBOX
            col_chk2, col_chk3 = st.columns(2)
            # Maintenance is now always included, so no checkbox needed.
            inc_m = True
           
            with col_chk2:
                 # RENAMED to 'Capital'
                 inc_c = st.checkbox("Capital", value=st.session_state.get("pref_inc_c", True), key="widget_inc_c")
                 st.session_state.pref_inc_c = inc_c
            with col_chk3:
                 inc_d = st.checkbox("Deprec.", value=st.session_state.get("pref_inc_d", True), key="widget_inc_d")
                 st.session_state.pref_inc_d = inc_d
           
            if inc_c or inc_d:
                val_cap = st.number_input("Purchase ($/pt)", value=st.session_state.get("pref_purchase_price", 18.0), key="widget_purchase_price", step=1.0)
                st.session_state.pref_purchase_price = val_cap
                cap = val_cap
            else:
                cap = st.session_state.get("pref_purchase_price", 18.0)
           
            if inc_c:
                val_coc = st.number_input("Cost of Capital (%)", value=st.session_state.get("pref_capital_cost", 5.0), key="widget_capital_cost", step=0.5)
                st.session_state.pref_capital_cost = val_coc
                coc = val_coc / 100.0
            else:
                coc = 0.06
           
            if inc_d:
                c1, c2 = st.columns(2)
                with c1:
                    val_life = st.number_input("Useful Life (yrs)", value=st.session_state.get("pref_useful_life", 10), key="widget_useful_life", min_value=1)
                    st.session_state.pref_useful_life = val_life
                    life = val_life
                with c2:
                    val_salvage = st.number_input("Salvage ($/pt)", value=st.session_state.get("pref_salvage_value", 3.0), key="widget_salvage_value", step=0.5)
                    st.session_state.pref_salvage_value = val_salvage
                    salvage = val_salvage
            else:
                life, salvage = 15, 3.0
           
            owner_params = {
                "disc_mul": 1.0, "inc_m": inc_m, "inc_c": inc_c, "inc_d": inc_d,
                "cap_rate": cap * coc, "dep_rate": (cap - salvage) / life if life > 0 else 0.0,
            }
        else:
            # RENTER MODE
            # st.markdown("##### 💵 Rental Rate")
            curr_rent = st.session_state.get("renter_rate_val", 0.50)
            renter_rate_input = st.number_input("Cost per Point ($)", value=curr_rent, step=0.01, key="widget_renter_rate")
            if renter_rate_input != curr_rent: st.session_state.renter_rate_val = renter_rate_input
            rate_to_use = renter_rate_input
            st.markdown("##### 🎯 Available Discounts")
            curr_r_tier = st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT)
            try: r_idx = TIER_OPTIONS.index(curr_r_tier)
            except ValueError: r_idx = 0
           
            opt = st.radio("Discount tier available:", TIER_OPTIONS, index=r_idx, key="widget_renter_discount_tier")
            st.session_state.renter_discount_tier = opt
           
            if "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL
            elif "Executive" in opt: policy = DiscountPolicy.EXECUTIVE
        # Apply discount logic
        if mode == UserMode.OWNER:
             if "Executive" in opt: policy = DiscountPolicy.EXECUTIVE
             elif "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL
        disc_mul = 0.75 if "Executive" in opt else 0.7 if "Presidential" in opt or "Chairman" in opt else 1.0
        if owner_params: owner_params["disc_mul"] = disc_mul
       
        st.divider()
    # UPDATED HEADER
    render_page_header("Calc", f"👤 {mode.value}", icon="🏨", badge_color="#059669" if mode == UserMode.OWNER else "#2563eb")
    # Resort Selection
    if resorts_full and st.session_state.current_resort_id is None:
        if "pref_resort_id" in st.session_state and any(r.get("id") == st.session_state.pref_resort_id for r in resorts_full):
            st.session_state.current_resort_id = st.session_state.pref_resort_id
        else:
            st.session_state.current_resort_id = resorts_full[0].get("id")
    render_resort_grid(resorts_full, st.session_state.current_resort_id)
    resort_obj = next((r for r in resorts_full if r.get("id") == st.session_state.current_resort_id), None)
    if not resort_obj: return
   
    r_name = resort_obj.get("display_name")
    info = repo.get_resort_info(r_name)
    render_resort_card(info["full_name"], info["timezone"], info["address"])
    st.divider()
# st.markdown("### 📅 Booking Details")
    c1, c2, c3, c4 = st.columns([2, 1, 2, 2])
    with c1:
        checkin = st.date_input("Check-in", value=st.session_state.calc_checkin, key="calc_checkin_widget")
        st.session_state.calc_checkin = checkin
   
    if not st.session_state.calc_checkin_user_set and checkin != st.session_state.calc_initial_default:
        st.session_state.calc_checkin_user_set = True
    with c2: nights = st.number_input("Nights", 1, 60, 7)
   
    if st.session_state.calc_checkin_user_set:
        adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)
    else:
        adj_in, adj_n, adj = checkin, nights, False
       
    if adj:
        st.info(f"ℹ️ Adjusted to holiday: {adj_in.strftime('%b %d')} - {(adj_in+timedelta(days=adj_n-1)).strftime('%b %d')}")
    pts, _ = calc._get_daily_points(calc.repo.get_resort(r_name), adj_in)
    if not pts:
        rd = calc.repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
             yd = rd.years[str(adj_in.year)]
             if yd.seasons: pts = yd.seasons[0].day_categories[0].room_points
   
    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("❌ No room data available.")
        return
    with c3: room_sel = st.selectbox("Room Type", room_types)
    with c4: comp_rooms = st.multiselect("Compare With", [r for r in room_types if r != room_sel])
   
    st.divider()
   
    res = calc.calculate_breakdown(r_name, room_sel, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
   
# st.markdown(f"### 📊 Results: {room_sel}")
   
    if mode == UserMode.OWNER:
        cols = st.columns(5)
        cols[0].metric("Total Points", f"{res.total_points:,}")
        cols[1].metric("Total Cost", f"${res.financial_total:,.0f}")
        # Always show Maint.
        cols[2].metric("Maintenance", f"${res.m_cost:,.0f}")
        if inc_c: cols[3].metric("Capital Cost", f"${res.c_cost:,.0f}")
        if inc_d: cols[4].metric("Depreciation", f"${res.d_cost:,.0f}")
    else:
        cols = st.columns(2)
        cols[0].metric("Total Points", f"{res.total_points:,}")
        cols[1].metric("Total Rent", f"${res.financial_total:,.0f}")
        if res.discount_applied: st.success(f"Discount Applied: {len(res.discounted_days)} days")
# st.divider()
# st.markdown("### 📋 Detailed Breakdown")
    st.dataframe(res.breakdown_df, use_container_width=True, hide_index=True)
    if comp_rooms:
        st.divider()
        st.markdown("### 🔍 Comparison")
        comp_res = calc.compare_stays(r_name, [room_sel] + comp_rooms, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
        st.dataframe(comp_res.pivot_df, use_container_width=True)
       
        c1, c2 = st.columns(2)
        if not comp_res.daily_chart_df.empty:
             with c1: st.plotly_chart(px.bar(comp_res.daily_chart_df, x="Day", y="TotalCostValue" if mode==UserMode.OWNER else "RentValue", color="Room Type", barmode="group", title="Daily Cost"), use_container_width=True)
        if not comp_res.holiday_chart_df.empty:
             with c2: st.plotly_chart(px.bar(comp_res.holiday_chart_df, x="Holiday", y="TotalCostValue" if mode==UserMode.OWNER else "RentValue", color="Room Type", barmode="group", title="Holiday Cost"), use_container_width=True)
    year_str = str(adj_in.year)
    res_data = calc.repo.get_resort(r_name)
    if res_data and year_str in res_data.years:
        st.divider()
        with st.expander("📅 Season and Holiday Calendar", expanded=False):
            st.plotly_chart(create_gantt_chart_from_resort_data(res_data, year_str, st.session_state.data.get("global_holidays", {})), use_container_width=True)
           
    # --- CONFIGURATION SECTION (MOVED TO BOTTOM) ---
    with st.sidebar:
        with st.expander("⚙️ Your Calculator Settings", expanded=False):
            st.info(
                """
                **Save time by saving your profile.**
               
                Store your costs, membership tier, and resort preference to a file.
                Upload it anytime to instantly restore your setup.
                """
            )
           
            st.markdown("###### 📂 Load/Save Settings")
            config_file = st.file_uploader("Load Settings (JSON)", type="json", key="user_cfg_upload")
           
            # AUTO LOAD LOGIC
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
                "maintenance_rate": st.session_state.get("pref_maint_rate", 0.55),
                "purchase_price": st.session_state.get("pref_purchase_price", 18.0),
                "capital_cost_pct": st.session_state.get("pref_capital_cost", 5.0),
                "salvage_value": st.session_state.get("pref_salvage_value", 3.0),
                "useful_life": st.session_state.get("pref_useful_life", 10),
                "discount_tier": st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT),
                # Maintenance is now always included
                "include_maintenance": True,
                "include_capital": st.session_state.get("pref_inc_c", True),
                "include_depreciation": st.session_state.get("pref_inc_d", True),
                "renter_rate": st.session_state.get("renter_rate_val", 0.50),
                "renter_discount_tier": st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT),
                "preferred_resort_id": current_pref_resort
            }
            st.download_button("💾 Save Settings", json.dumps(current_settings, indent=2), "mvc_owner_settings.json", "application/json", use_container_width=True)
def run() -> None:
    main()
