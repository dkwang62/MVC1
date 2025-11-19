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
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows, tot_eff_pts, tot_raw_pts, tot_rent = [], 0, 0, 0 
    cur_h, h_end = None, None
    applied, disc_days = False, []
    
    # Determine the discount multiplier and label based on the option
    disc_mul, disc_label = 1.0, "0%"
    if discount == "within_30_days": # Executive (25% off)
        disc_mul, disc_label = 0.75, "25%" 
    elif discount == "within_60_days": # Presidential (30% off)
        disc_mul, disc_label = 0.7, "30%" 

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        raw_pts = entry.get(room, 0)
        
        # Calculate discounted points (eff_pts) for POINTS REQUIRED total
        eff_pts = math.floor(raw_pts * disc_mul) if disc_mul < 1.0 else raw_pts
        disc = (disc_mul < 1.0) and (raw_pts > 0)
        
        if disc:
            applied = True
            disc_days.append(fmt_date(d))
        
        # Calculate rent based on RAW points 
        rent = math.ceil(raw_pts * rate)
        
        # Determine the effective discount percentage for the row display
        daily_disc_label = disc_label if disc else "0%"
        
        # Format rent without Markdown (No bolding)
        rent_formatted = f"${rent}"

        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                
                rows.append({"Date": f"{cur_h} ({fmt_date(h_start)} - {fmt_date(h_end)})",
                              "Day": "", 
                              "RentValue": rent_formatted, # Use generic name
                              "Undiscounted Points": raw_pts, # RENAMED
                              "Discount Applied": daily_disc_label,
                              "Points Used (Discounted)": eff_pts})
                tot_eff_pts += eff_pts
                tot_raw_pts += raw_pts 
                tot_rent += rent
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            rows.append({"Date": fmt_date(d), "Day": d.strftime("%a"),
                          "RentValue": rent_formatted, # Use generic name
                          "Undiscounted Points": raw_pts, # RENAMED
                          "Discount Applied": daily_disc_label,
                          "Points Used (Discounted)": eff_pts})
            tot_eff_pts += eff_pts
            tot_raw_pts += raw_pts 
            tot_rent += rent
            
    df = pd.DataFrame(rows)
    # RENAME the generic "RentValue" column to the actual room name for display
    if not df.empty and "RentValue" in df.columns:
        df = df.rename(columns={"RentValue": room})
        
    return df, tot_eff_pts, tot_raw_pts, tot_rent, applied, disc_days 

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

    # Determine the discount multiplier (CORRECTED)
    disc_mul = 1.0
    if discount == "within_30_days": # Executive (25% off)
        disc_mul = 0.75
    elif discount == "within_60_days": # Presidential (30% off)
        disc_mul = 0.7
    
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
            
            # Calculate discounted points (eff_pts)
            eff_pts = math.floor(raw_pts * disc_mul) if disc_mul < 1.0 else raw_pts
            disc = (disc_mul < 1.0) and (raw_pts > 0)
            
            if disc:
                applied = True
                disc_days.append(fmt_date(d))
            
            # Use RAW points for rent calculation 
            rent = math.ceil(raw_pts * rate)
            
            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    h_start = min(s for s, _, n in holiday_ranges if n == h_name)
                    h_end = max(e for _, e, n in holiday_ranges if n == h_name)
                    holiday_totals[room][h_name] = {"rent": rent, "start": h_start, "end": h_end}
                start_str = fmt_date(holiday_totals[room][h_name]["start"])
                end_str = fmt_date(holiday_totals[room][h_name]["end"])
                # Removed bolding: f"**${rent}**" -> f"${rent}"
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                  "Room Type": room, "Rent": f"${rent}"}) 
                continue
            
            if not is_holiday:
                # Removed bolding: f"**${rent}**" -> f"${rent}"
                data_rows.append({"Date": fmt_date(d),
                                  "Room Type": room, "Rent": f"${rent}"}) 
                total_rent[room] += rent
                # Use RAW points for chart value (Rent is based on RAW points)
                chart_rows.append({"Date": d, "Day": d.strftime("%a"),
                                   "Room Type": room, "RentValue": rent,
                                   "Holiday": "No"})
                                    
    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for r in rooms:
        # Removed bolding: f"**${total_rent[r]}**" -> f"${total_rent[r]}"
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
    rows, chart_rows = [], []
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
                rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                  "Room Type": room, "Total Cost": f"${day_cost}"})
                continue
                
            if not is_holiday:
                rows.append({"Date": fmt_date(d),
                                  "Room Type": room, "Total Cost": f"${day_cost}"})
                total_cost[room] += day_cost
                chart_rows.append({"Date": d, "Day": d.strftime("%a"),
                                   "Room Type": room, "TotalCostValue": day_cost,
                                   "Holiday": "No"})
                                    
    total_row = {"Date": "Total Cost (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_cost[r]}"
    rows.append(total_row)
    
    df = pd.DataFrame(rows)
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
    user_mode = st.selectbox("User Mode", ["Renter", "Owner"], key="mode", index=0)
    
    default_rate = data.get("maintenance_rates", {}).get("2026", 0.86)
    rate_per_point, discount_opt = default_rate, None # Initialize renter variables

    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price per Point ($)", 0.0, step=0.1, value=16.0, key="cap_per_pt")
        # Owner discount logic remains the same (0, 25, 30) for cost calculation
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
        
        opt = "Based on Maintenance Rate (No Discount)" 
        
        if st.session_state.allow_renter_modifications:
            # CORRECTED RENTER DISCOUNT OPTIONS
            opt = st.radio("Rate/Discount Option", [
                "Based on Maintenance Rate (No Discount)", 
                "Custom Rate (No Discount)",
                "Executive: 25% Points Discount (Booked within 30 days)", 
                "Presidential: 30% Points Discount (Booked within 60 days)"
            ], key="rate_opt")
            
            if opt == "Custom Rate (No Discount)":
                rate_per_point = st.number_input("Custom Rate per Point ($)", 0.0, step=0.01, value=default_rate, key="custom_rate")
                discount_opt = None
            elif "Executive" in opt:
                rate_per_point, discount_opt = default_rate, "within_30_days" # 30 days is Executive (25%)
            elif "Presidential" in opt:
                rate_per_point, discount_opt = default_rate, "within_60_days" # 60 days is Presidential (30%)
            else: # "Based on Maintenance Rate (No Discount)"
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

# ----------------------------------------------------------------------
# RENTER MODE (Revised Explanation using st.expander)
# ----------------------------------------------------------------------
if user_mode == "Renter":
    df, pts, raw_pts_total, rent, disc_applied, disc_days = renter_breakdown(
        resort, room, checkin_adj, nights_adj, rate_per_point, discount_opt)
    
    st.subheader(f"{resort} Rental Breakdown")
    
    cols = ["Date", "Day", room, "Undiscounted Points", "Discount Applied", "Points Used (Discounted)"]
    
    # Use standard rendering
    st.dataframe(df[cols], use_container_width=True) 
    
    # --- Renter Calculation Explanation placed inside an Expander ---
    with st.expander("💡 Rent Calculation Explained"):
        
        # Define rate_opt here to ensure it exists for the check below
        rate_opt = st.session_state.get('rate_opt', "Based on Maintenance Rate (No Discount)")
        is_custom_rate = rate_opt == "Custom Rate (No Discount)"
        
        if is_custom_rate:
            rate_basis = f"a **Custom Rate** of **${rate_per_point:.2f} per point**."
        else:
            # Note: This logic now pulls the latest rate_per_point from the sidebar 
            # if the "More Options" is checked, otherwise it uses the default.
            if st.session_state.get('rate_opt') == "Based on Maintenance Rate (No Discount)":
                rate_basis = f"the **Maintenance Rate** of **${default_rate:.2f} per point**."
            else:
                # If a discount option is selected, the rent is still calculated on the default maintenance rate
                rate_basis = f"the **Maintenance Rate** of **${default_rate:.2f} per point**."


        st.markdown(f"""
        * The **Rent** amount is calculated based on the **Undiscounted Points** for the night using {rate_basis}
        * The **Discount Applied** column reflects the selected last-minute discount:
            * **Executive**: 25% off points (booked within 30 days)
            * **Presidential**: 30% off points (booked within 60 days)
        * **Points Used (Discounted)** are the points actually **debited** from the member's account (this is the value after the discount, if applicable).
        """)

    # Display discount message only if a discount was selected
    if discount_opt:
        pct = 25 if discount_opt == "within_30_days" else 30
        lvl = "Executive" if discount_opt == "within_30_days" else "Presidential"
        
        if disc_applied:
            days_str = f"({len(disc_days)} day(s): {', '.join(disc_days)})"
            st.success(f"**{lvl} ({pct}%) Last-Minute Discount** Applied to Points {days_str}")
        else:
            st.info(f"**{lvl} ({pct}%) Last-Minute Discount** selected, but no points were found for this room on these dates to apply it to.")
    
    # Display the final totals clearly
    st.success(f"Total Undiscounted Points: {raw_pts_total:,} | Total Points Used (Discounted): {pts:,} | Final Total Rent: **${rent:,}**")
    
    # Download button remains
    df_export = df.copy()
    if room in df_export.columns:
        df_export[room] = df_export[room].astype(str).str.replace('$', '', regex=False)
    st.download_button("Download Breakdown CSV", df_export[cols].to_csv(index=False),
                       f"{resort}_{fmt_date(checkin_adj)}_rental.csv", "text/csv")
# ----------------------------------------------------------------------
# OWNER MODE
# ----------------------------------------------------------------------
else:  
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
    st.success(f"Total Points Used: {pts:,} | Total Cost: **${cost:,}**")
    if inc_maint and m_cost: st.info(f"Maintenance Cost Included: ${m_cost:,}")
    if inc_cap and c_cost: st.info(f"Capital Cost Included: ${c_cost:,}")
    if inc_dep and d_cost: st.info(f"Depreciation Cost Included: ${d_cost:,}")
    st.download_button("Download Breakdown CSV", df[cols].to_csv(index=False),
                       f"{resort}_{fmt_date(checkin_adj)}_owner_cost.csv", "text/csv")

# ----------------------------------------------------------------------
# Gantt Chart Display and Comparison (Final Section)
# ----------------------------------------------------------------------
# st.markdown("---")
# st.subheader("Season & Holiday Overview")
st.plotly_chart(gantt, use_container_width=True)

# ----------------------------------------------------------------------
# COMPARISON MODE (REVISED RENTER SECTION)
# ----------------------------------------------------------------------
if compare:
    all_rooms = [room] + compare
    compare_df_pivot, chart_df, holiday_df, disc_applied, disc_days = compare_renter(
        resort, all_rooms, checkin_adj, nights_adj, rate_per_point, discount_opt)
    
    st.write(f"### {resort} Room Type Comparison")
    st.dataframe(compare_df_pivot, use_container_width=True)

    # --- START: NEW TOTAL RENT COMPARISON CHART LOGIC ---
    try:
        # all_rooms is already defined as [room] + compare
        # Extract the Total Rent (Non-Holiday) row from the comparison pivot table
        total_rent_row = compare_df_pivot[compare_df_pivot["Date"] == "Total Rent (Non-Holiday)"]
        if not total_rent_row.empty:
            total_rent_data = []
            for room_name in all_rooms:
                # Safely extract and clean the rent string (e.g., "$1,234")
                if room_name in total_rent_row.columns:
                    rent_str = total_rent_row[room_name].iloc[0]
                    try:
                        # Remove '$' and ',' and convert to integer
                        rent_value = int(rent_str.replace('$', '').replace(',', '').strip())
                    except:
                        rent_value = 0
                    total_rent_data.append({
                        "Room Type": room_name,
                        "Total Rent ($)": rent_value
                    })
            total_rent_df = pd.DataFrame(total_rent_data)

            if not total_rent_df.empty:
                st.write("### Total Rent Comparison (Non-Holiday Stay)")
                fig_total = px.bar(
                    total_rent_df,
                    x="Room Type",
                    y="Total Rent ($)",
                    color="Room Type",
                    labels={"Total Rent ($)": "Total Rent for Stay ($)"},
                    height=500,
                    text="Total Rent ($)",
                    text_auto=True
                )
                fig_total.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                fig_total.update_layout(showlegend=False)
                st.plotly_chart(fig_total, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not generate Total Rent Comparison chart: {e}")
    # --- END: NEW TOTAL RENT COMPARISON CHART LOGIC ---

    compare_csv = compare_df_pivot.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Room Comparison for Excel",
        data=compare_csv,
        file_name=f"{resort}_room_comparison.csv",
        mime="text/csv"
    )

    if not chart_df.empty:
        non_holiday_df = chart_df[chart_df["Holiday"] == "No"]
        if not non_holiday_df.empty:
            start_date = non_holiday_df["Date"].min()
            end_date = non_holiday_df["Date"].max()
            start_date_str = start_date.strftime("%b %d")
            end_date_str = end_date.strftime("%b %d, %Y")
            # title = f"{resort} Daily Rent Comparison (Non-Holiday, {start_date_str} - {end_date_str})"
            # st.subheader(title)

            day_order = ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]
            fig = px.bar(
                non_holiday_df,
                x="Day",
                y="RentValue",
                color="Room Type",
                barmode="group",
                labels={"RentValue": "Rent ($)", "Day": "Day of Week"},
                height=600,
                text="RentValue",
                text_auto=True,
                category_orders={"Day": day_order}
            )
            fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
            fig.update_xaxes(
                ticktext=day_order,
                tickvals=[0, 1, 2, 3, 4, 5, 6],
                tickmode="array"
            )
            fig.update_layout(
                legend_title_text="Room Type",
                bargap=0.2,
                bargroupgap=0.1
            )
            st.plotly_chart(fig, use_container_width=True)

    if not holiday_df.empty:
        start_date = holiday_df["start"].min()
        end_date = holiday_df["end"].max()
        start_date_str = start_date.strftime("%b %d")
        end_date_str = end_date.strftime("%b %d, %Y")
        title = f"{resort} Room Type Comparison (Holiday Weeks, {start_date_str} - {end_date_str})"
        st.subheader(title)
        fig = px.bar(
            holiday_df,
            x="Holiday",
            y="RentValue",
            color="Room Type",
            barmode="group",
            labels={"RentValue": "Rent ($)", "Holiday": "Holiday Week"},
            height=600,
            text="RentValue",
            text_auto=True
        )
        fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
        fig.update_layout(
            legend_title_text="Room Type",
            bargap=0.2,
            bargroupgap=0.1
        )
        st.plotly_chart(fig, use_container_width=True)
