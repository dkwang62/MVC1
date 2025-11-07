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
st.session_state.setdefault("allow_renter_modifications", False)
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

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
            rows.append(dict(Task=name, Start=datetime.strptime(raw[0], "%Y-%m-%d").date(),
                             Finish=datetime.strptime(raw[1], "%Y-%m-%d").date(), Type="Holiday"))
    for s_name, ranges in SEASON_BLOCKS.get(resort, {}).get(ys, {}).items():
        for i, (s, e) in enumerate(ranges, 1):
            rows.append(dict(Task=f"{s_name} {i}", Start=datetime.strptime(s, "%Y-%m-%d").date(),
                             Finish=datetime.strptime(e, "%Y-%m-%d").date(), Type=s_name))
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
# Discount
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None = None, disc_lvl: int = 0) -> int:
    if discount == "within_60_days":
        return math.floor(points * 0.7)
    if discount == "within_30_days":
        return math.floor(points * 0.75)
    if disc_lvl == 30:
        return math.floor(points * 0.7)
    if disc_lvl == 25:
        return math.floor(points * 0.75)
    return points

# ----------------------------------------------------------------------
# Adjust date range
# ----------------------------------------------------------------------
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
# RENTER MODE
# ----------------------------------------------------------------------
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows = []
    tot_pts = tot_rent = 0
    cur_h = h_end = None
    applied = False

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts = apply_discount(pts, discount=discount)
        applied = applied or (eff_pts != pts)
        rent = math.ceil(eff_pts * rate)
        tot_pts += eff_pts
        tot_rent += rent

        row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff_pts, room: f"${rent:,}"}

        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                row["Date"] = f"{cur_h} ({h_start:%b %d, %Y} - {h_end:%b %d, %Y})"
                row["Day"] = ""
            elif cur_h and d <= h_end:
                continue

        rows.append(row)

    rows.append({"Date": "TOTAL", "Day": "", "Points": tot_pts, room: f"${tot_rent:,}"})
    return pd.DataFrame(rows), tot_pts, tot_rent, applied

def compare_renter(resort, rooms, checkin, nights, rate, discount):
    data_rows = []
    chart_rows = []
    totals = {r: 0 for r in rooms}
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
            eff_pts = apply_discount(pts, discount=discount)
            applied = applied or (eff_pts != pts)
            rent = math.ceil(eff_pts * rate)
            totals[room] += rent

            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    holiday_totals[room][h_name] = rent
                data_rows.append({"Date": h_name, "Room Type": room, "Rent": f"${rent:,}"})
            elif not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Rent": f"${rent:,}"})
                chart_rows.append({"Date": d, "Day": d.strftime("%a"), "Room Type": room, "RentValue": rent})

    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${totals[r]:,}"
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Rent", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]

    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "RentValue": cost}
                               for room in rooms for h, cost in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)

    return pivot, chart_df, holiday_df, applied

# ----------------------------------------------------------------------
# OWNER MODE
# ----------------------------------------------------------------------
def owner_breakdown(resort, room, checkin, nights, rate, disc_lvl,
                    cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep):
    rows = []
    tot_pts = tot_maint = tot_cap = tot_dep = 0
    cur_h = None

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts = apply_discount(pts, disc_lvl=disc_lvl)
        tot_pts += eff_pts

        maint = eff_pts * rate if inc_maint else 0
        cap = eff_pts * cap_per_pt * coc if inc_cap else 0
        dep = eff_pts * (cap_per_pt - salvage) / life if inc_dep else 0
        total_night = maint + cap + dep
        tot_maint += maint
        tot_cap += cap
        tot_dep += dep

        row = {
            "Date": d.strftime("%Y-%m-%d"),
            "Day": d.strftime("%a"),
            "Points": eff_pts,
            "Maintenance": f"${maint:,.0f}",
            "Capital Cost": f"${cap:,.0f}",
            "Depreciation": f"${dep:,.0f}",
            "Total Cost": f"${total_night:,.0f}"
        }

        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                row["Date"] = f"{cur_h} ({h_start:%b %d, %Y} - {h_end:%b %d, %Y})"
                row["Day"] = ""
            elif cur_h and d <= entry["holiday_end"]:
                continue

        rows.append(row)

    total_cost = tot_maint + tot_cap + tot_dep
    rows.append({
        "Date": "TOTAL", "Day": "", "Points": tot_pts,
        "Maintenance": f"${tot_maint:,.0f}",
        "Capital Cost": f"${tot_cap:,.0f}",
        "Depreciation": f"${tot_dep:,.0f}",
        "Total Cost": f"${total_cost:,.0f}"
    })

    return pd.DataFrame(rows), tot_pts, total_cost, tot_maint, tot_cap, tot_dep

def compare_owner(resort, rooms, checkin, nights, rate, disc_lvl,
                  cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep):
    data_rows = []
    chart_rows = []
    totals = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}

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
            eff_pts = apply_discount(pts, disc_lvl=disc_lvl)
            maint = eff_pts * rate if inc_maint else 0
            cap = eff_pts * cap_per_pt * coc if inc_cap else 0
            dep = eff_pts * (cap_per_pt - salvage) / life if inc_dep else 0
            total_night = maint + cap + dep
            totals[room] += total_night

            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    holiday_totals[room][h_name] = total_night
                data_rows.append({"Date": h_name, "Room Type": room, "Total Cost": f"${total_night:,.0f}"})
            elif not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Total Cost": f"${total_night:,.0f}"})
                chart_rows.append({"Date": d, "Day": d.strftime("%a"), "Room Type": room, "TotalCostValue": total_night})

    total_row = {"Date": "Total Cost (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${totals[r]:,.0f}"
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Total Cost", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]

    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "TotalCostValue": cost}
                               for room in rooms for h, cost in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)

    return pivot, chart_df, holiday_df

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=0, key="mode")
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")

