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
from sheets_export_import import render_excel_export_import
import time
from aggrid_editor import (
    render_season_dates_grid,
    render_season_points_grid,
    render_holiday_points_grid,
)

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
        st.session_state[k] = {} if k == "working_resorts" else None
        if k == "download_verified":
            st.session_state[k] = False

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
    parts = [p for p in name.replace("'", "'").split() if p]
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
# FILE OPERATIONS
# ----------------------------------------------------------------------
def handle_file_upload():
    st.sidebar.markdown("### 📤 File to Memory")
    with st.sidebar.expander("📤 Load", expanded=False):
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
                        st.error("❌ Invalid file format")
                        return
                    reset_state_for_new_file()
                    st.session_state.data = raw_data
                    st.session_state.last_upload_sig = current_sig
                    resorts_list = get_resort_list(raw_data)
                    st.success(f"✅ Loaded {len(resorts_list)} resorts")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")



def create_download_button_v2(data: Dict[str, Any]):
    st.sidebar.markdown("### 📥 Memory to File")
    
    # 1. Check for unsaved changes in the currently open resort
    current_id = st.session_state.get("current_resort_id")
    working_resorts = st.session_state.get("working_resorts", {})
    has_unsaved_changes = False
    
    if current_id and current_id in working_resorts:
        working_copy = working_resorts[current_id]
        committed_copy = find_resort_by_id(data, current_id)
        if committed_copy != working_copy:
            has_unsaved_changes = True
    
    with st.sidebar.expander("💾 Save & Download", expanded=True):
        if has_unsaved_changes:
            st.warning("⚠️ You have unsaved edits in the current resort.")
            st.caption("Commit these changes to memory before downloading.")
            
            if st.button("🧠 COMMIT TO MEMORY", type="primary", width="stretch"):
                # Commit the changes
                commit_working_to_data_v2(data, working_resorts[current_id], current_id)
                st.toast("Changes committed to memory!", icon="✅")
                st.rerun()
        else:
            # 2. If no unsaved changes, show download immediately
            st.success("✅ Memory is up to date.")
            
            filename = st.text_input(
                "File name",
                value="resort_data_v2.json",
                key="download_filename_input",
            ).strip()
            
            if not filename.lower().endswith(".json"):
                filename += ".json"
            
            # Helper to handle Date objects if any slipped into the data
            def json_serial(obj):
                if isinstance(obj, (datetime, date)):
                    return obj.isoformat()
                raise TypeError (f"Type {type(obj)} not serializable")

            try:
                # Serialize with custom date handler
                json_data = json.dumps(
                    data, 
                    indent=2, 
                    ensure_ascii=False,
                    default=json_serial 
                )
                
                st.download_button(
                    label="⬇️ DOWNLOAD JSON FILE",
                    data=json_data,
                    file_name=filename,
                    mime="application/json",
                    key="download_v2_btn",
                    type="primary", 
                    width="stretch",
                )
            except Exception as e:
                st.error(f"Serialization Error: {e}")

def handle_file_verification():
    with st.sidebar.expander("🔍 Verify File", expanded=False):
        verify_upload = st.file_uploader(
            "Upload file to compare with memory", type="json", key="verify_uploader"
        )
        if verify_upload:
            try:
                uploaded_data = json.load(verify_upload)
                current_json = json.dumps(st.session_state.data, sort_keys=True)
                uploaded_json = json.dumps(uploaded_data, sort_keys=True)
                if current_json == uploaded_json:
                    st.success("✅ File matches memory exactly.")
                else:
                    st.error("❌ File differs from memory.")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# ----------------------------------------------------------------------
# SIDEBAR ACTIONS (Merge, Clone, Delete, Create)
# ----------------------------------------------------------------------
def is_duplicate_resort_name(name: str, resorts: List[Dict[str, Any]]) -> bool:
    target = name.strip().lower()
    return any(
        r.get("display_name", "").strip().lower() == target for r in resorts
    )

