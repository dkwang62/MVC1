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
from dataclasses import dataclass  # ← NEW IMPORT FOR INTEGRITY CHECKER

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
            key=rk(resort_id, "delete_season", year, idx),
            type="secondary"
        ):
            if st.session_state.get(rk(resort_id, "confirm_delete", year, idx)):
                del seasons[idx]
                st.success(f"Deleted season '{sname}' for {year}")
                st.rerun()
            else:
                st.session_state[rk(resort_id, "confirm_delete", year, idx)] = True
                st.warning("Click again to confirm deletion")
                st.rerun()

# ----------------------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------------------
def validate_resort_data_v2(
    working: Dict[str, Any], data: Dict[str, Any], years: List[str]
) -> List[str]:
    issues: List[str] = []
    global_holidays = data.get("global_holidays", {})

    # Collect all room types across all seasons/holidays
    all_rooms: Set[str] = set()
    for year in years:
        year_obj = working.get("years", {}).get(year)
        if not year_obj:
            continue
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    all_rooms.update(rp.keys())
        for h in year_obj.get("holidays", []):
            if isinstance(rp := h.get("room_points", {}), dict):
                all_rooms.update(rp.keys())

    for year in years:
        year_obj = working.get("years", {}).get(year)
        if not year_obj:
            issues.append(f"[{year}] No year data defined")
            continue

        # Season room coverage
        for s in year_obj.get("seasons", []):
            sname = s.get("name", "(Unnamed)")
            season_rooms: Set[str] = set()
            for cat in s.get("day_categories", {}).values():
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
    source_date = datetime(source_year, 1, 1)
    target_date = datetime(target_year, 1, 1)
    delta = target_date - source_date
    return delta.days

def adjust_date_string(date_str: str, days_offset: int) -> str:
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
    source_year_data = resort.get("years", {}).get(source_year)
    if not source_year_data:
        return {}
    new_year_data = copy.deepcopy(source_year_data)
    for season in new_year_data.get("seasons", []):
        for period in season.get("periods", []):
            if "start" in period:
                period["start"] = adjust_date_string(period["start"], days_offset)
            if "end" in period:
                period["end"] = adjust_date_string(period["end"], days_offset)
    return new_year_data

def render_year_generator(data: Dict[str, Any]):
    st.info("""
    **💡 How it works:**
    1. Select a source year to copy from.
    2. Enter the new target year.
    3. **Adjust the Date Offset:** Use **364** to keep the same day of the week, or **365/366** for the same calendar date.
    4. **Preview:** Check both Holidays and Resort Seasons to ensure alignment.
    """)
    
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
    
    if target_year_str in existing_years:
        st.error(f"❌ Year {target_year} already exists! Choose a different target year or delete the existing one first.")
        return
    
    st.markdown("---")

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

    st.markdown("#### 📊 Preview")
    
    pv_tab1, pv_tab2 = st.tabs(["🌎 Global Holidays", "🏨 Resort Seasons"])
    
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

    with pv_tab2:
        resorts = data.get("resorts", [])
        resorts_with_source = [r for r in resorts if source_year in r.get("years", {})]
        
        if resorts_with_source:
            sample_resort_name = st.selectbox(
                "Select a resort to preview season shifts:",
                options=[r.get("display_name") for r in resorts_with_source],
                key="season_preview_resort_select"
            )
            
            sample_resort = next((r for r in resorts_with_source if r.get("display_name") == sample_resort_name), None)
            
            if sample_resort:
                season_preview = []
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
                    
                    if changes_made:
                        st.session_state.working_resorts = {} 
                        
                        save_data()
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
# GLOBAL SETTINGS
# ----------------------------------------------------------------------
def render_global_holiday_dates_editor_v2(
    data: Dict[str, Any], years: List[str]
):
    global_holidays = data.setdefault("global_holidays", {})
    
    sorted_years = sorted(years, reverse=True)
    
    for year_idx, year in enumerate(sorted_years):
        holidays = global_holidays.setdefault(year, {})
        
        with st.expander(f"📆 {year}", expanded=(year_idx == 0)):
            if not holidays:
                st.info("No global holidays defined for this year yet.")
            
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
    
    with st.expander("📅 Year Generator (Clone & Offset)", expanded=False):
        render_year_generator(data)
        
    with st.expander("🎅 Global Holiday Calendar (Classic)", expanded=False):
        render_global_holiday_dates_editor_v2(data, years)

