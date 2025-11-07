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
SEASON_BLOCKS   = data.get("season_blocks", {})
REF_POINTS      = data.get("reference_points", {})
HOLIDAY_WEEKS   = data.get("holiday_weeks", {})

# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
defaults = {
    "data_cache": {},
    "allow_renter_modifications": False,
    "selected_resort": data["resorts_list"][0],
    "last_resort": None,
    "last_year": None,
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# ----------------------------------------------------------------------
# Helpers
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

# ----------------------------------------------------------------------
# Core data generation
# ----------------------------------------------------------------------
def generate_data(resort: str, date: datetime.date):
    cache = st.session_state.data_cache
    ds = date.strftime("%Y-%m-%d")
    if ds in cache:
        return cache[ds]

    year = date.strftime("%Y")
    dow = date.strftime("%a")
    is_fri_sat = dow in {"Fri", "Sat"}
    is_sun = dow == "Sun"

    entry = {}
    season = "Default Season"
    holiday = h_start = h_end = None
    is_h_start = False

    # Year-end
    if (date.month == 12 and date.day >= 26) or (date.month == 1 and date.day <= 1):
        prev = str(int(year) - 1)
        start = datetime.strptime(f"{prev}-12-26", "%Y-%m-%d").date()
        end = datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date()
        if start <= date <= end:
            holiday, h_start, h_end, is_h_start = "New Year's Eve/Day", start, end, date == start

    # Explicit holidays
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

    # Season
    if not holiday and year in SEASON_BLOCKS.get(resort, {}):
        for s_name, ranges in SEASON_BLOCKS[resort][year].items():
            for rs, re in ranges:
                s = datetime.strptime(rs, "%Y-%m-%d").date()
                e = datetime.strptime(re, "%Y-%m-%d").date()
                if s <= date <= e:
                    season = s_name
                    break
            if season != "Default Season": break

    # Points
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

    disp_to_int = {display_room(k): k for k in src}
    cache[ds] = (entry, disp_to_int)
    return entry, disp_to_int

# ----------------------------------------------------------------------
# Gantt + Adjust
# ----------------------------------------------------------------------
def gantt_chart(resort: str, year: int):
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
    df = pd.DataFrame(rows) if rows else pd.DataFrame({"Task": ["No Data"], "Start": [datetime.now().date()],
                                                       "Finish": [datetime.now().date() + timedelta(days=1)], "Type": ["No Data"]})
    colors = {"Holiday": "#FF6347", "Low Season": "#87CEFA", "High Season": "#FF4500",
              "Peak Season": "#FFD700", "Shoulder": "#90EE90", "No Data": "#808080"}
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Task", color="Type", color_discrete_map=colors,
                      title=f"{resort} Seasons & Holidays ({year})", height=600)
    fig.update_yaxes(autorange="reversed")
    return fig

def adjust_date_range(resort, start, nights):
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

# ----------------------------------------------------------------------
# Discount
# ----------------------------------------------------------------------
def apply_discount(points: int, disc_lvl: int) -> int:
    if disc_lvl == 25:
        return math.floor(points * 0.75)
    if disc_lvl == 30:
        return math.floor(points * 0.7)
    return points

# ----------------------------------------------------------------------
# OWNER MODE: Full cost breakdown
# ----------------------------------------------------------------------
def owner_breakdown(resort, room, checkin, nights, rate_per_point, disc_lvl,
                    cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep):
    rows = []
    total_points = total_maint = total_cap = total_dep = 0
    cur_h = h_end = None

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts = apply_discount(pts, disc_lvl)
        total_points += eff_pts

        maint = eff_pts * rate_per_point if inc_maint else 0
        cap = eff_pts * cap_per_pt * coc if inc_cap else 0
        dep = eff_pts * (cap_per_pt - salvage) / life if inc_dep else 0

        total_maint += maint
        total_cap += cap
        total_dep += dep

        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                rows.append({
                    "Date": f"{cur_h} ({h_start:%b %d} - {h_end:%b %d, %Y})",
                    "Day": "", "Points": eff_pts,
                    "Maintenance": f"${maint:,.0f}",
                    "Capital": f"${cap:,.0f}",
                    "Depreciation": f"${dep:,.0f}",
                    "Total": f"${maint + cap + dep:,.0f}"
                })
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            rows.append({
                "Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"),
                "Points": eff_pts,
                "Maintenance": f"${maint:,.0f}",
                "Capital": f"${cap:,.0f}",
                "Depreciation": f"${dep:,.0f}",
                "Total": f"${maint + cap + dep:,.0f}"
            })

    # Total row
    total_cost = total_maint + total_cap + total_dep
    rows.append({
        "Date": "TOTAL", "Day": "", "Points": total_points,
        "Maintenance": f"${total_maint:,.0f}",
        "Capital": f"${total_cap:,.0f}",
        "Depreciation": f"${total_dep:,.0f}",
        "Total": f"${total_cost:,.0f}"
    })

    return pd.DataFrame(rows), total_points, total_cost

