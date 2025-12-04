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
            st.session_state[k] = v


def save_data():
    """
    CRITICAL FIX: This function now commits changes to the main data
    structure. It is designed to be called inside callbacks to ensure
    freshness before re-renders.
    """
    st.session_state.last_save_time = datetime.now()
    
    rid = st.session_state.get("current_resort_id")
    data = st.session_state.get("data")
    working_resorts = st.session_state.get("working_resorts", {})
    
    if rid and data and rid in working_resorts:
        commit_working_to_data_v2(data, working_resorts[rid], rid)

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
        uploaded = st.file_uploader("Choose JSON file", type="json", key="file_uploader")
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
    
    # Because we use callbacks, 'data' is guaranteed to be fresh here.
    with st.sidebar.expander("💾 Save & Download", expanded=False):
        st.success("✅ Auto-Saved & Ready")
        
        filename = st.text_input("File name", value="data_v2.json", key="download_filename_input").strip()
        if not filename: filename = "data_v2.json"
        if not filename.lower().endswith(".json"): filename += ".json"
            
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        
        st.download_button(
            label="⬇️ DOWNLOAD JSON FILE",
            data=json_data,
            file_name=filename,
            mime="application/json",
            key="download_v2_btn",
            type="primary",
            use_container_width=True,
        )

def handle_file_verification():
    with st.sidebar.expander("🔍 Verify File", expanded=False):
        verify_upload = st.file_uploader("Upload file to compare", type="json", key="verify_uploader")
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

def handle_merge_from_another_file_v2(data: Dict[str, Any]):
    with st.sidebar.expander("🔀 Merge", expanded=False):
        merge_upload = st.file_uploader("File with resorts", type="json", key="merge_uploader_v2")
        if merge_upload:
            try:
                merge_data = json.load(merge_upload)
                target_resorts = data.setdefault("resorts", [])
                existing_ids = {r.get("id") for r in target_resorts}
                merge_resorts = merge_data.get("resorts", [])
                
                display_map = {f"{r.get('display_name', r.get('id'))} ({r.get('id')})": r for r in merge_resorts}
                selected_labels = st.multiselect("Select resorts", list(display_map.keys()), key="selected_merge_resorts_v2")

                if selected_labels and st.button("🔀 Merge", key="merge_btn_v2", use_container_width=True):
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
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")


# ----------------------------------------------------------------------
# RESORT MANAGEMENT
# ----------------------------------------------------------------------
def is_duplicate_resort_name(name: str, resorts: List[Dict[str, Any]]) -> bool:
    target = name.strip().lower()
    return any(r.get("display_name", "").strip().lower() == target for r in resorts)

def handle_resort_creation_v2(data: Dict[str, Any], current_resort_id: Optional[str]):
    resorts = data.setdefault("resorts", [])
    with st.expander("➕ Create or Clone Resort", expanded=False):
        tab_new, tab_clone = st.tabs(["✨ New Blank", "📋 Clone Current"])
        with tab_new:
            new_name = st.text_input("New Resort Name", key="new_resort_name_blank")
            if st.button("Create Blank Resort", use_container_width=True):
                if new_name and not is_duplicate_resort_name(new_name, resorts):
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
                if st.button("📋 Clone This Resort", use_container_width=True):
                    src = find_resort_by_id(data, current_resort_id)
                    if src:
                        new_name = f"{src.get('display_name')} (Copy)"
                        counter = 1
                        while is_duplicate_resort_name(new_name, resorts):
                            counter += 1
                            new_name = f"{src.get('display_name')} (Copy {counter})"
                        cloned = copy.deepcopy(src)
                        cloned["id"] = make_unique_resort_id(generate_resort_id(new_name), resorts)
                        cloned["display_name"] = new_name
                        cloned["resort_name"] = new_name
                        cloned["code"] = generate_resort_code(new_name)
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
        st.warning("Are you sure you want to delete this resort?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔥 DELETE", key="del_final", type="primary", use_container_width=True):
                idx = find_resort_index(data, current_resort_id)
                if idx is not None: data.get("resorts", []).pop(idx)
                st.session_state.current_resort_id = None
                st.session_state.delete_confirm = False
                st.session_state.working_resorts.pop(current_resort_id, None)
                save_data()
                st.rerun()
        with c2:
            if st.button("Cancel", key="del_cancel", use_container_width=True):
                st.session_state.delete_confirm = False
                st.rerun()


