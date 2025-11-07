import streamlit as st
import math
import json
from datetime import datetime, timedelta
from collections import defaultdict
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
st.session_state.setdefault("allow_renter_modifications", False)
# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def display_room(key: str) -> str:
    if key in ROOM_VIEW_LEGEND:
        return ROOM_VIEW_LEGEND[key]
    if key.startswith("AP_"):
        return {"AP_Studio_MA": "AP Studio Mountain",
                "AP_1BR_MA": "AP 1BR Mountain",
                "AP_2BR_MA": "AP 2BR Mountain",
                "AP_2BR_MK": "AP 2BR Ocean"}[key]
    parts = key.split()
    view = parts[-1] if len(parts) > 1 and parts[-1] in ROOM_VIEW_LEGEND else ""
    return f"{parts[0]} {ROOM_VIEW_LEGEND.get(view, view)}" if view else key
def internal_room(display: str) -> str:
    rev = {v: k for k, v in ROOM_VIEW_LEGEND.items()}
    if display in rev:
        return rev[display]
    if display.startswith("AP "):
        return {"AP Studio Mountain": "AP_Studio_MA",
                "AP 1BR Mountain": "AP_1BR_MA",
                "AP 2BR Mountain": "AP_2BR_MA",
                "AP 2BR Ocean": "AP_2BR_MK"}[display]
    base, *view = display.rsplit(maxsplit=1)
    return f"{base} {rev.get(view[0], view[0])}" if view else display
def resolve_global(year: str, key: str) -> list:
    return data.get("global_dates", {}).get(year, {}).get(key, [])
# ----------------------------------------------------------------------
# Core data generation (cached)
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
    day_cat = "Fri-Sat" if is_fri_sat else ("Sun" if is_sun else "Mon-Thu")
    entry = {}
    season = "Default Season"
    holiday = None
    h_start = h_end = None
    is_h_start = False
    # Year-end hard-coded
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
                if datetime.strptime(rs, "%Y-%m-%d").date() <= date <= datetime.strptime(re, "%Y-%m-%d").date():
                    season = s_name
                    break
            if season != "Default Season":
                break
    # Points
    if holiday:
        src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {})
        # FIX: Loop first, then assign
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
    # Build disp_to_int from final src (after holiday/season resolution)
    final_src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {}) if holiday else src
    disp_to_int = {display_room(k): k for k in final_src}
    cache[ds] = (entry, disp_to_int)
    return entry, disp_to_int
# ----------------------------------------------------------------------
# Gantt
# ----------------------------------------------------------------------
def gantt_chart(resort: str, year: int):
    rows = []
    ys = str(year)
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(ys, {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(ys, raw.split(":", 1)[1])
        if len(raw) >= 2:
            rows.append(dict(Task=name,
                             Start=datetime.strptime(raw[0], "%Y-%m-%d").date(),
                             Finish=datetime.strptime(raw[1], "%Y-%m-%d").date(),
                             Type="Holiday"))
    for s_name, ranges in SEASON_BLOCKS.get(resort, {}).get(ys, {}).items():
        for i, (s, e) in enumerate(ranges, 1):
            rows.append(dict(Task=f"{s_name} {i}",
                             Start=datetime.strptime(s, "%Y-%m-%d").date(),
                             Finish=datetime.strptime(e, "%Y-%m-%d").date(),
                             Type=s_name))
    df = pd.DataFrame(rows) if rows else pd.DataFrame({
        "Task": ["No Data"], "Start": [datetime.now().date()],
        "Finish": [datetime.now().date() + timedelta(days=1)], "Type": ["No Data"]
    })
    colors = {t: {"Holiday": "rgb(255,99,71)", "Low Season": "rgb(135,206,250)",
                 "High Season": "rgb(255,69,0)", "Peak Season": "rgb(255,215,0)",
                 "Shoulder": "rgb(50,205,50)", "Peak": "rgb(255,69,0)",
                 "Summer": "rgb(255,165,0)", "Low": "rgb(70,130,180)",
                 "Mid Season": "rgb(60,179,113)", "No Data": "rgb(128,128,128)"}.get(t, "rgb(169,169,169)")
              for t in df["Type"].unique()}
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Task",
                      color="Type", color_discrete_map=colors,
                      title=f"{resort} Seasons & Holidays ({year})", height=600)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(xaxis_title="Date", yaxis_title="Period", showlegend=True)
    return fig
# ----------------------------------------------------------------------
# Discount helper — ALWAYS apply selected discount (for demo / planning)
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None, date: datetime.date) -> tuple[int, bool]:
    if not discount:
        return points, False
    # Ignore real date — always apply discount if user selected it
    if discount == "within_60_days":
        return math.floor(points * 0.7), True # 30% off
    if discount == "within_30_days":
        return math.floor(points * 0.75), True # 25% off
    return points, False