def render_sidebar_actions(data: Dict[str, Any], current_resort_id: Optional[str]):
    st.sidebar.markdown("### 🛠️ Manage Resorts")
    with st.sidebar.expander("Operations", expanded=False):
        tab_import, tab_current = st.tabs(["Import/New", "Current"])
        
        # --- TAB 1: IMPORT / NEW ---
        with tab_import:
            st.caption("Create New")
            new_name = st.text_input("Resort Name", key="sb_new_resort_name", placeholder="e.g. Pulse NYC")
            if st.button("✨ Create Blank", key="sb_btn_create_new", width="stretch"):
                if not new_name.strip():
                    st.error("Name required")
                else:
                    resorts = data.setdefault("resorts", [])
                    if is_duplicate_resort_name(new_name, resorts):
                        st.error("Name exists")
                    else:
                        base_id = generate_resort_id(new_name)
                        rid = make_unique_resort_id(base_id, resorts)
                        new_resort = {
                            "id": rid,
                            "display_name": new_name,
                            "code": generate_resort_code(new_name),
                            "resort_name": get_resort_full_name(rid, new_name),
                            "address": "",
                            "timezone": "UTC",
                            "years": {},
                        }
                        resorts.append(new_resort)
                        st.session_state.current_resort_id = rid
                        save_data()
                        st.success("Created!")
                        st.rerun()
            
            st.divider()
            st.caption("Merge from File")
            merge_upload = st.file_uploader("Select JSON", type="json", key="sb_merge_uploader")
            if merge_upload:
                try:
                    merge_data = json.load(merge_upload)
                    if "resorts" in merge_data:
                        merge_resorts = merge_data.get("resorts", [])
                        target_resorts = data.setdefault("resorts", [])
                        existing_ids = {r.get("id") for r in target_resorts}
                        display_map = {f"{r.get('display_name')}": r for r in merge_resorts}
                        sel = st.multiselect("Select", list(display_map.keys()), key="sb_merge_select")
                        
                        if sel and st.button("🔀 Merge Selected", key="sb_merge_btn", width="stretch"):
                            count = 0
                            for label in sel:
                                r_obj = display_map[label]
                                if r_obj.get("id") not in existing_ids:
                                    target_resorts.append(copy.deepcopy(r_obj))
                                    existing_ids.add(r_obj.get("id"))
                                    count += 1
                            save_data()
                            st.success(f"Merged {count} resorts")
                            st.rerun()
                except Exception as e:
                    st.error("Invalid file")

        # --- TAB 2: CURRENT RESORT ACTIONS ---
        with tab_current:
            if not current_resort_id:
                st.info("Select a resort from the grid first.")
            else:
                curr_resort = find_resort_by_id(data, current_resort_id)
                if curr_resort:
                    st.markdown(f"**Source:** {curr_resort.get('display_name')}")
                    
                    # --- Clone Logic with Manual ID/Name Input ---
                    default_name = f"{curr_resort.get('display_name')} (Copy)"
                    default_id = generate_resort_id(default_name)
                    
                    resorts = data.get("resorts", [])
                    existing_ids = {r.get("id") for r in resorts}
                    if default_id in existing_ids:
                        base_def_id = default_id
                        c = 1
                        while default_id in existing_ids:
                            c += 1
                            default_id = f"{base_def_id}-{c}"
                            
                    new_clone_name = st.text_input("New Name", value=default_name, key=f"clone_name_{current_resort_id}")
                    new_clone_id = st.text_input("New ID", value=default_id, key=f"clone_id_{current_resort_id}")

                    if st.button("📋 Clone Resort", key="sb_clone_btn", width="stretch"):
                        if not new_clone_name.strip():
                            st.error("Name required")
                        elif not new_clone_id.strip():
                            st.error("ID required")
                        elif new_clone_id in existing_ids:
                            st.error(f"ID '{new_clone_id}' already exists")
                        else:
                            cloned = copy.deepcopy(curr_resort)
                            cloned.update({
                                "id": new_clone_id.strip(),
                                "display_name": new_clone_name.strip(),
                                "code": generate_resort_code(new_clone_name),
                                "resort_name": get_resort_full_name(new_clone_id, new_clone_name)
                            })
                            resorts.append(cloned)
                            st.session_state.current_resort_id = new_clone_id
                            save_data()
                            st.success(f"Cloned to {new_clone_name}")
                            st.rerun()
                    
                    st.divider()
                    
                    # --- Download Just This Resort ---
                    single_resort_wrapper = {
                        "schema_version": "2.0.0",
                        "resorts": [curr_resort]
                    }
                    single_json = json.dumps(single_resort_wrapper, indent=2, ensure_ascii=False)
                    safe_filename = f"{curr_resort.get('id', 'resort')}.json"
                    
                    st.download_button(
                        label="⬇️ Download This Resort",
                        data=single_json,
                        file_name=safe_filename,
                        mime="application/json",
                        key="sb_download_single",
                        width="stretch"
                    )
                    
                    st.divider()
                    
                    # DELETE
                    if not st.session_state.delete_confirm:
                        if st.button("🗑️ Delete Resort", key="sb_del_init", type="secondary", width="stretch"):
                            st.session_state.delete_confirm = True
                            st.rerun()
                    else:
                        st.warning("Are you sure?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Yes, Delete", key="sb_del_conf", type="primary", width="stretch"):
                                idx = find_resort_index(data, current_resort_id)
                                if idx is not None:
                                    data.get("resorts", []).pop(idx)
                                st.session_state.current_resort_id = None
                                st.session_state.delete_confirm = False
                                st.session_state.working_resorts.pop(current_resort_id, None)
                                save_data()
                                st.success("Deleted")
                                st.rerun()
                        with c2:
                            if st.button("Cancel", key="sb_del_cancel", width="stretch"):
                                st.session_state.delete_confirm = False
                                st.rerun()

# ----------------------------------------------------------------------
# WORKING RESORT MANAGEMENT
# ----------------------------------------------------------------------
def handle_resort_switch_v2(
    data: Dict[str, Any],
    current_resort_id: Optional[str],
    previous_resort_id: Optional[str],
):
    if previous_resort_id and previous_resort_id != current_resort_id:
        working_resorts = st.session_state.working_resorts
        if previous_resort_id in working_resorts:
            working = working_resorts[previous_resort_id]
            committed = find_resort_by_id(data, previous_resort_id)
            if committed is None:
                working_resorts.pop(previous_resort_id, None)
            elif working != committed:
                st.warning(
                    f"⚠️ Unsaved changes in {committed.get('display_name', previous_resort_id)}"
                )
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Save changes to memory", key="switch_save_prev", width="stretch"):
                        commit_working_to_data_v2(data, working, previous_resort_id)
                        del working_resorts[previous_resort_id]
                        st.session_state.previous_resort_id = current_resort_id
                        st.rerun()
                with col2:
                    if st.button("🚫 Discard", key="switch_discard_prev", width="stretch"):
                        del working_resorts[previous_resort_id]
                        st.session_state.previous_resort_id = current_resort_id
                        st.rerun()
                with col3:
                    if st.button("↩️ Stay", key="switch_cancel_prev", width="stretch"):
                        st.session_state.current_resort_id = previous_resort_id
                        st.rerun()
                st.stop()
    st.session_state.previous_resort_id = current_resort_id

def commit_working_to_data_v2(data: Dict[str, Any], working: Dict[str, Any], resort_id: str):
    idx = find_resort_index(data, resort_id)
    
    if idx is not None:
        # Update existing resort
        data["resorts"][idx] = copy.deepcopy(working)
    else:
        # SAFETY NET: If this is a new resort being edited that wasn't in the list yet
        # (Though your creation logic usually adds it first, this prevents crashes)
        if "resorts" not in data:
            data["resorts"] = []
        data["resorts"].append(copy.deepcopy(working))
        
    save_data() # Update timestamp

def render_save_button_v2(
    data: Dict[str, Any], working: Dict[str, Any], resort_id: str
):
    committed = find_resort_by_id(data, resort_id)
    if committed is not None and committed != working:
        st.caption(
            "Changes in this resort are currently kept in memory. "
            "You’ll be asked to **Save or Discard** only when you leave this resort."
        )
    else:
        st.caption("All changes for this resort are in sync with the saved data.")

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
# SEASON MANAGEMENT
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
        names.update(
            s.get("name") for s in year_obj.get("seasons", []) if s.get("name")
        )
    return names

def delete_season_across_years(working: Dict[str, Any], season_name: str):
    years = working.get("years", {})
    for year_obj in years.values():
        year_obj["seasons"] = [
            s
            for s in year_obj.get("seasons", [])
            if s.get("name") != season_name
        ]

def rename_season_across_years(
    working: Dict[str, Any], old_name: str, new_name: str
):
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name:
        st.error("Season names cannot be empty")
        return
    if old_name == new_name:
        st.info("Season name unchanged.")
        return
    all_names = get_all_season_names_for_resort(working)
    if any(
        n.lower() == new_name.lower() and n != old_name for n in all_names
    ):
        st.error(f"❌ Season '{new_name}' already exists")
        return
    changed = False
    for year_obj in working.get("years", {}).values():
        for s in year_obj.get("seasons", []):
            if (s.get("name") or "").strip() == old_name:
                s["name"] = new_name
                changed = True
    if changed:
        st.success(
            f"✅ Renamed season '{old_name}' → '{new_name}' across all years"
        )
    else:
        st.warning(f"No season named '{old_name}' found")

