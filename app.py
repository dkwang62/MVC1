import streamlit as st
import math
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px

# ----------------------------------------------------------------------
# Load data + all your existing code up to compare_owner function
# ----------------------------------------------------------------------
# ... (keep everything exactly as in your last working version)
# ... including generate_data, gantt_chart, owner_breakdown, etc.

# ----------------------------------------------------------------------
# FIXED compare_owner — TOTAL ROW NOW ALWAYS APPEARS
# ----------------------------------------------------------------------
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
            eff_pts = apply_discount(pts, disc_lvl)
            maint = eff_pts * rate if inc_maint else 0
            cap = eff_pts * cap_per_pt * coc if inc_cap else 0
            dep = eff_pts * (cap_per_pt - salvage) / life if inc_dep else 0
            total_night = maint + cap + dep
            totals[room] += total_night

            if is_holiday and is_h_start:
                if h_name not in holiday_totals[room]:
                    holiday_totals[room][h_name] = total_night
                data_rows.append({"Date": h_name, "Room Type": room, "Cost": f"${total_night:,.0f}"})
            elif not is_holiday:
                data_rows.append({"Date": d.strftime("%Y-%m-%d"), "Room Type": room, "Cost": f"${total_night:,.0f}"})
                chart_rows.append({"Date": d, "Day": d.strftime("%a"), "Room Type": room, "CostValue": total_night})

    # ADD TOTAL ROW FIRST (so it appears in final table)
    total_row = {"Date": "TOTAL"}
    for r in rooms:
        total_row[r] = f"${totals[r]:,.0f}"
    data_rows.append(total_row)

    # BUILD PIVOT MANUALLY — TOTAL ROW GUARANTEED
    df = pd.DataFrame(data_rows)
    pivot_df = pd.DataFrame(columns=["Date"] + rooms)

    # Group by Date and collect values
    for date_val in df["Date"].unique():
        row = {"Date": date_val}
        subset = df[df["Date"] == date_val]
        for room in rooms:
            match = subset[subset["Room Type"] == room]
            if not match.empty:
                row[room] = match.iloc[0]["Cost"]
            else:
                row[room] = ""  # empty if no data
        pivot_df = pd.concat([pivot_df, pd.DataFrame([row])], ignore_index=True)

    # Ensure TOTAL is last
    pivot_df = pivot_df[pivot_df["Date"] != "TOTAL"]
    total_df = pd.DataFrame([total_row])
    pivot_df = pd.concat([pivot_df, total_df], ignore_index=True)

    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "CostValue": cost}
                               for room in rooms for h, cost in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)

    return pivot_df, chart_df, holiday_df

# ----------------------------------------------------------------------
# UI — ONLY THIS PART CHANGED (rest same as before)
# ----------------------------------------------------------------------
if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Owner":
        df, total_points, total_cost = owner_breakdown(resort, room, checkin_adj, nights_adj, rate, disc_lvl,
                                                       cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)

        st.subheader("Ownership Cost Breakdown")
        cols = ["Date", "Day", "Points", "Maintenance", "Capital", "Depreciation", room]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)

        msg = f"**Total Points Used:** {total_points:,} → **Total Cost: ${total_cost:,.0f}**"
        if disc_lvl > 0:
            msg = f"**{disc_lvl}% Discount Applied** → " + msg
        st.success(msg)

        st.download_button("Download Breakdown", df.to_csv(index=False), f"{resort}_owner.csv")

        if compare:
            all_rooms = [room] + compare
            pivot_df, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, rate, disc_lvl,
                                                           cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
            
            st.subheader("Room Comparison")
            st.dataframe(pivot_df, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison", pivot_df.to_csv(index=False), f"{resort}_compare.csv")

            if not chart_df.empty:
                fig = px.bar(chart_df, x="Day", y="CostValue", color="Room Type", barmode="group",
                             title="Daily Cost Comparison", height=500)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                fig.update_xaxes(categoryorder="array", categoryarray=["Fri","Sat","Sun","Mon","Tue","Wed","Thu"])
                st.plotly_chart(fig, use_container_width=True)

            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="CostValue", color="Room Type", barmode="group",
                             title="Holiday Cost Comparison", height=500)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

    st.plotly_chart(gantt, use_container_width=True)