# ----------------------------------------------------------------------
# Single-stay breakdowns (unchanged)
# ----------------------------------------------------------------------
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows, tot_pts, tot_rent = [], 0, 0
    cur_h, h_end = None, None
    applied, disc_days = False, []
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts, disc = apply_discount(pts, discount, d)
        if disc:
            applied = True
            disc_days.append(d.strftime("%Y-%m-%d"))
        rent = math.ceil(pts * rate)
        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                rows.append({"Date": f"{cur_h} ({h_start:%b %d, %Y} - {h_end:%b %d, %Y})",
                             "Day": "", "Points": eff_pts, room: f"${rent}"})
                tot_pts += eff_pts
                tot_rent += rent
            elif cur_h and d <= h_end:
                continue
        else:
            cur_h = h_end = None
            rows.append({"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"),
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
    dep_per_pt = (cap_per_pt - salvage) / life if inc_dep else 0
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        dpts = math.floor(pts * disc_mul)
        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                row = {"Date": f"{cur_h} ({h_start:%b %d, %Y} - {h_end:%b %d, %Y})",
                       "Day": "", "Points": dpts}
                if inc_maint or inc_cap or inc_dep:
                    mc = math.ceil(dpts * rate) if inc_maint else 0
                    cc = math.ceil(dpts * cap_per_pt * coc) if inc_cap else 0
                    dc = math.ceil(dpts * dep_per_pt) if inc_dep else 0
                    day_cost = mc + cc + dc
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
            row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": dpts}
            if inc_maint or inc_cap or inc_dep:
                mc = math.ceil(dpts * rate) if inc_maint else 0
                cc = math.ceil(dpts * cap_per_pt * coc) if inc_cap else 0
                dc = math.ceil(dpts * dep_per_pt) if inc_dep else 0
                day_cost = mc + cc + dc
                if inc_maint: row["Maintenance"] = f"${mc}"; totals["m"] += mc
                if inc_cap: row["Capital Cost"] = f"${cc}"; totals["c"] += cc
                if inc_dep: row["Depreciation"] = f"${dc}"; totals["d"] += dc
                if day_cost: row["Total Cost"] = f"${day_cost}"; tot_cost += day_cost
            rows.append(row)
            tot_pts += dpts
    return (pd.DataFrame(rows), tot_pts, tot_cost,
            totals["m"], totals["c"], totals["d"])
# ----------------------------------------------------------------------
# COMPARISON helpers (new)
# ----------------------------------------------------------------------
def compare_renter(resort, rooms, checkin, nights, rate, discount):
    data_rows = []
    chart_rows = []
    total_rent = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}
    applied, disc_days = False, []
    # pre-compute holiday ranges that intersect the stay
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
            eff_pts, disc = apply_discount(pts, discount, d)
            if disc:
                applied = True
                disc_days.append(d.strftime("%Y-%m-%d"))
            rent = math.ceil(pts * rate)
            if is_holiday and is_h_start:
                # store holiday total once
                if h_name not in holiday_totals[room]:
                    h_start = min(s for s, _, n in holiday_ranges if n == h_name)
                    h_end = max(e for _, e, n in holiday_ranges if n == h_name)
                    holiday_totals[room][h_name] = {"rent": rent, "start": h_start, "end": h_end}
                start_str = holiday_totals[room][h_name]["start"].strftime("%b %d")
                end_str = holiday_totals[room][h_name]["end"].strftime("%b %d, %Y")
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                 "Room Type": room, "Rent": f"${rent}"})
                continue
            if not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"),
                                 "Room Type": room, "Rent": f"${rent}"})
                total_rent[room] += rent
                chart_rows.append({"Date": d, "Day": d.strftime("%a"),
                                  "Room Type": room, "RentValue": rent,
                                  "Holiday": "No"})
    # total non-holiday row
    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_rent[r]}"
    data_rows.append(total_row)
    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Rent", aggfunc="first")
    pivot = pivot.reset_index()[["Date"] + [c for c in rooms if c in pivot.columns]]
    # holiday chart data
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
    dep_per_pt = (cap_per_pt - salvage) / life if inc_dep else 0
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
                start_str = holiday_totals[room][h_name]["start"].strftime("%b %d")
                end_str = holiday_totals[room][h_name]["end"].strftime("%b %d, %Y")
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})",
                                 "Room Type": room, "Total Cost": f"${day_cost}"})
                continue
            if not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"),
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
# UI
# ----------------------------------------------------------------------
user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=0, key="mode")
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")
with st.expander("\U0001F334 How " + ("Rent" if user_mode=="Renter" else "Cost") + " Is Calculated"):
    if user_mode == "Renter":
        if st.session_state.allow_renter_modifications:
            st.markdown("""
            - Authored by Desmond Kwang https://www.facebook.com/dkwang62
            - Rental Rate per Point is based on MVC Abound maintenance fees or custom input
            - Default: $0.81 for 2025 stays (actual rate)
            - Default: $0.86 for 2026 stays (forecasted rate)
            - **Booked within 60 days**: 30% discount on points required (Presidential)
            - **Booked within 30 days**: 25% discount on points required (Executive)
            - Rent = (Points × Discount Multiplier) × Rate per Point
            """)
        else:
            st.markdown("""
            - Authored by Desmond Kwang https://www.facebook.com/dkwang62
            - Rental Rate per Point is based on MVC Abound maintenance fees
            - Default: $0.81 for 2025 stays (actual rate)
            - Default: $0.86 for 2026 stays (forecasted rate)
            - Rent = Points × Rate per Point
            - Note: Rate modifications are disabled by the owner.
            """)
    else:
        st.markdown("""
        - Authored by Desmond Kwang https://www.facebook.com/dkwang62
        - Cost of capital = Points × Purchase Price per Point × Cost of Capital %
        - Depreciation = Points × [(Purchase Price – Salvage) ÷ Useful Life]
        - Total cost = Maintenance + Capital Cost + Depreciation
        - If no cost components are selected, only points are displayed
        """)
