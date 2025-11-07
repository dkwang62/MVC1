import streamlit as st
import math
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px

# ----------------------------------------------------------------------
# Load data
# ----------------------------------------------------------------------
with open("data.json", "r") as f:
    data = json.load(f)

ROOM_VIEW_LEGEND = {
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
SEASON_BLOCKS = data.get("season_blocks", {})
REF_POINTS = data.get("reference_points", {})
HOLIDAY_WEEKS = data.get("holiday_weeks", {})

# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
st.session_state.setdefault("data_cache", {})
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

# ----------------------------------------------------------------------
# ALL FUNCTIONS (unchanged from your base + fixed renter)
# ----------------------------------------------------------------------
def display_room(key: str) -> str:
    if key in ROOM_VIEW_LEGEND: return ROOM_VIEW_LEGEND[key]
    if key.startswith("AP_"):
        return {"AP_Studio_MA": "AP Studio Mountain", "AP_1BR_MA": "AP 1BR Mountain",
                "AP_2BR_MA": "AP 2BR Mountain", "AP_2BR_MK": "AP 2BR Ocean"}.get(key, key)
    parts = key.split()
    view = parts[-1] if len(parts) > 1 and parts[-1] in ROOM_VIEW_LEGEND else ""
    return f"{parts[0]} {ROOM_VIEW_LEGEND.get(view, view)}".strip() or key

def resolve_global(year: str, key: str) -> list:
    return data.get("global_dates", {}).get(year, {}).get(key, [])

def generate_data(resort: str, date: datetime.date):
    cache = st.session_state.data_cache
    ds = date.strftime("%Y-%m-%d")
    if ds in cache:
        return cache[ds]
    # ... [your full generate_data logic - unchanged]
    year = date.strftime("%Y")
    dow = date.strftime("%a")
    is_fri_sat = dow in {"Fri", "Sat"}
    is_sun = dow == "Sun"
    entry = {}
    season = "Default Season"
    holiday = h_start = h_end = None
    is_h_start = False
    if (date.month == 12 and date.day >= 26) or (date.month == 1 and date.day <= 1):
        prev = str(int(year) - 1)
        start = datetime.strptime(f"{prev}-12-26", "%Y-%m-%d").date()
        end = datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date()
        if start <= date <= end:
            holiday, h_start, h_end, is_h_start = "New Year's Eve/Day", start, end, date == start
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
    if not holiday and year in SEASON_BLOCKS.get(resort, {}):
        for s_name, ranges in SEASON_BLOCKS[resort][year].items():
            for rs, re in ranges:
                s = datetime.strptime(rs, "%Y-%m-%d").date()
                e = datetime.strptime(re, "%Y-%m-%d").date()
                if s <= date <= e:
                    season = s_name
                    break
            if season != "Default Season": break
    if holiday:
        src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {})
        for k, pts in src.items():
            entry[display_room(k)] = pts if is_h_start else 0
    else:
        cats = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
        avail = [c for c in cats if REF_POINTS.get(resort, {}).get(season, {}).get(c)]
        cat = ("Fri-Sat" if is_fri_sat and "Fri-Sat" in avail else
               "Sun" if is_sun and "Sun" in avail else
               "Mon-Thu" if not is_fri_sat and "Mon-Thu" in avail else
               "Sun-Thu" if "Sun-Thu" in avail else avail[0]) if avail else None
        src = REF_POINTS.get(resort, {}).get(season, {}).get(cat, {}) if cat else {}
        for k, pts in src.items():
            entry[display_room(k)] = pts
    if holiday:
        entry.update(HolidayWeek=True, holiday_name=holiday,
                     holiday_start=h_start, holiday_end=h_end,
                     HolidayWeekStart=is_h_start)
    cache[ds] = (entry, {})
    return entry, {}

