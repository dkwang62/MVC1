import streamlit as st
import math
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
                        room_points=h.get("room_points", {})
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
    
    def get_resort_info(self, resort_name: str) -> Dict[str, str]:
        """Get additional resort information"""
        raw_r = next((r for r in self._raw["resorts"] if r["display_name"] == resort_name), None)
        if raw_r:
            return {
                "full_name": raw_r.get("resort_name", resort_name),
                "timezone": raw_r.get("timezone", "Unknown")
            }
        return {"full_name": resort_name, "timezone": "Unknown"}

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
        
        # Check if date falls within a holiday
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
        
        processed_holidays = set()
        
        i = 0
        while i < nights:
            d = checkin + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            day_str = d.strftime("%a")
            pts_map, holiday = self._get_daily_points(resort, d)
            
            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                
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
                    for j in range(holiday_days):
                        disc_date = holiday.start_date + timedelta(days=j)
                        disc_days.append(disc_date.strftime("%Y-%m-%d"))
                
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
                    holiday_cost = math.ceil(raw * rate)
                
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
                
                i += holiday_days
                
            elif not holiday:
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
        processed_holidays = {}
        
        for room in rooms:
            processed_holidays[room] = set()
            i = 0
            while i < nights:
                d = checkin + timedelta(days=i)
                pts_map, h = self._get_daily_points(resort, d)
                
                if h and h.name not in processed_holidays[room]:
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
                    if is_owner:
                        m = c = dp = 0.0
                        if owner_config['inc_m']: m = math.ceil(eff * rate)
                        if owner_config['inc_c']: c = math.ceil(eff * owner_config['cap_rate'])
                        if owner_config['inc_d']: dp = math.ceil(eff * owner_config['dep_rate'])
                        cost = m + c + dp
                    else:
                        cost = math.ceil(raw * rate)
                    
                    holiday_data[room][h.name] += cost
                    holiday_days = (h.end_date - h.start_date).days + 1
                    i += holiday_days
                    
                elif not h:
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
                    if is_owner:
                        m = c = dp = 0.0
                        if owner_config['inc_m']: m = math.ceil(eff * rate)
                        if owner_config['inc_c']: c = math.ceil(eff * owner_config['cap_rate'])
                        if owner_config['inc_d']: dp = math.ceil(eff * owner_config['dep_rate'])
                        cost = m + c + dp
                    else:
                        cost = math.ceil(raw * rate)
                    
                    daily_data.append({
                        "Day": d.strftime("%a"), "Date": d, "Room Type": room,
                        val_key: cost, "Holiday": "No"
                    })
                    i += 1
                else:
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
        
        overlapping_holidays = []
        for h in resort.years[str(checkin.year)].holidays:
            if h.start_date <= end and h.end_date >= checkin:
                overlapping_holidays.append(h)
        
        if not overlapping_holidays:
            return checkin, nights, False
        
        earliest_start = min(h.start_date for h in overlapping_holidays)
        latest_end = max(h.end_date for h in overlapping_holidays)
        
        adjusted_start = min(checkin, earliest_start)
        adjusted_end = max(end, latest_end)
        adjusted_nights = (adjusted_end - adjusted_start).days + 1
        
        return adjusted_start, adjusted_nights, True

# ==============================================================================
# LAYER 4: UI (Streamlit)
# ==============================================================================