def render_season_rename_panel_v2(working: Dict[str, Any], resort_id: str):
    all_names = sorted(get_all_season_names_for_resort(working))
    if not all_names:
        st.caption("No seasons available to rename yet.")
        return
    st.markdown("**✏️ Rename Seasons (applies to all years)**")
    for name in all_names:
        col1, col2 = st.columns([3, 1])
        with col1:
            new_name = st.text_input(
                f"Rename '{name}' to",
                value=name,
                key=rk(resort_id, "rename_season_input", name),
            )
        with col2:
            if st.button(
                "Apply", key=rk(resort_id, "rename_season_btn", name)
            ):
                if new_name and new_name != name:
                    rename_season_across_years(working, name, new_name)
                    st.rerun()

def render_season_dates_editor_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown(
        "<div class='section-header'>📅 Season Dates</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Define season date ranges for each year. Season names apply across all years."
    )
    render_season_rename_panel_v2(working, resort_id)
    all_names = get_all_season_names_for_resort(working)
    
    # Sort years descending: latest year first (e.g., 2026, 2025, 2024...)
    sorted_years = sorted(years, reverse=True)
    
    for year_idx, year in enumerate(sorted_years):
        year_obj = ensure_year_structure(working, year)
        seasons = year_obj.get("seasons", [])
        
        # Each full year is now in its own collapsible expander
        # Latest year expanded by default
        with st.expander(f"📆 {year} Seasons", expanded=(year_idx == 0)):
            # Add new season form (applies to all years)
            col1, col2 = st.columns([4, 1])
            with col1:
                new_season_name = st.text_input(
                    "New season (applies to all years)",
                    key=rk(resort_id, "new_season", year),
                    placeholder="e.g., Peak Season",
                )
            with col2:
                if (
                    st.button(
                        "➕ Add",
                        key=rk(resort_id, "add_season_all_years", year),
                        use_container_width=True,
                    )
                    and new_season_name
                ):
                    name = new_season_name.strip()
                    if not name:
                        st.error("❌ Name required")
                    elif any(name.lower() == n.lower() for n in all_names):
                        st.error("❌ Season exists")
                    else:
                        for y2 in years:
                            y2_obj = ensure_year_structure(working, y2)
                            y2_obj.setdefault("seasons", []).append(
                                {
                                    "name": name,
                                    "periods": [],
                                    "day_categories": {},
                                }
                            )
                        st.success(f"✅ Added '{name}'")
                        st.rerun()
            
            # Render each season for this year
            if not seasons:
                st.info("No seasons defined yet for this year.")
            
            for idx, season in enumerate(seasons):
                render_single_season_v2(working, year, season, idx, resort_id)

def render_single_season_v2(
    working: Dict[str, Any],
    year: str,
    season: Dict[str, Any],
    idx: int,
    resort_id: str,
):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**🎯 {sname}**")
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
        width="stretch",
        column_config={
            "start": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End Date", format="YYYY-MM-DD", required=True),
        },
        hide_index=True
    )
    if st.button("Save Dates", key=rk(resort_id, "save_season_dates", year, idx)):
        new_periods = []
        for _, row in edited_df.iterrows():
            if row["start"] and row["end"]:
                new_periods.append({
                    "start": row["start"].isoformat() if hasattr(row["start"], 'isoformat') else str(row["start"]),
                    "end": row["end"].isoformat() if hasattr(row["end"], 'isoformat') else str(row["end"])
                })
        season["periods"] = new_periods
        st.success("Dates saved!")
        st.rerun()
    col_spacer, col_del = st.columns([4, 1])
    with col_del:
        if st.button(
            "🗑️ Delete Season",
            key=rk(resort_id, "season_del_all_years", year, idx),
            width="stretch",
        ):
            delete_season_across_years(working, sname)
            st.rerun()

# ----------------------------------------------------------------------
# ROOM TYPE MANAGEMENT
# ----------------------------------------------------------------------
def get_all_room_types_for_resort(working: Dict[str, Any]) -> List[str]:
    rooms: Set[str] = set()
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    rooms.update(rp.keys())
        for h in year_obj.get("holidays", []):
            if isinstance(rp := h.get("room_points", {}), dict):
                rooms.update(rp.keys())
    return sorted(rooms)

def add_room_type_master(working: Dict[str, Any], room: str, base_year: str):
    room = room.strip()
    if not room:
        return
    years = working.get("years", {})
    if base_year in years:
        base_year_obj = ensure_year_structure(working, base_year)
        for season in base_year_obj.get("seasons", []):
            for cat in season.setdefault("day_categories", {}).values():
                cat.setdefault("room_points", {}).setdefault(room, 0)
    for year_obj in years.values():
        for h in year_obj.get("holidays", []):
            h.setdefault("room_points", {}).setdefault(room, 0)

def delete_room_type_master(working: Dict[str, Any], room: str):
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    rp.pop(room, None)
        for h in year_obj.get("holidays", []):
            if isinstance(rp := h.get("room_points", {}), dict):
                rp.pop(room, None)

def rename_room_type_across_resort(
    working: Dict[str, Any], old_name: str, new_name: str
):
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name:
        st.error("Room names cannot be empty")
        return
    if old_name == new_name:
        st.info("Room name unchanged.")
        return
    all_rooms = get_all_room_types_for_resort(working)
    if any(
        r.lower() == new_name.lower() and r != old_name for r in all_rooms
    ):
        st.error(f"❌ Room type '{new_name}' already exists")
        return
    changed = False
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                rp = cat.get("room_points")
                if isinstance(rp, dict) and old_name in rp:
                    rp[new_name] = rp.pop(old_name)
                    changed = True
        for h in year_obj.get("holidays", []):
            rp = h.get("room_points")
            if isinstance(rp, dict) and old_name in rp:
                rp[new_name] = rp.pop(old_name)
                changed = True
    if changed:
        st.success(
            f"✅ Renamed room '{old_name}' → '{new_name}' across all years and holidays"
        )
    else:
        st.warning(f"No room named '{old_name}' found")

# ----------------------------------------------------------------------
# SYNC FUNCTIONS
# ----------------------------------------------------------------------
def sync_season_room_points_across_years(
    working: Dict[str, Any], base_year: str
):
    years = working.get("years", {})
    if not years or base_year not in years:
        return
    canonical_rooms: Set[str] = set()
    for y_obj in years.values():
        for season in y_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    canonical_rooms |= set(rp.keys())
    if not canonical_rooms:
        return
    base_year_obj = years[base_year]
    base_seasons = base_year_obj.get("seasons", [])
    for season in base_seasons:
        for cat in season.setdefault("day_categories", {}).values():
            rp = cat.setdefault("room_points", {})
            for room in canonical_rooms:
                rp.setdefault(room, 0)
            for room in list(rp.keys()):
                if room not in canonical_rooms:
                    del rp[room]
    base_by_name = {
        s.get("name", ""): s for s in base_seasons if s.get("name")
    }
    for year_name, year_obj in years.items():
        if year_name != base_year:
            for season in year_obj.get("seasons", []):
                if (name := season.get("name", "")) in base_by_name:
                    season["day_categories"] = copy.deepcopy(
                        base_by_name[name].get("day_categories", {})
                    )

