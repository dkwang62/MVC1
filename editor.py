# editor.py
import streamlit as st
from common.ui import render_resort_card, render_resort_grid, render_page_header
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
# KEY HELPER
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
    keys_to_reset = ["data", "current_resort_id", "previous_resort_id", "working_resorts",
                     "delete_confirm", "last_save_time"]
    for k in keys_to_reset:
        if k == "working_resorts":
            st.session_state[k] = {}
        else:
            st.session_state[k] = None
    st.session_state.download_verified = False

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def safe_date(d: Optional[str], default: str = "2025-01-01") -> date:
    if not d or not isinstance(d, str):
        return datetime.strptime(default, "%Y-%m-%d").date()
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d").date()
    except ValueError:
        return datetime.strptime(default, "%Y-%m-%d").date()

def get_resort_list(data: Dict) -> List[Dict]:
    return data.get("resorts", [])

def find_resort_by_id(data: Dict, rid: str) -> Optional[Dict]:
    return next((r for r in data.get("resorts", []) if r.get("id") == rid), None)

def find_resort_index(data: Dict, rid: str) -> Optional[int]:
    return next((i for i, r in enumerate(data.get("resorts", [])) if r.get("id") == rid), None)

def generate_resort_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", slug).strip("-") or "resort"

def generate_resort_code(name: str) -> str:
    parts = [p for p in name.replace("'", "").split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "RST"

def make_unique_resort_id(base_id: str, resorts: List[Dict]) -> str:
    existing = {r.get("id") for r in resorts}
    if base_id not in existing:
        return base_id
    i = 2
    while f"{base_id}-{i}" in existing:
        i += 1
    return f"{base_id}-{i}"

# ----------------------------------------------------------------------
# WORKING RESORT LOADER
# ----------------------------------------------------------------------
def load_resort(data: Dict, current_resort_id: Optional[str]) -> Optional[Dict]:
    if not current_resort_id:
        return None
    working_resorts = st.session_state.working_resorts
    if current_resort_id not in working_resorts:
        if resort_obj := find_resort_by_id(data, current_resort_id):
            working_resorts[current_resort_id] = copy.deepcopy(resort_obj)
    return working_resorts.get(current_resort_id)

# ----------------------------------------------------------------------
# SEASON MANAGEMENT – FIXED
# ----------------------------------------------------------------------
def ensure_year_structure(resort: Dict, year: str):
    years = resort.setdefault("years", {})
    year_obj = years.setdefault(year, {})
    year_obj.setdefault("seasons", [])
    year_obj.setdefault("holidays", [])
    return year_obj

def get_all_season_names_for_resort(working: Dict) -> Set[str]:
    names = set()
    for year_obj in working.get("years", {}).values():
        names.update(s.get("name") for s in year_obj.get("seasons", []) if s.get("name"))
    return names

def delete_season_across_years(working: Dict, season_name: str):
    for year_obj in working.get("years", {}).values():
        year_obj["seasons"] = [s for s in year_obj.get("seasons", []) if s.get("name") != season_name]

def render_single_season_v2(working: Dict, year: str, season: Dict, idx: int, resort_id: str):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**{sname}**")

    periods = season.get("periods", [])
    df_data = [{"start": safe_date(p.get("start")), "end": safe_date(p.get("end"))} for p in periods]
    df = pd.DataFrame(df_data)

    edited_df = st.data_editor(
        df,
        key=rk(resort_id, "season_editor", year, idx),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "start": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End Date", format="YYYY-MM-DD", required=True),
        },
        hide_index=True,
    )

    if not edited_df.equals(df):
        new_periods = []
        for _, row in edited_df.iterrows():
            if pd.notna(row["start"]) and pd.notna(row["end"]):
                new_periods.append({
                    "start": row["start"].isoformat(),
                    "end": row["end"].isoformat(),
                })
        season["periods"] = new_periods

    # Delete button
    _, col_del = st.columns([5, 1])
    with col_del:
        if st.button("Delete", key=rk(resort_id, "del_season", year, idx), width="stretch"):
            delete_season_across_years(working, sname)
            st.rerun()

# ----------------------------------------------------------------------
# ROOM TYPES HELPERS
# ----------------------------------------------------------------------
def get_all_room_types_for_resort(working: Dict) -> List[str]:
    rooms = set()
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                rooms.update(cat.get("room_points", {}).keys())
        for h in year_obj.get("holidays", []):
            rooms.update(h.get("room_points", {}).keys())
    return sorted(rooms)

