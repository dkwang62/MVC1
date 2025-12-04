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
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ----------------------------------------------------------------------
# WIDGET KEY HELPER
# ----------------------------------------------------------------------
@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    """Build a unique Streamlit widget key scoped to a resort."""
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
def initialize_session_state():
    defaults = {
        "data": None,
        "current_resort_id": None,
        "previous_resort_id": None,
        "working_resorts": {},
        "last_save_time": None,
        "delete_confirm": False,
        "download_verified": False,
        "last_upload_sig": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def save_data():
    st.session_state.last_save_time = datetime.now()

# ----------------------------------------------------------------------
# HELPER FUNCTIONS
# ----------------------------------------------------------------------
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
    parts = [p for p in name.replace("'", "'").split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "RST"

def make_unique_resort_id(base_id: str, resorts: List[Dict[str, Any]]) -> str:
    existing = {r.get("id") for r in resorts}
    if base_id not in existing: return base_id
    i = 2
    while f"{base_id}-{i}" in existing: i += 1
    return f"{base_id}-{i}"

# ----------------------------------------------------------------------
# SANITIZATION (Critical for calculating summary)
# ----------------------------------------------------------------------
def sanitize_loaded_data(data: Dict[str, Any]) -> Dict[str, Any]:
    # Fix Day Patterns
    for r in data.get("resorts", []):
        for y_obj in r.get("years", {}).values():
            for s in y_obj.get("seasons", []):
                dc = s.get("day_categories", {})
                if not dc:
                    s["day_categories"] = {
                        "sun_thu": {"day_pattern": ["Sun", "Mon", "Tue", "Wed", "Thu"], "room_points": {}},
                        "fri_sat": {"day_pattern": ["Fri", "Sat"], "room_points": {}}
                    }
                else:
                    for cat_key, cat_val in dc.items():
                        if "day_pattern" not in cat_val or not cat_val["day_pattern"]:
                            if "fri" in cat_key.lower() or "sat" in cat_key.lower():
                                cat_val["day_pattern"] = ["Fri", "Sat"]
                            else:
                                cat_val["day_pattern"] = ["Sun", "Mon", "Tue", "Wed", "Thu"]
    return data

# ----------------------------------------------------------------------
# FILE OPERATIONS
# ----------------------------------------------------------------------
def handle_file_upload():
    st.sidebar.markdown("### 📤 File to Memory")
    with st.sidebar.expander("📤 Load", expanded=False):
        uploaded = st.file_uploader("Choose JSON file", type="json", key="file_uploader")
        if uploaded:
            size = getattr(uploaded, "size", 0)
            current_sig = f"{uploaded.name}:{size}"
            if current_sig != st.session_state.last_upload_sig:
                try:
                    raw_data = json.load(uploaded)
                    # SANITIZE
                    clean_data = sanitize_loaded_data(raw_data)
                    st.session_state.data = clean_data
                    st.session_state.last_upload_sig = current_sig
                    st.session_state.working_resorts = {}
                    st.session_state.current_resort_id = None
                    st.success(f"✅ Loaded {len(clean_data.get('resorts', []))} resorts")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

def create_download_button_v2(data: Dict[str, Any]):
    st.sidebar.markdown("### 📥 Memory to File")
    if "download_verified" not in st.session_state:
        st.session_state.download_verified = False

    with st.sidebar.expander("💾 Save & Download", expanded=False):
        current_id = st.session_state.get("current_resort_id")
        working_resorts = st.session_state.get("working_resorts", {})
        has_unsaved_changes = False
       
        if current_id and current_id in working_resorts:
            working_copy = working_resorts[current_id]
            committed_copy = find_resort_by_id(data, current_id)
            if committed_copy != working_copy:
                has_unsaved_changes = True

        if has_unsaved_changes:
            st.session_state.download_verified = False
            st.warning("⚠️ Unsaved changes pending.")
            if st.button("🧠 COMMIT TO MEMORY", type="primary", width="stretch"):
                commit_working_to_data_v2(data, working_resorts[current_id], current_id)
                st.toast("Committed to memory.", icon="✅")
                st.rerun()
        elif not st.session_state.download_verified:
            st.info("ℹ️ Memory updated.")
            if st.button("🔍 Verify that memory is up to date", width="stretch"):
                st.session_state.download_verified = True
                st.rerun()
        else:
            st.success("✅ Verified & Ready.")
            filename = st.text_input("File name", value="data_v2.json", key="download_filename_input").strip()
            if not filename: filename = "data_v2.json"
            if not filename.lower().endswith(".json"): filename += ".json"
            json_data = json.dumps(data, indent=2, ensure_ascii=False)
            st.download_button("⬇️ DOWNLOAD JSON FILE", data=json_data, file_name=filename, mime="application/json", key="download_v2_btn", type="primary", width="stretch")

def handle_file_verification():
    with st.sidebar.expander("🔍 Verify File", expanded=False):
        verify_upload = st.file_uploader("Upload file to compare", type="json", key="verify_uploader")
        if verify_upload:
            try:
                uploaded_data = json.load(verify_upload)
                current_json = json.dumps(st.session_state.data, sort_keys=True)
                uploaded_json = json.dumps(sanitize_loaded_data(uploaded_data), sort_keys=True)
                if current_json == uploaded_json: st.success("✅ File matches memory exactly.")
                else: st.error("❌ File differs from memory.")
            except Exception as e: st.error(f"❌ Error: {str(e)}")

def handle_merge_from_another_file_v2(data: Dict[str, Any]):
    with st.sidebar.expander("🔀 Merge", expanded=False):
        merge_upload = st.file_uploader("File with resorts", type="json", key="merge_uploader_v2")
        if merge_upload:
            try:
                merge_data = sanitize_loaded_data(json.load(merge_upload))
                target_resorts = data.setdefault("resorts", [])
                existing_ids = {r.get("id") for r in target_resorts}
                merge_resorts = merge_data.get("resorts", [])
                display_map = {f"{r.get('display_name', r.get('id'))} ({r.get('id')})": r for r in merge_resorts}
                selected_labels = st.multiselect("Select resorts", list(display_map.keys()), key="selected_merge_resorts_v2")
                if selected_labels and st.button("🔀 Merge", key="merge_btn_v2", width="stretch"):
                    merged_count = 0
                    for label in selected_labels:
                        resort_obj = display_map[label]
                        rid = resort_obj.get("id")
                        if rid not in existing_ids:
                            target_resorts.append(copy.deepcopy(resort_obj))
                            existing_ids.add(rid)
                            merged_count += 1
                    save_data()
                    if merged_count: st.success(f"✅ Merged {merged_count} resort(s)")
                    st.rerun()
            except Exception as e: st.error(f"❌ Error: {str(e)}")

# ----------------------------------------------------------------------
# RESORT MANAGEMENT
# ----------------------------------------------------------------------
def handle_resort_creation_v2(data: Dict[str, Any], current_resort_id: Optional[str]):
    resorts = data.setdefault("resorts", [])
    with st.expander("➕ Create or Clone Resort", expanded=False):
        tab_new, tab_clone = st.tabs(["✨ New Blank", "📋 Clone Current"])
        with tab_new:
            new_name = st.text_input("New Resort Name", key="new_resort_name_blank")
            if st.button("Create Blank Resort", width="stretch"):
                base_id = generate_resort_id(new_name)
                rid = make_unique_resort_id(base_id, resorts)
                new_resort = {
                    "id": rid, "display_name": new_name, "code": generate_resort_code(new_name),
                    "resort_name": new_name, "address": "", "timezone": "UTC", "years": {},
                }
                resorts.append(new_resort)
                st.session_state.current_resort_id = rid
                save_data()
                st.rerun()
        with tab_clone:
            if current_resort_id:
                if st.button("📋 Clone This Resort", width="stretch"):
                    src = find_resort_by_id(data, current_resort_id)
                    if src:
                        new_name = f"{src.get('display_name')} (Copy)"
                        cloned = copy.deepcopy(src)
                        cloned["id"] = make_unique_resort_id(generate_resort_id(new_name), resorts)
                        cloned["display_name"] = new_name
                        resorts.append(cloned)
                        st.session_state.current_resort_id = cloned["id"]
                        save_data()
                        st.rerun()

def handle_resort_deletion_v2(data: Dict[str, Any], current_resort_id: Optional[str]):
    if not current_resort_id: return
    if not st.session_state.delete_confirm:
        if st.button("🗑️ Delete Resort", key="delete_resort_init", type="secondary"):
            st.session_state.delete_confirm = True
            st.rerun()
    else:
        st.warning("Are you sure?")
        if st.button("🔥 CONFIRM DELETE", key="del_final", type="primary", width="stretch"):
            idx = find_resort_index(data, current_resort_id)
            if idx is not None: data.get("resorts", []).pop(idx)
            st.session_state.current_resort_id = None
            st.session_state.delete_confirm = False
            st.session_state.working_resorts.pop(current_resort_id, None)
            save_data()
            st.rerun()

def handle_resort_switch_v2(data: Dict[str, Any], current_resort_id: Optional[str], previous_resort_id: Optional[str]):
    if previous_resort_id and previous_resort_id != current_resort_id:
        working_resorts = st.session_state.working_resorts
        if previous_resort_id in working_resorts:
            working = working_resorts[previous_resort_id]
            committed = find_resort_by_id(data, previous_resort_id)
            if committed and working != committed:
                st.warning(f"⚠️ Unsaved changes in {committed.get('display_name')}")
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("Save changes", key="sw_save", width="stretch"):
                        commit_working_to_data_v2(data, working, previous_resort_id)
                        del working_resorts[previous_resort_id]
                        st.session_state.previous_resort_id = current_resort_id
                        st.rerun()
                with c2:
                    if st.button("Discard", key="sw_discard", width="stretch"):
                        del working_resorts[previous_resort_id]
                        st.session_state.previous_resort_id = current_resort_id
                        st.rerun()
                with c3:
                    if st.button("Stay", key="sw_stay", width="stretch"):
                        st.session_state.current_resort_id = previous_resort_id
                        st.rerun()
                st.stop()
    st.session_state.previous_resort_id = current_resort_id

def commit_working_to_data_v2(data: Dict[str, Any], working: Dict[str, Any], resort_id: str):
    idx = find_resort_index(data, resort_id)
    if idx is not None:
        data["resorts"][idx] = copy.deepcopy(working)
        save_data()

def render_save_button_v2(data: Dict[str, Any], working: Dict[str, Any], resort_id: str):
    committed = find_resort_by_id(data, resort_id)
    if committed is not None and committed != working:
        st.caption("Changes are in memory. You will be asked to save when switching resorts.")
    else:
        st.caption("Changes are in sync with memory.")

# ----------------------------------------------------------------------
# WORKING RESORT LOADER
# ----------------------------------------------------------------------
def load_resort(data: Dict[str, Any], current_resort_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not current_resort_id: return None
    working_resorts = st.session_state.working_resorts
    if current_resort_id not in working_resorts:
        if resort_obj := find_resort_by_id(data, current_resort_id):
            working_resorts[current_resort_id] = copy.deepcopy(resort_obj)
    return working_resorts.get(current_resort_id)

# ----------------------------------------------------------------------
# EDITORS
# ----------------------------------------------------------------------
def edit_resort_basics(working: Dict[str, Any], resort_id: str):
    st.markdown("### Basic Info")
    c1, c2 = st.columns([3, 1])
    with c1:
        dn = st.text_input("Display Name", value=working.get("display_name", ""), key=rk(resort_id, "dn"))
        if dn != working.get("display_name"): working["display_name"] = dn
    with c2:
        cd = st.text_input("Code", value=working.get("code", ""), key=rk(resort_id, "cd"))
        if cd != working.get("code"): working["code"] = cd
    
    rn = st.text_input("Official Name", value=working.get("resort_name", ""), key=rk(resort_id, "rn"))
    working["resort_name"] = rn
    
    c3, c4 = st.columns(2)
    with c3:
        tz = st.text_input("Timezone", value=working.get("timezone", "UTC"), key=rk(resort_id, "tz"))
        working["timezone"] = tz
    with c4:
        ad = st.text_area("Address", value=working.get("address", ""), key=rk(resort_id, "ad"), height=100)
        working["address"] = ad

def ensure_year_structure(resort: Dict[str, Any], year: str):
    years = resort.setdefault("years", {})
    year_obj = years.setdefault(year, {})
    year_obj.setdefault("seasons", [])
    year_obj.setdefault("holidays", [])
    return year_obj

def get_all_season_names_for_resort(working: Dict[str, Any]) -> Set[str]:
    names = set()
    for year_obj in working.get("years", {}).values():
        names.update(s.get("name") for s in year_obj.get("seasons", []) if s.get("name"))
    return names

def render_season_dates_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>📅 Season Dates</div>", unsafe_allow_html=True)
    
    # Add/Rename Seasons Logic
    for year in years:
        with st.expander(f"📆 {year} Seasons", expanded=True):
            c1, c2 = st.columns([4, 1])
            with c1: ns = st.text_input("New Season", key=rk(resort_id, "ns", year))
            with c2:
                if st.button("Add", key=rk(resort_id, "add_s", year)) and ns:
                    for y2 in years:
                        ensure_year_structure(working, y2).setdefault("seasons", []).append(
                            {"name": ns, "periods": [], "day_categories": {}}
                        )
                    st.rerun()

            year_obj = ensure_year_structure(working, year)
            for idx, season in enumerate(year_obj.get("seasons", [])):
                render_single_season_v2(working, year, season, idx, resort_id)

def render_single_season_v2(working: Dict[str, Any], year: str, season: Dict[str, Any], idx: int, resort_id: str):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**🎯 {sname}**")
    
    # TABLE-BASED EDITING (MY STYLE)
    periods = season.get("periods", [])
    df_data = [{"start": safe_date(p.get("start")), "end": safe_date(p.get("end"))} for p in periods]
    df = pd.DataFrame(df_data)
    
    wk = rk(resort_id, "se_edit", year, idx)
    edited_df = st.data_editor(
        df, key=wk, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "start": st.column_config.DateColumn("Start", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End", format="YYYY-MM-DD", required=True)
        }
    )
    
    # Save back
    new_periods = []
    for _, row in edited_df.iterrows():
        if pd.notnull(row["start"]) and pd.notnull(row["end"]):
            new_periods.append({
                "start": row["start"].isoformat() if hasattr(row["start"], 'isoformat') else str(row["start"]),
                "end": row["end"].isoformat() if hasattr(row["end"], 'isoformat') else str(row["end"])
            })
    season["periods"] = new_periods

def get_all_room_types_for_resort(working: Dict[str, Any]) -> List[str]:
    rooms = set()
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                rooms.update(cat.get("room_points", {}).keys())
        for h in year_obj.get("holidays", []):
            rooms.update(h.get("room_points", {}).keys())
    return sorted(rooms)

def sync_season_room_points_across_years(working: Dict[str, Any], base_year: str):
    years = working.get("years", {})
    if base_year not in years: return
    
    # Sync Logic from Grok
    canonical_rooms = set()
    for y_obj in years.values():
        for season in y_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                canonical_rooms.update(cat.get("room_points", {}).keys())

    base_seasons = years[base_year].get("seasons", [])
    base_by_name = {s.get("name"): s for s in base_seasons if s.get("name")}

    for year_name, year_obj in years.items():
        if year_name != base_year:
            for season in year_obj.get("seasons", []):
                if (name := season.get("name")) in base_by_name:
                    season["day_categories"] = copy.deepcopy(base_by_name[name].get("day_categories", {}))

def render_reference_points_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>🎯 Master Room Points</div>", unsafe_allow_html=True)
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
    base_year_obj = ensure_year_structure(working, base_year)
    
    canonical_rooms = get_all_room_types_for_resort(working)

    # MASTER ADD ROOM
    c1, c2 = st.columns(2)
    with c1:
        nr = st.text_input("Add Room Type", key=rk(resort_id, "new_room"))
        if st.button("Add Room", key=rk(resort_id, "add_room_btn")) and nr:
             for y in working.get("years", {}).values():
                for s in y.get("seasons", []):
                    for c in s.get("day_categories", {}).values():
                        c.setdefault("room_points", {})[nr] = 0
                for h in y.get("holidays", []):
                    h.setdefault("room_points", {})[nr] = 0
             st.rerun()

    for s_idx, season in enumerate(base_year_obj.get("seasons", [])):
        with st.expander(f"🏖️ {season.get('name')}", expanded=True):
            dc = season.setdefault("day_categories", {})
            if not dc:
                dc["sun_thu"] = {"day_pattern": ["Sun", "Mon", "Tue", "Wed", "Thu"], "room_points": {}}
                dc["fri_sat"] = {"day_pattern": ["Fri", "Sat"], "room_points": {}}
            
            for key, cat in dc.items():
                st.markdown(f"**📅 {key}**")
                
                # DAY PATTERN EDITOR
                curr_days = cat.get("day_pattern", [])
                new_days = st.multiselect("Days", WEEKDAYS, default=curr_days, key=rk(resort_id, "dp", base_year, s_idx, key))
                cat["day_pattern"] = new_days

                # POINTS TABLE EDITOR (MY STYLE)
                rp = cat.setdefault("room_points", {})
                df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in canonical_rooms]
                df = pd.DataFrame(df_data)
                
                wk = rk(resort_id, "rp_ed", base_year, s_idx, key)
                edited_df = st.data_editor(
                    df, key=wk, width="stretch", hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    }
                )
                
                # Update Dict
                new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
                cat["room_points"] = new_rp
    
    sync_season_room_points_across_years(working, base_year)

def render_holiday_management_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>🎄 Holiday Management</div>", unsafe_allow_html=True)
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
    
    # Simple Holiday List & Points
    holidays_map = {}
    for y_obj in working.get("years", {}).values():
        for h in y_obj.get("holidays", []):
            k = h.get("global_reference") or h.get("name")
            if k and k not in holidays_map: holidays_map[k] = h

    if holidays_map:
        for k, h in holidays_map.items():
            c1, c2 = st.columns([3, 1])
            with c1: st.text_input("Name", value=h.get("name"), disabled=True, key=rk(resort_id, "hn", k))
            with c2: 
                 if st.button("🗑️", key=rk(resort_id, "hd", k)):
                     for y_obj in working.get("years", {}).values():
                         y_obj["holidays"] = [x for x in y_obj.get("holidays", []) if (x.get("global_reference") or x.get("name")) != k]
                     st.rerun()

    st.markdown("**➕ Add New Holiday**")
    c1, c2 = st.columns([3, 1])
    with c1: nh = st.text_input("Holiday Name", key=rk(resort_id, "new_h_name"))
    with c2:
        if st.button("Add", key=rk(resort_id, "add_h_btn")) and nh:
            for y_obj in working.get("years", {}).values():
                if not any((x.get("global_reference") == nh) for x in y_obj.get("holidays", [])):
                    y_obj.setdefault("holidays", []).append({"name": nh, "global_reference": nh, "room_points": {}})
            st.rerun()
    
    st.markdown("---")
    st.markdown("**💰 Master Holiday Points**")
    
    base_year_obj = ensure_year_structure(working, base_year)
    canonical_rooms = get_all_room_types_for_resort(working)

    for idx, h in enumerate(base_year_obj.get("holidays", [])):
        with st.expander(f"🎊 {h.get('name')}", expanded=False):
            rp = h.setdefault("room_points", {})
            df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in canonical_rooms]
            df = pd.DataFrame(df_data)
            wk = rk(resort_id, "hp_ed", base_year, idx)
            edited_df = st.data_editor(
                df, key=wk, width="stretch", hide_index=True,
                column_config={
                    "Room Type": st.column_config.TextColumn(disabled=True),
                    "Points": st.column_config.NumberColumn(min_value=0, step=25)
                }
            )
            new_rp = dict(zip(edited_df["Room Type"], edited_df["Points"]))
            h["room_points"] = new_rp
    
    # Sync holidays across years
    base_holidays = base_year_obj.get("holidays", [])
    base_map = { (h.get("global_reference") or h.get("name")): h for h in base_holidays }
    for y, y_obj in working.get("years", {}).items():
        if y != base_year:
            for h in y_obj.get("holidays", []):
                k = h.get("global_reference") or h.get("name")
                if k in base_map:
                    h["room_points"] = copy.deepcopy(base_map[k].get("room_points", {}))

