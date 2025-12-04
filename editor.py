import streamlit as st
from common.ui import render_resort_card, render_resort_grid, render_page_header
from common.data import load_data
from functools import lru_cache
import json
import pandas as pd
import copy
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Any, Optional, Tuple, Set

# ----------------------------------------------------------------------
# CONSTANTS
# ----------------------------------------------------------------------
DEFAULT_YEARS = ["2025", "2026"]
BASE_YEAR_FOR_POINTS = "2025"

# ----------------------------------------------------------------------
# WIDGET KEY HELPER (RESORT-SCOPED)
# ----------------------------------------------------------------------
@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    """Build a unique Streamlit widget key scoped to a resort."""
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

# ----------------------------------------------------------------------
# SESSION STATE MANAGEMENT
# ----------------------------------------------------------------------
def initialize_session_state():
    defaults = {
        "refresh_trigger": False,
        "last_upload_sig": None,
        "data": None,
        "current_resort_id": None,
        "previous_resort_id": None,
        "working_resorts": {},
        "last_save_time": None,
        "delete_confirm": False,
        "download_verified": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            continue
        st.session_state[k] = v

def save_data():
    st.session_state.last_save_time = datetime.now()

def reset_state_for_new_file():
    for k in [
        "data",
        "current_resort_id",
        "previous_resort_id",
        "working_resorts",
        "delete_confirm",
        "last_save_time",
        "download_verified",
    ]:
        if k == "working_resorts":
            st.session_state[k] = {}
        elif k == "download_verified":
            st.session_state[k] = False
        else:
            st.session_state[k] = None

# ----------------------------------------------------------------------
# BASIC RESORT NAME / TIMEZONE HELPERS
# ----------------------------------------------------------------------
def detect_timezone_from_name(name: str) -> str:
    return "UTC"

def get_resort_full_name(resort_id: str, display_name: str) -> str:
    return display_name

# ----------------------------------------------------------------------
# OPTIMIZED HELPER FUNCTIONS
# ----------------------------------------------------------------------
@lru_cache(maxsize=128)
def get_years_from_data_cached(data_hash: int) -> Tuple[str, ...]:
    return tuple(sorted(get_years_from_data(st.session_state.data)))

def get_years_from_data(data: Dict[str, Any]) -> List[str]:
    years: Set[str] = set()
    gh = data.get("global_holidays", {})
    years.update(gh.keys())
    for r in data.get("resorts", []):
        years.update(str(y) for y in r.get("years", {}).keys())
    return sorted(years) if years else DEFAULT_YEARS

def safe_date(d: Optional[str], default: str = "2025-01-01") -> date:
    if not d or not isinstance(d, str):
        return datetime.strptime(default, "%Y-%m-%d").date()
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d").date()
    except ValueError:
        return datetime.strptime(default, "%Y-%m-%d").date()

def get_resort_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return data.get("resorts", [])

def find_resort_by_id(data: Dict[str, Any], rid: str) -> Optional[Dict[str, Any]]:
    return next((r for r in data.get("resorts", []) if r.get("id") == rid), None)

def find_resort_index(data: Dict[str, Any], rid: str) -> Optional[int]:
    return next(
        (i for i, r in enumerate(data.get("resorts", [])) if r.get("id") == rid), None
    )

def generate_resort_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", slug).strip("-") or "resort"

def generate_resort_code(name: str) -> str:
    parts = [p for p in name.replace("'", "").split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "RST"

def make_unique_resort_id(base_id: str, resorts: List[Dict[str, Any]]) -> str:
    existing = {r.get("id") for r in resorts}
    if base_id not in existing:
        return base_id
    i = 2
    while f"{base_id}-{i}" in existing:
        i += 1
    return f"{base_id}-{i}"

# ----------------------------------------------------------------------
# FILE OPERATIONS WITH ENHANCED UI (unchanged)
# ----------------------------------------------------------------------
# ... [all your file handling functions remain exactly as you wrote them] ...
# (kept 100% untouched)

def handle_file_upload():
    st.sidebar.markdown("### File to Memory")
    with st.sidebar.expander("Load", expanded=False):
        uploaded = st.file_uploader(
            "Choose JSON file",
            type="json",
            key="file_uploader",
            help="Upload your MVC data file",
        )
        if uploaded:
            size = getattr(uploaded, "size", 0)
            current_sig = f"{uploaded.name}:{size}"
            if current_sig != st.session_state.last_upload_sig:
                try:
                    raw_data = json.load(uploaded)
                    if "schema_version" not in raw_data or not raw_data.get("resorts"):
                        st.error("Invalid file format")
                        return
                    reset_state_for_new_file()
                    st.session_state.data = raw_data
                    st.session_state.last_upload_sig = current_sig
                    resorts_list = get_resort_list(raw_data)
                    st.success(f"Loaded {len(resorts_list)} resorts")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")

# ... [download, merge, verify functions unchanged] ...

# ----------------------------------------------------------------------
# WORKING RESORT MANAGEMENT (unchanged)
# ----------------------------------------------------------------------
def load_resort(data: Dict[str, Any], current_resort_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not current_resort_id:
        return None
    working_resorts = st.session_state.working_resorts
    if current_resort_id not in working_resorts:
        if resort_obj := find_resort_by_id(data, current_resort_id):
            working_resorts[current_resort_id] = copy.deepcopy(resort_obj)
    return working_resorts.get(current_resort_id)

# ----------------------------------------------------------------------
# SEASON MANAGEMENT – FIXED render_single_season_v2
# ----------------------------------------------------------------------
def render_single_season_v2(
    working: Dict[str, Any],
    year: str,
    season: Dict[str, Any],
    idx: int,
    resort_id: str,
):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**{sname}**")

    periods = season.get("periods", [])

    df_data = []
    for p in periods:
        df_data.append({
            "start": safe_date(p.get("start")),
            "end": safe_date(p.get("end"))
        })
    df = pd.DataFrame(df_data)

    edited_df = st.data_editor(
        df,
        key=rk(resort_id, "season_editor", year, idx),
        num_rows="dynamic",
        width="stretch",  # ← fixed deprecation
        column_config={
            "start": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End Date", format="YYYY-MM-DD", required=True),
        },
        hide_index=True
    )

    # ONLY update when actually changed → fixes double-entry bug
    if not edited_df.equals(df):
        new_periods = []
        for _, row in edited_df.iterrows():
            if pd.notna(row["start"]) and pd.notna(row["end"]):
                new_periods.append({
                    "start": row["start"].isoformat(),
                    "end": row["end"].isoformat()
                })
        season["periods"] = new_periods

    col_spacer, col_del = st.columns([4, 1])
    with col_del:
        if st.button(
            "Delete Season",
            key=rk(resort_id, "season_del_all_years", year, idx),
            width="stretch",
        ):
            # your existing delete logic
            for y_obj in working.get("years", {}).values():
                y_obj["seasons"] = [s for s in y_obj.get("seasons", []) if s.get("name") != sname]
            st.rerun()

# ----------------------------------------------------------------------
# MASTER POINTS EDITOR – also fixed (same safe pattern)
# ----------------------------------------------------------------------
def render_reference_points_editor_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown(
        "<div class='section-header'>Master Room Points</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Edit nightly points for each season using the table editor. Changes apply to all years automatically."
    )
    base_year = (
        BASE_YEAR_FOR_POINTS
        if BASE_YEAR_FOR_POINTS in years
        else (sorted(years)[0] if years else BASE_YEAR_FOR_POINTS)
    )
    base_year_obj = ensure_year_structure(working, base_year)
    seasons = base_year_obj.get("seasons", [])
    if not seasons:
        st.info(
            "No seasons defined yet. Add seasons in the Season Dates section first."
        )
        return

    canonical_rooms = get_all_room_types_for_resort(working)

    for s_idx, season in enumerate(seasons):
        with st.expander(
            f"{season.get('name', f'Season {s_idx+1}')}", expanded=True
        ):
            dc = season.setdefault("day_categories", {})
            if not dc:
                dc["sun_thu"] = {
                    "day_pattern": ["Sun", "Mon", "Tue", "Wed", "Thu"],
                    "room_points": {},
                }
                dc["fri_sat"] = {
                    "day_pattern": ["Fri", "Sat"],
                    "room_points": {},
                }
            for key, cat in dc.items():
                day_pattern = cat.setdefault("day_pattern", [])
                st.markdown(
                    f"**{key}** – {', '.join(day_pattern) if day_pattern else 'No days set'}"
                )
                room_points = cat.setdefault("room_points", {})
                rooms_here = canonical_rooms or sorted(room_points.keys())

                pts_data = []
                for room in rooms_here:
                    pts_data.append({
                        "Room Type": room,
                        "Points": int(room_points.get(room, 0) or 0)
                    })
                df_pts = pd.DataFrame(pts_data)

                edited_df = st.data_editor(
                    df_pts,
                    key=rk(resort_id, "master_rp_editor", base_year, s_idx, key),
                    width="stretch",  # ← fixed
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )

                # ONLY write back if changed → fixes double-entry bug
                if not edited_df.empty and not edited_df.equals(df_pts):
                    new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                    cat["room_points"] = new_rp

    # ... rest of your room type management unchanged ...

# ----------------------------------------------------------------------
# HOLIDAY MANAGEMENT – FIXED (the main culprit)
# ----------------------------------------------------------------------
def render_holiday_management_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown(
        "<div class='section-header'>Holiday Management</div>",
        unsafe_allow_html=True,
    )
    base_year = (
        BASE_YEAR_FOR_POINTS
        if BASE_YEAR_FOR_POINTS in years
        else (sorted(years)[0] if years else BASE_YEAR_FOR_POINTS)
    )

    # ... your holiday list/add/rename UI unchanged ...

    st.markdown("---")
    st.markdown("**Master Holiday Points**")
    st.caption(
        "Edit holiday room points once. Applied to all years automatically."
    )
    base_year_obj = ensure_year_structure(working, base_year)
    base_holidays = base_year_obj.get("holidays", [])
    if not base_holidays:
        st.info(
            f"No holidays defined in {base_year}. Add holidays above first."
        )
    else:
        all_rooms = get_all_room_types_for_resort(working)
        for h_idx, h in enumerate(base_holidays):
            disp_name = h.get("name", f"Holiday {h_idx+1}")
            key = (h.get("global_reference") or h.get("name") or "").strip()
            with st.expander(f"{disp_name}", expanded=False):
                st.caption(f"Reference key: {key}")
                rp = h.setdefault("room_points", {})
                rooms_here = sorted(all_rooms or rp.keys())

                pts_data = []
                for room in rooms_here:
                    pts_data.append({
                        "Room Type": room,
                        "Points": int(rp.get(room, 0) or 0)
                    })
                df_pts = pd.DataFrame(pts_data)

                edited_df = st.data_editor(
                    df_pts,
                    key=rk(resort_id, "holiday_master_rp_editor", base_year, h_idx),
                    width="stretch",  # ← fixed
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )

                # ONLY update when changed → fixes double-entry bug
                if not edited_df.empty and not edited_df.equals(df_pts):
                    new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                    h["room_points"] = new_rp

    sync_holiday_room_points_across_years(working, base_year=base_year)

# ----------------------------------------------------------------------
# ALL OTHER FUNCTIONS ARE 100% UNTOUCHED
# ----------------------------------------------------------------------
# Your original functions below remain exactly as you wrote them:
# - ensure_year_structure
# - get_all_season_names_for_resort
# - delete_season_across_years
# - render_season_dates_editor_v2
# - get_all_room_types_for_resort
# - sync functions
# - validation
# - gantt
# - global settings
# - main()
# etc.

# Just make sure in your main() you call the editors like this:
# with tab2:
#     render_gantt_charts_v2(...)
#     render_season_dates_editor_v2(...)
# with tab3:
#     render_reference_points_editor_v2(...)
# with tab4:
#     render_holiday_management_v2(...)

# ----------------------------------------------------------------------
# Keep your original main() and if __name__ == "__main__": block unchanged
# ----------------------------------------------------------------------

    st.markdown("---")
    st.markdown("**💰 Master Holiday Points**")
    st.caption(
        "Edit holiday room points once. Applied to all years automatically."
    )

    base_year_obj = ensure_year_structure(working, base_year)
    base_holidays = base_year_obj.get("holidays", [])
    if not base_holidays:
        st.info(
            f"💡 No holidays defined in {base_year}. Add holidays above first."
        )
    else:
        all_rooms = get_all_room_types_for_resort(working)
        for h_idx, h in enumerate(base_holidays):
            disp_name = h.get("name", f"Holiday {h_idx+1}")
            key = (h.get("global_reference") or h.get("name") or "").strip()
            with st.expander(f"🎊 {disp_name}", expanded=False):
                st.caption(f"Reference key: {key}")
                rp = h.setdefault("room_points", {})
                rooms_here = sorted(all_rooms or rp.keys())
                
                # --- Use Data Editor for Points ---
                pts_data = []
                for room in rooms_here:
                    pts_data.append({
                        "Room Type": room,
                        "Points": int(rp.get(room, 0) or 0)
                    })
                
                df_pts = pd.DataFrame(pts_data)
                
                edited_df = st.data_editor(
                    df_pts,
                    key=rk(resort_id, "holiday_master_rp_editor", base_year, h_idx),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )
                
                if not edited_df.empty:
                    new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                    h["room_points"] = new_rp
                # ------------------------------

    sync_holiday_room_points_across_years(working, base_year=base_year)


# ----------------------------------------------------------------------
# RESORT SUMMARY
# ----------------------------------------------------------------------
def compute_weekly_totals_for_season_v2(
    season: Dict[str, Any], room_types: List[str]
) -> Tuple[Dict[str, int], bool]:
    weekly_totals = {room: 0 for room in room_types}
    any_data = False
    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

    for cat in season.get("day_categories", {}).values():
        pattern = cat.get("day_pattern", [])
        if not (rp := cat.get("room_points", {})) or not isinstance(rp, dict):
            continue

        n_days = len([d for d in pattern if d in valid_days])
        if n_days > 0:
            for room in room_types:
                if room in rp and rp[room] is not None:
                    weekly_totals[room] += int(rp[room]) * n_days
                    any_data = True

    return weekly_totals, any_data


def render_resort_summary_v2(working: Dict[str, Any]):
    st.markdown(
        "<div class='section-header'>📊 Resort Summary</div>",
        unsafe_allow_html=True,
    )

    resort_years = working.get("years", {})
    if not resort_years:
        st.info("💡 No data available yet")
        return

    sorted_years = sorted(
        resort_years.keys(), key=lambda y: int(y) if str(y).isdigit() else 0
    )
    ref_year = next(
        (y for y in sorted_years if resort_years[y].get("seasons")), None
    )
    if not ref_year:
        st.info("💡 No seasons defined yet")
        return

    room_types = get_all_room_types_for_resort(working)
    if not room_types:
        st.info("💡 No room types defined yet")
        return

    rows = []
    for season in resort_years[ref_year].get("seasons", []):
        sname = season.get("name", "").strip() or "(Unnamed)"
        weekly_totals, any_data = compute_weekly_totals_for_season_v2(
            season, room_types
        )
        if any_data:
            row = {"Season": sname}
            row.update(
                {
                    room: (total if total else "—")
                    for room, total in weekly_totals.items()
                }
            )
            rows.append(row)

    last_holiday_year = None
    for y in reversed(sorted_years):
        if resort_years.get(y, {}).get("holidays"):
            last_holiday_year = y
            break

    if last_holiday_year:
        for h in resort_years[last_holiday_year].get("holidays", []):
            hname = h.get("name", "").strip() or "(Unnamed)"
            rp = h.get("room_points", {}) or {}
            row = {"Season": f"Holiday – {hname}"}
            for room in room_types:
                val = rp.get(room)
                row[room] = (
                    val
                    if isinstance(val, (int, float)) and val not in (0, None)
                    else "—"
                )
            rows.append(row)

    if rows:
        df = pd.DataFrame(rows, columns=["Season"] + room_types)
        st.caption(
            "Season rows show 7-night totals computed from nightly rates. "
            "Holiday rows show weekly totals directly from holiday points (no extra calculations)."
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("💡 No rate or holiday data available")


# ----------------------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------------------
def validate_resort_data_v2(
    working: Dict[str, Any], data: Dict[str, Any], years: List[str]
) -> List[str]:
    issues = []
    all_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    all_rooms = set(get_all_room_types_for_resort(working))
    global_holidays = data.get("global_holidays", {})

    for year in years:
        year_obj = working.get("years", {}).get(year, {})

        # Day pattern coverage
        for season in year_obj.get("seasons", []):
            sname = season.get("name", "(Unnamed)")
            covered_days = set()
            for cat in season.get("day_categories", {}).values():
                pattern_days = {
                    d for d in cat.get("day_pattern", []) if d in all_days
                }
                if overlap := covered_days & pattern_days:
                    issues.append(
                        f"[{year}] Season '{sname}' has overlapping days: {', '.join(sorted(overlap))}"
                    )
                covered_days |= pattern_days
            if missing := all_days - covered_days:
                issues.append(
                    f"[{year}] Season '{sname}' missing days: {', '.join(sorted(missing))}"
                )

            if all_rooms:
                season_rooms = set()
                for cat in season.get("day_categories", {}).values():
                    if isinstance(rp := cat.get("room_points", {}), dict):
                        season_rooms |= set(rp.keys())
                if missing_rooms := all_rooms - season_rooms:
                    issues.append(
                        f"[{year}] Season '{sname}' missing rooms: {', '.join(sorted(missing_rooms))}"
                    )

        # Holiday references and room coverage
        for h in year_obj.get("holidays", []):
            hname = h.get("name", "(Unnamed)")
            global_ref = h.get("global_reference") or hname
            if global_ref not in global_holidays.get(year, {}):
                issues.append(
                    f"[{year}] Holiday '{hname}' references missing global holiday '{global_ref}'"
                )
            if all_rooms and isinstance(
                rp := h.get("room_points", {}), dict
            ):
                if missing_rooms := all_rooms - set(rp.keys()):
                    issues.append(
                        f"[{year}] Holiday '{hname}' missing rooms: {', '.join(sorted(missing_rooms))}"
                    )

        # GAP detection
        try:
            year_start = date(int(year), 1, 1)
            year_end = date(int(year), 12, 31)
        except Exception:
            continue

        covered_ranges = []
        gh_year = global_holidays.get(year, {})

        # Season ranges
        for season in year_obj.get("seasons", []):
            for period in season.get("periods", []):
                try:
                    start = datetime.strptime(
                        period.get("start", ""), "%Y-%m-%d"
                    ).date()
                    end = datetime.strptime(
                        period.get("end", ""), "%Y-%m-%d"
                    ).date()
                    if start <= end:
                        covered_ranges.append(
                            (
                                start,
                                end,
                                f"Season '{season.get('name', '(Unnamed)')}'",
                            )
                        )
                except Exception:
                    continue

        # Holiday ranges (from global calendar)
        for h in year_obj.get("holidays", []):
            global_ref = h.get("global_reference") or h.get("name")
            if gh := gh_year.get(global_ref):
                try:
                    start = datetime.strptime(
                        gh.get("start_date", ""), "%Y-%m-%d"
                    ).date()
                    end = datetime.strptime(
                        gh.get("end_date", ""), "%Y-%m-%d"
                    ).date()
                    if start <= end:
                        covered_ranges.append(
                            (
                                start,
                                end,
                                f"Holiday '{h.get('name', '(Unnamed)')}'",
                            )
                        )
                except Exception:
                    continue

        covered_ranges.sort(key=lambda x: x[0])

        if covered_ranges:
            if covered_ranges[0][0] > year_start:
                gap_days = (covered_ranges[0][0] - year_start).days
                issues.append(
                    f"[{year}] GAP: {gap_days} days from {year_start} to "
                    f"{covered_ranges[0][0] - timedelta(days=1)} (before first range)"
                )

            for i in range(len(covered_ranges) - 1):
                current_end = covered_ranges[i][1]
                next_start = covered_ranges[i + 1][0]
                if next_start > current_end + timedelta(days=1):
                    gap_start = current_end + timedelta(days=1)
                    gap_end = next_start - timedelta(days=1)
                    gap_days = (next_start - current_end - timedelta(days=1)).days
                    issues.append(
                        f"[{year}] GAP: {gap_days} days from {gap_start} to {gap_end} "
                        f"(between {covered_ranges[i][2]} and {covered_ranges[i+1][2]})"
                    )

            if covered_ranges[-1][1] < year_end:
                gap_days = (year_end - covered_ranges[-1][1]).days
                issues.append(
                    f"[{year}] GAP: {gap_days} days from "
                    f"{covered_ranges[-1][1] + timedelta(days=1)} to {year_end} (after last range)"
                )
        else:
            issues.append(
                f"[{year}] No date ranges defined (entire year is uncovered)"
            )

    return issues


def render_validation_panel_v2(
    working: Dict[str, Any], data: Dict[str, Any], years: List[str]
):
    with st.expander("🔍 Data Validation", expanded=False):
        issues = validate_resort_data_v2(working, data, years)
        if issues:
            st.error(f"**Found {len(issues)} issue(s):**")
            for issue in issues:
                st.write(f"• {issue}")
        else:
            st.success("✅ All validation checks passed!")


# ----------------------------------------------------------------------
# WORKING RESORT LOADER
# ----------------------------------------------------------------------
def load_resort(
    data: Dict[str, Any], current_resort_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not current_resort_id:
        return None

    working_resorts = st.session_state.working_resorts
    if current_resort_id not in working_resorts:
        if resort_obj := find_resort_by_id(data, current_resort_id):
            working_resorts[current_resort_id] = copy.deepcopy(resort_obj)

    working = working_resorts.get(current_resort_id)
    if not working:
        return None
    return working


# ----------------------------------------------------------------------
# GANTT CHART (delegates to common.charts)
# ----------------------------------------------------------------------
def render_gantt_charts_v2(
    working: Dict[str, Any], years: List[str], data: Dict[str, Any]
):
    from common.charts import create_gantt_chart_from_working

    st.markdown(
        "<div class='section-header'>📊 Visual Timeline</div>",
        unsafe_allow_html=True,
    )
    tabs = st.tabs([f"📅 {year}" for year in years])
    for tab, year in zip(tabs, years):
        with tab:
            fig = create_gantt_chart_from_working(
                working,
                year,
                data,
                height=max(
                    400,
                    len(
                        working.get("years", {})
                        .get(year, {})
                        .get("seasons", [])
                    )
                    * 35
                    + 150,
                ),
            )
            st.plotly_chart(fig, use_container_width=True)


# ----------------------------------------------------------------------
# GLOBAL SETTINGS
# ----------------------------------------------------------------------
def render_maintenance_fees_v2(data: Dict[str, Any]):
    rates = (
        data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
    )
    st.caption("Define maintenance fee rates per point for each year")
    for year in sorted(rates.keys()):
        current_rate = float(rates[year])
        new_rate = st.number_input(
            f"💵 {year}",
            value=current_rate,
            step=0.01,
            format="%.4f",
            key=f"mf_{year}",
        )
        if new_rate != current_rate:
            rates[year] = float(new_rate)
            save_data()


def render_global_holiday_dates_editor_v2(
    data: Dict[str, Any], years: List[str]
):
    global_holidays = data.setdefault("global_holidays", {})
    for year in years:
        st.markdown(f"**📆 {year}**")
        holidays = global_holidays.setdefault(year, {})
        for i, (name, obj) in enumerate(list(holidays.items())):
            with st.expander(f"🎉 {name}", expanded=False):
                col1, col2, col3 = st.columns([3, 3, 1])
                with col1:
                    new_start = st.date_input(
                        "Start date",
                        safe_date(obj.get("start_date") or f"{year}-01-01"),
                        key=f"ghs_{year}_{i}",
                    )
                with col2:
                    new_end = st.date_input(
                        "End date",
                        safe_date(obj.get("end_date") or f"{year}-01-07"),
                        key=f"ghe_{year}_{i}",
                    )
                with col3:
                    if st.button("🗑️", key=f"ghd_{year}_{i}"):
                        del holidays[name]
                        save_data()
                        st.rerun()

                obj["start_date"] = new_start.isoformat()
                obj["end_date"] = new_end.isoformat()
                new_type = st.text_input(
                    "Type",
                    value=obj.get("type", "other"),
                    key=f"ght_{year}_{i}",
                )
                obj["type"] = new_type or "other"
                regions_str = ", ".join(obj.get("regions", []))
                new_regions = st.text_input(
                    "Regions (comma-separated)",
                    value=regions_str,
                    key=f"ghr_{year}_{i}",
                )
                obj["regions"] = [
                    r.strip() for r in new_regions.split(",") if r.strip()
                ]
                save_data()

        st.markdown("---")
        col1, col2, col3 = st.columns([3, 2, 2])
        with col1:
            new_name = st.text_input(
                "New holiday name",
                key=f"gh_new_name_{year}",
                placeholder="e.g., New Year",
            )
        with col2:
            new_start = st.date_input(
                "Start",
                datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date(),
                key=f"gh_new_start_{year}",
            )
        with col3:
            new_end = st.date_input(
                "End",
                datetime.strptime(f"{year}-01-07", "%Y-%m-%d").date(),
                key=f"gh_new_end_{year}",
            )
        if (
            st.button(
                "➕ Add Global Holiday",
                key=f"gh_add_{year}",
                use_container_width=True,
            )
            and new_name
            and new_name not in holidays
        ):
            holidays[new_name] = {
                "start_date": new_start.isoformat(),
                "end_date": new_end.isoformat(),
                "type": "other",
                "regions": ["global"],
            }
            save_data()
            st.rerun()


def render_global_settings_v2(data: Dict[str, Any], years: List[str]):
    st.markdown(
        "<div class='section-header'>⚙️ Global Configuration</div>",
        unsafe_allow_html=True,
    )
    with st.expander("💰 Maintenance Fee Rates", expanded=False):
        render_maintenance_fees_v2(data)
    with st.expander("🎅 Global Holiday Calendar", expanded=False):
        render_global_holiday_dates_editor_v2(data, years)


# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------
def main():
    # Page config is now handled centrally in common.ui.setup_page() via app.py
    initialize_session_state()

    # Auto-load data file (optional)
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                raw_data = json.load(f)
                if "schema_version" in raw_data and "resorts" in raw_data:
                    st.session_state.data = raw_data
                    st.toast(
                        f"✅ Auto-loaded {len(raw_data.get('resorts', []))} resorts",
                        icon="✅",
                    )
        except FileNotFoundError:
            pass
        except Exception as e:
            st.toast(f"⚠️ Auto-load error: {str(e)}", icon="⚠️")

    # Sidebar
    with st.sidebar:
        st.divider()
    with st.expander("ℹ️ How to create your own personalised resort dataset", expanded=False):
        st.markdown(
            """
If you want a wider set of resorts or need to fix errors in the data without waiting for the author to update it, you can make the changes yourself. The Editor allows you to modify the default dataset in memory and create your own personalised JSON file to reuse each time you open the app. You may also merge resorts from your personalised file into the dataset currently in memory.

Restarting the app resets everything to the default dataset, so be sure to save and download the in-memory data to preserve your edits. To confirm your saved file matches what is in memory, use the verification step by loading your personalised JSON file."""
        )
            
        handle_file_upload()

        if st.session_state.data:
            # st.markdown(
            #    "<div style='margin: 20px 0;'></div>", unsafe_allow_html=True
            # )
            # Move merge logic to File to Memory
            handle_merge_from_another_file_v2(st.session_state.data)

            create_download_button_v2(st.session_state.data)
            handle_file_verification()

    
    # Main content
    
    render_page_header(
    "Edit",
    "Creating Your Data File",
    icon="🏨",
    badge_color="#EF4444"  # Adjust to match the red color in the image, e.g., #DC2626 or #EF4444
)

    if not st.session_state.data:
        st.markdown(
            """
            <div class='info-box'>
                <h3>👋 Welcome!</h3>
                <p>Load json file from the sidebar to begin editing resort data.</p>
            </div>
        """,
            unsafe_allow_html=True,
        )
        return

    data = st.session_state.data
    resorts = get_resort_list(data)
    years = get_years_from_data(data)

    current_resort_id = st.session_state.current_resort_id
    previous_resort_id = st.session_state.previous_resort_id

    # Shared grid (column-first, West → East) from common.ui
    render_resort_grid(resorts, current_resort_id)

    handle_resort_switch_v2(data, current_resort_id, previous_resort_id)

    # Working resort
    working = load_resort(data, current_resort_id)

    if working:
        resort_name = (
            working.get("resort_name")
            or working.get("display_name")
            or current_resort_id
        )
        timezone = working.get("timezone", "UTC")
        address = working.get("address", "No address provided")

        # Shared resort card from common.ui
        render_resort_card(resort_name, timezone, address)

        render_validation_panel_v2(working, data, years)
        render_save_button_v2(data, working, current_resort_id)
        handle_resort_creation_v2(data, current_resort_id)
        handle_resort_deletion_v2(data, current_resort_id)

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            [
                "📊 Overview",
                "📅 Season Dates",
                "💰 Room Points",
                "🎄 Holidays",
                "📈 Points Summary",
            ]
        )

        with tab1:
            edit_resort_basics(working, current_resort_id)
        with tab2:
            render_gantt_charts_v2(working, years, data)
            render_season_dates_editor_v2(working, years, current_resort_id)
        with tab3:
            render_reference_points_editor_v2(working, years, current_resort_id)
        with tab4:
            render_holiday_management_v2(working, years, current_resort_id)
        with tab5:
            render_resort_summary_v2(working)

    st.markdown("---")
    render_global_settings_v2(data, years)
    st.markdown(
        """
        <div class='success-box'>
            <p style='margin: 0;'>✨ MVC Resort Editor V2</p>
            <p style='margin: 8px 0 0 0; font-size: 14px; opacity: 0.9;'>
                Master data management • Real-time sync across years • Professional-grade tools
            </p>
        </div>
    """,
        unsafe_allow_html=True,
    )


def run():
    main()


if __name__ == "__main__":
    main()
