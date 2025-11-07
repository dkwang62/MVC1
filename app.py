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

ROOM_VIEW_LEGEND = { ... }  # your full legend
SEASON_BLOCKS   = data.get("season_blocks", {})
REF_POINTS      = data.get("reference_points", {})
HOLIDAY_WEEKS   = data.get("holiday_weeks", {})

# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
st.session_state.setdefault("data_cache", {})
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

# ----------------------------------------------------------------------
# Helpers + Core functions (unchanged)
# ----------------------------------------------------------------------
# [Keep all your existing: display_room, resolve_global, generate_data, gantt_chart, adjust_date_range]
# ... (copy from your base code above — they are perfect)

# ----------------------------------------------------------------------
# Discount
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None = None) -> tuple[int, bool]:
    if discount == "within_60_days":
        return math.floor(points * 0.7), True
    if discount == "within_30_days":
        return math.floor(points * 0.75), True
    return points, False

# ----------------------------------------------------------------------
# RENTER MODE - FULLY FIXED
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
        eff_pts, disc = apply_discount(pts, discount)
        applied |= disc
        rent = math.ceil(eff_pts * rate)  # use discounted points
        tot_pts += eff_pts
        tot_rent += rent

        row = {
            "Date": d.strftime("%Y-%m-%d"),
            "Day": d.strftime("%a"),
            "Points": eff_pts,
            room: f"${rent:,}"
        }

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

    rows.append({
        "Date": "TOTAL", "Day": "", "Points": tot_pts,
        room: f"${tot_rent:,}"
    })

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
            eff_pts, disc = apply_discount(pts, discount)
            applied |= disc
            rent = math.ceil(eff_pts * rate)
            totals[room] += rent

            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    holiday_totals[room][h_name] = rent
                data_rows.append({"Date": h_name, "Room Type": room, "Rent": f"${rent:,}"})
            elif not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Rent": f"${rent:,}"})
                chart_rows.append({"Date": d, "Day": d.strftime("%a"), "Room Type": room, "RentValue": rent})

    # TOTAL ROW
    total_row = {"Date": "TOTAL"}
    for r in rooms:
        total_row[r] = f"${totals[r]:,}"
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows)
    pivot = pd.pivot_table(df, index="Date", columns="Room Type", values="Rent", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]

    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "RentValue": cost}
                               for room in rooms for h, cost in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)

    return pivot, chart_df, holiday_df, applied

# ----------------------------------------------------------------------
# UI - NOW SUPPORTS RENTER SETTINGS + TOTAL ROWS
# ----------------------------------------------------------------------
st.title("Marriott Vacation Club Cost Calculator")

with st.expander("How It Works"):
    st.markdown("""
    **Owner Mode:** Cost = Maintenance + Capital + Depreciation  
    **Renter Mode:** Rent = Points × Rate (with optional 25%/30% discount)
    """)

user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=0)

checkin = st.date_input("Check-in", value=datetime(2026,6,12).date())
nights = st.number_input("Nights", 1, 30, 7)

# Default rate
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
        disc_lvl = st.selectbox("Owner Discount", [0, 25, 30], format_func=lambda x: f"{x}%")
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

    else:  # RENTER MODE
        st.markdown("### Renter Settings")
        rate_option = st.radio("Rate Option", ["Standard", "60 Days (30% off)", "30 Days (25% off)", "Custom Rate"])
        if "60 Days" in rate_option:
            discount = "within_60_days"
            rate = st.info("Using 30% discount on points")
        elif "30 Days" in rate_option:
            discount = "within_30_days"
            rate = st.info("Using 25% discount on points")
        elif "Custom" in rate_option:
            rate = st.number_input("Custom Rate $/point", 0.30, 2.00, rate, 0.01)
        else:
            discount = None

# Resort & Room
st.subheader("Resort")
resorts = st.multiselect("Select Resort", data["resorts_list"], default=[data["resorts_list"][0]], max_selections=1)
resort = resorts[0] if resorts else data["resorts_list"][0]

year = str(checkin.year)
if st.session_state.get("last_resort") != resort or st.session_state.get("last_year") != year:
    st.session_state.data_cache.clear()
    st.session_state.last_resort = resort
    st.session_state.last_year = year

entry, _ = generate_data(resort, checkin)
room_types = sorted([k for k in entry.keys() if k not in {"HolidayWeek","HolidayWeekStart","holiday_name","holiday_start","holiday_end"}])
room = st.selectbox("Room Type", room_types)
compare = st.multiselect("Compare With", [r for r in room_types if r != room])

checkin_adj, nights_adj, adjusted = adjust_date_range(resort, checkin, nights)
if adjusted:
    st.info(f"Extended to full holiday: {nights_adj} nights")

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Owner":
        df, total_points, total_cost = owner_breakdown(resort, room, checkin_adj, nights_adj, rate, disc_lvl,
                                                       cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
        st.subheader("Ownership Cost Breakdown")
        st.dataframe(df[["Date", "Day", "Points", "Maintenance", "Capital", "Depreciation", room]],
                     use_container_width=True, hide_index=True)

        msg = f"**Total Points:** {total_points:,} → **Total Cost: ${total_cost:,.0f}**"
        if disc_lvl > 0:
            msg = f"**{disc_lvl}% Discount Applied** → " + msg
        st.success(msg)
        st.download_button("Download", df.to_csv(index=False), f"{resort}_owner.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, rate, disc_lvl,
                                                        cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
            st.subheader("Room Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison", pivot.to_csv(index=False), f"{resort}_compare.csv")

            if not chart_df.empty:
                fig = px.bar(chart_df, x="Day", y="CostValue", color="Room Type", barmode="group",
                             text="CostValue", height=500)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

    else:  # RENTER MODE
        df, total_pts, total_rent, disc_applied = renter_breakdown(resort, room, checkin_adj, nights_adj, rate, discount)
        st.subheader("Rental Cost Breakdown")
        st.dataframe(df[["Date", "Day", "Points", room]], use_container_width=True, hide_index=True)

        msg = f"**Total Points:** {total_pts:,} → **Total Rent: ${total_rent:,}**"
        if disc_applied:
            disc_pct = "30%" if discount == "within_60_days" else "25%"
            msg = f"**{disc_pct} Discount Applied** → " + msg
        st.success(msg)
        st.download_button("Download", df.to_csv(index=False), f"{resort}_renter.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df, _ = compare_renter(resort, all_rooms, checkin_adj, nights_adj, rate, discount)
            st.subheader("Room Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison", pivot.to_csv(index=False), f"{resort}_renter_compare.csv")

            if not chart_df.empty:
                fig = px.bar(chart_df, x="Day", y="RentValue", color="Room Type", barmode="group",
                             text="RentValue", height=500)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

    st.plotly_chart(gantt, use_container_width=True)
