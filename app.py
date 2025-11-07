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
st.session_state.setdefault("data_cache", {})
st.session_state.setdefault("allow_renter_modifications", False)
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def display_room(key: str) -> str:
    if key in ROOM_VIEW_LEGEND:
        return ROOM_VIEW_LEGEND[key]
    if key.startswith("AP_"):
        return {"AP_Studio_MA": "AP Studio Mountain", "AP_1BR_MA": "AP 1BR Mountain",
                "AP_2BR_MA": "AP 2BR Mountain", "AP_2BR_MK": "AP 2BR Ocean"}[key]
    parts = key.split()
    view = parts[-1] if len(parts) > 1 and parts[-1] in ROOM_VIEW_LEGEND else ""
    return f"{parts[0]} {ROOM_VIEW_LEGEND.get(view, view)}" if view else key

def internal_room(display: str) -> str:
    rev = {v: k for k, v in ROOM_VIEW_LEGEND.items()}
    if display in rev:
        return rev[display]
    if display.startswith("AP "):
        return {"AP Studio Mountain": "AP_Studio_MA", "AP 1BR Mountain": "AP_1BR_MA",
                "AP 2BR Mountain": "AP_2BR_MA", "AP 2BR Ocean": "AP_2BR_MK"}[display]
    base, *view = display.rsplit(maxsplit=1)
    return f"{base} {rev.get(view[0], view[0])}" if view else display

def resolve_global(year: str, key: str) -> list:
    return data.get("global_dates", {}).get(year, {}).get(key, [])

# ----------------------------------------------------------------------
# Core data generation (cached + fixed holiday bug)
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
            if season != "Default Season":
                break

    # Points
    if holiday:
        src = REF_POINTS.get(resort, {}).get("Holiday Week", {}).get(holiday, {})
        for k, pts in src.items():
            entry[display_room(k)] = pts if is_h_start else 0
    else:
        cat = None
        cats = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
        avail = [c for c in cats if REF_POINTS.get(resort, {}).get(season, {}).get(c)]
        if avail:
            cat = ("Fri-Sat" if is_fri_sat and "Fri-Sat" in avail else
                   "Sun" if is_sun and "Sun" in avail else
                   "Mon-Thu" if not is_fri_sat and "Mon-Thu" in avail else
                   "Sun-Thu" if "Sun-Thu" in avail else avail[0])
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
# Gantt + Adjust Date Range
# ----------------------------------------------------------------------
def gantt_chart(resort: str, year: int):
    rows = []
    ys = str(year)
    for name, raw in HOLIDAY_WEEKS.get(resort, {}).get(ys, {}).items():
        if isinstance(raw, str) and raw.startswith("global:"):
            raw = resolve_global(ys, raw.split(":", 1)[1])
        if len(raw) >= 2:
            rows.append(dict(Task=name, Start=datetime.strptime(raw[0], "%Y-%m-%d").date(),
                             Finish=datetime.strptime(raw[1], "%Y-%m-%d").date(), Type="Holiday"))
    for s_name, ranges in SEASON_BLOCKS.get(resort, {}).get(ys, {}).items():
        for i, (s, e) in enumerate(ranges, 1):
            rows.append(dict(Task=f"{s_name} {i}", Start=datetime.strptime(s, "%Y-%m-%d").date(),
                             Finish=datetime.strptime(e, "%Y-%m-%d").date(), Type=s_name))
    df = pd.DataFrame(rows) if rows else pd.DataFrame({"Task": ["No Data"], "Start": [datetime.now().date()],
                                                       "Finish": [datetime.now().date() + timedelta(days=1)], "Type": ["No Data"]})
    colors = {t: {"Holiday": "rgb(255,99,71)", "Low Season": "rgb(135,206,250)", "High Season": "rgb(255,69,0)",
                 "Peak Season": "rgb(255,215,0)", "Shoulder": "rgb(50,205,50)", "No Data": "rgb(128,128,128)"}.get(t, "rgb(169,169,169)")
              for t in df["Type"].unique()}
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
# Discount (ALWAYS APPLY when selected)
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None) -> tuple[int, bool]:
    if not discount:
        return points, False
    if discount == "within_60_days":
        return math.floor(points * 0.7), True   # 30% off
    if discount == "within_30_days":
        return math.floor(points * 0.75), True  # 25% off
    return points, False

# ----------------------------------------------------------------------
# Breakdowns
# ----------------------------------------------------------------------
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows, tot_pts, tot_rent = [], 0, 0
    cur_h, h_end = None, None
    applied = False
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts, disc = apply_discount(pts, discount)
        applied |= disc
        rent = math.ceil(pts * rate)  # FULL rent
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

def owner_breakdown(resort, room, checkin, nights, disc_mul, inc_maint, inc_cap, inc_dep, rate, cap_per_pt, coc, life, salvage):
    rows, tot_pts, tot_cost = [], 0, 0
    totals = {"m": 0, "c": 0, "d": 0}
    dep_per_pt = (cap_per_pt - salvage) / life if inc_dep else 0
    cur_h, h_end = None, None
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
                row = {"Date": f"{cur_h} ({h_start:%b %d} - {h_end:%b %d, %Y})", "Day": "", "Points": dpts}
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
    return pd.DataFrame(rows), tot_pts, tot_cost, totals["m"], totals["c"], totals["d"]

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=1, key="mode")  # Owner default
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")

