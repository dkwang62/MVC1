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
from dataclasses import dataclass
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
# DATA INTEGRITY CLASSES & LOGIC
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
        
        total_points = 0
        current_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        while current_date <= end_date:
            day_points = self._get_points_for_date(resort, year, current_date)
            total_points += sum(day_points.values())
            current_date += timedelta(days=1)
        
        return total_points
    
    def _get_points_for_date(self, resort: Dict, year: int, target_date: date) -> Dict[str, int]:
        """Get point values for all room types on a specific date."""
        year_str = str(year)
        y_data = resort['years'].get(year_str, {})
        
        # 1. Check holidays
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

    def check_resort_variance(self, baseline_id: str, target_id: str, tolerance_percent: float) -> Tuple[ResortVarianceResult, ResortVarianceResult]:
        baseline_resort = next((r for r in self.data['resorts'] if r['id'] == baseline_id), None)
        target_resort = next((r for r in self.data['resorts'] if r['id'] == target_id), None)
        
        baseline_name = baseline_resort.get('display_name', baseline_id)
        target_name = target_resort.get('display_name', target_id)
        
        b25 = self.calculate_annual_total(baseline_id, 2025)
        b26 = self.calculate_annual_total(baseline_id, 2026)
        bv = b26 - b25
        bp = (bv / b25 * 100) if b25 > 0 else 0
        
        baseline_result = ResortVarianceResult(baseline_name, b25, b26, bv, bp, "BASELINE", "📊", "Reference standard")
        
        t25 = self.calculate_annual_total(target_id, 2025)
        t26 = self.calculate_annual_total(target_id, 2026)
        tv = t26 - t25
        tp = (tv / t25 * 100) if t25 > 0 else 0
        
        diff = abs(tp - bp)
        if tv < 0:
            status, icon, msg = "ERROR", "🚨", "Negative variance detected"
        elif diff > (tolerance_percent * 2):
            status, icon, msg = "ERROR", "🚨", f"Variance diff: {diff:.2f}% (Threshold {tolerance_percent*2}%)"
        elif diff > tolerance_percent:
            status, icon, msg = "WARNING", "⚠️", f"Variance diff: {diff:.2f}% (Threshold {tolerance_percent}%)"
        else:
            status, icon, msg = "NORMAL", "✅", "Variance within tolerance"
            
        target_result = ResortVarianceResult(target_name, t25, t26, tv, tp, status, icon, msg)
        return baseline_result, target_result

def render_data_integrity_tab(data: Dict, current_resort_id: str):
    st.markdown("## 🔍 Data Quality Assurance")
    resorts = data.get('resorts', [])
    resort_options = {r.get('display_name', r['id']): r['id'] for r in resorts}
    
    col1, col2 = st.columns([3, 1])
    with col1:
        selected_baseline_name = st.selectbox("Baseline Resort for Comparison", options=list(resort_options.keys()))
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Clear"):
            st.session_state.pop("editor_integrity_check_result", None)
            st.rerun()

    tolerance = st.slider("Variance Tolerance (%)", 0.0, 20.0, 5.0)
    if st.button("🔍 Check Data", type="primary"):
        auditor = EditorPointAuditor(data)
        b_res, t_res = auditor.check_resort_variance(resort_options[selected_baseline_name], current_resort_id, tolerance)
        st.session_state.editor_integrity_check_result = t_res
        st.session_state.editor_baseline_check_result = b_res

    if "editor_integrity_check_result" in st.session_state:
        b, t = st.session_state.editor_baseline_check_result, st.session_state.editor_integrity_check_result
        st.divider()
        st.subheader(f"Results: {t.resort_name}")
        st.metric("Variance Difference", f"{abs(t.variance_percent - b.variance_percent):.2f}%", delta_color="inverse")
        if t.status == "ERROR": st.error(f"{t.status_icon} {t.status_message}")
        elif t.status == "WARNING": st.warning(f"{t.status_icon} {t.status_message}")
        else: st.success(f"{t.status_icon} {t.status_message}")