# ----------------------------------------------------------------------
# MASTER POINTS & HOLIDAY POINTS – FIXED
# ----------------------------------------------------------------------
def render_reference_points_editor_v2(working: Dict, years: List[str], resort_id: str):
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else sorted(years)[0]
    base_year_obj = ensure_year_structure(working, base_year)
    seasons = base_year_obj.get("seasons", [])

    if not seasons:
        st.info("No seasons defined yet.")
        return

    rooms = get_all_room_types_for_resort(working)

    for s_idx, season in enumerate(seasons):
        with st.expander(season.get("name", f"Season {s_idx+1}"), expanded=True):
            dc = season.setdefault("day_categories", {})
            for key, cat in dc.items():
                st.markdown(f"**{key.replace('_', ' ').title()}**")

                rp = cat.setdefault("room_points", {})
                data = [{"Room Type": r, "Points": int(rp.get(r, 0))} for r in rooms]
                df = pd.DataFrame(data)

                edited = st.data_editor(
                    df,
                    key=rk(resort_id, "master_points", base_year, s_idx, key),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25),
                    },
                )

                if not edited.empty and not edited.equals(df):
                    cat["room_points"] = dict(zip(edited["Room Type"], edited["Points"]))

def render_holiday_management_v2(working: Dict, years: List[str], resort_id: str):
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else sorted(years)[0]
    base_year_obj = ensure_year_structure(working, base_year)
    holidays = base_year_obj.get("holidays", [])

    st.markdown("**Master Holiday Points**")
    if not holidays:
        st.info("No holidays defined.")
        return

    rooms = get_all_room_types_for_resort(working)

    for h_idx, h in enumerate(holidays):
        name = h.get("name", f"Holiday {h_idx+1}")
        with st.expander(f"{name}", expanded=False):
            rp = h.setdefault("room_points", {})
            data = [{"Room Type": r, "Points": int(rp.get(r,0))} for r in rooms]
            df = pd.DataFrame(data)

            edited = st.data_editor(
                df,
                key=rk(resort_id, "holiday_points", base_year, h_idx),
                width="stretch",
                hide_index=True,
                column_config={
                    "Room Type": st.column_config.TextColumn(disabled=True),
                    "Points": st.column_config.NumberColumn(min_value=0, step=25),
                },
            )

            if not edited.empty and not edited.equals(df):
                h["room_points"] = dict(zip(edited["Room Type"], edited["Points"]))

# ----------------------------------------------------------------------
# MAIN RUN FUNCTION
# ----------------------------------------------------------------------
def run():
    initialize_session_state()

    # Try auto-load
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                data = json.load(f)
                if "schema_version" in data and "resorts" in data:
                    st.session_state.data = data
                    st.toast(f"Auto-loaded {len(data.get('resorts',[]))} resorts", icon="success")
        except FileNotFoundError:
            pass

    render_page_header("Edit", "MVC Resort Data Editor", icon="hotel", badge_color="#EF4444")

    if not st.session_state.data:
        st.info("Upload or auto-load a JSON file from the sidebar to begin.")
        return

    data = st.session_state.data
    resorts = get_resort_list(data)
    years = sorted(set(str(y) for r in resorts for y in r.get("years", {})) or DEFAULT_YEARS)

    render_resort_grid(resorts, st.session_state.current_resort_id)

    working = load_resort(data, st.session_state.current_resort_id)

    if working:
        resort_name = working.get("resort_name") or working.get("display_name") or "Unknown"
        tz = working.get("timezone", "UTC")
        addr = working.get("address", "")
        render_resort_card(resort_name, tz, addr)

        tab_overview, tab_seasons, tab_points, tab_holidays, tab_summary = st.tabs([
            "Overview", "Season Dates", "Room Points", "Holidays", "Summary"
        ])

        with tab_seasons:
            for year in years:
                year_obj = ensure_year_structure(working, year)
                for idx, season in enumerate(year_obj.get("seasons", [])):
                    render_single_season_v2(working, year, season, idx, working.get("id", ""))

        with tab_points:
            render_reference_points_editor_v2(working, years, working.get("id", ""))

        with tab_holidays:
            render_holiday_management_v2(working, years, working.get("id", ""))

    # Add your sidebar download/upload logic here if needed

# (or keep it in app.py)

# Allow running directly
if __name__ == "__main__":
    run()
