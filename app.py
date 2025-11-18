import streamlit as st
import math
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px

# ----------------------------------------------------------------------
# Setup page
# ----------------------------------------------------------------------
def setup_page():
    st.set_page_config(page_title="MVC Calculator", layout="wide")
    st.markdown("""
    <style>
        .stButton button {
            font-size: 12px !important;
            padding: 5px 10px !important;
            height: auto !important;
        }
        .block-container {
            padding-top: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)

# ----------------------------------------------------------------------
# Initialize session state
# ----------------------------------------------------------------------
def initialize_session_state():
    defaults = {
        "data": None,
        "current_resort": None,
        "data_cache": {},
        "allow_renter_modifications": False,
        "last_resort": None,
        "last_year": None,
        "room_types": None,
        "disp_to_int": None
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

# ----------------------------------------------------------------------
# File handling
# ----------------------------------------------------------------------
def handle_file_upload():
    uploaded_file = st.file_uploader("Upload JSON file", type="json")
    if uploaded_file:
        try:
            raw_data = json.load(uploaded_file)
            st.session_state.data = raw_data
            st.success("File uploaded successfully!")
        except Exception as e:
            st.error(f"Error loading file: {e}")

# ----------------------------------------------------------------------
# Custom date formatter
# ----------------------------------------------------------------------
def fmt_date(d):
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    elif isinstance(d, (pd.Timestamp, datetime)):
        d = d.date()
    return d.strftime("%d %b %Y")

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def display_room(key: str) -> str:
    legend = {
        "GV": "Garden", "OV": "Ocean View", "OF": "Oceanfront", "S": "Standard",
        "IS": "Island Side", "PS": "Pool Low Flrs", "PSH": "Pool High Flrs",
        "UF": "Gulf Front", "UV": "Gulf View", "US": "Gulf Side",
        "PH": "Penthouse", "PHGV": "Penthouse Garden", "PHOV": "Penthouse Ocean View",
        "PHOF": "Penthouse Ocean Front", "IV": "Island", "MG": "Garden",
        "PHMA": "Penthouse Mountain", "PHMK": "Penthouse Ocean", "PHUF": "Penthouse Gulf Front",
        "AP_Studio_MA": "AP Studio Mountain", "AP_1BR_MA": "AP 1BR Mountain",
        "AP_2BR_MA": "AP 2BR Mountain", "AP_2BR_MK": "AP 2BR Ocean",
        "LO": "Lock-Off", "CV": "City", "LV": "Lagoon", "PV": "Pool", "OS": "Oceanside",
        "K": "King", "DB": "Double Bed", "MV": "Mountain", "MA": "Mountain", "MK": "Ocean",
    }
    if key in legend:
        return legend[key]
    if key.startswith("AP_"):
        return {"AP_Studio_MA": "AP Studio Mountain", "AP_1BR_MA": "AP 1BR Mountain",
                "AP_2BR_MA": "AP 2BR Mountain", "AP_2BR_MK": "AP 2BR Ocean"}.get(key, key)
    parts = key.split()
    view = parts[-1] if len(parts) > 1 and parts[-1] in legend else ""
    return f"{parts[0]} {legend.get(view, view)}" if view else key

def resolve_global(year: str, key: str) -> list:
    return st.session_state.data.get("global_dates", {}).get(year, {}).get(key, [])

# ----------------------------------------------------------------------
# Core data generation (cached)
# ----------------------------------------------------------------------
def generate_data(resort: str, date: datetime.date):
    cache = st.session_state.data_cache
    ds = date.strftime("%Y-%m-%d")
    if ds in cache:
        return cache[ds]
    
    # Access global data here to avoid NameErrors
    HOLIDAY_WEEKS = st.session_state.data.get("holiday_weeks", {})
    SEASON_BLOCKS = st.session_state.data.get("season_blocks", {})
    REF_POINTS = st.session_state.data.get("reference_points", {})

    year = date.strftime("%Y")
    dow = date.strftime("%a")
    is_fri_sat = dow in {"Fri", "Sat"}
    is_sun = dow == "Sun"
    day_cat = "Fri-Sat" if is_fri_sat else ("Sun" if is_sun else "Mon-Thu")
    entry = {}
    season = "Default Season"
    holiday = None
    h_start = h_end = None
    is_h_start = False

    # New Year's (Specific logic for split year)
    if (date.month == 12 and date.day >= 26) or (date.month == 1 and date.day <= 1):
        prev = str(int(year) - 1)
        start = datetime.strptime(f"{prev}-12-26", "%Y-%m-%d").date()
        end = datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date()
        if start <= date <= end:
            holiday, h_start, h_end, is_h_start = "New Year's Eve/Day", start, end, date == start

    # Holiday Weeks
    if not holiday and year in HOLIDAY_WEEKS.get(resort, {}):
        for name, raw in HOLIDAY_WEEKS[resort][year].items():
            if isinstance(raw, str) and raw.startswith("global:"):
                raw = resolve_global(year, raw.split(":", 1)[1])
            if len(raw) >= 2:
                s = datetime.strptime(raw[0], "%Y-%m-%d").date()
                e = datetime.strptime(raw[1], "%Y-%m-%d").date()
                if s <= date <= e:
                    holiday, h_start, h_end, is_h_start = name, s, e, date == s
                    break

    # Seasons
    if not holiday and year in SEASON_BLOCKS.get(resort, {}):
        for s_name, ranges in SEASON_BLOCKS[resort][year].items():
            for rs, re in ranges:
                if datetime.strptime(rs, "%Y-%m-%d").date() <= date <= datetime.strptime(re, "%Y-%m-%d").date():
                    season = s_name
                    break
            if season != "Default Season":
                break

    # Points Assignment
    if holiday:
        src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {})
        for internal_key, pts in src.items():
            display_key = display_room(internal_key)
            entry[display_key] = pts if is_h_start else 0
    else:
        cat = None
        if season != "Holiday Week":
            cats = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
            avail = [c for c in cats if REF_POINTS.get(resort, {}).get(season, {}).get(c)]
            if avail:
                cat = ("Fri-Sat" if is_fri_sat and "Fri-Sat" in avail else
                       "Sun" if is_sun and "Sun" in avail else
                       "Mon-Thu" if not is_fri_sat and "Mon-Thu" in avail else
                       "Sun-Thu" if "Sun-Thu" in avail else avail[0])
        src = REF_POINTS.get(resort, {}).get(season, {}).get(cat, {}) if cat else {}
        for internal_key, pts in src.items():
            entry[display_room(internal_key)] = pts

    if holiday:
        entry.update(HolidayWeek=True, holiday_name=holiday,
                     holiday_start=h_start, holiday_end=h_end,
                     HolidayWeekStart=is_h_start)

    final_src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {}) if holiday else src
    disp_to_int = {display_room(k): k for k in final_src}
    cache[ds] = (entry, disp_to_int)
    return entry, disp_to_int

# ----------------------------------------------------------------------
# GANTT CHART
# ----------------------------------------------------------------------
def gantt_chart(resort: str, year: int):
    rows = []
    ys = str(year)
    
    HOLIDAY_WEEKS = st.session_state.data.get("holiday_weeks", {})
    SEASON_BLOCKS = st.session_state.data.get("season_blocks", {})

    # === HOLIDAYS ===
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(ys, {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(ys, raw.split(":", 1)[1])
        if len(raw) >= 2:
            try:
                start_dt = datetime.strptime(raw[0], "%Y-%m-%d")
                end_dt = datetime.strptime(raw[1], "%Y-%m-%d")
                if start_dt >= end_dt:
                    continue
                rows.append({
                    "Task": name,
                    "Start": start_dt,
                    "Finish": end_dt,
                    "Type": "Holiday"
                })
            except:
                continue

    # === SEASONS ===
    for s_name, ranges in SEASON_BLOCKS.get(resort, {}).get(ys, {}).items():
        for i, (s, e) in enumerate(ranges, 1):
            try:
                start_dt = datetime.strptime(s, "%Y-%m-%d")
                end_dt = datetime.strptime(e, "%Y-%m-%d")
                if start_dt >= end_dt:
                    continue
                rows.append({
                    "Task": f"{s_name} #{i}",
                    "Start": start_dt,
                    "Finish": end_dt,
                    "Type": s_name
                })
            except:
                continue

    # === FALLBACK ===
    if not rows:
        today = datetime.now()
        rows = [{
            "Task": "No Data",
            "Start": today,
            "Finish": today + timedelta(days=1),
            "Type": "No Data"
        }]

    df = pd.DataFrame(rows)
    df["Start"] = pd.to_datetime(df["Start"])
    df["Finish"] = pd.to_datetime(df["Finish"])

    # === COLORS ===
    color_dict = {
        "Holiday": "rgb(255,99,71)",
        "Low Season": "rgb(135,206,250)",
        "High Season": "rgb(255,69,0)",
        "Peak Season": "rgb(255,215,0)",
        "Shoulder": "rgb(50,205,50)",
        "Peak": "rgb(255,69,0)",
        "Summer": "rgb(255,165,0)",
        "Low": "rgb(70,130,180)",
        "Mid Season": "rgb(60,179,113)",
        "No Data": "rgb(128,128,128)"
    }
    colors = {t: color_dict.get(t, "rgb(169,169,169)") for t in df["Type"].unique()}

    # === PLOT ===
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Task",
        color="Type",
        color_discrete_map=colors,
        title=f"{resort} Seasons & Holidays ({year})",
        height=max(400, len(df) * 35)
    )

    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickformat="%d %b %Y")

    # CORRECT HOVER
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Start: %{base|%d %b %Y}<br>"
            "End: %{x|%d %b %Y}<extra></extra>"
        )
    )

    fig.update_layout(showlegend=True, xaxis_title="Date", yaxis_title="Period")
    return fig

# ----------------------------------------------------------------------
# Adjust holiday range
# ----------------------------------------------------------------------
def adjust_date_range(resort, start, nights):
    end = start + timedelta(days=nights-1)
    ranges = []
    
    HOLIDAY_WEEKS = st.session_state.data.get("holiday_weeks", {})

    if resort in HOLIDAY_WEEKS:
        for name, raw in HOLIDAY_WEEKS[resort].get(str(start.year), {}).items():
            if isinstance(raw, str) and raw.startswith("global:"):
                raw = resolve_global(str(start.year), raw.split(":",1)[1])
            if len(raw) >= 2:
                s = datetime.strptime(raw[0], "%Y-%m-%d").date()
                e = datetime.strptime(raw[1], "%Y-%m-%d").date()
                if s <= end and e >= start:
                    ranges.append((s, e, name))
    if ranges:
        s0 = min(s for s, _, _ in ranges)
        e0 = max(e for _, e, _ in ranges)
        return min(start, s0), (max(end, e0) - min(start, s0)).days + 1, True
    return start, nights, False


# ----------------------------------------------------------------------
# Discount & Breakdowns
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None, date: datetime.date) -> tuple[int, bool]:
    if not discount:
        return points, False
    if discount == "within_60_days":
        return math.floor(points * 0.7), True
    if discount == "within_30_days":
        return math.floor(points * 0.75), True
    return points, False

def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows, tot_pts, tot_rent = [], 0, 0
    cur_h, h_end = None, None
    applied, disc_days = False, []
    
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        raw_pts = entry.get(room, 0)
        
        # Calculate discounted points (eff_pts) for POINTS REQUIRED total
        eff_pts, disc = apply_discount(raw_pts, discount, d)
        
        if disc:
            applied = True
            disc_days.append(fmt_date(d))
        
        # Calculate rent based on RAW points (as requested by user)
        rent = math.ceil(raw_pts * rate)
        
        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                
                rows.append({"Date": f"{cur_h} ({fmt_date(h_start)} - {fmt_date(h_end)})",
                             "Day": "", "Points": eff_pts, room: f"${rent}"})
                tot_pts += eff_pts
                tot_rent += rent
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            rows.append({"Date": fmt_date(d), "Day": d.strftime("%a"),
                         "Points": eff_pts, room: f"${rent}"})
            tot_pts += eff_pts
            tot_rent += rent
            
    return pd.DataFrame(rows), tot_pts, tot_rent, applied, disc_days

def owner_breakdown(resort, room, checkin, nights, disc_mul,
                    inc_maint, inc_cap, inc_dep,
                    rate, cap_per_pt, coc, life, salvage):
    rows, tot_pts, tot_cost = [], 0, 0
    totals = {"m": 0, "c": 0, "d": 0}
    cur_h, h_end = None, None
    
    dep_per_pt = (cap_per_pt - salvage) / life if inc_dep and life > 0 else 0
    
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        dpts = math.floor(pts * disc_mul) # discounted points for owner
        
        # Cost calculations based on discounted points (dpts)
        mc = math.ceil(dpts * rate) if inc_maint else 0
        cc = math.ceil(dpts * cap_per_pt * coc) if inc_cap else 0
        dc = math.ceil(dpts * dep_per_pt) if inc_dep else 0
        day_cost = mc + cc + dc

        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                row = {"Date": f"{cur_h} ({fmt_date(h_start)} - {fmt_date(h_end)})",
                       "Day": "", "Points": dpts}
                if inc_maint: row["Maintenance"] = f"${mc}"; totals["m"] += mc
                if inc_cap: row["Capital Cost"] = f"${cc}"; totals["c"] += cc
                if inc_dep: row["Depreciation"] = f"${dc}"; totals["d"] += dc
                if day_cost: row["Total Cost"] = f"${day_cost}"; tot_cost += day_cost
                
                rows.append(row)
                tot_pts += dpts
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            row = {"Date": fmt_date(d), "Day": d.strftime("%a"), "Points": dpts}
            
            if inc_maint: row["Maintenance"] = f"${mc}"; totals["m"] += mc
            if inc_cap: row["Capital Cost"] = f"${cc}"; totals["c"] += cc
            if inc_dep: row["Depreciation"] = f"${dc}"; totals["d"] += dc
            if day_cost: row["Total Cost"] = f"${day_cost}"; tot_cost += day_cost

            rows.append(row)
            tot_pts += dpts
            
    return (pd.DataFrame(rows), tot_pts, tot_cost,
            totals["m"], totals["c"], totals["d"])

# ----------------------------------------------------------------------
# COMPARISON helpers
# ----------------------------------------------------------------------
def compare_renter(resort, rooms, checkin, nights, rate, discount):
    data_rows = []
    chart_rows = []
    total_rent = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}
    applied, disc_days = False, []
    
    HOLIDAY_WEEKS = st.session_state.data.get("holiday_weeks", {})

    stay_end = checkin + timedelta(days=nights - 1)
    holiday_ranges = []
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(str(checkin.year), {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(str(checkin.year), raw.split(":", 1)[1])
        if len(raw) >= 2:
            s = datetime.strptime(raw[0], "%Y-%m-%d").date()
            e = datetime.strptime(raw[1], "%Y-%m-%d").date()
            if s <= stay_end and e >= checkin:
                holiday_ranges.append((s, e, name))
                
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        
        is_holiday = any(s <= d <= e for s, e, _ in holiday_ranges)
        h_name = next((n for s, e, n in holiday_ranges if s <= d <= e), None)
        is_h_start = entry.get("HolidayWeekStart")
        
        for room in rooms:
            raw_pts = entry.get(room, 0)
            eff_pts, disc = apply_discount(raw_pts, discount, d)
            
            if disc:
                applied = True
                disc_days.append(fmt_date(d))
            
            # Use RAW points for rent calculation (as requested by user)
            rent = math.ceil(raw_pts * rate)
            
            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    h_start = min(s for s, _, n in holiday_ranges if n == h_name)
                    h_end = max(e for _, e, n in holiday_ranges if n == h_name)
                    holiday_totals[room][h_name] = {"rent": rent, "start": h_start, "end": h_end}
                start_str = fmt_date(holiday_totals[room][h_name]["start"])
                end_str = fmt_date(holiday_totals[room][h_name]["end"])
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                  "Room Type": room, "Rent": f"${rent}"})
                continue
            
            if not is_holiday:
                data_rows.append({"Date": fmt_date(d),
                                  "Room Type": room, "Rent": f"${rent}"})
                total_rent[room] += rent
                # Use RAW points for chart value
                chart_rows.append({"Date": d, "Day": d.strftime("%a"),
                                   "Room Type": room, "RentValue": rent,
                                   "Holiday": "No"})
                                   
    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_rent[r]}"
    data_rows.append(total_row)
    
    df = pd.DataFrame(data_rows)
    # Ensure all rooms are columns in pivot for complete comparison
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Rent", aggfunc="first")
    pivot = pivot.reset_index()[["Date"] + [c for c in rooms if c in pivot.columns]]
    
    holiday_chart = []
    for room in rooms:
        for h, info in holiday_totals[room].items():
            holiday_chart.append({"Holiday": h, "Room Type": room,
                                  "RentValue": info["rent"]})
    
    holiday_df = pd.DataFrame(holiday_chart)
    chart_df = pd.DataFrame(chart_rows)
    
    return pivot, chart_df, holiday_df, applied, disc_days

def compare_owner(resort, rooms, checkin, nights, disc_mul,
                  inc_maint, inc_cap, inc_dep,
                  rate, cap_per_pt, coc, life, salvage):
    data_rows = []
    chart_rows = []
    total_cost = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}
    
    HOLIDAY_WEEKS = st.session_state.data.get("holiday_weeks", {})

    dep_per_pt = (cap_per_pt - salvage) / life if inc_dep and life > 0 else 0
    stay_end = checkin + timedelta(days=nights - 1)
    holiday_ranges = []
    
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(str(checkin.year), {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(str(checkin.year), raw.split(":", 1)[1])
        if len(raw) >= 2:
            s = datetime.strptime(raw[0], "%Y-%m-%d").date()
            e = datetime.strptime(raw[1], "%Y-%m-%d").date()
            if s <= stay_end and e >= checkin:
                holiday_ranges.append((s, e, name))
                
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        
        is_holiday = any(s <= d <= e for s, e, _ in holiday_ranges)
        h_name = next((n for s, e, n in holiday_ranges if s <= d <= e), None)
        is_h_start = entry.get("HolidayWeekStart")
        
        for room in rooms:
            pts = entry.get(room, 0)
            dpts = math.floor(pts * disc_mul)
            
            mc = math.ceil(dpts * rate) if inc_maint else 0
            cc = math.ceil(dpts * cap_per_pt * coc) if inc_cap else 0
            dc = math.ceil(dpts * dep_per_pt) if inc_dep else 0
            day_cost = mc + cc + dc
            
            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    h_start = min(s for s, _, n in holiday_ranges if n == h_name)
                    h_end = max(e for _, e, n in holiday_ranges if n == h_name)
                    holiday_totals[room][h_name] = {"cost": day_cost, "start": h_start, "end": h_end}
                start_str = fmt_date(holiday_totals[room][h_name]["start"])
                end_str = fmt_date(holiday_totals[room][h_name]["end"])
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                  "Room Type": room, "Total Cost": f"${day_cost}"})
                continue
                
            if not is_holiday:
                data_rows.append({"Date": fmt_date(d),
                                  "Room Type": room, "Total Cost": f"${day_cost}"})
                total_cost[room] += day_cost
                chart_rows.append({"Date": d, "Day": d.strftime("%a"),
                                   "Room Type": room, "TotalCostValue": day_cost,
                                   "Holiday": "No"})
                                   
    total_row = {"Date": "Total Cost (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_cost[r]}"
    data_rows.append(total_row)
    
    df = pd.DataFrame(data_rows)
    # Ensure all rooms are columns in pivot for complete comparison
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Total Cost", aggfunc="first")
    pivot = pivot.reset_index()[["Date"] + [c for c in rooms if c in pivot.columns]]
    
    holiday_chart = []
    for room in rooms:
        for h, info in holiday_totals[room].items():
            holiday_chart.append({"Holiday": h, "Room Type": room,
                                  "TotalCostValue": info["cost"]})
    
    holiday_df = pd.DataFrame(holiday_chart)
    chart_df = pd.DataFrame(chart_rows)
    
    return pivot, chart_df, holiday_df

# ----------------------------------------------------------------------
# Main App
# ----------------------------------------------------------------------
setup_page()
initialize_session_state()

# Load data
if st.session_state.data is None:
    try:
        with open("data.json", "r") as f:
            st.session_state.data = json.load(f)
            st.info(f"Loaded {len(st.session_state.data.get('resorts_list', []))} resorts from data.json")
    except FileNotFoundError:
        st.info("No data.json found. Please upload a file.")
    except Exception as e:
        st.error(f"Error loading data.json: {e}")

with st.sidebar:
    handle_file_upload()

if not st.session_state.data:
    st.error("No data loaded. Please upload a JSON file.")
    st.stop()

data = st.session_state.data
# Accessing global constants from data for the main script scope
ROOM_VIEW_LEGEND = data.get("room_view_legend", {})
SEASON_BLOCKS = data.get("season_blocks", {})
REF_POINTS = data.get("reference_points", {})
HOLIDAY_WEEKS = data.get("holiday_weeks", {})
resorts = data.get("resorts_list", [])

# --- SIDEBAR: User Mode & Parameters (Always Visible) ---
with st.sidebar:
    st.header("Mode & Parameters")
    user_mode = st.selectbox("User Mode", ["Renter", "Owner"], key="mode")

    default_rate = data.get("maintenance_rates", {}).get("2026", 0.86)

    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price per Point ($)", 0.0, step=0.1, value=16.0, key="cap_per_pt")
        disc_lvl = st.selectbox("Last-Minute Discount", [0, 25, 30],
                                format_func=lambda x: f"{x}% ({['Ordinary','Executive','Presidential'][x//25]})",
                                key="disc_lvl")
        disc_mul = 1 - disc_lvl/100

        inc_maint = st.checkbox("Include Maintenance Cost", True, key="inc_maint")
        rate_per_point = st.number_input("Maintenance Rate per Point ($)", 0.0, step=0.01, value=default_rate,
                                         disabled=not inc_maint, key="maint_rate")

        inc_cap = st.checkbox("Include Capital Cost", True, key="inc_cap")
        if inc_cap:
            coc = st.number_input("Cost of Capital (%)", 0.0, 100.0, 7.0, 0.1, key="coc") / 100

        inc_dep = st.checkbox("Include Depreciation Cost", True, key="inc_dep")
        if inc_dep:
            life = st.number_input("Useful Life (Years)", 1, value=15, key="life")
            salvage = st.number_input("Salvage Value per Point ($)", 0.0, value=3.0, step=0.1, key="salvage")

    else:  # Renter mode
        st.session_state.allow_renter_modifications = st.checkbox("More Options", key="allow_renter_mod")
        if st.session_state.allow_renter_modifications:
            opt = st.radio("Rate Option", [
                "Based on Maintenance Rate", "Custom Rate",
                "Booked within 60 days", "Booked within 30 days"
            ], key="rate_opt")
            if opt == "Custom Rate":
                rate_per_point = st.number_input("Custom Rate per Point ($)", 0.0, step=0.01, value=default_rate, key="custom_rate")
                discount_opt = None
            elif opt == "Booked within 60 days":
                rate_per_point, discount_opt = default_rate, "within_60_days"
            elif opt == "Booked within 30 days":
                rate_per_point, discount_opt = default_rate, "within_30_days"
            else:
                rate_per_point, discount_opt = default_rate, None
        else:
            rate_per_point, discount_opt = default_rate, None

# --- Resort Selection ---
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")
cols = st.columns(6)
current_resort = st.session_state.current_resort
for i, resort_name in enumerate(resorts):
    with cols[i % 6]:
        if st.button(resort_name, key=f"resort_{i}",
                     type="primary" if current_resort == resort_name else "secondary"):
            st.session_state.current_resort = resort_name
            st.rerun()

resort = st.session_state.current_resort
if not resort:
    st.warning("Please select a resort to continue.")
    st.stop()

# --- Main Inputs (Compact Layout) ---
# st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")

col1, col2, col3, col4 = st.columns(4)

with col1:
    checkin = st.date_input("Check-in Date", value=datetime(2026, 6, 12).date(),
                            min_value=datetime(2025, 1, 3).date(),
                            max_value=datetime(2026, 12, 31).date(), key="checkin")

with col2:
    nights = st.number_input("Number of Nights", 1, 30, 7, key="nights")

# Cache management
year = str(checkin.year)
if (st.session_state.last_resort != resort or st.session_state.last_year != year):
    st.session_state.data_cache.clear()
    st.session_state.room_types = None
    st.session_state.last_resort = resort
    st.session_state.last_year = year

# Load room types
if st.session_state.room_types is None:
    entry, d2i = generate_data(resort, checkin)
    st.session_state.room_types = sorted([k for k in entry.keys() if k not in
                                          {"HolidayWeek", "HolidayWeekStart", "holiday_name",
                                           "holiday_start", "holiday_end"}])
    st.session_state.disp_to_int = d2i

with col3:
    room = st.selectbox("Select Room Type", st.session_state.room_types, key="room_sel")

with col4:
    compare = st.multiselect("Compare With", [r for r in st.session_state.room_types if r != room], key="compare")

# Adjust dates for full holiday weeks
checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    end_date = checkin_adj + timedelta(days=nights_adj - 1)
    st.info(f"Adjusted to full holiday week: **{fmt_date(checkin_adj)} – {fmt_date(end_date)}** ({nights_adj} nights)")

# --- AUTOMATIC CALCULATION (No Button!) ---
gantt = gantt_chart(resort, checkin.year)

if user_mode == "Renter":
    df, pts, rent, disc_applied, disc_days = renter_breakdown(
        resort, room, checkin_adj, nights_adj, rate_per_point, discount_opt)
    
    st.subheader(f"{resort} Rental Breakdown")
    st.dataframe(df, use_container_width=True)
    
    # Always show discount message, using disc_applied for dynamic message
    if discount_opt:
        pct = 30 if discount_opt == "within_60_days" else 25
        if disc_applied:
             days_str = f"({len(disc_days)} day(s): {', '.join(disc_days)})"
             st.success(f"Discount Applied: {pct}% off points {days_str}")
        else:
             st.info(f"Discount Applied: {pct}% off points (0 days). No points found for selection.")
    else:
        st.info("Discount Applied: 0% off points (Standard Rate Option)")
    
    st.success(f"Total Points Required: {pts:,} | Total Rent: ${rent:,}")
    st.download_button("Download Breakdown CSV", df.to_csv(index=False),
                        f"{resort}_{fmt_date(checkin_adj)}_rental.csv", "text/csv")

else:  # Owner mode
    df, pts, cost, m_cost, c_cost, d_cost = owner_breakdown(
        resort, room, checkin_adj, nights_adj, disc_mul,
        inc_maint, inc_cap, inc_dep,
        rate_per_point, cap_per_pt,
        coc if 'coc' in locals() else 0.07,
        life if 'life' in locals() else 15,
        salvage if 'salvage' in locals() else 3.0)

    cols = ["Date", "Day", "Points"]
    if inc_maint or inc_cap or inc_dep:
        if inc_maint: cols.append("Maintenance")
        if inc_cap: cols.append("Capital Cost")
        if inc_dep: cols.append("Depreciation")
        cols.append("Total Cost")

    st.subheader(f"{resort} Ownership Cost Breakdown")
    st.dataframe(df[cols], use_container_width=True)
    st.success(f"Total Points Used: {pts:,} | Total Cost: ${cost:,}")
    if inc_maint and m_cost: st.info(f"Maintenance: ${m_cost:,}")
    if inc_cap and c_cost: st.info(f"Capital Cost: ${c_cost:,}")
    if inc_dep and d_cost: st.info(f"Depreciation: ${d_cost:,}")
    st.download_button("Download Cost CSV", df.to_csv(index=False),
                        f"{resort}_{fmt_date(checkin_adj)}_cost.csv", "text/csv")

# --- Comparison ---
if compare:
    all_rooms = [room] + compare
    if user_mode == "Renter":
        pivot, chart_df, holiday_df, _, _ = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate_per_point, discount_opt)
    else:
        pivot, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, disc_mul,
                                                     inc_maint, inc_cap, inc_dep,
                                                     rate_per_point, cap_per_pt,
                                                     coc if 'coc' in locals() else 0.07,
                                                     life if 'life' in locals() else 15,
                                                     salvage if 'salvage' in locals() else 3.0)

    st.subheader("Room Type Comparison")
    st.dataframe(pivot, use_container_width=True)
    if not chart_df.empty:
        fig = px.bar(chart_df, x="Day", y="RentValue" if user_mode == "Renter" else "TotalCostValue",
                     color="Room Type", barmode="group", text_auto=True,
                     category_orders={"Day": ["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]})
        st.plotly_chart(fig, use_container_width=True)
    if not holiday_df.empty:
        fig = px.bar(holiday_df, x="Holiday", y="RentValue" if user_mode == "Renter" else "TotalCostValue",
                     color="Room Type", barmode="group", text_auto=True)
        st.plotly_chart(fig, use_container_width=True)

# --- Gantt Chart ---
st.plotly_chart(gantt, use_container_width=True)