def sync_holiday_room_points_across_years(
    working: Dict[str, Any], base_year: str
):
    years = working.get("years", {})
    if not years or base_year not in years:
        return
    base_year_obj = ensure_year_structure(working, base_year)
    base_holidays = base_year_obj.get("holidays", [])
    all_rooms = get_all_room_types_for_resort(working)
    for h in base_holidays:
        rp = h.setdefault("room_points", {})
        for room in all_rooms:
            rp.setdefault(room, 0)
        for room in list(rp.keys()):
            if room not in all_rooms:
                del rp[room]
    base_by_key = {
        (h.get("global_reference") or h.get("name") or "").strip(): h
        for h in base_holidays
        if (h.get("global_reference") or h.get("name") or "").strip()
    }
    for year_name, year_obj in years.items():
        if year_name != base_year:
            for h in year_obj.get("holidays", []):
                if (
                    key := (
                        h.get("global_reference") or h.get("name") or ""
                    ).strip()
                ) in base_by_key:
                    h["room_points"] = copy.deepcopy(
                        base_by_key[key].get("room_points", {})
                    )

# ----------------------------------------------------------------------
# RESORT BASIC INFO EDITOR
# ----------------------------------------------------------------------
def edit_resort_basics(working: Dict[str, Any], resort_id: str):
    """
    Renders editable fields for resort_name, timezone, address, AND display_name.
    Returns nothing – directly mutates the working dict.
    """
    st.markdown("### Basic Resort Information")
    col_disp, col_code = st.columns([3, 1])
    with col_disp:
        current_display = working.get("display_name", "")
        new_display = st.text_input(
            "Display Name (Internal ID)",
            value=current_display,
            key=rk(resort_id, "display_name_edit"),
            help="The short name used in lists and menus."
        )
        if new_display and new_display != current_display:
            working["display_name"] = new_display.strip()
   
    with col_code:
        current_code = working.get("code", "")
        new_code = st.text_input(
            "Code",
            value=current_code,
            key=rk(resort_id, "code_edit")
        )
        if new_code != current_code:
            working["code"] = new_code.strip()
    
    current_name = working.get("resort_name", "")
    current_tz = working.get("timezone", "UTC")
    current_addr = working.get("address", "")
    new_name = st.text_input(
        "Full Resort Name (Official)",
        value=current_name,
        key=rk(resort_id, "resort_name_edit"),
        help="Official name stored in the 'resort_name' field",
    )
    working["resort_name"] = new_name.strip()
    col_tz, col_addr = st.columns(2)
    with col_tz:
        new_tz = st.text_input(
            "Timezone",
            value=current_tz,
            key=rk(resort_id, "timezone_edit"),
            help="e.g. America/New_York, Europe/London, etc.",
        )
        working["timezone"] = new_tz.strip() or "UTC"
    with col_addr:
        new_addr = st.text_area(
            "Address",
            value=current_addr,
            height=80,
            key=rk(resort_id, "address_edit"),
            help="Full street address of the resort",
        )
        working["address"] = new_addr.strip()

# ----------------------------------------------------------------------
# MASTER POINTS EDITOR
# ----------------------------------------------------------------------
def render_reference_points_editor_v2(
    working: Dict[str, Any], years: List[str], resort_id: str
):
    st.markdown(
        "<div class='section-header'>🎯 Master Room Points</div>",
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
            "💡 No seasons defined yet. Add seasons in the Season Dates section first."
        )
        return
    canonical_rooms = get_all_room_types_for_resort(working)
    for s_idx, season in enumerate(seasons):
        with st.expander(
            f"🏖️ {season.get('name', f'Season {s_idx+1}')}", expanded=True
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
                    f"**📅 {key}** – {', '.join(day_pattern) if day_pattern else 'No days set'}"
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
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )
               
                if st.button("Save Changes", key=rk(resort_id, "save_master_rp", base_year, s_idx, key)):
                    if not edited_df.empty:
                        new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                        cat["room_points"] = new_rp
                        st.success("Points saved!")
                        st.rerun()
    st.markdown("---")
    st.markdown("**🏠 Manage Room Types**")
    col1, col2 = st.columns(2)
    with col1:
        new_room = st.text_input(
            "Add room type (applies to all seasons/years)",
            key=rk(resort_id, "room_add_master"),
            placeholder="e.g., 2BR Ocean View",
        )
        if st.button(
            "➕ Add Room",
            key=rk(resort_id, "room_add_btn_master"),
            width="stretch",
        ) and new_room:
            add_room_type_master(working, new_room.strip(), base_year)
            st.success(f"✅ Added {new_room}")
            st.rerun()
    with col2:
        del_room = st.selectbox(
            "Delete room type",
            [""] + get_all_room_types_for_resort(working),
            key=rk(resort_id, "room_del_master"),
        )
        if del_room and st.button(
            "🗑️ Delete Room",
            key=rk(resort_id, "room_del_btn_master"),
            width="stretch",
        ):
            delete_room_type_master(working, del_room)
            st.success(f"✅ Deleted {del_room}")
            st.rerun()
    all_rooms_list = get_all_room_types_for_resort(working)
    if all_rooms_list:
        st.markdown("**✏️ Rename Room Type (applies everywhere)**")
        col3, col4 = st.columns(2)
        with col3:
            old_room = st.selectbox(
                "Room to rename",
                [""] + all_rooms_list,
                key=rk(resort_id, "room_rename_old"),
            )
        with col4:
            new_room_name = st.text_input(
                "New name", key=rk(resort_id, "room_rename_new")
            )
        if st.button(
            "✅ Apply Rename",
            key=rk(resort_id, "room_rename_apply"),
            width="stretch",
        ):
            if old_room and new_room_name:
                rename_room_type_across_resort(
                    working, old_room, new_room_name
                )
                st.rerun()
    sync_season_room_points_across_years(working, base_year=base_year)

# ----------------------------------------------------------------------
# HOLIDAY MANAGEMENT
# ----------------------------------------------------------------------
def get_available_global_holidays(data: Dict[str, Any]) -> List[str]:
    if not data or "global_holidays" not in data:
        return []
    unique_names = set()
    for year_data in data["global_holidays"].values():
        unique_names.update(year_data.keys())
    return sorted(list(unique_names))