# ----------------------------------------------------------------------
# WORKING RESORT SWITCHING
# ----------------------------------------------------------------------
def handle_resort_switch_v2(data: Dict[str, Any], current_resort_id: Optional[str], previous_resort_id: Optional[str]):
    # Silent auto-save on switch
    if previous_resort_id and previous_resort_id != current_resort_id:
        working_resorts = st.session_state.working_resorts
        if previous_resort_id in working_resorts:
            commit_working_to_data_v2(data, working_resorts[previous_resort_id], previous_resort_id)
            del working_resorts[previous_resort_id]
    st.session_state.previous_resort_id = current_resort_id

def commit_working_to_data_v2(data: Dict[str, Any], working: Dict[str, Any], resort_id: str):
    idx = find_resort_index(data, resort_id)
    if idx is not None:
        data["resorts"][idx] = copy.deepcopy(working)


# ----------------------------------------------------------------------
# CALLBACK HANDLERS (CRITICAL FOR FIXING "TYPE TWICE")
# ----------------------------------------------------------------------
def on_basic_info_change(key: str, field: str):
    """Updates working resort immediately when input changes, then saves."""
    rid = st.session_state.current_resort_id
    val = st.session_state[key]
    if rid and rid in st.session_state.working_resorts:
        st.session_state.working_resorts[rid][field] = val
        save_data()

def on_global_rate_change(key: str, year: str):
    """Updates maintenance rates immediately."""
    val = st.session_state[key]
    data = st.session_state.data
    if data:
        rates = data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
        rates[year] = val
        # Global settings don't use 'working_resorts', they save directly to 'data'
        # But we explicitly trigger save_timestamp/sync logic if needed
        st.session_state.last_save_time = datetime.now()


# ----------------------------------------------------------------------
# RESORT EDITING UI
# ----------------------------------------------------------------------
def edit_resort_basics(working: Dict[str, Any], resort_id: str):
    st.markdown("### Basic Info")
    
    # NOTE: We use on_change callbacks. The 'value' is set from 'working',
    # but the update happens in the callback BEFORE the script re-runs.
    
    c1, c2 = st.columns([3, 1])
    with c1:
        k_dn = rk(resort_id, "dn")
        st.text_input(
            "Display Name", 
            value=working.get("display_name", ""), 
            key=k_dn,
            on_change=on_basic_info_change, args=(k_dn, "display_name")
        )
    with c2:
        k_cd = rk(resort_id, "cd")
        st.text_input(
            "Code", 
            value=working.get("code", ""), 
            key=k_cd,
            on_change=on_basic_info_change, args=(k_cd, "code")
        )
    
    k_rn = rk(resort_id, "rn")
    st.text_input(
        "Official Name", 
        value=working.get("resort_name", ""), 
        key=k_rn,
        on_change=on_basic_info_change, args=(k_rn, "resort_name")
    )
    
    c3, c4 = st.columns(2)
    with c3:
        k_tz = rk(resort_id, "tz")
        st.text_input(
            "Timezone", 
            value=working.get("timezone", "UTC"), 
            key=k_tz,
            on_change=on_basic_info_change, args=(k_tz, "timezone")
        )
    with c4:
        k_ad = rk(resort_id, "ad")
        st.text_area(
            "Address", 
            value=working.get("address", ""), 
            key=k_ad, 
            height=100,
            on_change=on_basic_info_change, args=(k_ad, "address")
        )
    
    st.caption("✅ Auto-saving active")


def render_global_settings_v2(data: Dict[str, Any], years: List[str]):
    st.markdown("<div class='section-header'>⚙️ Global Configuration</div>", unsafe_allow_html=True)
    with st.expander("💰 Maintenance Fees", expanded=False):
        rates = data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
        for y in sorted(rates.keys()):
            k_mf = f"mf_{y}"
            st.number_input(
                f"{y}", 
                value=float(rates[y]), 
                step=0.01, 
                key=k_mf,
                on_change=on_global_rate_change, args=(k_mf, y)
            )


