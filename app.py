import streamlit as st
import math
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
from collections import defaultdict

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
    start_date: datetime.date
    end_date: datetime.date
    room_points: Dict[str, int]

@dataclass
class DayCategory:
    days: List[str]
    room_points: Dict[str, int]

@dataclass
class SeasonPeriod:
    start: datetime.date
    end: datetime.date

@dataclass
class Season:
    name: str
    periods: List[SeasonPeriod]
    day_categories: List[DayCategory]

@dataclass
class ResortData:
    id: str
    name: str
    years: Dict[str, 'YearData']

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

    def get_config_val(self, year: int) -> float:
        return self._raw.get("configuration", {}).get("maintenance_rates", {}).get(str(year), 0.86)

    def _parse_global_holidays(self) -> Dict[str, Dict[str, Tuple[datetime.date, datetime.date]]]:
        parsed = {}
        for year, hols in self._raw.get("global_holidays", {}).items():
            parsed[year] = {}
            for name, data in hols.items():
                try:
                    parsed[year][name] = (
                        datetime.strptime(data["start_date"], "%Y-%m-%d").date(),
                        datetime.strptime(data["end_date"], "%Y-%m-%d").date()
                    )
                except:
                    continue
        return parsed

    def get_resort(self, resort_name: str) -> Optional[ResortData]:
        if resort_name in self._resort_cache:
            return self._resort_cache[resort_name]
        raw_r = next((r for r in self._raw["resorts"] if r["display_name"] == resort_name), None)
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
                        room_points=h.get("room_points", {})  # Keep as total period points
                    ))
            seasons = []
            for s in y_content.get("seasons", []):
                periods = []
                for p in s.get("periods", []):
                    try:
                        periods.append(SeasonPeriod(
                            datetime.strptime(p["start"], "%Y-%m-%d").date(),
                            datetime.strptime(p["end"], "%Y-%m-%d").date()
                        ))
                    except:
                        continue
                day_cats = []
                for cat in s.get("day_categories", {}).values():
                    day_cats.append(DayCategory(
                        days=cat.get("day_pattern", []),
                        room_points=cat.get("room_points", {})
                    ))
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))
            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)
        resort_obj = ResortData(id=raw_r["id"], name=raw_r["display_name"], years=years_data)
        self._resort_cache[resort_name] = resort_obj
        return resort_obj

# ==============================================================================
# LAYER 3: SERVICE (Pure Business Logic Engine)
# ==============================================================================