def render_resort_summary_v2(working: Dict[str, Any]):
    st.markdown("<div class='section-header'>📊 Resort Summary</div>", unsafe_allow_html=True)
    room_types = get_all_room_types_for_resort(working)
    if not room_types:
        st.info("No room types.")
        return

    years = sorted(working.get("years", {}).keys())
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (years[0] if years else "2025")
    
    if base_year not in working.get("years", {}):
        st.warning(f"No data for {base_year}")
        return

    ref_year_data = working["years"][base_year]
    rows = []

    def calc_weekly(season):
        total = {r: 0 for r in room_types}
        has_data = False
        valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        for cat in season.get("day_categories", {}).values():
            pat = cat.get("day_pattern", [])
            count = len([d for d in pat if d in valid_days])
            rp = cat.get("room_points", {})
            if count > 0:
                for r in room_types:
                    val = rp.get(r)
                    if val is not None:
                        total[r] += int(val) * count
                        has_data = True
        return total, has_data

    for s in ref_year_data.get("seasons", []):
        t, ok = calc_weekly(s)
        if ok:
            r = {"Season": s.get("name")}
            r.update({k: (v if v else "—") for k, v in t.items()})
            rows.append(r)
            
    for h in ref_year_data.get("holidays", []):
        rp = h.get("room_points", {})
        r = {"Season": f"Holiday - {h.get('name')}"}
        r.update({rt: (rp.get(rt) if rp.get(rt) else "—") for rt in room_types})
        rows.append(r)

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df.astype(str), width="stretch", hide_index=True)