# ----------------------------------------------------------------------
# DATA INTEGRITY CHECKER (NEW SECTION – ADDED FROM editor_integrity_checker.py)
# ----------------------------------------------------------------------
@dataclass
class ResortVarianceResult:
    """Results of variance check for a single resort."""
    resort_name: str
    points_2025: int
    points_2026: int
    variance_points: int
    variance_percent: float
    status: str  # "NORMAL", "WARNING", "ERROR"
    status_icon: str
    status_message: str


class EditorPointAuditor:
    """Audits point data integrity by comparing year-over-year variance."""
    
    def __init__(self, data_dict: Dict):
        self.data = data_dict
        self.global_holidays = data_dict.get("global_holidays", {})
    
    def calculate_annual_total(self, resort_id: str, year: int) -> int:
        """Calculate total points for ALL room types in a specific year."""
        resort = next((r for r in self.data['resorts'] if r['id'] == resort_id), None)
        if not resort:
            return 0
        
        year_str = str(year)
        if year_str not in resort.get('years', {}):
            return 0
        
        y_data = resort['years'][year_str]
        total_points = 0
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        current_date = start_date
        
        while current_date <= end_date:
            day_points = self._get_points_for_date(resort, year, current_date)
            total_points += sum(day_points.values())
            current_date += timedelta(days=1)
        
        return total_points
    
    def _get_points_for_date(self, resort: Dict, year: int, target_date: date) -> Dict[str, int]:
        year_str = str(year)
        y_data = resort['years'].get(year_str, {})
        
        # 1. Check holidays first
        for h in y_data.get('holidays', []):
            ref = h.get('global_reference')
            g_h = self.global_holidays.get(year_str, {}).get(ref, {})
            if g_h:
                h_start = datetime.strptime(g_h['start_date'], '%Y-%m-%d').date()
                h_end = datetime.strptime(g_h['end_date'], '%Y-%m-%d').date()
                if h_start <= target_date <= h_end:
                    return h.get('room_points', {})
        
        # 2. Check seasons
        day_name = target_date.strftime('%a')
        for s in y_data.get('seasons', []):
            for p in s.get('periods', []):
                try:
                    p_start = datetime.strptime(p['start'], '%Y-%m-%d').date()
                    p_end = datetime.strptime(p['end'], '%Y-%m-%d').date()
                    if p_start <= target_date <= p_end:
                        for cat in s.get('day_categories', {}).values():
                            if day_name in cat.get('day_pattern', []):
                                return cat.get('room_points', {})
                except:
                    continue
        
        return {}
    
    def check_resort_variance(
        self, 
        baseline_id: str, 
        target_id: str, 
        tolerance_percent: float
    ) -> Tuple[ResortVarianceResult, ResortVarianceResult]:
        baseline_resort = next((r for r in self.data['resorts'] if r['id'] == baseline_id), None)
        target_resort = next((r for r in self.data['resorts'] if r['id'] == target_id), None)
        
        baseline_name = baseline_resort.get('display_name', baseline_id) if baseline_resort else baseline_id
        target_name = target_resort.get('display_name', target_id) if target_resort else target_id
        
        baseline_2025 = self.calculate_annual_total(baseline_id, 2025)
        baseline_2026 = self.calculate_annual_total(baseline_id, 2026)
        baseline_variance = baseline_2026 - baseline_2025
        baseline_percent = (baseline_variance / baseline_2025 * 100) if baseline_2025 > 0 else 0
        
        baseline_result = ResortVarianceResult(
            resort_name=baseline_name,
            points_2025=baseline_2025,
            points_2026=baseline_2026,
            variance_points=baseline_variance,
            variance_percent=baseline_percent,
            status="BASELINE",
            status_icon="📊",
            status_message="Reference standard"
        )
        
        target_2025 = self.calculate_annual_total(target_id, 2025)
        target_2026 = self.calculate_annual_total(target_id, 2026)
        target_variance = target_2026 - target_2025
        target_percent = (target_variance / target_2025 * 100) if target_2025 > 0 else 0
        
        percent_diff = abs(target_percent - baseline_percent)
        
        if target_variance < 0:
            status = "ERROR"
            icon = "🚨"
            message = "Negative variance detected - 2026 has fewer points than 2025"
        elif percent_diff > (tolerance_percent * 2):
            status = "ERROR"
            icon = "🚨"
            message = f"Variance differs from baseline by {percent_diff:.2f}% (threshold: {tolerance_percent * 2:.1f}%)"
        elif percent_diff > tolerance_percent:
            status = "WARNING"
            icon = "⚠️"
            message = f"Variance differs from baseline by {percent_diff:.2f}% (threshold: {tolerance_percent:.1f}%)"
        else:
            status = "NORMAL"
            icon = "✅"
            message = f"Variance within tolerance ({percent_diff:.2f}% difference from baseline)"
        
        target_result = ResortVarianceResult(
            resort_name=target_name,
            points_2025=target_2025,
            points_2026=target_2026,
            variance_points=target_variance,
            variance_percent=target_percent,
            status=status,
            status_icon=icon,
            status_message=message
        )
        
        return baseline_result, target_result