class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _get_daily_points(self, resort: ResortData, date: datetime.date) -> Tuple[Dict[str, int], Optional[Holiday]]:
        year_str = str(date.year)
        if year_str not in resort.years:
            return {}, None
        yd = resort.years[year_str]
        
        # Check if date falls within a holiday - return full holiday points
        for h in yd.holidays:
            if h.start_date <= date <= h.end_date:
                return h.room_points, h
        
        # Not a holiday, check regular seasons
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[date.weekday()]
        for s in yd.seasons:
            for p in s.periods:
                if p.start <= date <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days:
                            return cat.room_points, None
        return {}, None

    def calculate_breakdown(self, resort_name: str, room: str, checkin: datetime.date, nights: int,
                            user_mode: UserMode, rate: float,
                            discount_policy: DiscountPolicy = DiscountPolicy.NONE,
                            owner_config: dict = None) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])
        
        rows = []
        tot_eff_pts = 0
        tot_financial = 0.0
        tot_m = tot_c = tot_d = 0.0
        disc_applied = False
        disc_days = []
        
        is_owner = user_mode == UserMode.OWNER
        disc_mul = owner_config.get('disc_mul', 1.0) if owner_config else 1.0
        r_disc_mul = 1.0
        if not is_owner:
            if discount_policy == DiscountPolicy.PRESIDENTIAL:
                r_disc_mul = 0.7
            elif discount_policy == DiscountPolicy.EXECUTIVE:
                r_disc_mul = 0.75
        
        # Track which holidays we've already processed
        processed_holidays = set()
        
        i = 0
        while i < nights:
            d = checkin + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            day_str = d.strftime("%a")
            pts_map, holiday = self._get_daily_points(resort, d)
            
            if holiday and holiday.name not in processed_holidays:
                # Process entire holiday period as one entry
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                
                # Calculate days in this holiday
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                
                # Apply discounts to the points
                is_disc_holiday = False
                if is_owner:
                    eff = math.floor(raw * disc_mul)
                else:
                    days_out = (holiday.start_date - datetime.now().date()).days
                    if (discount_policy == DiscountPolicy.PRESIDENTIAL and days_out <= 60) or \
                       (discount_policy == DiscountPolicy.EXECUTIVE and days_out <= 30):
                        eff = math.floor(raw * r_disc_mul)
                        is_disc_holiday = True
                
                if is_disc_holiday:
                    disc_applied = True
                    # Mark all days in holiday as discounted
                    for j in range(holiday_days):
                        disc_date = holiday.start_date + timedelta(days=j)
                        disc_days.append(disc_date.strftime("%Y-%m-%d"))
                
                # Calculate costs for entire holiday period
                # For renters: cost is ALWAYS based on undiscounted (raw) points
                holiday_cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    if owner_config.get('inc_m', False):
                        m = math.ceil(eff * rate)
                    if owner_config.get('inc_c', False):
                        c = math.ceil(eff * owner_config.get('cap_rate', 0.0))
                    if owner_config.get('inc_d', False):
                        dp = math.ceil(eff * owner_config.get('dep_rate', 0.0))
                    holiday_cost = m + c + dp
                else:
                    # Renter: Cost based on RAW (undiscounted) points
                    holiday_cost = math.ceil(raw * rate)
                
                # Add single row for entire holiday
                row = {
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d, %Y')} - {holiday.end_date.strftime('%b %d, %Y')})",
                    "Day": "",
                    "Points": eff
                }
                if is_owner:
                    if owner_config['inc_m']: row["Maintenance"] = m
                    if owner_config['inc_c']: row["Capital Cost"] = c
                    if owner_config['inc_d']: row["Depreciation"] = dp
                    row["Total Cost"] = holiday_cost
                else:
                    row[room] = holiday_cost
                rows.append(row)
                
                tot_eff_pts += eff
                tot_financial += holiday_cost
                tot_m += m
                tot_c += c
                tot_d += dp
                
                # Skip ahead past the holiday
                i += holiday_days
                
            elif not holiday:
                # Regular day (not a holiday)
                raw = pts_map.get(room, 0)
                eff = raw
                is_disc_day = False
                
                if is_owner:
                    eff = math.floor(raw * disc_mul)
                else:
                    days_out = (d - datetime.now().date()).days
                    if (discount_policy == DiscountPolicy.PRESIDENTIAL and days_out <= 60) or \
                       (discount_policy == DiscountPolicy.EXECUTIVE and days_out <= 30):
                        eff = math.floor(raw * r_disc_mul)
                        is_disc_day = True
                
                if is_disc_day:
                    disc_applied = True
                    disc_days.append(d_str)
                
                day_cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    if owner_config.get('inc_m', False):
                        m = math.ceil(eff * rate)
                    if owner_config.get('inc_c', False):
                        c = math.ceil(eff * owner_config.get('cap_rate', 0.0))
                    if owner_config.get('inc_d', False):
                        dp = math.ceil(eff * owner_config.get('dep_rate', 0.0))
                    day_cost = m + c + dp
                else:
                    # Renter: Cost based on RAW (undiscounted) points
                    day_cost = math.ceil(raw * rate)
                
                row = {
                    "Date": d_str,
                    "Day": day_str,
                    "Points": eff
                }
                if is_owner:
                    if owner_config['inc_m']: row["Maintenance"] = m
                    if owner_config['inc_c']: row["Capital Cost"] = c
                    if owner_config['inc_d']: row["Depreciation"] = dp
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
                # Already processed this holiday, skip this day
                i += 1
        
        df = pd.DataFrame(rows)
        if is_owner and not df.empty:
            for col in ["Maintenance", "Capital Cost", "Depreciation", "Total Cost"]:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: f"${x:,.2f}" if isinstance(x, (int, float)) else x)
        else:
            for col in df.columns:
                if col not in ["Date", "Day", "Points"]:
                    df[col] = df[col].apply(lambda x: f"${x:,.2f}" if isinstance(x, (int, float)) else x)
        
        return CalculationResult(
            df, tot_eff_pts, tot_financial, disc_applied, list(set(disc_days)),
            tot_m, tot_c, tot_d
        )

    def compare_stays(self, resort_name, rooms, checkin, nights, user_mode, rate, policy, owner_config):
        daily_data = []
        holiday_data = defaultdict(lambda: defaultdict(float))
        is_owner = user_mode == UserMode.OWNER
        disc_mul = owner_config['disc_mul'] if owner_config else 1.0
        r_mul = 1.0
        if not is_owner:
            if policy == DiscountPolicy.PRESIDENTIAL: r_mul = 0.7
            elif policy == DiscountPolicy.EXECUTIVE: r_mul = 0.75
        val_key = "TotalCostValue" if is_owner else "RentValue"
        
        resort = self.repo.get_resort(resort_name)
        processed_holidays = {}  # Track processed holidays per room
        
        for room in rooms:
            processed_holidays[room] = set()
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)
                
                if h and h.name not in processed_holidays[room]:
                    # Process entire holiday
                    processed_holidays[room].add(h.name)
                    raw = pts_map.get(room, 0)
                    eff = raw
                    
                    if is_owner:
                        eff = math.floor(raw * disc_mul)
                    else:
                        days_out = (h.start_date - datetime.now().date()).days
                        if (policy == DiscountPolicy.PRESIDENTIAL and days_out <= 60) or \
                           (policy == DiscountPolicy.EXECUTIVE and days_out <= 30):
                            eff = math.floor(raw * r_mul)
                    
                    cost = 0.0
                    m = c = dp = 0.0
                    if is_owner:
                        if owner_config['inc_m']: m = math.ceil(eff * rate)
                        if owner_config['inc_c']: c = math.ceil(eff * owner_config['cap_rate'])
                        if owner_config['inc_d']: dp = math.ceil(eff * owner_config['dep_rate'])
                        cost = m + c + dp
                    else:
                        # Renter: Cost based on RAW (undiscounted) points
                        cost = math.ceil(raw * rate)
                    
                    holiday_data[room][h.name] += cost
                    
                    # Skip past holiday
                    holiday_days = (h.end_date - h.start_date).days + 1
                    i += holiday_days
                    
                elif not h:
                    # Regular day
                    raw = pts_map.get(room, 0)
                    eff = raw
                    
                    if is_owner:
                        eff = math.floor(raw * disc_mul)
                    else:
                        days_out = (d - datetime.now().date()).days
                        if (policy == DiscountPolicy.PRESIDENTIAL and days_out <= 60) or \
                           (policy == DiscountPolicy.EXECUTIVE and days_out <= 30):
                            eff = math.floor(raw * r_mul)
                    
                    cost = 0.0
                    m = c = dp = 0.0
                    if is_owner:
                        if owner_config['inc_m']: m = math.ceil(eff * rate)
                        if owner_config['inc_c']: c = math.ceil(eff * owner_config['cap_rate'])
                        if owner_config['inc_d']: dp = math.ceil(eff * owner_config['dep_rate'])
                        cost = m + c + dp
                    else:
                        # Renter: Cost based on RAW (undiscounted) points
                        cost = math.ceil(raw * rate)
                    
                    daily_data.append({
                        "Day": d.strftime("%a"), "Date": d, "Room Type": room,
                        val_key: cost, "Holiday": "No"
                    })
                    i += 1
                else:
                    # Already processed holiday
                    i += 1
        
        template_res = self.calculate_breakdown(resort_name, rooms[0], checkin, nights, user_mode, rate, policy, owner_config)
        pivot_rows = []
        for _, tmpl_row in template_res.breakdown_df.iterrows():
            new_row = {"Date": tmpl_row["Date"]}
            for room in rooms:
                if "(" in str(tmpl_row["Date"]):
                    h_name = tmpl_row["Date"].split(" (")[0]
                    val = holiday_data[room].get(h_name, 0.0)
                else:
                    d_obj = datetime.strptime(tmpl_row["Date"], "%Y-%m-%d").date()
                    val = next((x[val_key] for x in daily_data if x["Date"] == d_obj and x["Room Type"] == room), 0.0)
                new_row[room] = f"${val:,.2f}"
            pivot_rows.append(new_row)
        
        total_label = "Total Cost" if is_owner else "Total Rent"
        tot_row = {"Date": total_label}
        for r in rooms:
            tot_sum = sum(x[val_key] for x in daily_data if x["Room Type"] == r)
            tot_sum += sum(holiday_data[r].values())
            tot_row[r] = f"${tot_sum:,.2f}"
        pivot_rows.append(tot_row)
        
        h_chart_rows = []
        for r, h_map in holiday_data.items():
            for h_name, val in h_map.items():
                h_chart_rows.append({"Holiday": h_name, "Room Type": r, val_key: val})
        
        daily_df = pd.DataFrame(daily_data)
        return ComparisonResult(
            pd.DataFrame(pivot_rows),
            daily_df,
            pd.DataFrame(h_chart_rows)
        )

    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years:
            return checkin, nights, False
        
        end = checkin + timedelta(days=nights-1)
        
        # Find all holidays that overlap with the stay
        overlapping_holidays = []
        for h in resort.years[str(checkin.year)].holidays:
            if h.start_date <= end and h.end_date >= checkin:
                overlapping_holidays.append(h)
        
        if not overlapping_holidays:
            return checkin, nights, False
        
        # Find the earliest start and latest end among all overlapping holidays
        earliest_start = min(h.start_date for h in overlapping_holidays)
        latest_end = max(h.end_date for h in overlapping_holidays)
        
        # Extend to cover all holidays
        adjusted_start = min(checkin, earliest_start)
        adjusted_end = max(end, latest_end)
        adjusted_nights = (adjusted_end - adjusted_start).days + 1
        
        return adjusted_start, adjusted_nights, True