def get_all_holidays_for_resort(
    working: Dict[str, Any]
) -> List[Dict[str, Any]]:
    holidays_map = {}
    for year_obj in working.get("years", {}).values():
        for h in year_obj.get("holidays", []):
            key = (h.get("global_reference") or h.get("name") or "").strip()
            if key and key not in holidays_map:
                holidays_map[key] = {
                    "name": h.get("name", key),
                    "global_reference": key,
                }
    return list(holidays_map.values())

def sort_holidays_chronologically(working: Dict[str, Any], data: Dict[str, Any]):
    global_holidays = data.get("global_holidays", {})
    years = working.get("years", {})
    
    for year_str, year_obj in years.items():
        current_holidays = year_obj.get("holidays", [])
        if not current_holidays:
            continue
        gh_year = global_holidays.get(year_str, {})
        def sort_key(h):
            ref = h.get("global_reference") or h.get("name")
            if ref in gh_year:
                return gh_year[ref].get("start_date", "9999-12-31")
            return "9999-12-31" 
        current_holidays.sort(key=sort_key)

def add_holiday_to_all_years(
    working: Dict[str, Any], holiday_name: str, global_ref: str
):
    holiday_name = holiday_name.strip()
    global_ref = (global_ref or holiday_name).strip()
    if not holiday_name or not global_ref:
        return False
    years = working.get("years", {})
    for year_obj in years.values():
        holidays = year_obj.setdefault("holidays", [])
        if any(
            (h.get("global_reference") or h.get("name") or "").strip()
            == global_ref
            for h in holidays
        ):
            continue
        holidays.append(
            {
                "name": holiday_name,
                "global_reference": global_ref,
                "room_points": {},
            }
        )
    return True

def delete_holiday_from_all_years(working: Dict[str, Any], global_ref: str):
    global_ref = (global_ref or "").strip()
    if not global_ref:
        return False
    changed = False
    for year_obj in working.get("years", {}).values():
        holidays = year_obj.get("holidays", [])
        original_len = len(holidays)
        year_obj["holidays"] = [
            h
            for h in holidays
            if (h.get("global_reference") or h.get("name") or "").strip()
            != global_ref
        ]
        if len(year_obj["holidays"]) < original_len:
            changed = True
    return changed

def rename_holiday_across_years(
    working: Dict[str, Any],
    old_global_ref: str,
    new_name: str,
    new_global_ref: str,
):
    old_global_ref = (old_global_ref or "").strip()
    new_name = (new_name or "").strip()
    new_global_ref = (new_global_ref or "").strip()
    if not old_global_ref or not new_name or not new_global_ref:
        st.error("All fields must be filled")
        return False
    changed = False
    for year_obj in working.get("years", {}).values():
        for h in year_obj.get("holidays", []):
            if (
                (h.get("global_reference") or h.get("name") or "").strip()
                == old_global_ref
            ):
                h["name"] = new_name
                h["global_reference"] = new_global_ref
                changed = True
    return changed

def render_holiday_management_v2(
    working: Dict[str, Any], years: List[str], resort_id: str, data: Dict[str, Any]
):
    st.markdown(
        "<div class='section-header'>🎄 Holiday Management</div>",
        unsafe_allow_html=True,
    )
    base_year = (
        BASE_YEAR_FOR_POINTS
        if BASE_YEAR_FOR_POINTS in years
        else (sorted(years)[0] if years else BASE_YEAR_FOR_POINTS)
    )
    st.markdown("**📋 Manage Holidays (applies to all years)**")
    st.caption(
        "Holidays are automatically synchronized across all years. Changes here affect every year."
    )
    
    sort_holidays_chronologically(working, data)
    
    current_holidays = get_all_holidays_for_resort(working)
    gh_base = data.get("global_holidays", {}).get(base_year, {})
    
    def display_sort_key(h):
        ref = h.get("global_reference", "")
        return gh_base.get(ref, {}).get("start_date", "9999-12-31")
    
    current_holidays.sort(key=display_sort_key)

    if current_holidays:
        st.markdown("**Current Holidays:**")
        for h in current_holidays:
            unique_key = h.get("global_reference", "")
            col1, col2, col3 = st.columns([3, 3, 1])
            with col1:
                st.text_input(
                    "Display Name",
                    value=h.get("name", ""),
                    key=rk(resort_id, "holiday_display", unique_key),
                    disabled=True 
                )
            with col2:
                st.text_input(
                    "Global Reference",
                    value=h.get("global_reference", ""),
                    key=rk(resort_id, "holiday_ref", unique_key),
                    disabled=True
                )
            with col3:
                if st.button(
                    "🗑️",
                    key=rk(resort_id, "holiday_del_global", unique_key),
                ):
                    if delete_holiday_from_all_years(working, unique_key):
                        st.success(
                            f"✅ Deleted '{h['name']}' from all years"
                        )
                        st.rerun()
    else:
        st.info("💡 No holidays assigned yet. Add one below.")
        
    st.markdown("---")
    st.markdown("**➕ Add New Holiday**")
    
    available_globals = get_available_global_holidays(data)
    existing_refs = set(h["global_reference"] for h in current_holidays)
    options = [opt for opt in available_globals if opt not in existing_refs]
    
    if not options:
        st.info("All global holidays have already been added to this resort.")
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_holiday = st.selectbox(
                "Select Global Holiday to Add",
                options=options,
                key=rk(resort_id, "new_holiday_select"),
            )
        with col2:
            if st.button(
                "➕ Add to All Years",
                key=rk(resort_id, "btn_add_holiday_global"),
                width="stretch",
            ):
                if selected_holiday:
                    if add_holiday_to_all_years(working, selected_holiday, selected_holiday):
                        st.success(f"✅ Added '{selected_holiday}' to all years")
                        st.rerun()
                    else:
                        st.error("Failed to add holiday.")

    sync_holiday_room_points_across_years(working, base_year=base_year)
    
    st.markdown("---")
    st.markdown("**💰 Master Holiday Points**")
    st.caption(
        "Edit holiday room points once. Applied to all years automatically."
    )
    
    sort_holidays_chronologically(working, data)
    
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
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )
               
                if st.button("Save Changes", key=rk(resort_id, "save_holiday_rp", base_year, h_idx)):
                    if not edited_df.empty:
                        new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                        h["room_points"] = new_rp
                        st.success("Points saved!")
                        st.rerun()
    sync_holiday_room_points_across_years(working, base_year=base_year)