def render_data_integrity_tab(data: Dict, current_resort_id: str):
    st.markdown("## 🔍 Data Quality Assurance")
    st.markdown("Verify data integrity by comparing 2025-2026 point variance across resorts.")
    
    resorts = data.get('resorts', [])
    resort_options = {r.get('display_name', r['id']): r['id'] for r in resorts}
    resort_names = list(resort_options.keys())
    
    current_resort = next((r for r in resorts if r['id'] == current_resort_id), None)
    current_name = current_resort.get('display_name', current_resort_id) if current_resort else ""
    
    st.info(f"📍 **Currently editing:** {current_name}")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        baseline_label = "Baseline Resort for Comparison"
        if "editor_baseline_check_result" in st.session_state:
            cached_baseline = st.session_state.editor_baseline_check_result.resort_name
            baseline_label = f"Baseline Resort (Current: {cached_baseline})"
        
        selected_baseline_name = st.selectbox(
            baseline_label,
            options=resort_names,
            index=0 if resort_names else 0,
            help="Select a resort with verified data to use as reference",
            key="editor_baseline_selector"
        )
        
        selected_baseline_id = resort_options.get(selected_baseline_name)
        
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Clear", use_container_width=True, help="Clear results"):
            if "editor_integrity_check_result" in st.session_state:
                del st.session_state.editor_integrity_check_result
            if "editor_baseline_check_result" in st.session_state:
                del st.session_state.editor_baseline_check_result
            st.rerun()
    
    st.caption(f"ℹ️ {selected_baseline_name} will be recalculated fresh to ensure accuracy")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        tolerance = st.slider(
            "Variance Tolerance (%)",
            min_value=0.0,
            max_value=20.0,
            value=5.0,
            step=0.5,
            help=f"Alert thresholds: Warning above tolerance, Error above 2× tolerance",
            key="editor_tolerance_slider"
        )
    
    with col2:
        check_button = st.button(
            "🔍 Check Data", 
            use_container_width=True, 
            type="primary",
            help=f"Compare {current_name} against {selected_baseline_name}"
        )
    
    if check_button:
        with st.spinner(f"Calculating annual points for {selected_baseline_name} and {current_name}..."):
            auditor = EditorPointAuditor(data)
            
            try:
                baseline_result, target_result = auditor.check_resort_variance(
                    selected_baseline_id, 
                    current_resort_id, 
                    tolerance
                )
                
                if baseline_result.points_2025 == 0 and baseline_result.points_2026 == 0:
                    st.error(f"❌ No point data found for {selected_baseline_name}. Check that 2025 and 2026 years exist with seasons/holidays.")
                    return
                
                if target_result.points_2025 == 0 and target_result.points_2026 == 0:
                    st.error(f"❌ No point data found for {current_name}. Check that 2025 and 2026 years exist with seasons/holidays.")
                    return
                
                st.session_state.editor_integrity_check_result = target_result
                st.session_state.editor_baseline_check_result = baseline_result
                st.rerun()
                
            except Exception as e:
                st.error(f"Error during calculation: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
                return
    
    if ("editor_integrity_check_result" in st.session_state and 
        "editor_baseline_check_result" in st.session_state):
        
        baseline = st.session_state.editor_baseline_check_result
        target = st.session_state.editor_integrity_check_result
        
        st.divider()
        
        st.markdown(f"### 📊 {baseline.resort_name} (Baseline Reference)")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("2025 Total Points", f"{baseline.points_2025:,}")
        with col2:
            st.metric("2026 Total Points", f"{baseline.points_2026:,}")
        with col3:
            st.metric(
                "Variance", 
                f"+{baseline.variance_points:,} pts",
                f"+{baseline.variance_percent:.2f}%"
            )
        
        st.caption("Expected variance due to leap year (2026 has 366 days)")
        
        st.divider()
        
        st.markdown(f"### 📍 {target.resort_name} (Current Resort)")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("2025 Total Points", f"{target.points_2025:,}")
        with col2:
            st.metric("2026 Total Points", f"{target.points_2026:,}")
        with col3:
            st.metric(
                "Variance", 
                f"{'+' if target.variance_points >= 0 else ''}{target.variance_points:,} pts",
                f"{'+' if target.variance_percent >= 0 else ''}{target.variance_percent:.2f}%"
            )
        
        st.divider()
        
        st.markdown("### ⚖️ Comparison Analysis")
        
        percent_diff = abs(target.variance_percent - baseline.variance_percent)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(f"{baseline.resort_name}", f"{baseline.variance_percent:.2f}%")
        with col2:
            st.metric(f"{target.resort_name}", f"{target.variance_percent:.2f}%")
        with col3:
            st.metric("Difference", f"{percent_diff:.2f}%")
        
        if target.status == "ERROR":
            st.error(f"{target.status_icon} **{target.status}**: {target.status_message}")
            st.markdown("**Recommended Actions:**")
            st.markdown("- Review season periods for missing or overlapping dates")
            st.markdown("- Check holiday definitions for 2026")
            st.markdown("- Verify room point values weren't accidentally changed")
        elif target.status == "WARNING":
            st.warning(f"{target.status_icon} **{target.status}**: {target.status_message}")
            st.markdown("**Suggested Actions:**")
            st.markdown("- Review data for potential inconsistencies")
            st.markdown("- Compare with baseline to understand differences")
        else:
            st.success(f"{target.status_icon} **{target.status}**: {target.status_message}")
        
        with st.expander("ℹ️ Understanding Results"):
            st.markdown("""
            **Status Levels:**
            - ✅ **NORMAL**: Data appears consistent with baseline pattern
            - ⚠️ **WARNING**: Some variance detected - review recommended
            - 🚨 **ERROR**: Significant issues found - likely data entry error
            
            **Common Causes of Variance:**
            - **Leap Year Effect**: 2026 has 366 days (one extra day) - typically adds ~0.27% points
            - **Missing Dates**: Gaps in season coverage leave days without point values
            - **Season Pattern Changes**: Different high/low season distribution between years
            - **Holiday Shifts**: Holidays falling on different dates/day-of-week
            
            **Typical Issues:**
            - **Negative variance**: 2026 incomplete or has fewer days covered
            - **Zero variance**: Likely copied 2025 data to 2026 without adjustments
            - **Excessive variance**: Point values changed or duplicate entries
            - **Zero points**: Years not defined or missing seasons/holidays
            
            **Using This Tool:**
            1. Choose a baseline resort you know has accurate data
            2. Set tolerance based on how strictly you want to validate
            3. Check each resort you're editing against the baseline
            4. Fix any ERRORs before saving
            5. Review WARNINGs to understand if differences are intentional
            """)
    else:
        st.info("👆 Select a baseline resort and click 'Check Data' to validate this resort's data quality")

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
        
        # ← MODIFIED TABS TO INCLUDE NEW DATA QUALITY TAB
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            [
                "📊 Overview",
                "📅 Season Dates",
                "💰 Room Points",
                "🎄 Holidays",
                "📋 Spreadsheet",
                "🔍 Data Quality",
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
    
            with st.expander("📅 Edit Season Dates", expanded=False):
                render_season_dates_grid(working, current_resort_id)
    
            with st.expander("🎯 Edit Season Points", expanded=False):
                render_season_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)

            with st.expander("🎄 Edit Holiday Points", expanded=False):
                render_holiday_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)
            st.markdown("---")
            render_excel_export_import(working, current_resort_id, data)
        
        # ← NEW TAB CONTENT
        with tab6:
            render_data_integrity_tab(data, current_resort_id)
            
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
