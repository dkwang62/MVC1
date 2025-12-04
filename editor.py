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
# WIDGET KEY HELPER
# ----------------------------------------------------------------------
@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

# ----------------------------------------------------------------------
# SESSION STATE
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
            st.session_state[k] = v

def save_data():
    st.session_state.last_save_time = datetime.now()

def reset_state_for_new_file():
    for k in ["data", "current_resort_id", "previous_resort_id", "working_resorts",
              "delete_confirm", "last_save_time", "download_verified"]:
        if k == "working_resorts":
            st.session_state[k] = {}
        elif k == "download_verified":
            st.session_state[k] = False
        else:
            st.session_state[k] = None

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def detect_timezone_from_name(name: str) -> str:
    return "UTC"

def get_resort_full_name(resort_id: str, display_name: str) -> str:
    return display_name

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
    return next((i for i, r in enumerate(data.get("resorts", [])) if r.get("id") == rid), None)

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
# FILE OPERATIONS (unchanged – already perfect)
# ----------------------------------------------------------------------
# ... [Your existing handle_file_upload, create_download_button_v2, etc. remain exactly the same] ...
# (I've kept them unchanged to save for tiny formatting)

# ----------------------------------------------------------------------
# RESORT MANAGEMENT (creation/deletion/switch) – unchanged
# ----------------------------------------------------------------------
# ... [All your excellent working-copy logic stays 100% the same] ...

# ----------------------------------------------------------------------
# SEASON MANAGEMENT – FIXED VERSION
# ----------------------------------------------------------------------
def ensure_year_structure(resort: Dict[str, Any], year: str):
    years = resort.setdefault("years", {})
    year_obj = years.setdefault(year, {})
    year_obj.setdefault("seasons", [])
    year_obj.setdefault("holidays", [])
    return year_obj

def get_all_season_names_for_resort(working: Dict[str, Any]) -> Set[str]:
    names: Set[str] = set()
    for year_obj in working.get("years", {}).values():
        names.update(s.get("name") for s in year_obj.get("seasons", []) if s.get("name"))
    return names

def delete_season_across_years(working: Dict[str, Any], season_name: str):
    for year_obj in working.get("years", {}).values():
        year_obj["seasons"] = [
            s for s in year_obj.get("seasons", []) if s.get("name") != season_name
        ]

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

    # Build current DataFrame
    df_data = []
    for p in periods:
        df_data.append({
            "start": safe_date(p.get("start")),
            "end": safe_date(p.get("end"))
        })
    df = pd.DataFrame(df_data)

    editor_key = rk(resort_id, "season_editor", year, idx)

    edited_df = st.data_editor(
        df,
        key=editor_key,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "start": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End Date", format="YYYY-MM-DD", required=True),
        },
        hide_index=True
    )

    # CRITICAL FIX: Only update when actually changed
    if not edited_df.equals(df):
        new_periods = []
        for _, row in edited_df.iterrows():
            if pd.notna(row["start"]) and pd.notna(row["end"]):
                new_periods.append({
                    "start": row["start"].isoformat(),
                    "end": row["end"].isoformat()
                })
        season["periods"] = new_periods

    # Delete button stays outside
    col_spacer, col_del = st.columns([4, 1])
    with col_del:
        if st.button("Delete Season", key=rk(resort_id, "season_del_all_years", year, idx), use_container_width=True):
            delete_season_across_years(working, sname)
            st.rerun()

