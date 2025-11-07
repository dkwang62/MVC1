import streamlit as st
import math
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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

st.session_state.setdefault("data_cache", {})
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

# ----------------------------------------------------------------------
# Core Functions (from your perfect code)
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

    colors = {"Holiday": "#d62728", "High Season": "#d62728", "Peak Season": "#ff7f0e",
              "Mid Season": "#2ca02c", "Low Season": "#1f77b4", "Info": "gray"}
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Task", color="Type",
                      color_discrete_map=colors, title=f"{resort} Seasons & Holidays ({year})", height=480)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(showlegend=True, legend_title="Type", font=dict(size=13))
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
                ranges.append((s, e, name))
    if ranges:
        s0 = min(s for s, _, _ in ranges)
        e0 = max(e for _, e, _ in ranges)
        return min(start, s0), (max(end, e0) - min(start, s0)).days + 1, True
    return start, nights, False

def apply_discount(points: int, discount: str | None = None) -> int:
    if discount == "within_60_days": return math.floor(points * 0.7)
    if discount == "within_30_days": return math.floor(points * 0.75)
    return points

# ----------------------------------------------------------------------
# RENTER: Breakdown + Comparison (EXACTLY LIKE YOUR CODE)
# ----------------------------------------------------------------------
def renter_breakdown(resort, room, checkin, nights, rate, discount):
    rows = []
    tot_pts = tot_rent = 0
    cur_h = h_end = None
    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts = apply_discount(pts, discount)
        rent = math.ceil(eff_pts * rate)
        tot_pts += eff_pts
        tot_rent += rent
        row = {"Date": d.strftime("%Y-%m-%d"), "Day": d.strftime("%a"), "Points": eff_pts, room: f"${rent:,}"}
        if entry.get("HolidayWeek"):
            if entry.get("HolidayWeekStart"):
                cur_h = entry["holiday_name"]
                h_start = entry["holiday_start"]
                h_end = entry["holiday_end"]
                row["Date"] = f"{cur_h} ({h_start:%b %d} - {h_end:%b %d, %Y})"
                row["Day"] = ""
            elif cur_h and d <= h_end:
                continue
        rows.append(row)
    rows.append({"Date": "TOTAL", "Day": "", "Points": tot_pts, room: f"${tot_rent:,}"})
    return pd.DataFrame(rows), tot_pts, tot_rent

def compare_renter(resort, rooms, checkin, nights, rate, discount):
    data_rows = []
    chart_rows = []
    total_rent = {r: 0 for r in rooms}
    holiday_totals = {r: {} for r in rooms}
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
            eff_pts = apply_discount(pts, discount)
            rent = math.ceil(eff_pts * rate)
            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    h_start = min(s for s, _, n in holiday_ranges if n == h_name)
                    h_end = max(e for _, e, n in holiday_ranges if n == h_name)
                    holiday_totals[room][h_name] = {"rent": rent, "start": h_start, "end": h_end}
                start_str = holiday_totals[room][h_name]["start"].strftime("%b %d")
                end_str = holiday_totals[room][h_name]["end"].strftime("%b %d, %Y")
                data_rows.append({"Date": f"{h_name} ({start_str} - {end_str})", "Room Type": room, "Rent": f"${rent:,}"})
                continue
            if not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Rent": f"${rent:,}"})
                total_rent[room] += rent
                chart_rows.append({"Day": d.strftime("%a"), "Room Type": room, "RentValue": rent})

    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for r in rooms:
        total_row[r] = f"${total_rent[r]:,}"
    data_rows.append(total_row)
    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Rent", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]
    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "RentValue": info["rent"]}
                               for room in rooms for h, info in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)
    return pivot, chart_df, holiday_df

# ----------------------------------------------------------------------
# UI — MALAYSIA 03:32 PM — DEPLOY NOW!
# ----------------------------------------------------------------------
st.set_page_config(page_title="Marriott Calculator", layout="wide")
st.title("Marriott Vacation Club Rent Calculator")

with st.expander("How Rent Is Calculated"):
    st.markdown("**Rent = Points × Rate** • 30% off within 60 days • 25% off within 30 days")