# ----------------------------------------------------------------------
# GANTT CHART
# ----------------------------------------------------------------------
def render_gantt_charts_v2(
    working: Dict[str, Any], years: List[str], data: Dict[str, Any]
):
    from common.charts import create_gantt_chart_from_working
    st.markdown(
        "<div class='section-header'>📊 Visual Timeline</div>",
        unsafe_allow_html=True,
    )
   
    sort_holidays_chronologically(working, data)
   
    # Sort years descending: latest year first (e.g., 2026, 2025, 2024...)
    sorted_years = sorted(years, reverse=True)
   
    # Create tabs with latest year on the left
    tabs = st.tabs([f"📅 {year}" for year in sorted_years])
    
    for tab, year in zip(tabs, sorted_years):
        with tab:
            year_data = working.get("years", {}).get(year, {})
            n_seasons = len(year_data.get("seasons", []))
            n_holidays = len(year_data.get("holidays", []))
           
            total_rows = n_seasons + n_holidays
            fig = create_gantt_chart_from_working(
                working,
                year,
                data,
                height=max(400, total_rows * 35 + 150),
            )
            st.plotly_chart(fig, use_container_width=True)  # Better responsiveness

# ----------------------------------------------------------------------
# RESORT SUMMARY HELPERS
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

def _build_season_rows(resort_years: Dict[str, Any], ref_year: str, room_types: List[str]) -> List[Dict[str, Any]]:
    """Helper: Build 7-night totals for seasons."""
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
    return rows

def _build_holiday_rows(resort_years: Dict[str, Any], sorted_years: List[str], room_types: List[str]) -> List[Dict[str, Any]]:
    """Helper: Extract totals for holidays (uses the most recent year with data)."""
    rows = []
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
    return rows

def render_seasons_summary_table(working: Dict[str, Any]):
    st.markdown("#### 📆 Seasons Summary (7-night)")
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
    room_types = get_all_room_types_for_resort(working)
    if not room_types:
        st.info("💡 No room types defined yet")
        return

    season_rows = []
    if ref_year:
        season_rows = _build_season_rows(resort_years, ref_year, room_types)
        
    if season_rows:
        st.caption("Calculated weekly totals derived from nightly points.")
        df_seasons = pd.DataFrame(season_rows, columns=["Season"] + room_types)
        st.dataframe(df_seasons, width="stretch", hide_index=True)
    else:
        st.info("💡 No season data available")

def render_holidays_summary_table(working: Dict[str, Any]):
    st.markdown("#### 🎄 Holidays Summary")
    resort_years = working.get("years", {})
    if not resort_years:
        st.info("💡 No data available yet")
        return

    sorted_years = sorted(
        resort_years.keys(), key=lambda y: int(y) if str(y).isdigit() else 0
    )
    room_types = get_all_room_types_for_resort(working)
    if not room_types:
        st.info("💡 No room types defined yet")
        return

    holiday_rows = _build_holiday_rows(resort_years, sorted_years, room_types)
    
    if holiday_rows:
        st.caption("Weekly totals directly from holiday points.")
        df_holidays = pd.DataFrame(holiday_rows, columns=["Season"] + room_types)
        st.dataframe(df_holidays, width="stretch", hide_index=True)
    else:
        st.info("💡 No holiday data available")

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
            if all_rooms and isinstance(rp := h.get("room_points", {}), dict):
                if missing_rooms := all_rooms - set(rp.keys()):
                    issues.append(
                        f"[{year}] Holiday '{hname}' missing rooms: {', '.join(sorted(missing_rooms))}"
                    )

        # GAP and OVERLAP detection
        try:
            year_start = date(int(year), 1, 1)
            year_end = date(int(year), 12, 31)
        except Exception:
            continue

        covered_ranges = []
        gh_year = global_holidays.get(year, {})

        # Collect season periods
        for season in year_obj.get("seasons", []):
            for period in season.get("periods", []):
                try:
                    start = datetime.strptime(period.get("start", ""), "%Y-%m-%d").date()
                    end = datetime.strptime(period.get("end", ""), "%Y-%m-%d").date()
                    if start <= end:
                        covered_ranges.append(
                            (start, end, f"Season '{season.get('name', '(Unnamed)')}'")
                        )
                except Exception:
                    continue

        # Collect holiday ranges (from global calendar)
        for h in year_obj.get("holidays", []):
            global_ref = h.get("global_reference") or h.get("name")
            if gh := gh_year.get(global_ref):
                try:
                    start = datetime.strptime(gh.get("start_date", ""), "%Y-%m-%d").date()
                    end = datetime.strptime(gh.get("end_date", ""), "%Y-%m-%d").date()
                    if start <= end:
                        covered_ranges.append(
                            (start, end, f"Holiday '{h.get('name', '(Unnamed)')}'")
                        )
                except Exception:
                    continue

        # Sort ranges by start date
        covered_ranges.sort(key=lambda x: x[0])

        # === GAP DETECTION ===
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
                    gap_days = (gap_end - gap_start).days + 1
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
            issues.append(f"[{year}] No date ranges defined (entire year is uncovered)")

        # === OVERLAP DETECTION ===
        if covered_ranges:
            for i in range(len(covered_ranges) - 1):
                current_end = covered_ranges[i][1]
                next_start = covered_ranges[i + 1][0]
                if current_end >= next_start:
                    overlap_start = next_start
                    overlap_end = current_end
                    overlap_days = (overlap_end - overlap_start).days + 1
                    issues.append(
                        f"[{year}] OVERLAP: {overlap_days} days from {overlap_start} to {overlap_end} "
                        f"(between {covered_ranges[i][2]} and {covered_ranges[i+1][2]})"
                    )

    return issues
def render_validation_panel_v2(
    working: Dict[str, Any], data: Dict[str, Any], years: List[str]
):
    with st.expander("🔍 Date gaps or overlaps", expanded=False):
        issues = validate_resort_data_v2(working, data, years)
        if issues:
            st.error(f"**Found {len(issues)} issue(s):**")
            for issue in issues:
                st.write(f"• {issue}")
        else:
            st.success("✅ All validation checks passed!")

# ----------------------------------------------------------------------
# YEAR GENERATOR LOGIC
# ----------------------------------------------------------------------
def calculate_date_offset(source_year: int, target_year: int) -> int:
    """
    Calculate the number of days between same calendar dates in different years.
    Accounts for leap years properly.
    """
    source_date = datetime(source_year, 1, 1)
    target_date = datetime(target_year, 1, 1)
    delta = target_date - source_date
    return delta.days

def adjust_date_string(date_str: str, days_offset: int) -> str:
    """Adjust a date string by adding/subtracting days."""
    try:
        original_date = datetime.strptime(date_str, "%Y-%m-%d")
        new_date = original_date + timedelta(days=days_offset)
        return new_date.strftime("%Y-%m-%d")
    except Exception:
        return date_str

