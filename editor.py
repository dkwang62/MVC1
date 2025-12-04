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
        "last_save_time": datetime.now(),
        "delete_confirm": False,
        "download_verified": False,
        "last_upload_sig": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def force_sync_working_to_data():
    """
    NUCLEAR OPTION: Immediately forces the current working resort 
    into the main data object. Called before any critical operation.
    """
    rid = st.session_state.get("current_resort_id")
    data = st.session_state.get("data")
    working = st.session_state.get("working_resorts", {}).get(rid)
    
    if rid and data and working:
        idx = find_resort_index(data, rid)
        if idx is not None:
            # Overwrite main memory with working copy
            data["resorts"][idx] = copy.deepcopy(working)
            st.session_state.last_save_time = datetime.now()

def save_data_cb():
    """Callback to trigger a save and update timestamp."""
    force_sync_working_to_data()

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
                    
                    st.session_state.data = raw_data
                    st.session_state.last_upload_sig = current_sig
                    st.session_state.working_resorts = {}
                    st.session_state.current_resort_id = None
                    st.success(f"✅ Loaded {len(raw_data.get('resorts', []))} resorts")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

def create_download_button_v2(data: Dict[str, Any]):
    st.sidebar.markdown("### 📥 Memory to File")
    
    # Force sync before creating the button to ensure DATA is fresh
    force_sync_working_to_data()
    
    with st.sidebar.expander("💾 Save & Download", expanded=False):
        st.caption("✅ Auto-Save Active. File is always up to date.")
        
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
                # Ensure memory is synced before comparing
                force_sync_working_to_data()
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
                    force_sync_working_to_data()
                    if merged_count: st.success(f"✅ Merged {merged_count} resort(s)")
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# ----------------------------------------------------------------------
# RESORT MANAGEMENT
# ----------------------------------------------------------------------
def handle_resort_creation_v2(data: Dict[str, Any], current_resort_id: Optional[str]):
    resorts = data.setdefault("resorts", [])
    with st.expander("➕ Create or Clone Resort", expanded=False):
        tab_new, tab_clone = st.tabs(["✨ New Blank", "📋 Clone Current"])
        with tab_new:
            new_name = st.text_input("New Resort Name", key="new_resort_name_blank")
            if st.button("Create Blank Resort", use_container_width=True):
                base_id = generate_resort_id(new_name)
                rid = make_unique_resort_id(base_id, resorts)
                new_resort = {
                    "id": rid, "display_name": new_name, "code": generate_resort_code(new_name),
                    "resort_name": new_name, "address": "", "timezone": "UTC", "years": {},
                }
                resorts.append(new_resort)
                st.session_state.current_resort_id = rid
                st.rerun()
        with tab_clone:
            if current_resort_id:
                if st.button("📋 Clone This Resort", use_container_width=True):
                    src = find_resort_by_id(data, current_resort_id)
                    if src:
                        new_name = f"{src.get('display_name')} (Copy)"
                        cloned = copy.deepcopy(src)
                        cloned["id"] = make_unique_resort_id(generate_resort_id(new_name), resorts)
                        cloned["display_name"] = new_name
                        resorts.append(cloned)
                        st.session_state.current_resort_id = cloned["id"]
                        st.rerun()

def handle_resort_deletion_v2(data: Dict[str, Any], current_resort_id: Optional[str]):
    if not current_resort_id: return
    if not st.session_state.delete_confirm:
        if st.button("🗑️ Delete Resort", key="delete_resort_init", type="secondary"):
            st.session_state.delete_confirm = True
            st.rerun()
    else:
        st.warning("Are you sure?")
        if st.button("🔥 CONFIRM DELETE", key="del_final", type="primary", use_container_width=True):
            idx = find_resort_index(data, current_resort_id)
            if idx is not None: data.get("resorts", []).pop(idx)
            st.session_state.current_resort_id = None
            st.session_state.delete_confirm = False
            st.session_state.working_resorts.pop(current_resort_id, None)
            st.rerun()

def handle_resort_switch_v2(data: Dict[str, Any]):
    current = st.session_state.current_resort_id
    prev = st.session_state.previous_resort_id
    
    if prev and prev != current:
        # Force sync old resort before switching
        if prev in st.session_state.working_resorts:
            idx = find_resort_index(data, prev)
            if idx is not None:
                data["resorts"][idx] = copy.deepcopy(st.session_state.working_resorts[prev])
            del st.session_state.working_resorts[prev]
            
    st.session_state.previous_resort_id = current

# ----------------------------------------------------------------------
# CALLBACK HANDLERS (THE FIX FOR "TYPE TWICE")
# ----------------------------------------------------------------------
def on_basic_info_change(key: str, field: str):
    rid = st.session_state.current_resort_id
    val = st.session_state[key]
    if rid and rid in st.session_state.working_resorts:
        st.session_state.working_resorts[rid][field] = val
        save_data_cb()

