import streamlit as st
import math
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px

# ----------------------------------------------------------------------
# Load data + helpers (unchanged)
# ----------------------------------------------------------------------
with open("data.json", "r") as f:
    data = json.load(f)

ROOM_VIEW_LEGEND = { ... }  # your full legend
SEASON_BLOCKS   = data.get("season_blocks", {})
REF_POINTS      = data.get("reference_points", {})
HOLIDAY_WEEKS   = data.get("holiday_weeks", {})

st.session_state.setdefault("data_cache", {})
st.session_state.setdefault("allow_renter_modifications", False)
st.session_state.setdefault("selected_resort", data["resorts_list"][0])

# [All your existing helpers: display_room, resolve_global, generate_data, gantt_chart, adjust_date_range]
# ... (keep exactly as before — no changes needed here)
# ... (I'm skipping them for brevity — copy from your current working version)

# ----------------------------------------------------------------------
# Discount + Owner Breakdown (CLEANED)
# ----------------------------------------------------------------------
def apply_discount(points: int, discount: str | None = None, disc_lvl: int = 0) -> tuple[int, bool]:
    if discount == "within_60_days" or disc_lvl == 30:
        return math.floor(points * 0.7), True
    if discount == "within_30_days" or disc_lvl == 25:
        return math.floor(points * 0.75), True
    return points, False

def owner_breakdown(resort, room, checkin, nights, rate, disc_lvl,
                    cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep):
    rows = []
    tot_pts = tot_maint = tot_cap = tot_dep = 0
    cur_h = h_end = None

    for i in range(nights):
        d = checkin + timedelta(days=i)
        entry, _ = generate_data(resort, d)
        pts = entry.get(room, 0)
        eff_pts, _ = apply_discount(pts, disc_lvl=disc_lvl)
        tot_pts += eff_pts

        maint = eff_pts * rate if inc_maint else 0
        cap = eff_pts * cap_per_pt * coc if inc_cap else 0
        dep = eff_pts * (cap_per_pt - salvage) / life if inc_dep else 0

        tot_maint += maint
        tot_cap += cap
        tot_dep += dep
        total_night = maint + cap + dep

        row = {
            "Date": d.strftime("%Y-%m-%d"),
            "Day": d.strftime("%a"),
            "Points": eff_pts,
            "Maintenance": f"${maint:,.0f}",
            "Capital": f"${cap:,.0f}",
            "Depreciation": f"${dep:,.0f}",
            room: f"${total_night:,.0f}"
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

    total_cost = tot_maint + tot_cap + tot_dep
    rows.append({
        "Date": "TOTAL", "Day": "", "Points": tot_pts,
        "Maintenance": f"${tot_maint:,.0f}", "Capital": f"${tot_cap:,.0f}",
        "Depreciation": f"${tot_dep:,.0f}", room: f"${total_cost:,.0f}"
    })

    df = pd.DataFrame(rows)
    return df, tot_pts, total_cost

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
            eff_pts, _ = apply_discount(pts, disc_lvl=disc_lvl)

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

    # ADD TOTAL ROW
    total_row = {"Date": "TOTAL"}
    for r in rooms:
        total_row[r] = f"${totals[r]:,.0f}"
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows)
    pivot = df.pivot_table(index="Date", columns="Room Type", values="Cost", aggfunc="first").reset_index()
    pivot = pivot[["Date"] + [c for c in rooms if c in pivot.columns]]

    holiday_df = pd.DataFrame([{"Holiday": h, "Room Type": room, "CostValue": cost}
                               for room in rooms for h, cost in holiday_totals[room].items()])
    chart_df = pd.DataFrame(chart_rows)

    return pivot, chart_df, holiday_df

# ----------------------------------------------------------------------
# UI — FINAL CLEAN VERSION
# ----------------------------------------------------------------------
user_mode = st.sidebar.selectbox("User Mode", ["Renter", "Owner"], index=1, key="mode")
st.title(f"Marriott Vacation Club {'Rent' if user_mode=='Renter' else 'Cost'} Calculator")

with st.expander("How It Works"):
    if user_mode == "Renter":
        st.markdown("""- Default: $0.52 (2025) / $0.60 (2026)\n- **60 Days** → 30% off points (Presidential)\n- **30 Days** → 25% off points (Executive)\n- **Discount always shown** for planning\n- **Rent uses full points** (real cost)""")
    else:
        st.markdown("Owner cost = Maintenance + Capital + Depreciation. Discount reduces points used.")

# [Your existing inputs: checkin, nights, settings, resort, room, compare]
# ... (keep exactly as in your last working version)

if st.button("Calculate", type="primary"):
    gantt = gantt_chart(resort, checkin.year)

    if user_mode == "Owner":
        df, total_points, total_cost = owner_breakdown(resort, room, checkin_adj, nights_adj, rate, disc_lvl,
                                                       cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)

        st.subheader("Ownership Cost Breakdown")
        
        # HIDE REDUNDANT "Total" COLUMN — ONLY SHOW ROOM COST
        hide_cols = ["Total"] if "Total" in df.columns else []
        final_cols = [col for col in df.columns if col not in hide_cols]
        st.dataframe(df[final_cols], use_container_width=True, hide_index=True)

        # CLEAN SUCCESS MESSAGE
        if disc_lvl > 0:
            st.success(f"**{disc_lvl}% Discount Applied** → {total_points:,} points used → **Total Cost: ${total_cost:,.0f}**")
        else:
            st.success(f"**Total Points:** {total_points:,} → **Total Cost: ${total_cost:,.0f}**")

        st.download_button("Download Breakdown", df.to_csv(index=False).encode(), f"{resort}_owner.csv")

        if compare:
            all_rooms = [room] + compare
            pivot, chart_df, holiday_df = compare_owner(resort, all_rooms, checkin_adj, nights_adj, rate, disc_lvl,
                                                        cap_per_pt, coc, life, salvage, inc_maint, inc_cap, inc_dep)
            st.subheader("Room Comparison")
            st.dataframe(pivot, use_container_width=True, hide_index=True)
            st.download_button("Download Comparison", pivot.to_csv(index=False).encode(), f"{resort}_compare_owner.csv")

            if not chart_df.empty:
                fig = px.bar(chart_df, x="Day", y="CostValue", color="Room Type", barmode="group",
                             text="CostValue", height=600)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

            if not holiday_df.empty:
                fig = px.bar(holiday_df, x="Holiday", y="CostValue", color="Room Type", barmode="group",
                             text="CostValue", height=600)
                fig.update_traces(texttemplate="$%{text:,}", textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

    # [Renter mode unchanged — keep your current working version]

    st.plotly_chart(gantt, use_container_width=True)