checkin = st.date_input("Check-in Date",
                        min_value=datetime(2025,1,3).date(),
                        max_value=datetime(2026,12,31).date(),
                        value=datetime(2026,6,12).date())
nights = st.number_input("Number of Nights", 1, 30, 7)
rate_per_point = 0.81
discount_opt = None
disc_mul = 1.0
coc = 0.07
cap_per_pt = 16.0
life = 15
salvage = 3.0
inc_maint = inc_cap = inc_dep = True
with st.sidebar:
    st.header("Parameters")
    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price per Point ($)", 0.0, step=0.1, value=16.0)
        disc_lvl = st.selectbox("Last-Minute Discount",
                                 [0, 25, 30],
                                 format_func=lambda x: f"{x}% Discount ({['Ordinary','Executive','Presidential'][x//25]})")
        disc_mul = 1 - disc_lvl/100
        inc_maint = st.checkbox("Include Maintenance Cost", True)
        if inc_maint:
            rate_per_point = st.number_input("Maintenance Rate per Point ($)", 0.0, step=0.01, value=0.81)
        inc_cap = st.checkbox("Include Capital Cost", True)
        if inc_cap:
            coc = st.number_input("Cost of Capital (%)", 0.0, 100.0, 7.0, 0.1) / 100
        inc_dep = st.checkbox("Include Depreciation Cost", True)
        if inc_dep:
            life = st.number_input("Useful Life (Years)", 1, value=15)
            salvage = st.number_input("Salvage Value per Point ($)", 0.0, value=3.0, step=0.1)
        st.caption(f"Cost based on {disc_lvl}% discount.")
    else:
        st.session_state.allow_renter_modifications = st.checkbox(
            "More Options", st.session_state.allow_renter_modifications)
        if st.session_state.allow_renter_modifications:
            opt = st.radio("Rate Option",
                           ["Based on Maintenance Rate", "Custom Rate",
                            "Booked within 60 days", "Booked within 30 days"])
            base = 0.81 if checkin.year == 2025 else 0.86
            if opt == "Based on Maintenance Rate":
                rate_per_point, discount_opt = base, None
            elif opt == "Booked within 60 days":
                rate_per_point, discount_opt = base, "within_60_days"
            elif opt == "Booked within 30 days":
                rate_per_point, discount_opt = base, "within_30_days"
            else:
                rate_per_point = st.number_input("Custom Rate per Point ($)", 0.0, step=0.01, value=base)
                discount_opt = None
        else:
            rate_per_point = 0.81 if checkin.year == 2025 else 0.86