def generate_new_year_global_holidays(
    data: Dict[str, Any],
    source_year: str,
    target_year: str,
    days_offset: int
) -> Dict[str, Any]:
    """Generate global holidays for a new year based on a source year."""
    source_holidays = data.get("global_holidays", {}).get(source_year, {})
    if not source_holidays:
        return {}
    new_holidays = {}
    for holiday_name, holiday_data in source_holidays.items():
        new_holiday = copy.deepcopy(holiday_data)
        if "start_date" in new_holiday:
            new_holiday["start_date"] = adjust_date_string(
                new_holiday["start_date"], days_offset
            )
        if "end_date" in new_holiday:
            new_holiday["end_date"] = adjust_date_string(
                new_holiday["end_date"], days_offset
            )
        new_holidays[holiday_name] = new_holiday
    return new_holidays

def generate_new_year_for_resort(
    resort: Dict[str, Any],
    source_year: str,
    target_year: str,
    days_offset: int
) -> Dict[str, Any]:
    """Generate year data for a resort based on a source year."""
    source_year_data = resort.get("years", {}).get(source_year)
    if not source_year_data:
        return {}
    new_year_data = copy.deepcopy(source_year_data)
    # Adjust season dates
    for season in new_year_data.get("seasons", []):
        for period in season.get("periods", []):
            if "start" in period:
                period["start"] = adjust_date_string(period["start"], days_offset)
            if "end" in period:
                period["end"] = adjust_date_string(period["end"], days_offset)
    return new_year_data

def render_year_generator(data: Dict[str, Any]):
    """Render the year generator UI with Holiday AND Season previews."""
    st.info("""
    **💡 How it works:**
    1. Select a source year to copy from.
    2. Enter the new target year.
    3. **Adjust the Date Offset:** Use **364** to keep the same day of the week, or **365/366** for the same calendar date.
    4. **Preview:** Check both Holidays and Resort Seasons to ensure alignment.
    """)
    
    # Get available years
    existing_years = sorted(data.get("global_holidays", {}).keys())
    
    if not existing_years:
        st.warning("⚠️ No years found in global holidays. Add at least one year first.")
        return
    
    col1, col2 = st.columns(2)
    with col1:
        source_year = st.selectbox(
            "Source Year (copy from)",
            options=existing_years,
            key="year_gen_source"
        )
    with col2:
        target_year = st.number_input(
            "Target Year (create new)",
            min_value=2020,
            max_value=2050,
            value=int(source_year) + 1 if source_year else 2027,
            step=1,
            key="year_gen_target"
        )
    
    target_year_str = str(target_year)
    
    # Check if target year already exists
    if target_year_str in existing_years:
        st.error(f"❌ Year {target_year} already exists! Choose a different target year or delete the existing one first.")
        return
    
    st.markdown("---")

    # --- OFFSET SETTINGS ---
    suggested_offset = calculate_date_offset(int(source_year), target_year)
    
    st.markdown("#### ⚙️ Date Adjustment settings")
    col_off1, col_off2 = st.columns([1, 1])
    
    with col_off1:
        days_offset = st.number_input(
            "Date Offset (Days to Add)",
            value=suggested_offset,
            step=1,
            help="Positive adds days, negative subtracts. 364 preserves day-of-week; 365 preserves calendar date.",
            key=f"offset_input_{source_year}_{target_year}" 
        )

    with col_off2:
        if days_offset % 7 == 0:
            st.success(f"✅ Offset {days_offset} is a multiple of 7. Day of the week will be preserved.")
        else:
            st.warning(f"⚠️ Offset {days_offset} is NOT a multiple of 7. Day of the week will shift.")

    # --- PREVIEW SECTION ---
    st.markdown("#### 📊 Preview")
    
    pv_tab1, pv_tab2 = st.tabs(["🌎 Global Holidays", "🏨 Resort Seasons"])
    
    # TAB 1: Global Holidays Preview
    with pv_tab1:
        source_holidays = data.get("global_holidays", {}).get(source_year, {})
        if source_holidays:
            preview_data = []
            for holiday_name, holiday_data in list(source_holidays.items())[:5]:
                old_start = holiday_data.get("start_date", "")
                old_end = holiday_data.get("end_date", "")
                new_start = adjust_date_string(old_start, days_offset)
                new_end = adjust_date_string(old_end, days_offset)
                
                preview_data.append({
                    "Holiday": holiday_name,
                    "Old Dates": f"{old_start} to {old_end}",
                    "New Dates": f"{new_start} to {new_end}"
                })
            st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)
        else:
            st.info("No holidays in source year.")

    # TAB 2: Resort Seasons Preview
    with pv_tab2:
        resorts = data.get("resorts", [])
        resorts_with_source = [r for r in resorts if source_year in r.get("years", {})]
        
        if resorts_with_source:
            # Let user pick a resort to inspect
            sample_resort_name = st.selectbox(
                "Select a resort to preview season shifts:",
                options=[r.get("display_name") for r in resorts_with_source],
                key="season_preview_resort_select"
            )
            
            sample_resort = next((r for r in resorts_with_source if r.get("display_name") == sample_resort_name), None)
            
            if sample_resort:
                season_preview = []
                # Look at seasons in the source year
                source_seasons = sample_resort["years"][source_year].get("seasons", [])
                
                for s in source_seasons:
                    s_name = s.get("name", "Unnamed")
                    for p in s.get("periods", []):
                        old_s = p.get("start", "")
                        old_e = p.get("end", "")
                        new_s = adjust_date_string(old_s, days_offset)
                        new_e = adjust_date_string(old_e, days_offset)
                        
                        season_preview.append({
                            "Season": s_name,
                            "Old Range": f"{old_s} to {old_e}",
                            "New Range": f"{new_s} to {new_e}"
                        })
                
                if season_preview:
                    st.dataframe(pd.DataFrame(season_preview), use_container_width=True, hide_index=True)
                else:
                    st.warning("This resort has no seasons defined for the source year.")
        else:
            st.warning(f"No resorts found with data for {source_year}.")
    
    st.markdown("---")
    
    # Scope selection
    st.markdown("#### 🎯 What to Generate")
    
    col_scope1, col_scope2 = st.columns(2)
    with col_scope1:
        include_global_holidays = st.checkbox(
            "📅 Global Holidays",
            value=True,
            help="Create global holiday calendar for the new year"
        )
    with col_scope2:
        include_resorts = st.checkbox(
            "🏨 Resort Data (Seasons)",
            value=True,
            help="Create season dates for all resorts by applying the date offset"
        )
    
    if not include_global_holidays and not include_resorts:
        st.warning("⚠️ Please select at least one option to generate.")
        return
    
    if include_resorts and resorts_with_source:
        st.caption(f"Will generate data for **{len(resorts_with_source)} resorts** that have {source_year} data.")
    
    st.markdown("---")
    
    # Generate button
    col_btn1, col_btn2 = st.columns([3, 1])
    
    with col_btn1:
        if st.button(
            f"✨ Generate Year {target_year}",
            type="primary",
            use_container_width=True
        ):
            try:
                with st.spinner(f"Generating {target_year} from {source_year} with offset {days_offset}..."):
                    changes_made = []
                    
                    # Generate global holidays
                    if include_global_holidays:
                        new_global_holidays = generate_new_year_global_holidays(
                            data, source_year, target_year_str, days_offset
                        )
                        if new_global_holidays:
                            if "global_holidays" not in data:
                                data["global_holidays"] = {}
                            
                            data["global_holidays"][target_year_str] = new_global_holidays
                            changes_made.append(
                                f"✅ Created {len(new_global_holidays)} global holidays"
                            )
                    
                    # Generate resort data
                    if include_resorts:
                        resorts_updated = 0
                        for resort in data.get("resorts", []):
                            if source_year in resort.get("years", {}):
                                new_year_data = generate_new_year_for_resort(
                                    resort, source_year, target_year_str, days_offset
                                )
                                if new_year_data:
                                    resort["years"][target_year_str] = new_year_data
                                    resorts_updated += 1
                        
                        if resorts_updated > 0:
                            changes_made.append(
                                f"✅ Updated {resorts_updated} resorts"
                            )
                    
                    # Show success
                    if changes_made:
                        # CRITICAL FIX: Clear the "Working Resorts" cache. 
                        # This prevents the app from later overwriting your new 2028 data 
                        # with an old "in-progress" copy of the resort you were just looking at.
                        st.session_state.working_resorts = {} 
                        
                        save_data() # Update last save time
                        st.success(f"🎉 Successfully generated year {target_year}!")
                        for msg in changes_made:
                            st.write(msg)
                        
                        st.info("💾 The working memory has been refreshed. You can now download your updated JSON!")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("⚠️ No changes were made. Check your source year has data.")
                
            except Exception as e:
                st.error(f"❌ Error generating year: {str(e)}")
                import traceback
                with st.expander("🐛 Debug Info"):
                    st.code(traceback.format_exc())
    
    with col_btn2:
        if st.button("🔄 Reset", use_container_width=True):
            st.rerun()