# ----------------------------------------------------------------------
# SEASON / POINTS / HOLIDAYS LOGIC
# ----------------------------------------------------------------------
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

def delete_season_across_years(working: Dict[str, Any], season_name: str):
    for year_obj in working.get("years", {}).values():
        year_obj["seasons"] = [s for s in year_obj.get("seasons", []) if s.get("name") != season_name]
    save_data()

def rename_season_across_years(working: Dict[str, Any], old_name: str, new_name: str):
    if not old_name or not new_name: return
    for year_obj in working.get("years", {}).values():
        for s in year_obj.get("seasons", []):
            if s.get("name") == old_name:
                s["name"] = new_name
    save_data()

def render_season_dates_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>📅 Season Dates</div>", unsafe_allow_html=True)
    
    # Rename Panel
    all_names = sorted(get_all_season_names_for_resort(working))
    if all_names:
        with st.expander("✏️ Rename Seasons", expanded=False):
            for name in all_names:
                c1, c2 = st.columns([3, 1])
                with c1:
                    nn = st.text_input(f"Rename {name}", value=name, key=rk(resort_id, "rn_s", name))
                with c2:
                    if st.button("Apply", key=rk(resort_id, "rn_b", name)) and nn != name:
                        rename_season_across_years(working, name, nn)
                        st.rerun()

    # Create New Season
    for year in years:
        with st.expander(f"📆 {year} Seasons", expanded=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                ns = st.text_input("New Season", key=rk(resort_id, "ns", year))
            with c2:
                if st.button("Add", key=rk(resort_id, "add_s", year)) and ns:
                    for y2 in years:
                        y_obj = ensure_year_structure(working, y2)
                        y_obj.setdefault("seasons", []).append({"name": ns, "periods": [], "day_categories": {}})
                    save_data()
                    st.rerun()

            year_obj = ensure_year_structure(working, year)
            for idx, season in enumerate(year_obj.get("seasons", [])):
                render_single_season_v2(working, year, season, idx, resort_id)

def render_single_season_v2(working: Dict[str, Any], year: str, season: Dict[str, Any], idx: int, resort_id: str):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**🎯 {sname}**")

    # --- CALLBACK FOR DATE SAVING ---
    def save_dates_cb(k, s_dict):
        edited = st.session_state.get(k)
        if edited is not None and isinstance(edited, pd.DataFrame):
            new_periods = []
            for _, row in edited.iterrows():
                if pd.notnull(row["start"]) and pd.notnull(row["end"]):
                    new_periods.append({
                        "start": row["start"].isoformat() if hasattr(row["start"], 'isoformat') else str(row["start"]),
                        "end": row["end"].isoformat() if hasattr(row["end"], 'isoformat') else str(row["end"])
                    })
            s_dict["periods"] = new_periods
            save_data()
    
    periods = season.get("periods", [])
    df_data = [{"start": safe_date(p.get("start")), "end": safe_date(p.get("end"))} for p in periods]
    df = pd.DataFrame(df_data)
    
    wk = rk(resort_id, "se_edit", year, idx)
    st.data_editor(
        df, key=wk, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "start": st.column_config.DateColumn("Start", format="YYYY-MM-DD", required=True),
            "end": st.column_config.DateColumn("End", format="YYYY-MM-DD", required=True)
        },
        on_change=save_dates_cb, args=(wk, season)
    )

    if st.button("🗑️ Delete Season", key=rk(resort_id, "del_s", year, idx)):
        delete_season_across_years(working, sname)
        st.rerun()

def get_all_room_types_for_resort(working: Dict[str, Any]) -> List[str]:
    rooms = set()
    for year_obj in working.get("years", {}).values():
        for season in year_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    rooms.update(rp.keys())
        for h in year_obj.get("holidays", []):
            if isinstance(rp := h.get("room_points", {}), dict):
                rooms.update(rp.keys())
    return sorted(rooms)