# ----------------------------------------------------------------------
# HELPER FUNCTIONS (UNCHANGED)
# ----------------------------------------------------------------------
@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

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
    for k in ["data", "current_resort_id", "previous_resort_id", "working_resorts", "delete_confirm", "last_save_time", "download_verified"]:
        st.session_state[k] = {} if k == "working_resorts" else None

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
# FILE & SIDEBAR OPERATIONS
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
                    reset_state_for_new_file()
                    st.session_state.data = raw_data
                    st.session_state.last_upload_sig = current_sig
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

def create_download_button_v2(data: Dict[str, Any]):
    st.sidebar.markdown("### 📥 Memory to File")
    current_id = st.session_state.get("current_resort_id")
    working_resorts = st.session_state.get("working_resorts", {})
    has_unsaved = False
    if current_id and current_id in working_resorts:
        if find_resort_by_id(data, current_id) != working_resorts[current_id]:
            has_unsaved = True
    
    with st.sidebar.expander("💾 Save & Download", expanded=True):
        if has_unsaved:
            if st.button("🧠 COMMIT TO MEMORY", type="primary", width="stretch"):
                commit_working_to_data_v2(data, working_resorts[current_id], current_id)
                st.rerun()
        else:
            filename = st.text_input("File name", value="resort_data_v2.json")
            json_data = json.dumps(data, indent=2, ensure_ascii=False, default=lambda o: o.isoformat() if isinstance(o, (date, datetime)) else None)
            st.download_button("⬇️ DOWNLOAD JSON", data=json_data, file_name=filename, mime="application/json", type="primary")

def handle_file_verification():
    with st.sidebar.expander("🔍 Verify File", expanded=False):
        verify_upload = st.file_uploader("Upload to compare", type="json", key="verify_uploader")
        if verify_upload:
            try:
                uploaded_data = json.load(verify_upload)
                if json.dumps(st.session_state.data, sort_keys=True) == json.dumps(uploaded_data, sort_keys=True):
                    st.success("✅ Match")
                else: st.error("❌ Differs")
            except Exception as e: st.error(str(e))

def is_duplicate_resort_name(name: str, resorts: List[Dict[str, Any]]) -> bool:
    target = name.strip().lower()
    return any(r.get("display_name", "").strip().lower() == target for r in resorts)

def render_sidebar_actions(data: Dict[str, Any], current_resort_id: Optional[str]):
    st.sidebar.markdown("### 🛠️ Manage Resorts")
    with st.sidebar.expander("Operations", expanded=False):
        tab_import, tab_current = st.tabs(["Import/New", "Current"])
        with tab_import:
            new_name = st.text_input("Resort Name", key="sb_new_resort_name")
            if st.button("✨ Create Blank", width="stretch"):
                resorts = data.setdefault("resorts", [])
                base_id = generate_resort_id(new_name)
                rid = make_unique_resort_id(base_id, resorts)
                resorts.append({"id": rid, "display_name": new_name, "code": generate_resort_code(new_name), "years": {}})
                st.session_state.current_resort_id = rid
                save_data(); st.rerun()
        with tab_current:
            if current_resort_id:
                if st.button("🗑️ Delete Resort", type="secondary", width="stretch"):
                    idx = find_resort_index(data, current_resort_id)
                    if idx is not None: data["resorts"].pop(idx)
                    st.session_state.current_resort_id = None
                    save_data(); st.rerun()

# ----------------------------------------------------------------------
# WORKING RESORT LOGIC
# ----------------------------------------------------------------------
def handle_resort_switch_v2(data: Dict[str, Any], current_resort_id: Optional[str], previous_resort_id: Optional[str]):
    if previous_resort_id and previous_resort_id != current_resort_id:
        working = st.session_state.working_resorts.get(previous_resort_id)
        committed = find_resort_by_id(data, previous_resort_id)
        if working and committed and working != committed:
            st.warning(f"Unsaved changes in {previous_resort_id}")
            if st.button("Save & Continue"):
                commit_working_to_data_v2(data, working, previous_resort_id)
                st.rerun()
    st.session_state.previous_resort_id = current_resort_id