# ----------------------------------------------------------------------
# MASTER POINTS EDITOR – ALSO FIXED (safe pattern)
# ----------------------------------------------------------------------
def render_reference_points_editor_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown("<div class='section-header'>Master Room Points</div>", unsafe_allow_html=True)
    st.caption("Edit nightly points for each season using the table editor. Changes apply to all years automatically.")

    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else BASE_YEAR_FOR_POINTS)
    base_year_obj = ensure_year_structure(working, base_year)
    seasons = base_year_obj.get("seasons", [])

    if not seasons:
        st.info("No seasons defined yet. Add seasons in the Season Dates section first.")
        return

    canonical_rooms = get_all_room_types_for_resort(working)

    for s_idx, season in enumerate(seasons):
        with st.expander(f"{season.get('name', f'Season {s_idx+1}')}", expanded=True):
            dc = season.setdefault("day_categories", {})
            if not dc:
                dc["sun_thu"] = {"day_pattern": ["Sun","Mon","Tue","Wed","Thu"], "room_points": {}}
                dc["fri_sat"] = {"day_pattern": ["Fri","Sat"], "room_points": {}}

            for key, cat in dc.items():
                day_pattern = cat.get("day_pattern", [])
                st.markdown(f"**{key}** – {', '.join(day_pattern) if day_pattern else 'No days set'}")

                room_points = cat.setdefault("room_points", {})
                rooms_here = canonical_rooms or sorted(room_points.keys())

                # Build original DataFrame
                pts_data = [{"Room Type": room, "Points": int(room_points.get(room, 0) or 0)} for room in rooms_here]
                df_pts = pd.DataFrame(pts_data)

                edited_df = st.data_editor(
                    df_pts,
                    key=rk(resort_id, "master_rp_editor", base_year, s_idx, key),
                    use_container_width=True,
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

    # ... rest of room type add/delete/rename/delete unchanged ...

    sync_season_room_points_across_years(working, base_year)

# ----------------------------------------------------------------------
# HOLIDAY MANAGEMENT – FIXED VERSION (the big one!)
# ----------------------------------------------------------------------
def render_holiday_management_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown("<div class='section-header'>Holiday Management</div>", unsafe_allow_html=True)
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else BASE_YEAR_FOR_POINTS)

    # ... [your existing holiday list/add/rename UI – unchanged] ...

    st.markdown("**Master Holiday Points**")
    st.caption("Edit holiday room points once. Applied to all years automatically.")

    base_year_obj = ensure_year_structure(working, base_year)
    base_holidays = base_year_obj.get("holidays", [])

    if not base_holidays:
        st.info(f"No holidays defined in {base_year}. Add holidays above first.")
        return

    all_rooms = get_all_room_types_for_resort(working)

    for h_idx, h in enumerate(base_holidays):
        disp_name = h.get("name", f"Holiday {h_idx+1}")
        with st.expander(f"{disp_name}", expanded=False):
            rp = h.setdefault("room_points", {})
            rooms_here = sorted(all_rooms or rp.keys())

            # Original DataFrame
            pts_data = [{"Room Type": room, "Points": int(rp.get(room, 0) or 0)} for room in rooms_here]
            df_pts = pd.DataFrame(pts_data)

            edited_df = st.data_editor(
                df_pts,
                key=rk(resort_id, "holiday_master_rp_editor", base_year, h_idx),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Room Type": st.column_config.TextColumn(disabled=True),
                    "Points": st.column_config.NumberColumn(min_value=0, step=25, format="%d")
                }
            )

            # ONLY update when changed → fixes the double-entry bug
            if not edited_df.empty and not edited_df.equals(df_pts):
                new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                h["room_points"] = new_rp

    sync_holiday_room_points_across_years(working, base_year)

# ----------------------------------------------------------------------
# EVERYTHING ELSE (unchanged)
# ----------------------------------------------------------------------
# Keep all your existing functions exactly as they were:
# - handle_resort_creation_v2, handle_resort_deletion_v2
# - load_resort, commit_working_to_data_v2, render_save_button_v2
# - render_resort_summary_v2, validate_resort_data_v2, etc.
# They are already excellent and don’t touch the buggy parts.

# ----------------------------------------------------------------------
# MAIN (unchanged)
# ----------------------------------------------------------------------
def main():
    initialize_session_state()

    # ... [your existing main() logic – file upload, sidebar, tabs, etc.] ...

    if working:
        # ... your tabs and calls ...
        with tab2:  # Season Dates
            render_gantt_charts_v2(working, years, data)
            render_season_dates_editor_v2(working, years, current_resort_id)  # uses fixed render_single_season_v2

        with tab3:  # Room Points
            render_reference_points_editor_v2(working, years, current_resort_id)  # fixed

        with tab4:  # Holidays
            render_holiday_management_v2(working, years, current_resort_id)  # fixed

        # ... rest unchanged ...

if __name__ == "__main__":
    main()