def sync_season_room_points_across_years(working: Dict[str, Any], base_year: str):
    years = working.get("years", {})
    if base_year not in years: return
    
    canonical_rooms = set()
    for y_obj in years.values():
        for season in y_obj.get("seasons", []):
            for cat in season.get("day_categories", {}).values():
                if isinstance(rp := cat.get("room_points", {}), dict):
                    canonical_rooms.update(rp.keys())
    
    base_seasons = years[base_year].get("seasons", [])
    for season in base_seasons:
        for cat in season.setdefault("day_categories", {}).values():
            rp = cat.setdefault("room_points", {})
            for room in canonical_rooms:
                rp.setdefault(room, 0)
    
    base_map = {s.get("name"): s for s in base_seasons if s.get("name")}
    for y, y_obj in years.items():
        if y != base_year:
            for s in y_obj.get("seasons", []):
                if s.get("name") in base_map:
                    s["day_categories"] = copy.deepcopy(base_map[s.get("name")].get("day_categories", {}))

def render_reference_points_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>🎯 Master Room Points</div>", unsafe_allow_html=True)
    
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
    base_year_obj = ensure_year_structure(working, base_year)
    seasons = base_year_obj.get("seasons", [])
    canonical_rooms = get_all_room_types_for_resort(working)

    # --- CALLBACK FOR POINTS SAVING ---
    def save_pts_cb(k, cat_dict):
        edited = st.session_state.get(k)
        if edited is not None and isinstance(edited, pd.DataFrame) and not edited.empty:
            new_rp = dict(zip(edited["Room Type"], edited["Points"]))
            cat_dict["room_points"] = new_rp
            save_data()

    for s_idx, season in enumerate(seasons):
        with st.expander(f"🏖️ {season.get('name')}", expanded=True):
            dc = season.setdefault("day_categories", {})
            if not dc:
                dc["sun_thu"] = {"day_pattern": ["Sun", "Mon", "Tue", "Wed", "Thu"], "room_points": {}}
                dc["fri_sat"] = {"day_pattern": ["Fri", "Sat"], "room_points": {}}
            
            for key, cat in dc.items():
                st.markdown(f"**📅 {key}**")
                rp = cat.setdefault("room_points", {})
                rooms_here = canonical_rooms or sorted(rp.keys())
                
                df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in rooms_here]
                df = pd.DataFrame(df_data)
                wk = rk(resort_id, "rp_ed", base_year, s_idx, key)
                
                st.data_editor(
                    df, key=wk, width="stretch", hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    },
                    on_change=save_pts_cb, args=(wk, cat)
                )

    st.markdown("---")
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
            save_data()
            st.rerun()

    sync_season_room_points_across_years(working, base_year)

def sync_holiday_points(working: Dict[str, Any], base_year: str):
    years = working.get("years", {})
    if base_year not in years: return
    base_holidays = years[base_year].get("holidays", [])
    base_map = { (h.get("global_reference") or h.get("name")): h for h in base_holidays }
    for y, y_obj in years.items():
        if y != base_year:
            for h in y_obj.get("holidays", []):
                k = h.get("global_reference") or h.get("name")
                if k in base_map:
                    h["room_points"] = copy.deepcopy(base_map[k].get("room_points", {}))