def commit_working_to_data_v2(data: Dict[str, Any], working: Dict[str, Any], resort_id: str):
    idx = find_resort_index(data, resort_id)
    if idx is not None: data["resorts"][idx] = copy.deepcopy(working)
    save_data()

def load_resort(data: Dict[str, Any], current_resort_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not current_resort_id: return None
    if current_resort_id not in st.session_state.working_resorts:
        if resort_obj := find_resort_by_id(data, current_resort_id):
            st.session_state.working_resorts[current_resort_id] = copy.deepcopy(resort_obj)
    return st.session_state.working_resorts.get(current_resort_id)

# ----------------------------------------------------------------------
# UI RENDERING (SEASONS, HOLIDAYS, GANTT)
# ----------------------------------------------------------------------
def ensure_year_structure(resort: Dict[str, Any], year: str):
    y_obj = resort.setdefault("years", {}).setdefault(year, {})
    y_obj.setdefault("seasons", []); y_obj.setdefault("holidays", [])
    return y_obj

def render_season_dates_editor_v2(working: Dict[str, Any], years: List[str], resort_id: str):
    st.markdown("### 📅 Season Dates")
    for year in sorted(years, reverse=True):
        with st.expander(f"📆 {year} Seasons"):
            y_obj = ensure_year_structure(working, year)
            for idx, s in enumerate(y_obj["seasons"]):
                st.text(f"Season: {s.get('name')}")
                df = pd.DataFrame([{"start": safe_date(p.get("start")), "end": safe_date(p.get("end"))} for p in s.get("periods", [])])
                st.data_editor(df, key=rk(resort_id, "se_dt", year, idx))

def edit_resort_basics(working: Dict[str, Any], resort_id: str):
    st.markdown("### Basic Info")
    working["display_name"] = st.text_input("Display Name", working.get("display_name"), key=rk(resort_id, "bn_dn"))
    working["address"] = st.text_area("Address", working.get("address"), key=rk(resort_id, "bn_ad"))

def render_gantt_charts_v2(working: Dict[str, Any], years: List[str], data: Dict[str, Any]):
    from common.charts import create_gantt_chart_from_working
    for year in sorted(years, reverse=True):
        fig = create_gantt_chart_from_working(working, year, data)
        st.plotly_chart(fig, use_container_width=True)

# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------
def run():
    initialize_session_state()
    if st.session_state.data is None:
        try:
            with open("data_v2.json", "r") as f:
                st.session_state.data = json.load(f)
        except: pass

    with st.sidebar:
        handle_file_upload()
        if st.session_state.data:
            render_sidebar_actions(st.session_state.data, st.session_state.current_resort_id)
            create_download_button_v2(st.session_state.data)
            handle_file_verification()

    render_page_header("Edit", "Resort Data", icon="🏨")
    if not st.session_state.data:
        st.info("Load JSON to begin.")
        return

    data = st.session_state.data
    resorts = get_resort_list(data)
    years = get_years_from_data(data)
    current_resort_id = st.session_state.current_resort_id
    
    render_resort_grid(resorts, current_resort_id)
    handle_resort_switch_v2(data, current_resort_id, st.session_state.previous_resort_id)
    
    working = load_resort(data, current_resort_id)
    if working:
        render_resort_card(working.get("display_name"), working.get("timezone", "UTC"), working.get("address"))
        
        # TAB DEFINITION WITH NEW DATA QUALITY TAB
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Overview", "📅 Season Dates", "💰 Room Points", 
            "🎄 Holidays", "📋 Spreadsheet", "🔍 Data Quality"
        ])
        
        with tab1: edit_resort_basics(working, current_resort_id)
        with tab2:
            render_gantt_charts_v2(working, years, data)
            render_season_dates_editor_v2(working, years, current_resort_id)
        with tab3: st.info("Room points editor logic here.")
        with tab4: st.info("Holiday management logic here.")
        with tab5:
            st.markdown("### Spreadsheet View")
            render_excel_export_import(working, current_resort_id, data)
        with tab6:
            # NEW DATA QUALITY CONTENT
            render_data_integrity_tab(data, current_resort_id)

    st.divider()
    # Global settings would follow here

if __name__ == "__main__":
    run()