# ==============================================================================
# LAYER 4: UI (Streamlit)
# ==============================================================================

def fmt_date(d):
    return d.strftime("%b %d, %Y")

def setup_page():
    st.set_page_config(page_title="MVC Calculator", layout="wide")

def main():
    setup_page()
    if "data" not in st.session_state:
        st.session_state.data = None
    if "current_resort" not in st.session_state:
        st.session_state.current_resort = None
    if "uploaded_file_name" not in st.session_state:
        st.session_state.uploaded_file_name = None
        
    # Try to load default file only once on first run
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
                st.session_state.uploaded_file_name = "data_v2.json"
        except:
            pass
    
    with st.sidebar:
        uploaded_file = st.file_uploader("Upload JSON file", type="json")
        if uploaded_file and uploaded_file.name != st.session_state.uploaded_file_name:
            try:
                st.session_state.data = json.load(uploaded_file)
                st.session_state.uploaded_file_name = uploaded_file.name
                st.session_state.current_resort = None  # Reset resort selection
                st.success(f"Loaded {uploaded_file.name}")
            except Exception as e:
                st.error(f"Error loading file: {str(e)}")
                
    if not st.session_state.data:
        st.warning("Please upload data_v2.json or ensure it exists.")
        st.stop()
    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts = repo.get_resort_list()
    with st.sidebar:
        st.header("Mode & Parameters")
        mode_sel = st.selectbox("User Mode", [m.value for m in UserMode], index=1)
        mode = UserMode(mode_sel)
        
        # Get year from check-in date (will be updated when user selects date)
        # For now, use current year as default
        year = datetime.now().year
        def_rate = repo.get_config_val(year)
        owner_params = None
        policy = DiscountPolicy.NONE
        rate = def_rate
        if mode == UserMode.OWNER:
            cap = st.number_input("Purchase Price per Point ($)", value=16.0, step=0.1)
            disc = st.selectbox("Last-Minute Discount", [0, 25, 30], format_func=lambda x: f"{x}%")
            inc_m = st.checkbox("Include Maintenance Cost", True)
            rate = st.number_input("Maintenance Rate per Point ($)", value=def_rate, step=0.01) if inc_m else 0.0
            inc_c = st.checkbox("Include Capital Cost", True)
            coc = st.number_input("Cost of Capital (%)", value=7.0, step=0.1)/100 if inc_c else 0.0
            inc_d = st.checkbox("Include Depreciation Cost", True)
            life = st.number_input("Useful Life (Years)", value=15) if inc_d else 1
            salvage = st.number_input("Salvage Value per Point ($)", value=3.0, step=0.1) if inc_d else 0.0
            owner_params = {
                "disc_mul": 1 - (disc/100), "inc_m": inc_m, "inc_c": inc_c, "inc_d": inc_d,
                "cap_rate": cap * coc, "dep_rate": (cap - salvage) / life
            }
        else:
            adv = st.checkbox("More Options")
            if adv:
                opt = st.radio("Rate Option", [
                    "Based on Maintenance Rate (No Discount)", 
                    "Custom Rate (No Discount)",
                    "Executive: 25% Points Discount (Booked within 30 days)", 
                    "Presidential: 30% Points Discount (Booked within 60 days)"
                ])
                if opt == "Custom Rate (No Discount)":
                    rate = st.number_input("Custom Rate per Point ($)", value=def_rate, step=0.01)
                elif "Presidential" in opt:
                    policy = DiscountPolicy.PRESIDENTIAL
                elif "Executive" in opt:
                    policy = DiscountPolicy.EXECUTIVE
    st.subheader("Select Resort")
    cols = st.columns(6)
    if st.session_state.current_resort not in resorts:
        st.session_state.current_resort = resorts[0]
    for i, r_name in enumerate(resorts):
        with cols[i % 6]:
            b_type = "primary" if st.session_state.current_resort == r_name else "secondary"
            if st.button(r_name, key=f"btn_{i}", type=b_type):
                st.session_state.current_resort = r_name
                st.rerun()
    r_name = st.session_state.current_resort
    if not r_name:
        st.stop()
    st.title(f"Marriott Vacation Club {'Rent' if mode == UserMode.RENTER else 'Cost'} Calculator")
    input_cols = st.columns(4)
    with input_cols[0]:
        checkin = st.date_input("Check-in Date", datetime.now().date() + timedelta(days=1))
    with input_cols[1]:
        nights = st.number_input("Number of Nights", 1, 60, 7)
    
    # Get the correct maintenance rate based on check-in year
    checkin_year = checkin.year
    maintenance_rate_for_year = repo.get_config_val(checkin_year)
    
    # Update rate if using maintenance rate (not custom)
    if mode == UserMode.RENTER:
        if policy == DiscountPolicy.NONE and rate == def_rate:
            rate = maintenance_rate_for_year
    elif mode == UserMode.OWNER and owner_params:
        if owner_params.get('inc_m', False):
            # Update the maintenance rate in calculations
            rate = maintenance_rate_for_year
    
    adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)
    if adj:
        end_date = adj_in + timedelta(days=adj_n - 1)
        st.info(f"Adjusted to full holiday week: **{fmt_date(adj_in)} — {fmt_date(end_date)}** ({adj_n} nights)")
    pts, _ = calc._get_daily_points(repo.get_resort(r_name), adj_in)
    if not pts:
        rd = repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
            yd = rd.years[str(adj_in.year)]
            if yd.seasons:
                pts = yd.seasons[0].day_categories[0].room_points
    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("No room data found.")
        st.stop()
    with input_cols[2]:
        room_sel = st.selectbox("Select Room Type", room_types)
    with input_cols[3]:
        comp_rooms = st.multiselect("Compare With", [r for r in room_types if r != room_sel])
    year_str = str(adj_in.year)
    res_data = repo.get_resort(r_name)
    g_rows = []
    if res_data and year_str in res_data.years:
        yd = res_data.years[year_str]
        for h in yd.holidays:
            g_rows.append({"Task": h.name, "Start": h.start_date, "Finish": h.end_date + timedelta(days=1), "Type": "Holiday"})
        for s in yd.seasons:
            for i, p in enumerate(s.periods, 1):
                g_rows.append({"Task": f"{s.name} #{i}", "Start": p.start, "Finish": p.end + timedelta(days=1), "Type": s.name})
    gantt_fig = None
    if g_rows:
        gdf = pd.DataFrame(g_rows)
        c_map = {"Holiday": "#FF4B4B", "Low Season": "#90EE90", "High Season": "#FF9900", "Peak Season": "#FFD700"}
        gantt_fig = px.timeline(gdf, x_start="Start", x_end="Finish", y="Task", color="Type", color_discrete_map=c_map, title=f"{r_name} Seasons")
    res = calc.calculate_breakdown(r_name, room_sel, adj_in, adj_n, mode, rate, policy, owner_params)
    st.subheader(f"{r_name} {'Rental' if mode == UserMode.RENTER else 'Ownership Cost'} Breakdown")
    st.dataframe(res.breakdown_df, use_container_width=True, hide_index=True)
    if res.discount_applied:
        pct = "30%" if policy == DiscountPolicy.PRESIDENTIAL else "25%"
        st.success(f"Discount Applied: {pct} off points ({len(res.discounted_days)} day(s): {', '.join(res.discounted_days)})")
    st.success(f"Total Points Required: {res.total_points:,} | Total {'Rent' if mode == UserMode.RENTER else 'Cost'}: ${res.financial_total:,.2f}")
    
    with st.expander("How the Calculation is Done"):
        if mode == UserMode.OWNER:
            st.markdown("""
            - **Maintenance Cost** = Maintenance rate per point × number of points used.
            - **Capital Cost** = Purchase price per point × cost of capital rate × number of points used.  
                *(This represents the "cost of tying up your money.")*
            - **Depreciation Cost** = (Purchase price − salvage value) ÷ useful life × number of points used.  
                *(This spreads out your ownership cost over the years.)*
            - Points used are floor(raw points × discount multiplier).
            - **Holiday points are for the entire holiday period (not daily averages).**
            - When your stay touches a holiday week, dates expand to cover the full holiday period.
            """)
        else:
            discount_text = ""
            if policy == DiscountPolicy.PRESIDENTIAL:
                discount_text = "**Presidential Discount**: 30% off points (booked within 60 days)"
            elif policy == DiscountPolicy.EXECUTIVE:
                discount_text = "**Executive Discount**: 25% off points (booked within 30 days)"
            else:
                discount_text = "**No Discount Applied**"
            
            st.markdown(f"""
            - The **Rent** amount is calculated using **${rate:.2f} per point**.
            - {discount_text}
            - When a discount applies, the points required is reduced BUT the rent cost remains the same (based on undiscounted points).
            - **Holiday points are for the entire holiday period (not daily averages).**
            - When your stay touches a holiday week, dates expand to cover the full holiday period.
            """)
    
    if mode == UserMode.OWNER:
        if owner_params['inc_m']: st.info(f"Maintenance: ${res.m_cost:,.2f}")
        if owner_params['inc_c']: st.info(f"Capital Cost: ${res.c_cost:,.2f}")
        if owner_params['inc_d']: st.info(f"Depreciation: ${res.d_cost:,.2f}")
    
    st.download_button("Download Breakdown CSV", res.breakdown_df.to_csv(index=False), f"{r_name}_{'rental' if mode == UserMode.RENTER else 'cost'}.csv")
    if comp_rooms:
        all_rooms = [room_sel] + comp_rooms
        comp_res = calc.compare_stays(r_name, all_rooms, adj_in, adj_n, mode, rate, policy, owner_params)
        st.subheader("Room Type Comparison")
        st.dataframe(comp_res.pivot_df, use_container_width=True, hide_index=True)
        if not comp_res.daily_chart_df.empty:
            y_col = "TotalCostValue" if mode == UserMode.OWNER else "RentValue"
            clean_df = comp_res.daily_chart_df[comp_res.daily_chart_df["Holiday"] == "No"]
            if not clean_df.empty:
                fig = px.bar(clean_df, x="Day", y=y_col, color="Room Type", barmode="group",
                             text=y_col, category_orders={"Day": ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]})
                fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)
        if not comp_res.holiday_chart_df.empty:
            y_col = "TotalCostValue" if mode == UserMode.OWNER else "RentValue"
            h_fig = px.bar(comp_res.holiday_chart_df, x="Holiday", y=y_col, color="Room Type",
                           barmode="group", text=y_col)
            h_fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
            st.plotly_chart(h_fig, use_container_width=True)
    if gantt_fig:
        st.subheader("Season and Holiday Schedule")
        st.plotly_chart(gantt_fig, use_container_width=True)

if __name__ == "__main__":
    main()