def render_holiday_management_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>🎄 Holiday Management</div>", unsafe_allow_html=True)
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
    
    holidays_map = {}
    for y_obj in working.get("years", {}).values():
        for h in y_obj.get("holidays", []):
            k = h.get("global_reference") or h.get("name")
            if k and k not in holidays_map:
                holidays_map[k] = h

    if holidays_map:
        for k, h in holidays_map.items():
            c1, c2, c3 = st.columns([3, 3, 1])
            with c1: st.text_input("Name", value=h.get("name"), disabled=True, key=rk(resort_id, "hn", k))
            with c3:
                if st.button("🗑️", key=rk(resort_id, "hd", k)):
                    for y_obj in working.get("years", {}).values():
                        y_obj["holidays"] = [x for x in y_obj.get("holidays", []) if (x.get("global_reference") or x.get("name")) != k]
                    save_data()
                    st.rerun()

    st.markdown("**➕ Add New Holiday**")
    c1, c2 = st.columns([3, 1])
    with c1: nh = st.text_input("Holiday Name", key=rk(resort_id, "new_h_name"))
    with c2:
        if st.button("Add", key=rk(resort_id, "add_h_btn")) and nh:
            for y_obj in working.get("years", {}).values():
                if not any((x.get("global_reference") == nh) for x in y_obj.get("holidays", [])):
                    y_obj.setdefault("holidays", []).append({"name": nh, "global_reference": nh, "room_points": {}})
            save_data()
            st.rerun()

    st.markdown("---")
    st.markdown("**💰 Master Holiday Points**")
    
    def save_h_pts_cb(k, h_obj):
        edited = st.session_state.get(k)
        if edited is not None and isinstance(edited, pd.DataFrame) and not edited.empty:
            new_rp = dict(zip(edited["Room Type"], edited["Points"]))
            h_obj["room_points"] = new_rp
            save_data()
    
    base_year_obj = ensure_year_structure(working, base_year)
    base_holidays = base_year_obj.get("holidays", [])
    all_rooms = get_all_room_types_for_resort(working)

    if not base_holidays:
        st.info("No holidays in base year.")
    else:
        for idx, h in enumerate(base_holidays):
            with st.expander(f"🎊 {h.get('name')}", expanded=False):
                rp = h.setdefault("room_points", {})
                rooms_here = sorted(all_rooms or rp.keys())
                df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in rooms_here]
                df = pd.DataFrame(df_data)
                
                wk = rk(resort_id, "hp_ed", base_year, idx)
                st.data_editor(
                    df, key=wk, width="stretch", hide_index=True,
                    column_config={
                        "Room Type": st.column_config.TextColumn(disabled=True),
                        "Points": st.column_config.NumberColumn(min_value=0, step=25)
                    },
                    on_change=save_h_pts_cb, args=(wk, h)
                )

    sync_holiday_points(working, base_year)

def render_resort_summary_v2(working: Dict[str, Any]):
    st.markdown("<div class='section-header'>📊 Resort Summary</div>", unsafe_allow_html=True)
    room_types = get_all_room_types_for_resort(working)
    if not room_types:
        st.info("No room types.")
        return

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
                    if r in rp:
                        total[r] += int(rp[r]) * count
                        has_data = True
        return total, has_data

    rows = []
    years = sorted(working.get("years", {}).keys())
    if not years: return
    ref_year = years[0]
    
    for s in working["years"][ref_year].get("seasons", []):
        t, ok = calc_weekly(s)
        if ok:
            r = {"Season": s.get("name")}
            r.update({k: (v if v else "—") for k, v in t.items()})
            rows.append(r)
            
    for h in working["years"][ref_year].get("holidays", []):
        rp = h.get("room_points", {})
        r = {"Season": f"Holiday - {h.get('name')}"}
        r.update({rt: (rp.get(rt) if rp.get(rt) else "—") for rt in room_types})
        rows.append(r)

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df.astype(str), width="stretch", hide_index=True)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    initialize_session_state()
    
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
                st.toast("Loaded data_v2.json")
        except: pass

    # SIDEBAR: ALWAYS FRESH DATA
    with st.sidebar:
        st.divider()
        handle_file_upload()
        if st.session_state.data:
            handle_merge_from_another_file_v2(st.session_state.data)
            create_download_button_v2(st.session_state.data)
            handle_file_verification()

    render_page_header("Editor", "Manage Resort Data", icon="🏨", badge_color="#EF4444")
    
    if not st.session_state.data:
        st.info("Please load a file.")
        return

    data = st.session_state.data
    resorts = get_resort_list(data)
    years = get_years_from_data(data)
    
    render_resort_grid(resorts, st.session_state.current_resort_id)
    handle_resort_switch_v2(data, st.session_state.current_resort_id, st.session_state.previous_resort_id)
    
    if st.session_state.current_resort_id:
        if st.session_state.current_resort_id not in st.session_state.working_resorts:
            orig = find_resort_by_id(data, st.session_state.current_resort_id)
            if orig: st.session_state.working_resorts[st.session_state.current_resort_id] = copy.deepcopy(orig)
        
        working = st.session_state.working_resorts.get(st.session_state.current_resort_id)
        if working:
            render_resort_card(working.get("display_name"), working.get("timezone"), working.get("address"))
            
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

def run():
    main()

if __name__ == "__main__":
    run()