if user_mode == "Renter" and not st.session_state.allow_renter_modifications:
    rate_per_point = 0.81 if checkin.year == 2025 else 0.86
    discount_opt = None
# Resort & room selection
st.subheader("Select Resort")
st.session_state.setdefault("selected_resort",
    data["resorts_list"][0] if data["resorts_list"] else "")
selected = st.multiselect("Type to filter", data["resorts_list"],
                          default=None, max_selections=1, key="resort_sel")
resort = selected[0] if selected else st.session_state.selected_resort
if resort != st.session_state.selected_resort:
    st.session_state.selected_resort = resort
st.subheader(f"{resort} {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")
year = str(checkin.year)
# Cache clear
if (st.session_state.get("last_resort") != resort or
        st.session_state.get("last_year") != year):
    st.session_state.data_cache.clear()
    for k in ("room_types", "disp_to_int"):
        st.session_state.pop(k, None)
    st.session_state.last_resort = resort
    st.session_state.last_year = year
# Room list
if "room_types" not in st.session_state:
    entry, d2i = generate_data(resort, checkin)
    st.session_state.room_types = sorted(k for k in entry if k not in
                                         {"HolidayWeek","HolidayWeekStart",
                                          "holiday_name","holiday_start","holiday_end"})
    st.session_state.disp_to_int = d2i
room_types = st.session_state.room_types
room = st.selectbox("Select Room Type", room_types, key="room_sel")
compare = st.multiselect("Compare With Other Room Types",
                         [r for r in room_types if r != room])
# Adjust for full holiday weeks
def adjust_date_range(resort, start, nights):
    end = start + timedelta(days=nights-1)
    ranges = []
    if resort in data.get("holiday_weeks", {}):
        for name, raw in data["holiday_weeks"][resort].get(str(start.year), {}).items():
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
checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Adjusted to full holiday: {checkin_adj} to {(checkin_adj + timedelta(days=nights_adj-1))}"
            f" ({nights_adj} nights)")