# ----------------------------------------------------------------------
# GLOBAL SETTINGS (Maintenance Fees Removed)
# ----------------------------------------------------------------------
def render_global_holiday_dates_editor_v2(
    data: Dict[str, Any], years: List[str]
):
    global_holidays = data.setdefault("global_holidays", {})
    
    # Sort years descending: latest year first
    sorted_years = sorted(years, reverse=True)
    
    for year_idx, year in enumerate(sorted_years):
        holidays = global_holidays.setdefault(year, {})
        
        # Each entire year (holidays list + add new form) is now nested in an expander
        with st.expander(f"📆 {year}", expanded=(year_idx == 0)):  # Latest year expanded by default
            if not holidays:
                st.info("No global holidays defined for this year yet.")
            
            # Existing holidays
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
            
            # Separator before the "Add new" form
            st.markdown("---")
            
            # Form to add a new holiday for this year
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
            
            if st.button(
                "➕ Add Global Holiday",
                key=f"gh_add_{year}",
                use_container_width=True,
            ):
                if not new_name:
                    st.error("Please enter a holiday name.")
                elif new_name in holidays:
                    st.error(f"A holiday named '{new_name}' already exists for {year}.")
                else:
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
    
    # NEW: Year Generator
    with st.expander("📅 Year Generator (Clone & Offset)", expanded=False):
        render_year_generator(data)
        
    # Keep existing form-based editor as backup
    with st.expander("🎅 Global Holiday Calendar (Classic)", expanded=False):
        render_global_holiday_dates_editor_v2(data, years)

# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------
def run():
    initialize_session_state()
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                raw_data = json.load(f)
                if "schema_version" in raw_data and "resorts" in raw_data:
                    st.session_state.data = raw_data
                    st.toast(f"Auto-loaded {len(raw_data.get('resorts', []))} resorts", icon="✅")
        except FileNotFoundError:
            pass
        except Exception as e:
            st.toast(f"Auto-load error: {str(e)}", icon="⚠️")
    
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
            render_sidebar_actions(st.session_state.data, st.session_state.current_resort_id)
            create_download_button_v2(st.session_state.data)
            handle_file_verification()
   
    # Main content
    render_page_header(
        "Edit",
        "Resort Data",
        icon="🏨",
        badge_color="#EF4444" 
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
    
    render_resort_grid(resorts, current_resort_id)
    handle_resort_switch_v2(data, current_resort_id, previous_resort_id)
    
    working = load_resort(data, current_resort_id)
    if working:
        resort_name = (
            working.get("resort_name")
            or working.get("display_name")
            or current_resort_id
        )
        timezone = working.get("timezone", "UTC")
        address = working.get("address", "No address provided")
        
        render_resort_card(resort_name, timezone, address)
        render_save_button_v2(data, working, current_resort_id)
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            [
                "📊 Overview",
                "📅 Season Dates",
                "💰 Room Points",
                "🎄 Holidays",
                "📋 Spreadsheet",
            ]
        )
        with tab1:
            edit_resort_basics(working, current_resort_id)
            render_seasons_summary_table(working)
            render_holidays_summary_table(working)
        with tab2:
            render_validation_panel_v2(working, data, years)
            render_gantt_charts_v2(working, years, data)            
            render_season_dates_editor_v2(working, years, current_resort_id)
        with tab3:
            render_seasons_summary_table(working) 
            st.markdown("---")
            render_reference_points_editor_v2(working, years, current_resort_id) 
        with tab4:
            render_holidays_summary_table(working) 
            st.markdown("---")
            render_holiday_management_v2(working, years, current_resort_id, data) 
        with tab5:
            st.markdown("## 📊 Spreadsheet-Style Editors")
            st.info("✨ Excel-like editing with copy/paste, drag-fill, and multi-select. Changes auto-sync across years where applicable.")
    
            # Season dates (year-specific)
            with st.expander("📅 Edit Season Dates", expanded=False):
                render_season_dates_grid(working, current_resort_id)
    
            # Season points (applies to all years)
            with st.expander("🎯 Edit Season Points", expanded=False):
                # BASE_YEAR = "2025"  # or your preferred base year
                render_season_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)

            # Holiday points (applies to all years)
            with st.expander("🎄 Edit Holiday Points", expanded=False):
                render_holiday_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)
            st.markdown("---")
            render_excel_export_import(working, current_resort_id, data)
            
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

if __name__ == "__main__":
    run()
    current_resort_id = st.session_state.current_resort_id
    working = load_resort(data, current_resort_id)
    committed = find_resort_by_id(data, current_resort_id)

    # Visual Indicator Logic
    if working and committed and working != committed:
        st.warning("⚠️ You have unsaved changes in this resort. Data is NOT saved to memory yet.")
    elif working:
        st.caption("✅ All changes in this resort are saved to memory (Ready to Download).")