def render_global_settings_v2(data: Dict[str, Any], years: List[str]):
    st.markdown("<div class='section-header'>⚙️ Global Configuration</div>", unsafe_allow_html=True)
    with st.expander("💰 Maintenance Fees", expanded=False):
        rates = data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
        for y in sorted(years):
            val = st.number_input(f"{y}", value=float(rates.get(y, 0)), step=0.01, key=f"mf_{y}")
            if val != rates.get(y):
                rates[y] = val
                save_data()

    with st.expander("🎅 Global Holiday Calendar", expanded=False):
        gh = data.setdefault("global_holidays", {})
        sel_year = st.selectbox("Select Year", years, key="gh_year")
        if sel_year not in gh: gh[sel_year] = []
        
        holidays = gh[sel_year]
        for idx, h in enumerate(holidays):
            # Sanitization Check
            if isinstance(h, str): h = {"name": h, "date": f"{sel_year}-01-01"}
            
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1: 
                h["name"] = st.text_input("Name", value=h.get("name"), key=f"ghn_{sel_year}_{idx}")
            with c2: 
                h["date"] = str(st.date_input("Date", safe_date(h.get("date")), key=f"ghd_{sel_year}_{idx}"))
            with c3:
                if st.button("🗑️", key=f"ghdel_{sel_year}_{idx}"):
                    holidays.pop(idx)
                    st.rerun()

        if st.button("➕ Add Global Holiday", key=f"gh_add_{sel_year}"):
            holidays.append({"name": "New Holiday", "date": f"{sel_year}-01-01"})
            st.rerun()

# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------
def run():
    initialize_session_state()
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = sanitize_loaded_data(json.load(f))
                st.toast("Loaded data_v2.json")
        except: pass

    with st.sidebar:
        st.divider()
        handle_file_upload()
        if st.session_state.data:
            handle_merge_from_another_file_v2(st.session_state.data)
            create_download_button_v2(st.session_state.data)
            handle_file_verification()
   
    render_page_header("Edit", "Creating Your Data File", icon="🏨", badge_color="#EF4444")

    if not st.session_state.data:
        st.info("Please load a file.")
        return

    data = st.session_state.data
    resorts = get_resort_list(data)
    years = get_years_from_data(data)
    
    render_resort_grid(resorts, st.session_state.current_resort_id)
    handle_resort_switch_v2(data, st.session_state.current_resort_id, st.session_state.previous_resort_id)

    working = load_resort(data, st.session_state.current_resort_id)
    if working:
        render_resort_card(working.get("display_name"), working.get("timezone"), working.get("address"))
        render_save_button_v2(data, working, st.session_state.current_resort_id)
        
        handle_resort_creation_v2(data, st.session_state.current_resort_id)
        handle_resort_deletion_v2(data, st.session_state.current_resort_id)
        
        t1, t2, t3, t4, t5 = st.tabs(["Overview", "Seasons", "Points", "Holidays", "Summary"])
        
        with t1: edit_resort_basics(working, st.session_state.current_resort_id)
        with t2: 
            render_gantt_charts_v2(working, years, data)
            render_season_dates_editor_v2(working, years, st.session_state.current_resort_id)
        with t3: render_reference_points_editor_v2(working, years, st.session_state.current_resort_id)
        with t4: render_holiday_management_v2(working, years, st.session_state.current_resort_id)
        with t5: render_resort_summary_v2(working)

    st.markdown("---")
    render_global_settings_v2(data, years)

def render_gantt_charts_v2(working, years, data):
    from common.charts import create_gantt_chart_from_working
    tabs = st.tabs(years)
    for t, y in zip(tabs, years):
        with t:
            fig = create_gantt_chart_from_working(working, y, data, height=400)
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    run()