# ----------------------------------------------------------------------
# Calculate
# ----------------------------------------------------------------------
if st.button("Calculate"):
    gantt = gantt_chart(resort, checkin.year)
    # ---------- single stay ----------
    if user_mode == "Renter":
        df, pts, rent, disc_ap, disc_days = renter_breakdown(
            resort, room, checkin_adj, nights_adj, rate_per_point, discount_opt)
        st.subheader(f"{resort} Stay Breakdown")
        st.dataframe(df, use_container_width=True)
        if st.session_state.allow_renter_modifications and discount_opt:
            if discount_opt:
                disc_pct = 30 if discount_opt == "within_60_days" else 25
                st.success(f"Discount Applied: {disc_pct}% off points "
                           f"({len(disc_days)} day(s): {', '.join(disc_days) if disc_days else 'All days'})")
            st.info("**Note:** Points shown are discounted; rent uses full points.")
        st.success(f"Total Points: {pts} Total Rent: ${rent}")
        st.download_button("Download CSV", df.to_csv(index=False).encode(),
                           f"{resort}_breakdown.csv", "text/csv")
    else:
        df, pts, cost, m_cost, c_cost, d_cost = owner_breakdown(
            resort, room, checkin_adj, nights_adj, disc_mul,
            inc_maint, inc_cap, inc_dep,
            rate_per_point, cap_per_pt, coc, life, salvage)
        cols = ["Date", "Day", "Points"]
        if inc_maint or inc_cap or inc_dep:
            if inc_maint: cols.append("Maintenance")
            if inc_cap: cols.append("Capital Cost")
            if inc_dep: cols.append("Depreciation")
            cols.append("Total Cost")
        st.subheader(f"{resort} Stay Breakdown")
        st.dataframe(df[cols], use_container_width=True)
        st.success(f"Total Points: {pts}")
        if cost: st.success(f"Total Cost: ${cost}")
        if inc_maint and m_cost: st.success(f"Maintenance: ${m_cost}")
        if inc_cap and c_cost: st.success(f"Capital Cost: ${c_cost}")
        if inc_dep and d_cost: st.success(f"Depreciation: ${d_cost}")
        st.download_button("Download CSV", df.to_csv(index=False).encode(),
                           f"{resort}_breakdown.csv", "text/csv")
    # ---------- comparison ----------
    if compare:
        all_rooms = [room] + compare
        if user_mode == "Renter":
            pivot, chart_df, holiday_df, disc_ap, disc_days = compare_renter(
                resort, all_rooms, checkin_adj, nights_adj, rate_per_point, discount_opt)
            st.subheader(f"{resort} Room-Type Comparison")
            st.dataframe(pivot, use_container_width=True)
            st.download_button("Download Comparison CSV", pivot.to_csv(index=False).encode(),
                               f"{resort}_comparison.csv", "text/csv")
            # non-holiday bar chart
            if not chart_df.empty:
                day_order = ["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]
                fig = px.bar(chart_df, x="Day", y="RentValue", color="Room Type",
                             barmode="group", text="RentValue", height=600,
                             category_orders={"Day": day_order})
                fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                fig.update_layout(legend_title_text="Room Type")
                st.plotly_chart(fig, use_container_width=True)
            # holiday bar chart
            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="RentValue", color="Room Type",
                             barmode="group", text="RentValue", height=600)
                fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)
        else: # Owner comparison
            pivot, chart_df, holiday_df = compare_owner(
                resort, all_rooms, checkin_adj, nights_adj, disc_mul,
                inc_maint, inc_cap, inc_dep,
                rate_per_point, cap_per_pt, coc, life, salvage)
            st.subheader(f"{resort} Room-Type Cost Comparison")
            st.dataframe(pivot, use_container_width=True)
            st.download_button("Download Comparison CSV", pivot.to_csv(index=False).encode(),
                               f"{resort}_comparison.csv", "text/csv")
            if not chart_df.empty:
                day_order = ["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]
                fig = px.bar(chart_df, x="Day", y="TotalCostValue", color="Room Type",
                             barmode="group", text="TotalCostValue", height=600,
                             category_orders={"Day": day_order})
                fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                fig.update_layout(legend_title_text="Room Type")
                st.plotly_chart(fig, use_container_width=True)
            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="TotalCostValue", color="Room Type",
                             barmode="group", text="TotalCostValue", height=600)
                fig.update_traces(texttemplate="$%{text:.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)
    # Gantt at the bottom
    st.plotly_chart(gantt, use_container_width=True)