def on_global_rate_change(key: str, year: str):
    val = st.session_state[key]
    rates = st.session_state.data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
    rates[year] = val
    # No need to sync working resort for global changes, but we verify save
    st.session_state.last_save_time = datetime.now()

# ----------------------------------------------------------------------
# UI RENDERERS
# ----------------------------------------------------------------------
def edit_resort_basics(working: Dict[str, Any], resort_id: str):
    st.markdown("### Basic Info")
    c1, c2 = st.columns([3, 1])
    with c1:
        st.text_input("Display Name", value=working.get("display_name", ""), key=rk(resort_id, "dn"), on_change=on_basic_info_change, args=(rk(resort_id, "dn"), "display_name"))
    with c2:
        st.text_input("Code", value=working.get("code", ""), key=rk(resort_id, "cd"), on_change=on_basic_info_change, args=(rk(resort_id, "cd"), "code"))
    
    st.text_input("Official Name", value=working.get("resort_name", ""), key=rk(resort_id, "rn"), on_change=on_basic_info_change, args=(rk(resort_id, "rn"), "resort_name"))
    
    c3, c4 = st.columns(2)
    with c3:
        st.text_input("Timezone", value=working.get("timezone", "UTC"), key=rk(resort_id, "tz"), on_change=on_basic_info_change, args=(rk(resort_id, "tz"), "timezone"))
    with c4:
        st.text_area("Address", value=working.get("address", ""), key=rk(resort_id, "ad"), height=100, on_change=on_basic_info_change, args=(rk(resort_id, "ad"), "address"))