def setup_page():
    st.set_page_config(
        page_title="MVC Points Calculator",
        page_icon="🏖️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Enhanced custom CSS
    st.markdown("""
        <style>
        /* Main container styling */
        .main {
            padding-top: 1rem;
        }
        
        /* Button styling */
        .stButton button {
            width: 100%;
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        
        .stButton button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        
        /* Metric cards */
        div[data-testid="stMetricValue"] {
            font-size: 28px;
            font-weight: 600;
        }
        
        div[data-testid="metric-container"] {
            background-color: #f8f9fa;
            padding: 1rem;
            border-radius: 10px;
            border-left: 4px solid #0d6efd;
        }
        
        /* Resort button grid */
        .resort-button {
            margin: 4px;
        }
        
        /* Sidebar styling */
        section[data-testid="stSidebar"] {
            background-color: #f8f9fa;
        }
        
        /* Dataframe styling */
        .dataframe {
            font-size: 14px;
        }
        
        /* Expander styling */
        .streamlit-expanderHeader {
            font-weight: 600;
            font-size: 16px;
        }
        
        /* Info boxes */
        .stAlert {
            border-radius: 8px;
        }
        
        /* Header styling */
        h1 {
            color: #1e3a8a;
            font-weight: 700;
        }
        
        h2 {
            color: #1e40af;
            font-weight: 600;
            margin-top: 2rem;
        }
        
        h3 {
            color: #2563eb;
            font-weight: 600;
        }
        
        /* Download button */
        .stDownloadButton button {
            background-color: #059669;
            color: white;
        }
        
        .stDownloadButton button:hover {
            background-color: #047857;
        }
        </style>
    """, unsafe_allow_html=True)

def render_resort_card(resort_name: str, timezone: str):
    """Render an enhanced resort information card"""
    st.markdown(f"""
        <div style="
            background: var(--card-bg);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
            margin-bottom: 20px;
            border-left: 4px solid var(--primary-color);
            transition: all 0.2s ease;
        ">
            <h2 style="margin:0; color: var(--primary-color); font-size: 28px; font-weight: 700;">
                🏖️ {resort_name}
            </h2>
            <p style="margin: 8px 0 0 0; color: #64748b; font-size: 16px;">
                🕒 Timezone: {timezone}
            </p>
        </div>
    """, unsafe_allow_html=True)

def render_metrics_grid(result: CalculationResult, mode: UserMode, owner_params: dict, policy: DiscountPolicy):
    """Render enhanced metrics in a grid layout"""
    if mode == UserMode.OWNER:
        num_components = sum([
            owner_params.get('inc_m', False),
            owner_params.get('inc_c', False),
            owner_params.get('inc_d', False)
        ])
        
        cols = st.columns(2 + num_components)
        
        with cols[0]:
            st.metric(
                label="📊 Total Points",
                value=f"{result.total_points:,}",
                delta=None,
                help="Total vacation points required for this stay"
            )
        
        with cols[1]:
            st.metric(
                label="💰 Total Cost",
                value=f"${result.financial_total:,.2f}",
                help="Total ownership cost including all selected components"
            )
        
        col_idx = 2
        if owner_params.get('inc_m'):
            with cols[col_idx]:
                st.metric(
                    label="🔧 Maintenance",
                    value=f"${result.m_cost:,.2f}",
                    help="Annual maintenance fees"
                )
            col_idx += 1
        
        if owner_params.get('inc_c'):
            with cols[col_idx]:
                st.metric(
                    label="💼 Capital Cost",
                    value=f"${result.c_cost:,.2f}",
                    help="Opportunity cost of capital"
                )
            col_idx += 1
        
        if owner_params.get('inc_d'):
            with cols[col_idx]:
                st.metric(
                    label="📉 Depreciation",
                    value=f"${result.d_cost:,.2f}",
                    help="Asset depreciation cost"
                )
    else:
        if result.discount_applied:
            cols = st.columns(3)
            pct = "30%" if policy == DiscountPolicy.PRESIDENTIAL else "25%"
            
            with cols[0]:
                st.metric(
                    label="📊 Total Points",
                    value=f"{result.total_points:,}",
                    help="Discounted points required"
                )
            
            with cols[1]:
                st.metric(
                    label="💰 Total Rent",
                    value=f"${result.financial_total:,.2f}",
                    help="Total rental cost (based on undiscounted points)"
                )
            
            with cols[2]:
                st.metric(
                    label="🎉 Discount Applied",
                    value=pct,
                    delta=f"{len(result.discounted_days)} days",
                    help="Points discount for last-minute booking"
                )
        else:
            cols = st.columns(2)
            
            with cols[0]:
                st.metric(
                    label="📊 Total Points",
                    value=f"{result.total_points:,}",
                    help="Total vacation points required"
                )
            
            with cols[1]:
                st.metric(
                    label="💰 Total Rent",
                    value=f"${result.financial_total:,.2f}",
                    help="Total rental cost"
                )

def main():
    setup_page()
    
    # Initialize session state
    if "data" not in st.session_state:
        st.session_state.data = None
    if "current_resort" not in st.session_state:
        st.session_state.current_resort = None
    if "uploaded_file_name" not in st.session_state:
        st.session_state.uploaded_file_name = None
    if "show_help" not in st.session_state:
        st.session_state.show_help = False
        
    # Try to load default file
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
                st.session_state.uploaded_file_name = "data_v2.json"
        except:
            pass
    
    # Sidebar configuration
    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        
        uploaded_file = st.file_uploader(
            "📁 Upload Resort Data",
            type="json",
            help="Upload your resort data JSON file"
        )
        if uploaded_file and uploaded_file.name != st.session_state.uploaded_file_name:
            try:
                st.session_state.data = json.load(uploaded_file)
                st.session_state.uploaded_file_name = uploaded_file.name
                st.session_state.current_resort = None
                st.success(f"✅ Loaded {uploaded_file.name}")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                
    if not st.session_state.data:
        st.warning("⚠️ Please upload data_v2.json to begin")
        st.info("💡 The calculator requires resort data to function. Upload your JSON data file using the sidebar.")
        st.stop()
    
    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts = repo.get_resort_list()
    
    # Sidebar parameters
    with st.sidebar:
        st.divider()
        st.markdown("### 👤 User Settings")
        
        mode_sel = st.selectbox(
            "User Mode",
            [m.value for m in UserMode],
            index=0,
            help="Select whether you're renting points or own them"
        )
        mode = UserMode(mode_sel)
        
        year = datetime.now().year
        def_rate = repo.get_config_val(year)
        owner_params = None
        policy = DiscountPolicy.NONE
        rate = def_rate
        
        if mode == UserMode.OWNER:
            st.markdown("#### 💰 Ownership Parameters")
            
            with st.expander("💵 Cost Parameters", expanded=True):
                cap = st.number_input(
                    "Purchase Price per Point ($)",
                    value=16.0,
                    step=0.5,
                    min_value=0.0,
                    help="Initial purchase price per vacation point"
                )
                disc = st.selectbox(
                    "Last-Minute Discount",
                    [0, 25, 30],
                    format_func=lambda x: f"{x}% off" if x > 0 else "No discount",
                    help="Discount on points for last-minute bookings"
                )
            
            with st.expander("📋 Cost Components", expanded=True):
                inc_m = st.checkbox("Include Maintenance Cost", True, help="Annual maintenance fees")
                if inc_m:
                    rate = st.number_input(
                        "Maintenance Rate ($/point)",
                        value=def_rate,
                        step=0.01,
                        min_value=0.0
                    )
                else:
                    rate = 0.0
                
                inc_c = st.checkbox("Include Capital Cost", True, help="Opportunity cost of capital invested")
                if inc_c:
                    coc = st.number_input(
                        "Cost of Capital (%)",
                        value=7.0,
                        step=0.5,
                        min_value=0.0,
                        help="Expected return on alternative investments"
                    ) / 100
                else:
                    coc = 0.0
                
                inc_d = st.checkbox("Include Depreciation", True, help="Asset depreciation over time")
                if inc_d:
                    col1, col2 = st.columns(2)
                    with col1:
                        life = st.number_input("Useful Life (yrs)", value=15, min_value=1)
                    with col2:
                        salvage = st.number_input("Salvage ($/pt)", value=3.0, step=0.5, min_value=0.0)
                else:
                    life = 1
                    salvage = 0.0
            
            owner_params = {
                "disc_mul": 1 - (disc/100),
                "inc_m": inc_m,
                "inc_c": inc_c,
                "inc_d": inc_d,
                "cap_rate": cap * coc,
                "dep_rate": (cap - salvage) / life
            }
        else:
            st.markdown("#### 🏨 Rental Parameters")
            
            show_advanced = st.checkbox("Show Advanced Options", value=False)
            if show_advanced:
                opt = st.radio(
                    "Rate Option",
                    [
                        "Based on Maintenance Rate (No Discount)", 
                        "Custom Rate (No Discount)",
                        "Executive: 25% Points Discount (within 30 days)", 
                        "Presidential: 30% Points Discount (within 60 days)"
                    ],
                    help="Select pricing and discount options"
                )
                
                if opt == "Custom Rate (No Discount)":
                    rate = st.number_input(
                        "Custom Rate per Point ($)",
                        value=def_rate,
                        step=0.01,
                        min_value=0.0
                    )
                elif "Presidential" in opt:
                    policy = DiscountPolicy.PRESIDENTIAL
                elif "Executive" in opt:
                    policy = DiscountPolicy.EXECUTIVE
            else:
                st.info("💡 Using maintenance rate with no discount")
    
    # Main content
    st.title("🏖️ Marriott Vacation Club Calculator")
    
    # Mode indicator badge
    if mode == UserMode.OWNER:
        st.markdown("""
            <div style="display: inline-block; background-color: #059669; color: white; padding: 8px 16px; 
                        border-radius: 20px; font-weight: 600; margin-bottom: 16px;">
                👤 Owner Mode: Ownership Cost Analysis
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <div style="display: inline-block; background-color: #2563eb; color: white; padding: 8px 16px; 
                        border-radius: 20px; font-weight: 600; margin-bottom: 16px;">
                👤 Renter Mode: Rental Cost Analysis
            </div>
        """, unsafe_allow_html=True)
    
    # Resort selection
    st.markdown("### 📍 Select Resort")
    
    if st.session_state.current_resort not in resorts:
        st.session_state.current_resort = resorts[0] if resorts else None
    
    # Display resorts in a grid
    cols = st.columns(6)
    for i, r_name in enumerate(resorts):
        with cols[i % 6]:
            b_type = "primary" if st.session_state.current_resort == r_name else "secondary"
            if st.button(r_name, key=f"btn_{i}", type=b_type, use_container_width=True):
                st.session_state.current_resort = r_name
                st.rerun()
    
    r_name = st.session_state.current_resort
    if not r_name:
        st.stop()
    
    # Get resort info and display
    resort_info = repo.get_resort_info(r_name)
    render_resort_card(resort_info["full_name"], resort_info["timezone"])
    
    st.divider()
    
    # Input parameters
    st.markdown("### 📅 Booking Details")
    
    input_cols = st.columns([2, 1, 2, 2])
    
    with input_cols[0]:
        checkin = st.date_input(
            "Check-in Date",
            datetime.now().date() + timedelta(days=1),
            format="YYYY/MM/DD",
            help="Your arrival date"
        )
    
    with input_cols[1]:
        nights = st.number_input(
            "Nights",
            1, 60, 7,
            help="Number of nights to stay"
        )
    
    # Get maintenance rate for check-in year
    checkin_year = checkin.year
    maintenance_rate_for_year = repo.get_config_val(checkin_year)
    
    # Update rate based on mode
    if mode == UserMode.RENTER:
        if policy == DiscountPolicy.NONE and rate == def_rate:
            rate = maintenance_rate_for_year
    elif mode == UserMode.OWNER and owner_params:
        if owner_params.get('inc_m', False):
            rate = maintenance_rate_for_year
    
    # Holiday adjustment
    adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)
    if adj:
        end_date = adj_in + timedelta(days=adj_n - 1)
        st.info(
            f"ℹ️ **Adjusted to full holiday period:** "
            f"{adj_in.strftime('%b %d, %Y')} — {end_date.strftime('%b %d, %Y')} "
            f"({adj_n} nights)"
        )
    
    # Get available room types
    pts, _ = calc._get_daily_points(repo.get_resort(r_name), adj_in)
    if not pts:
        rd = repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
            yd = rd.years[str(adj_in.year)]
            if yd.seasons:
                pts = yd.seasons[0].day_categories[0].room_points
    
    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("❌ No room data available for selected dates.")
        st.stop()
    
    with input_cols[2]:
        room_sel = st.selectbox(
            "Room Type",
            room_types,
            help="Select your primary room type"
        )
    
    with input_cols[3]:
        comp_rooms = st.multiselect(
            "Compare With",
            [r for r in room_types if r != room_sel],
            help="Select additional room types to compare"
        )
    
    st.divider()
    
    # Calculate results
    res = calc.calculate_breakdown(
        r_name, room_sel, adj_in, adj_n, mode, rate, policy, owner_params
    )
    
    # Display metrics
    st.markdown(f"### 📊 Results: {room_sel}")
    render_metrics_grid(res, mode, owner_params if owner_params else {}, policy)
    
    # Success message for discounts
    if res.discount_applied:
        pct = "30%" if policy == DiscountPolicy.PRESIDENTIAL else "25%"
        st.success(
            f"🎉 **Discount Applied!** {pct} off points for {len(res.discounted_days)} day(s). "
        )
    
    st.divider()
    
    # Breakdown table
    st.markdown("### 📋 Detailed Breakdown")
    st.dataframe(
        res.breakdown_df,
        use_container_width=True,
        hide_index=True,
        height=min(400, (len(res.breakdown_df) + 1) * 35 + 50)
    )
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        csv_data = res.breakdown_df.to_csv(index=False)
        st.download_button(
            "⬇️ Download CSV",
            csv_data,
            f"{r_name}_{room_sel}_{'rental' if mode == UserMode.RENTER else 'cost'}.csv",
            mime="text/csv",
            use_container_width=True
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
            hide_index=True
        )
        
        # Enhanced charts
        st.markdown("#### 📈 Visual Analysis")
        
        chart_cols = st.columns(2)
        
        with chart_cols[0]:
            if not comp_res.daily_chart_df.empty:
                y_col = "TotalCostValue" if mode == UserMode.OWNER else "RentValue"
                clean_df = comp_res.daily_chart_df[comp_res.daily_chart_df["Holiday"] == "No"]
                
                if not clean_df.empty:
                    fig = px.bar(
                        clean_df,
                        x="Day",
                        y=y_col,
                        color="Room Type",
                        barmode="group",
                        text=y_col,
                        category_orders={"Day": ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]},
                        title="Daily Costs by Day of Week",
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig.update_traces(
                        texttemplate="$%{text:.0f}",
                        textposition="outside"
                    )
                    fig.update_layout(
                        height=450,
                        xaxis_title="Day of Week",
                        yaxis_title="Cost ($)",
                        legend_title="Room Type",
                        hovermode="x unified"
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
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                h_fig.update_traces(
                    texttemplate="$%{text:.0f}",
                    textposition="outside"
                )
                h_fig.update_layout(
                    height=450,
                    xaxis_title="Holiday Period",
                    yaxis_title="Cost ($)",
                    legend_title="Room Type",
                    hovermode="x unified"
                )
                st.plotly_chart(h_fig, use_container_width=True)
    
    # Season/Holiday timeline
    st.divider()
    year_str = str(adj_in.year)
    res_data = repo.get_resort(r_name)
    g_rows = []
    
    if res_data and year_str in res_data.years:
        yd = res_data.years[year_str]
        
        for h in yd.holidays:
            g_rows.append({
                "Task": h.name,
                "Start": h.start_date,
                "Finish": h.end_date + timedelta(days=1),
                "Type": "Holiday"
            })
        
        for s in yd.seasons:
            for i, p in enumerate(s.periods, 1):
                g_rows.append({
                    "Task": f"{s.name} #{i}",
                    "Start": p.start,
                    "Finish": p.end + timedelta(days=1),
                    "Type": s.name
                })
    
    if g_rows:
        with st.expander("📅 Season and Holiday Calendar", expanded=False):
            gdf = pd.DataFrame(g_rows)
            
            c_map = {
                "Holiday": "#ef4444",
                "Low Season": "#10b981",
                "High Season": "#f59e0b",
                "Peak Season": "#eab308"
            }
            
            gantt_fig = px.timeline(
                gdf,
                x_start="Start",
                x_end="Finish",
                y="Task",
                color="Type",
                color_discrete_map=c_map,
                title=f"{resort_info['full_name']} - {year_str} Calendar Overview"
            )
            
            gantt_fig.update_layout(
                height=500,
                xaxis_title="Date",
                yaxis_title="Period",
                showlegend=True,
                hovermode="closest"
            )
            
            gantt_fig.update_xaxes(
                tickformat="%b %d",
                tickangle=-45
            )
            
            st.plotly_chart(gantt_fig, use_container_width=True)
    
    # Help section
    if st.session_state.show_help:
        st.divider()
        with st.expander("ℹ️ How the Calculation Works", expanded=True):
            if mode == UserMode.OWNER:
                st.markdown(f"""
                ### 💰 Owner Cost Calculation
                
                #### Cost Components:
                
                **1. Maintenance Cost**
                - Formula: Maintenance rate per point × points used
                - Current rate: **${rate:.2f}** per point (based on {checkin_year})
                - Covers: Property upkeep, utilities, staff, amenities
                
                **2. Capital Cost**
                - Formula: Purchase price × cost of capital rate × points used
                - Represents: Opportunity cost of capital invested in ownership
                - Example: If you invested the purchase price elsewhere, this is the return you'd miss
                
                **3. Depreciation Cost**
                - Formula: (Purchase price − salvage value) ÷ useful life × points used
                - Represents: Asset value decline over time
                - Spreads ownership cost over the expected useful life
                
                #### Points Calculation:
                - **Effective Points** = floor(raw points × discount multiplier)
                - Last-minute discounts (25% or 30%) reduce required points
                - Discounts apply when booking within specified windows
                
                #### Holiday Handling:
                - Holiday points represent the **FULL period** (not daily averages)
                - If your stay overlaps a holiday, dates expand to cover the complete period
                - Multiple consecutive holidays merge into one extended booking
                
                #### 💡 Pro Tips:
                - Enable/disable cost components to see their individual impact
                - Adjust capital cost rate to match your investment alternatives
                - Consider useful life based on your ownership timeline
                """)
            else:
                discount_text = ""
                if policy == DiscountPolicy.PRESIDENTIAL:
                    discount_text = "**Presidential last-minute 30% pts disc:** when booked within 60 days of check-in"
                elif policy == DiscountPolicy.EXECUTIVE:
                    discount_text = "**Executive last-minute 25% pts disc :** when booked within 30 days of check-in"
                else:
                    discount_text = "**Standard points applied**"
                
                st.markdown(f"""
                ### 🏨 Rent Calculation
                
                **Current Rate:** **${rate:.2f}** per point (based on {checkin_year} maintenance rate)
                
                {discount_text}                                
                - 📊 **Points column** shows **reduced points** used
                - 💰 Rent is ALWAYS based on **undiscounted points
                
                #### Holiday Handling:
                - Holiday points represent the **FULL period** (not per-night)
                - Stays overlapping holidays automatically expand to full period
                
                #### 💡 Pro Tips:
                - Compare room types to find the best value
                """)
    
    # Footer
    st.divider()
    st.markdown("""
        <div style="text-align: center; color: #6b7280; padding: 20px;">
            <p style="margin: 0;">Built with ❤️ for Marriott Vacation Club Members</p>
            <p style="margin: 4px 0 0 0; font-size: 14px;">
                Calculate smarter. Vacation better. 🏖️
            </p>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