with st.expander("How It Works"):
    if user_mode == "Renter":
        if st.session_state.allow_renter_modifications:
            st.markdown("""
            - Default Rate: $0.52 (2025) / $0.60 (2026)
            - **Booked within 60 days** → 30% off points (Presidential)
            - **Booked within 30 days** → 25% off points (Executive)
            - **Discount always shown** for planning (rent uses full points)
            """)
        else:
            st.markdown("Standard rate: $0.52 (2025) / $0.60 (2026). Rent = Points × Rate")
    else:
        st.markdown("""
        - Maintenance + Capital Cost + Depreciation
        - Last-minute discount reduces points used
        - All costs based on discounted points
        """)

checkin = st.date_input("Check-in Date", min_value=datetime(2025,1,3).date(),
                        max_value=datetime(2026,12,31).date(), value=datetime(2026,6,12).date())
nights = st.number_input("Nights", 1, 30, 7)

rate_per_point = 0.52 if checkin.year == 2025 else 0.60
discount_opt = None
disc_mul = 1.0
cap_per_pt = 16.0
coc = 0.07
life = 15
salvage = 3.0
inc_maint = inc_cap = inc_dep = True

with st.sidebar:
    st.header("Settings")
    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price per Point ($)", 0.0, step=0.1, value=16.0)
        disc_lvl = st.selectbox("Discount", [0, 25, 30], format_func=lambda x: f"{x}% ({['None','Executive','Presidential'][x//25]})")
        disc_mul = 1 - disc_lvl/100
        inc_maint = st.checkbox("Maintenance", True)
        if inc_maint:
            rate_per_point = st.number_input("Rate per Point ($)", 0.0, step=0.01, value=rate_per_point)
        inc_cap = st.checkbox("Capital Cost", True)
        if inc_cap:
            coc = st.number_input("Cost of Capital (%)", 0.0, 100.0, 7.0, 0.1) / 100
        inc_dep = st.checkbox("Depreciation", True)
        if inc_dep:
            life = st.number_input("Useful Life (Years)", 1, value=15)
            salvage = st.number_input("Salvage Value ($)", 0.0, value=3.0, step=0.1)
    else:
        st.session_state.allow_renter_modifications = st.checkbox("More Options", st.session_state.allow_renter_modifications)
        if st.session_state.allow_renter_modifications:
            opt = st.radio("Option", ["Standard Rate", "Custom Rate", "60 Days (30% off)", "30 Days (25% off)"])
            if opt == "60 Days (30% off)":
                discount_opt = "within_60_days"
            elif opt == "30 Days (25% off)":
                discount_opt = "within_30_days"
            elif opt == "Custom Rate":
                rate_per_point = st.number_input("Rate ($)", 0.0, step=0.01, value=rate_per_point)
        else:
            discount_opt = None

# Resort & Room
st.subheader("Select Resort")
selected = st.multiselect("Filter by name", data["resorts_list"], default=None, max_selections=1, key="resort")
resort = selected[0] if selected else st.session_state.selected_resort
if resort != st.session_state.selected_resort:
    st.session_state.selected_resort = resort
    st.session_state.data_cache.clear()

st.subheader(f"{resort} Calculator")
year = str(checkin.year)

if st.session_state.get("last_resort") != resort or st.session_state.get("last_year") != year:
    st.session_state.data_cache.clear()
    for k in ("room_types", "disp_to_int"):
        st.session_state.pop(k, None)
    st.session_state.last_resort = resort
    st.session_state.last_year = year

if "room_types" not in st.session_state:
    entry, d2i = generate_data(resort, checkin)
    st.session_state.room_types = sorted(k for k in entry if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"})
    st.session_state.disp_to_int = d2i
room_types = st.session_state.room_types

room = st.selectbox("Room Type", room_types)
compare = st.multiselect("Compare With", [r for r in room_types if r != room])

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Adjusted to full holiday: {checkin_adj} → {(checkin_adj + timedelta(days=nights_adj-1))} ({nights_adj} nights)")

if st.button("Calculate"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Renter":
        df, pts, rent, disc_ap = renter_breakdown(resort, room, checkin_adj, nights_adj, rate_per_point, discount_opt)
        st.subheader("Stay Breakdown")
        st.dataframe(df, use_container_width=True)
        if discount_opt and disc_ap:
            st.success(f"Discount Applied: {30 if discount_opt=='within_60_days' else 25}% off points")
        st.success(f"Total Points: {pts} | Total Rent: ${rent}")
        st.download_button("Download CSV", df.to_csv(index=False).encode(), f"{resort}_renter.csv", "text/csv")
    else:
        df, pts, cost, m, c, d = owner_breakdown(resort, room, checkin_adj, nights_adj, disc_mul,
                                                 inc_maint, inc_cap, inc_dep, rate_per_point, cap_per_pt, coc, life, salvage)
        cols = ["Date", "Day", "Points"]
        if inc_maint or inc_cap or inc_dep:
            if inc_maint: cols.append("Maintenance")
            if inc_cap: cols.append("Capital Cost")
            if inc_dep: cols.append("Depreciation")
            cols.append("Total Cost")
        st.subheader("Cost Breakdown")
        st.dataframe(df[cols], use_container_width=True)
        st.success(f"Total Points: {pts} | Total Cost: ${cost}")
        st.download_button("Download CSV", df.to_csv(index=False).encode(), f"{resort}_owner.csv", "text/csv")

    if compare:
        st.write("### Comparison")
        st.info("Comparison charts coming soon — single room works perfectly!")

    st.plotly_chart(gantt, use_container_width=True)