def render_global_settings_v2(data: Dict[str, Any], years: List[str]):
    st.markdown("<div class='section-header'>⚙️ Global Configuration</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("**💰 Maintenance Fees**")
        rates = data.setdefault("configuration", {}).setdefault("maintenance_rates", {})
        for y in sorted(years):
            st.number_input(f"Rate {y}", value=float(rates.get(y, 0)), step=0.01, key=f"mf_{y}", on_change=on_global_rate_change, args=(f"mf_{y}", y))

    with c2:
        render_global_holidays_editor(data, years)

def render_global_holidays_editor(data: Dict[str, Any], years: List[str]):
    st.markdown("**🌍 Global Holidays**")
    
    gh = data.setdefault("global_holidays", {})
    
    # Select Year
    sel_year = st.selectbox("Select Year", years + [str(int(max(years))+1)] if years else ["2025"], key="gh_year_sel")
    
    # Ensure structure
    if sel_year not in gh:
        gh[sel_year] = []
        
    holidays = gh[sel_year]
    
    # List Existing
    if holidays:
        for idx, h in enumerate(holidays):
            c_a, c_b = st.columns([3, 1])
            with c_a:
                st.text(f"{h.get('date')} - {h.get('name')}")
            with c_b:
                if st.button("🗑️", key=f"gh_del_{sel_year}_{idx}"):
                    holidays.pop(idx)
                    st.rerun()
    else:
        st.caption("No global holidays for this year.")
        
    # Add New
    with st.form(key=f"gh_add_{sel_year}"):
        c_x, c_y = st.columns(2)
        with c_x: new_date = st.date_input("Date")
        with c_y: new_name = st.text_input("Holiday Name")
        if st.form_submit_button("Add Global Holiday"):
            holidays.append({"name": new_name, "date": str(new_date)})
            st.session_state.last_save_time = datetime.now()
            st.rerun()

# ----------------------------------------------------------------------
# SEASONS & POINTS
# ----------------------------------------------------------------------
def ensure_year_structure(resort: Dict[str, Any], year: str):
    years = resort.setdefault("years", {})
    year_obj = years.setdefault(year, {})
    year_obj.setdefault("seasons", [])
    year_obj.setdefault("holidays", [])
    return year_obj

def render_season_dates_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>📅 Season Dates</div>", unsafe_allow_html=True)
    
    # Add/Rename Logic Here (Simplified for brevity, same as before)
    for year in years:
        with st.expander(f"📆 {year} Seasons", expanded=True):
            c1, c2 = st.columns([4, 1])
            with c1: ns = st.text_input("New Season", key=rk(resort_id, "ns", year))
            with c2:
                if st.button("Add", key=rk(resort_id, "add_s", year)) and ns:
                    y_obj = ensure_year_structure(working, year)
                    y_obj["seasons"].append({"name": ns, "periods": [], "day_categories": {}})
                    save_data_cb()
                    st.rerun()
            
            y_obj = ensure_year_structure(working, year)
            for idx, season in enumerate(y_obj.get("seasons", [])):
                render_single_season_v2(working, year, season, idx, resort_id)

def render_single_season_v2(working: Dict[str, Any], year: str, season: Dict[str, Any], idx: int, resort_id: str):
    sname = season.get("name", f"Season {idx+1}")
    st.markdown(f"**🎯 {sname}**")
    
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
            save_data_cb()

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
    if st.button("🗑️", key=rk(resort_id, "del_s", year, idx)):
        ensure_year_structure(working, year)["seasons"].pop(idx)
        save_data_cb()
        st.rerun()

def render_reference_points_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("<div class='section-header'>🎯 Master Room Points</div>", unsafe_allow_html=True)
    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
    base_year_obj = ensure_year_structure(working, base_year)
    
    # Helper: Get all rooms
    all_rooms = set()
    for y_obj in working.get("years", {}).values():
        for s in y_obj.get("seasons", []):
            for c in s.get("day_categories", {}).values():
                all_rooms.update(c.get("room_points", {}).keys())
        for h in y_obj.get("holidays", []):
            all_rooms.update(h.get("room_points", {}).keys())
    canonical_rooms = sorted(all_rooms)

    def save_pts_cb(k, cat_dict):
        edited = st.session_state.get(k)
        if edited is not None and isinstance(edited, pd.DataFrame):
            new_rp = dict(zip(edited["Room Type"], edited["Points"]))
            cat_dict["room_points"] = new_rp
            save_data_cb()

    for s_idx, season in enumerate(base_year_obj.get("seasons", [])):
        with st.expander(f"🏖️ {season.get('name')}", expanded=True):
            dc = season.setdefault("day_categories", {})
            if not dc:
                dc["sun_thu"] = {"day_pattern": ["Sun", "Mon", "Tue", "Wed", "Thu"], "room_points": {}}
                dc["fri_sat"] = {"day_pattern": ["Fri", "Sat"], "room_points": {}}
            
            for key, cat in dc.items():
                st.markdown(f"**📅 {key}**")
                rp = cat.setdefault("room_points", {})
                df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in canonical_rooms]
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
    
    # Add Room
    c1, c2 = st.columns(2)
    with c1: nr = st.text_input("Add Room Type", key=rk(resort_id, "new_room"))
    with c2:
        if st.button("Add Room", key=rk(resort_id, "add_room_btn")) and nr:
             for y in working.get("years", {}).values():
                for s in y.get("seasons", []):
                    for c in s.get("day_categories", {}).values():
                        c.setdefault("room_points", {})[nr] = 0
                for h in y.get("holidays", []):
                    h.setdefault("room_points", {})[nr] = 0
             save_data_cb()
             st.rerun()

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
                     save_data_cb()
                     st.rerun()

    st.markdown("**➕ Add New Holiday**")
    c1, c2 = st.columns([3, 1])
    with c1: nh = st.text_input("Holiday Name", key=rk(resort_id, "new_h_name"))
    with c2:
        if st.button("Add", key=rk(resort_id, "add_h_btn")) and nh:
            for y_obj in working.get("years", {}).values():
                if not any((x.get("global_reference") == nh) for x in y_obj.get("holidays", [])):
                    y_obj.setdefault("holidays", []).append({"name": nh, "global_reference": nh, "room_points": {}})
            save_data_cb()
            st.rerun()
    
    st.markdown("---")
    st.markdown("**💰 Master Holiday Points**")
    
    def save_h_pts_cb(k, h_obj):
        edited = st.session_state.get(k)
        if edited is not None and isinstance(edited, pd.DataFrame):
            new_rp = dict(zip(edited["Room Type"], edited["Points"]))
            h_obj["room_points"] = new_rp
            save_data_cb()
    
    base_year_obj = ensure_year_structure(working, base_year)
    
    # Get all rooms again for consistency
    all_rooms = set()
    for y_obj in working.get("years", {}).values():
        for s in y_obj.get("seasons", []):
            for c in s.get("day_categories", {}).values():
                all_rooms.update(c.get("room_points", {}).keys())
    canonical_rooms = sorted(all_rooms)

    for idx, h in enumerate(base_year_obj.get("holidays", [])):
        with st.expander(f"🎊 {h.get('name')}", expanded=False):
            rp = h.setdefault("room_points", {})
            df_data = [{"Room Type": r, "Points": int(rp.get(r, 0) or 0)} for r in canonical_rooms]
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

def render_resort_summary_v2(working: Dict[str, Any], years: List[str]):
    st.markdown("<div class='section-header'>📊 Resort Summary</div>", unsafe_allow_html=True)
    
    # Re-calculate rooms
    room_types = set()
    for y_obj in working.get("years", {}).values():
        for s in y_obj.get("seasons", []):
            for c in s.get("day_categories", {}).values():
                room_types.update(c.get("room_points", {}).keys())
    room_types = sorted(room_types)

    if not room_types:
        st.info("No room types.")
        return

    base_year = BASE_YEAR_FOR_POINTS if BASE_YEAR_FOR_POINTS in years else (sorted(years)[0] if years else "2025")
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
        # Unique key ensures redraw on every save
        st.dataframe(df.astype(str), width="stretch", hide_index=True, key=f"sum_tbl_{st.session_state.last_save_time}")

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    initialize_session_state()
    
    # Auto load
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
                st.toast("Loaded data_v2.json")
        except: pass

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
    handle_resort_switch_v2(data)
    
    if st.session_state.current_resort_id:
        # Lazy load working copy
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
            with t5: render_resort_summary_v2(working, years)

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