user_mode = st.sidebar.selectbox("Mode", ["Renter", "Owner"], index=0)
checkin = st.date_input("Check-in", value=datetime(2026,6,12).date())
nights = st.number_input("Nights", 1, 30, 7)

rate = 0.60
discount = None
with st.sidebar:
    st.header("Renter Settings")
    opt = st.radio("Rate", ["Standard $0.60", "60 Days (30% off)", "30 Days (25% off)", "Custom"])
    if "60 Days" in opt: discount = "within_60_days"
    elif "30 Days" in opt: discount = "within_30_days"
    elif "Custom" in opt: rate = st.number_input("Rate $/pt", 0.30, 2.00, 0.60, 0.01)

resort = st.selectbox("Resort", data["resorts_list"])
if st.session_state.get("last_resort") != resort:
    st.session_state.data_cache.clear()
    st.session_state.last_resort = resort

entry, _ = generate_data(resort, checkin)
room_types = sorted([k for k in entry.keys() if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"}])
room = st.selectbox("Main Room", room_types)
compare = st.multiselect("Compare With", [r for r in room_types if r != room], max_selections=3)

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Extended to full holiday week: {nights_adj} nights → {checkin_adj}")

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    # Single stay
    df, total_pts, total_rent = renter_breakdown(resort, room, checkin_adj, nights_adj, rate, discount)
    st.subheader("Rental Breakdown")
    st.dataframe(df[["Date", "Day", "Points", room]], use_container_width=True, hide_index=True)
    st.success(f"**Total: ${total_rent:,}** • {total_pts:,} pts")
    st.download_button("Download Breakdown", df.to_csv(index=False), f"{resort}_breakdown.csv")

    # Comparison
    if compare:
        all_rooms = [room] + compare
        pivot, chart_df, holiday_df = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate, discount)
        st.subheader("Room Comparison Table")
        st.dataframe(pivot, use_container_width=True, hide_index=True)
        st.download_button("Download Comparison", pivot.to_csv(index=False), f"{resort}_comparison.csv")

        # Daily Chart
        if not chart_df.empty:
            st.subheader("Daily Rental (Non-Holiday)")
            fig = go.Figure()
            colors = ["#1f77b4", "#17becf", "#ff7f0e", "#2ca02c"]
            for i, r in enumerate(all_rooms):
                data = chart_df[chart_df["Room Type"] == r]
                fig.add_trace(go.Bar(
                    x=data["Day"], y=data["RentValue"], name=r,
                    marker_color=colors[i % len(colors)],
                    text=data["RentValue"], textposition="inside",
                    textfont=dict(color="white", size=15, family="Arial Black")
                ))
            fig.update_layout(barmode="group", height=560,
                              xaxis=dict(categoryorder="array", categoryarray=["Fri","Sat","Sun","Mon","Tue","Wed","Thu"]),
                              yaxis=dict(title="Rent"), legend_title="Room Type")
            st.plotly_chart(fig, use_container_width=True)

        # Holiday Chart
        if not holiday_df.empty:
            st.subheader("Holiday Week Costs")
            fig = go.Figure()
            for i, r in enumerate(all_rooms):
                data = holiday_df[holiday_df["Room Type"] == r]
                fig.add_trace(go.Bar(
                    x=data["Holiday"], y=data["RentValue"], name=r,
                    marker_color=colors[i % len(colors)],
                    text=data["RentValue"], textposition="inside",
                    textfont=dict(color="white", size=15, family="Arial Black")
                ))
            fig.update_layout(barmode="group", height=480, legend_title="Room Type")
            st.plotly_chart(fig, use_container_width=True)

    st.plotly_chart(gantt, use_container_width=True)

# Ocean Background
st.markdown("""
<style>
    .stApp { background: linear-gradient(to bottom, #87CEEB 0%, #1E90FF 100%); }
    .css-1d391kg { background: rgba(255,255,255,0.97) !important; padding: 30px; border-radius: 20px; box-shadow: 0 12px 50px rgba(0,0,0,0.2); }
</style>
""", unsafe_allow_html=True)