with st.expander("How " + ("Rent" if user_mode=="Renter" else "Cost") + " Is Calculated"):
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

checkin = st.date_input("Check-in Date", value=datetime(2026,6,12).date())
nights = st.number_input("Number of Nights", 1, 30, 7)

rate = 0.81 if checkin.year == 2025 else 0.86
discount = None
disc_lvl = 0
cap_per_pt = 16.0
coc = 0.07
life = 15
salvage = 3.0
inc_maint = inc_cap = inc_dep = True

with st.sidebar:
    st.header("Parameters")
    if user_mode == "Owner":
        cap_per_pt = st.number_input("Purchase Price per Point ($)", 0.0, step=0.1, value=16.0)
        disc_lvl = st.selectbox("Last-Minute Discount", [0, 25, 30],
                                format_func=lambda x: f"{x}% Discount ({['Ordinary','Executive','Presidential'][x//25]})")
        inc_maint = st.checkbox("Include Maintenance Cost", True)
        if inc_maint:
            rate = st.number_input("Maintenance Rate per Point ($)", 0.0, step=0.01, value=rate)
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
            if opt == "Booked within 60 days":
                discount = "within_60_days"
            elif opt == "Booked within 30 days":
                discount = "within_30_days"
            elif opt == "Custom Rate":
                rate = st.number_input("Custom Rate per Point ($)", 0.0, step=0.01, value=rate)
        else:
            rate = 0.81 if checkin.year == 2025 else 0.86

st.subheader("Select Resort")
selected = st.multiselect("Type to filter", data["resorts_list"], default=[data["resorts_list"][0]], max_selections=1)
resort = selected[0] if selected else data["resorts_list"][0]

year = str(checkin.year)
if st.session_state.get("last_resort") != resort or st.session_state.get("last_year") != year:
    st.session_state.data_cache.clear()
    st.session_state.last_resort = resort
    st.session_state.last_year = year

entry, _ = generate_data(resort, checkin)
room_types = sorted([k for k in entry.keys() if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"}])
room = st.selectbox("Select Room Type", room_types)
compare = st.multiselect("Compare With Other Room Types", [r for r in room_types if r != room])

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Adjusted to full holiday: {checkin_adj} to {(checkin_adj + timedelta(days=nights_adj-1))} ({nights_adj} nights)")

st.subheader(f"{resort} {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    # Single stay
    if user_mode == "Renter":
        df, total_pts, total_rent, applied = renter_breakdown(resort, room, checkin_adj, nights_adj, rate, discount)
        st.subheader(f"{resort} Stay Breakdown")
        st.dataframe(df, use_container_width=True, hide_index=True)
        if applied:
            pct = "30%" if discount == "within_60_days" else "25%"
            st.success(f"Discount Applied: {pct} off points")
        st.success(f"Total Points: {total_pts}    Total Rent: ${total_rent:,}")
        st.download_button("Download CSV", df.to_csv(index=False), f"{resort}_breakdown.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df, _ = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate, discount)
            st.subheader(f"{resort} Room-Type Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison CSV", pivot.to_csv(index=False), f"{resort}_comparison.csv")

            if not chart_df.empty:
                day_order = ["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]
                fig = px.bar(chart_df, x="Day", y="RentValue", color="Room Type", barmode="group",
                             text="RentValue", height=600, category_orders={"Day": day_order})
                fig.update_traces(texttemplate="$%{text:,.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)

            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="RentValue", color="Room Type", barmode="group",
                             text="RentValue", height=600)
                fig.update_traces(texttemplate="$%{text:,.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)

    else:
        df, total_pts, total_cost, m_cost, c_cost, d_cost = owner_breakdown(
            resort, room, checkin_adj, nights_adj, rate, disc_lvl, cap_per_pt, coc, life, salvage,
            inc_maint, inc_cap, inc_dep)
        cols = ["Date", "Day", "Points"]
        if inc_maint: cols.append("Maintenance")
        if inc_cap: cols.append("Capital Cost")
        if inc_dep: cols.append("Depreciation")
        if inc_maint or inc_cap or inc_dep: cols.append("Total Cost")
        st.subheader(f"{resort} Stay Breakdown")
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
        st.success(f"Total Points: {total_pts}")
        if total_cost > 0: st.success(f"Total Cost: ${total_cost:,.0f}")
        if inc_maint and m_cost > 0: st.success(f"Maintenance: ${m_cost:,.0f}")
        if inc_cap and c_cost > 0: st.success(f"Capital Cost: ${c_cost:,.0f}")
        if inc_dep and d_cost > 0: st.success(f"Depreciation: ${d_cost:,.0f}")
        st.download_button("Download CSV", df.to_csv(index=False), f"{resort}_breakdown.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, rate, disc_lvl,
                                                        cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
            st.subheader(f"{resort} Room-Type Cost Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison CSV", pivot.to_csv(index=False), f"{resort}_comparison.csv")

            if not chart_df.empty:
                day_order = ["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]
                fig = px.bar(chart_df, x="Day", y="TotalCostValue", color="Room Type", barmode="group",
                             text="TotalCostValue", height=600, category_orders={"Day": day_order})
                fig.update_traces(texttemplate="$%{text:,.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)

            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="TotalCostValue", color="Room Type", barmode="group",
                             text="TotalCostValue", height=600)
                fig.update_traces(texttemplate="$%{text:,.0f}", textposition="auto")
                st.plotly_chart(fig, use_container_width=True)

    st.plotly_chart(gantt, use_container_width=True)