# ----------------------------------------------------------------------
# Renter mode (unchanged)
# ----------------------------------------------------------------------
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows, tot_pts, tot_rent = [], 0, 0
    cur_h, h_end = None, None
    applied = False
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts, disc = apply_discount(pts, 30 if discount == "within_60_days" else 25 if discount == "within_30_days" else 0)
        applied |= disc
        rent = math.ceil(pts * rate)
        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                rows.append({"Date": f"{cur_h} ({h_start:%b %d} - {h_end:%b %d, %Y})", "Day": "", "Points": eff_pts, room: f"${rent}"})
                tot_pts += eff_pts
                tot_rent += rent
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            rows.append({"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff_pts, room: f"${rent}"})
            tot_pts += eff_pts
            tot_rent += rent
    return pd.DataFrame(rows), tot_pts, tot_rent, applied

def compare_renter(resort, rooms, checkin, nights, rate, discount):
    # Same as before — unchanged and working
    data_rows = []
    chart_rows = []
    total_rent = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}
    applied = False

    stay_end = checkin + timedelta(days=nights - 1)
    holiday_names = {}
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(str(checkin.year), {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(str(checkin.year), raw.split(":", 1)[1])
        if len(raw) >= 2:
            s = datetime.strptime(raw[0], "%Y-%m-%d").date()
            e = datetime.strptime(raw[1], "%Y-%m-%d").date()
            if s <= stay_end and e >= checkin:
                for dd in [s + timedelta(days=x) for x in range((e-s).days + 1)]:
                    holiday_names[dd] = name

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        is_holiday = d in holiday_names
        h_name = holiday_names.get(d)
        is_h_start = entry.get("HolidayWeekStart")

        for room in rooms:
            pts = entry.get(room, 0)
            eff_pts, _ = apply_discount(pts, 30 if discount == "within_60_days" else 25 if discount == "within_30_days" else 0)
            applied = True
            rent = math.ceil(pts * rate)

            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    holiday_totals[room][h_name] = {"rent": rent}
                data_rows.append({"Date": h_name, "Room Type": room, "Rent": f"${rent}"})
            elif not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Rent": f"${rent}"})
                total_rent[room] += rent
                chart_rows.append({"Date": d, "Day": d.strftime("%a"), "Room Type": room, "RentValue": rent})

    total_row = {"Date": "Total (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_rent[r]}"
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Rent", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]

    holiday_chart = [{"Holiday": h, "Room Type": room, "RentValue": info["rent"]}
                     for room in rooms for h, info in holiday_totals[room].items()]
    holiday_df = pd.DataFrame(holiday_chart)
    chart_df = pd.DataFrame(chart_rows)

    return pivot, chart_df, holiday_df, applied

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=1, key="user_mode")
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Ownership Cost'} Calculator")

with st.expander("How It Works", expanded=True):
    if user_mode == "Owner":
        st.markdown("""
        **Owner Mode** shows your **true all-in cost per night**:
        - Maintenance Fees  
        - Capital Cost (opportunity cost)  
        - Depreciation  
        - **Discounts reduce points used → lower cost**
        """)
    else:
        st.markdown("""
        **Renter Mode**:  
        - Rent = **full points × rate**  
        - Points shown = **after discount**  
        - 30% off (Presidential) | 25% off (Executive)
        """)

checkin = st.date_input("Check-in", value=datetime(2026,6,12).date(), min_value=datetime(2025,1,3).date())
nights = st.number_input("Nights", 1, 30, 7)

rate_per_point = 0.52 if checkin.year == 2025 else 0.60
discount_opt = None
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
        disc_lvl = st.selectbox("Last-Minute Discount", [0, 25, 30],
                                format_func=lambda x: f"{x}% off points ({['None','Executive','Presidential'][x//25]})")

        col1, col2 = st.columns(2)
        with col1:
            inc_maint = st.checkbox("Maintenance", True)
            inc_cap = st.checkbox("Capital Cost", True)
        with col2:
            inc_dep = st.checkbox("Depreciation", True)

        if inc_maint:
            rate_per_point = st.number_input("Maint. Fee/Point ($)", 0.40, 0.80, rate_per_point, 0.01)
        if inc_cap:
            coc = st.number_input("Cost of Capital (%)", 1.0, 15.0, 7.0, 0.1) / 100
        if inc_dep:
            col3, col4 = st.columns(2)
            with col3:
                life = st.number_input("Life (yrs)", 5, 30, 15)
            with col4:
                salvage = st.number_input("Salvage/Point ($)", 0.0, 10.0, 3.0, 0.1)

    else:
        st.session_state.allow_renter_modifications = st.checkbox("More Options", False)
        if st.session_state.allow_renter_modifications:
            opt = st.radio("Discount", ["None", "60 Days (30% off)", "30 Days (25% off)", "Custom Rate"])
            if "60" in opt: discount_opt = "within_60_days"
            if "30" in opt: discount_opt = "within_30_days"
            if "Custom" in opt:
                rate_per_point = st.number_input("Rate/Point ($)", value=rate_per_point, step=0.01)

# Resort
st.subheader("Resort")
resorts = st.multiselect("Search", data["resorts_list"], max_selections=1, key="resort")
resort = resorts[0] if resorts else st.session_state.selected_resort
if resort != st.session_state.selected_resort:
    st.session_state.selected_resort = resort
    st.session_state.data_cache.clear()

st.subheader(f"{resort}")
year = str(checkin.year)
if st.session_state.last_resort != resort or st.session_state.last_year != year:
    st.session_state.data_cache.clear()
    st.session_state.pop("room_types", None)
    st.session_state.last_resort = resort
    st.session_state.last_year = year

if "room_types" not in st.session_state:
    entry, _ = generate_data(resort, checkin)
    st.session_state.room_types = sorted(k for k in entry.keys()
        if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"})
room_types = st.session_state.room_types

room = st.selectbox("Room Type", room_types)
compare = st.multiselect("Compare With", [r for r in room_types if r != room])

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Adjusted to full holiday week: {checkin_adj} → {checkin_adj + timedelta(days=nights_adj-1)} ({nights_adj} nights)")

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Owner":
        df, total_points, total_cost = owner_breakdown(
            resort, room, checkin_adj, nights_adj, rate_per_point, disc_lvl,
            cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep
        )
        st.subheader("Ownership Cost Breakdown")
        st.dataframe(df, use_container_width=True)
        st.success(f"**Total Points Used: {total_points:,} | Total Cost: ${total_cost:,.0f}**")
        if disc_lvl > 0:
            st.success(f"**{disc_lvl}% Discount Applied → {total_points:,} points used**")
        st.download_button("Download CSV", df.to_csv(index=False).encode(), f"{resort}_owner.csv")

    else:
        df, pts, rent, applied = renter_breakdown(resort, room, checkin_adj, nights_adj, rate_per_point, discount_opt)
        st.subheader("Rental Breakdown")
        st.dataframe(df, use_container_width=True)
        st.success(f"Total Points: {pts:,} | Total Rent: ${rent:,}")
        if applied:
            st.success(f"Discount Applied: {30 if discount_opt=='within_60_days' else 25}% off points")
        st.download_button("Download", df.to_csv(index=False).encode(), f"{resort}_renter.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df, _ = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate_per_point, discount_opt)
            st.subheader("Comparison")
            st.dataframe(pivot, use_container_width=True)

            if not chart_df.empty:
                fig = px.bar(chart_df, x="Day", y="RentValue", color="Room Type", barmode="group",
                             title="Daily Rent (Non-Holiday)", text="RentValue")
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)
            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="RentValue", color="Room Type", barmode="group",
                             title="Holiday Rent", text="RentValue")
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

    st.plotly_chart(gantt, use_container_width=True)