def gantt_chart(resort: str, year: int):
    # ... [your full gantt_chart - unchanged]
    rows = []
    ys = str(year)
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(ys, {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(ys, raw.split(":", 1)[1])
        if len(raw) >= 2:
            rows.append(dict(Task=name, Start=datetime.strptime(raw[0], "%Y-%m-%d").date(),
                             Finish=datetime.strptime(raw[1], "%Y-%m-%d").date() + timedelta(days=1), Type="Holiday"))
    for s_name, ranges in SEASON_BLOCKS.get(resort, {}).get(ys, {}).items():
        for i, (s, e) in enumerate(ranges, 1):
            rows.append(dict(Task=f"{s_name} {i}", Start=datetime.strptime(s, "%Y-%m-%d").date(),
                             Finish=datetime.strptime(e, "%Y-%m-%d").date() + timedelta(days=1), Type=s_name))
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if df.empty:
        df = pd.DataFrame({"Task": ["No Seasons/Holidays"], "Start": [datetime(year,1,1).date()],
                           "Finish": [datetime(year,1,2).date()], "Type": ["Info"]})
    colors = {"Holiday": "red", "Low Season": "lightblue", "High Season": "orange",
              "Peak Season": "gold", "Shoulder": "lightgreen", "Info": "gray"}
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Task", color="Type",
                      color_discrete_map=colors, title=f"{resort} Seasons & Holidays ({year})", height=400)
    fig.update_yaxes(autorange="reversed")
    return fig

def adjust_date_range(resort, start, nights):
    # ... [unchanged]
    end = start + timedelta(days=nights - 1)
    ranges = []
    year = str(start.year)
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(year, {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(year, raw.split(":", 1)[1])
        if len(raw) >= 2:
            s = datetime.strptime(raw[0], "%Y-%m-%d").date()
            e = datetime.strptime(raw[1], "%Y-%m-%d").date()
            if s <= end and e >= start:
                ranges.append((s, e))
    if ranges:
        s0 = min(s for s, _ in ranges)
        e0 = max(e for _, e in ranges)
        return min(start, s0), (max(end, e0) - min(start, s0)).days + 1, True
    return start, nights, False

def apply_discount(points: int, discount: str | None = None) -> tuple[int, bool]:
    if discount == "within_60_days":
        return math.floor(points * 0.7), True
    if discount == "within_30_days":
        return math.floor(points * 0.75), True
    return points, False

# ----------------------------------------------------------------------
# RENTER + OWNER FUNCTIONS (fixed TOTAL row)
# ----------------------------------------------------------------------
# [Keep your owner_breakdown, compare_owner, renter_breakdown, compare_renter]
# → Use the **exact same** versions from my last message (with manual pivot for TOTAL row)

# ----------------------------------------------------------------------
# UI - NO MORE generate_data() BEFORE RESORT
# ----------------------------------------------------------------------
st.title("Marriott Vacation Club Cost Calculator")

with st.expander("How It Works"):
    st.markdown("**Renter:** Rent = Points × Rate (with discount options)\n**Owner:** Cost = Maint + Capital + Dep")

user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=0)
checkin = st.date_input("Check-in", value=datetime(2026,6,12).date())
nights = st.number_input("Nights", 1, 30, 7)

# Default values
rate = 0.52 if checkin.year == 2025 else 0.60
discount = None
disc_lvl = 0
cap_per_pt = 16.0
coc = 0.07
life = 15
salvage = 3.0
inc_maint = inc_cap = inc_dep = True

with st.sidebar:
    st.header("Settings")
    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price/Point ($)", 10.0, 30.0, 16.0, 0.1)
        disc_lvl = st.selectbox("Discount", [0, 25, 30], format_func=lambda x: f"{x}%")
        inc_maint = st.checkbox("Include Maintenance", True)
        if inc_maint:
            rate = st.number_input("Maint Fee/Point ($)", 0.40, 0.80, rate, 0.01)
        inc_cap = st.checkbox("Include Capital Cost", True)
        if inc_cap:
            coc = st.number_input("Cost of Capital (%)", 1.0, 15.0, 7.0, 0.1) / 100
        inc_dep = st.checkbox("Include Depreciation", True)
        if inc_dep:
            life = st.number_input("Life (Years)", 5, 30, 15)
            salvage = st.number_input("Salvage/Point ($)", 0.0, 10.0, 3.0, 0.1)
    else:
        st.markdown("### Renter Settings")
        opt = st.radio("Rate", ["Standard", "60 Days (30% off)", "30 Days (25% off)", "Custom Rate"])
        if "60 Days" in opt:
            discount = "within_60_days"
        elif "30 Days" in opt:
            discount = "within_30_days"
        elif "Custom" in opt:
            rate = st.number_input("Custom Rate $/point", 0.30, 2.00, rate, 0.01)

st.subheader("Resort")
resorts = st.multiselect("Select Resort", data["resorts_list"], default=[data["resorts_list"][0]], max_selections=1)
resort = resorts[0] if resorts else data["resorts_list"][0]

# ONLY AFTER RESORT IS DEFINED → safe to use generate_data
year = str(checkin.year)
if st.session_state.get("last_resort") != resort or st.session_state.get("last_year") != year:
    st.session_state.data_cache.clear()
    st.session_state.last_resort = resort
    st.session_state.last_year = year

# NOW SAFE TO CALL generate_data
entry, _ = generate_data(resort, checkin)
room_types = sorted([k for k in entry.keys() if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"}])
room = st.selectbox("Room Type", room_types)
compare = st.multiselect("Compare With", [r for r in room_types if r != room])

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Extended to full holiday week: {nights_adj} nights")

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Owner":
        df, total_points, total_cost = owner_breakdown(resort, room, checkin_adj, nights_adj, rate, disc_lvl,
                                                       cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
        st.subheader("Ownership Cost Breakdown")
        st.dataframe(df[["Date", "Day", "Points", "Maintenance", "Capital", "Depreciation", room]],
                     use_container_width=True, hide_index=True)
        msg = f"**Total Points:** {total_points:,} → **Total Cost: ${total_cost:,.0f}**"
        if disc_lvl > 0: msg = f"**{disc_lvl}% Discount** → " + msg
        st.success(msg)

        if compare:
            all Rooms = [room] + compare
            pivot, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, rate, disc_lvl,
                                                        cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
            st.subheader("Room Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)

    else:  # RENTER
        df, total_pts, total_rent, applied = renter_breakdown(resort, room, checkin_adj, nights_adj, rate, discount)
        st.subheader("Rental Cost Breakdown")
        st.dataframe(df[["Date", "Day", "Points", room]], use_container_width=True, hide_index=True)
        msg = f"**Total Rent: ${total_rent:,}** ({total_pts:,} pts)"
        if applied:
            pct = "30%" if discount == "within_60_days" else "25%"
            msg = f"**{pct} Discount Applied** → " + msg
        st.success(msg)

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df, _ = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate, discount)
            st.subheader("Room Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)

    st.plotly_chart(gantt, use_container_width=True)
