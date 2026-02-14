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
# DATA INTEGRITY CHECKER LOGIC
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
        if not resort: return 0
        year_str = str(year)
        if year_str not in resort.get('years', {}): return 0
        
        total_points = 0
        current_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        
        # Simulated calendar walk to capture every point
        while current_date <= end_date:
            day_points = self._get_points_for_date(resort, year, current_date)
            total_points += sum(day_points.values())
            current_date += timedelta(days=1)
        return total_points
    
    def _get_points_for_date(self, resort: Dict, year: int, target_date: date) -> Dict[str, int]:
        year_str = str(year)
        y_data = resort['years'].get(year_str, {})
        
        # 1. Holiday Logic (Priority)
        for h in y_data.get('holidays', []):
            ref = h.get('global_reference')
            g_h = self.global_holidays.get(year_str, {}).get(ref, {})
            if g_h:
                h_start = datetime.strptime(g_h['start_date'], '%Y-%m-%d').date()
                h_end = datetime.strptime(g_h['end_date'], '%Y-%m-%d').date()
                if h_start <= target_date <= h_end: return h.get('room_points', {})
        
        # 2. Season Logic
        day_name = target_date.strftime('%a')
        for s in y_data.get('seasons', []):
            for p in s.get('periods', []):
                try:
                    p_start = datetime.strptime(p['start'], '%Y-%m-%d').date()
                    p_end = datetime.strptime(p['end'], '%Y-%m-%d').date()
                    if p_start <= target_date <= p_end:
                        for cat in s.get('day_categories', {}).values():
                            if day_name in cat.get('day_pattern', []): return cat.get('room_points', {})
                except: continue
        return {}

    def check_resort_variance(self, baseline_id: str, target_id: str, tolerance_percent: float) -> Tuple[ResortVarianceResult, ResortVarianceResult]:
        b_res = next((r for r in self.data['resorts'] if r['id'] == baseline_id), None)
        t_res = next((r for r in self.data['resorts'] if r['id'] == target_id), None)
        
        b25, b26 = self.calculate_annual_total(baseline_id, 2025), self.calculate_annual_total(baseline_id, 2026)
        bv = b26 - b25
        bp = (bv / b25 * 100) if b25 > 0 else 0
        b_out = ResortVarianceResult(b_res['display_name'], b25, b26, bv, bp, "BASELINE", "📊", "Reference")
        
        t25, t26 = self.calculate_annual_total(target_id, 2025), self.calculate_annual_total(target_id, 2026)
        tv = t26 - t25
        tp = (tv / t25 * 100) if t25 > 0 else 0
        diff = abs(tp - bp)
        
        status, icon, msg = ("NORMAL", "✅", "Within tolerance")
        if tv < 0: status, icon, msg = "ERROR", "🚨", "Negative variance detected"
        elif diff > (tolerance_percent * 2): status, icon, msg = "ERROR", "🚨", f"Diff: {diff:.2f}%"
        elif diff > tolerance_percent: status, icon, msg = "WARNING", "⚠️", f"Diff: {diff:.2f}%"
        
        t_out = ResortVarianceResult(t_res['display_name'], t25, t26, tv, tp, status, icon, msg)
        return b_out, t_out

# ----------------------------------------------------------------------
# SESSION STATE & HELPERS
# ----------------------------------------------------------------------

@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

def initialize_session_state():
    defaults = {
        "refresh_trigger": False, "last_upload_sig": None, "data": None,
        "current_resort_id": None, "previous_resort_id": None, "working_resorts": {},
        "last_save_time": None, "delete_confirm": False, "download_verified": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

def save_data(): st.session_state.last_save_time = datetime.now()

def reset_state_for_new_file():
    for k in ["data", "current_resort_id", "previous_resort_id", "working_resorts", "delete_confirm", "last_save_time", "download_verified"]:
        st.session_state[k] = {} if k == "working_resorts" else None
        if k == "download_verified": st.session_state[k] = False

def get_years_from_data(data: Dict[str, Any]) -> List[str]:
    years: Set[str] = set()
    gh = data.get("global_holidays", {})
    years.update(gh.keys())
    for r in data.get("resorts", []):
        years.update(str(y) for y in r.get("years", {}).keys())
    return sorted(years) if years else DEFAULT_YEARS

def find_resort_by_id(data: Dict[str, Any], rid: str) -> Optional[Dict[str, Any]]:
    return next((r for r in data.get("resorts", []) if r.get("id") == rid), None)

def find_resort_index(data: Dict[str, Any], rid: str) -> Optional[int]:
    return next((i for i, r in enumerate(data.get("resorts", [])) if r.get("id") == rid), None)

# ----------------------------------------------------------------------
# UI: DATA QUALITY TAB
# ----------------------------------------------------------------------

def render_data_integrity_tab(data: Dict, current_resort_id: str):
    st.markdown("## 🔍 Data Quality Assurance")
    resorts = data.get('resorts', [])
    resort_options = {r.get('display_name', r['id']): r['id'] for r in resorts}
    
    col1, col2 = st.columns([3, 1])
    with col1:
        selected_baseline = st.selectbox("Baseline Resort for Comparison", options=list(resort_options.keys()))
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Clear Results"):
            st.session_state.pop("editor_integrity_check_result", None)
            st.rerun()

    tolerance = st.slider("Variance Tolerance (%)", 0.0, 20.0, 5.0)
    if st.button("🔍 Run Audit", type="primary"):
        auditor = EditorPointAuditor(data)
        b, t = auditor.check_resort_variance(resort_options[selected_baseline], current_resort_id, tolerance)
        st.session_state.editor_integrity_check_result = t
        st.session_state.editor_baseline_check_result = b

    if "editor_integrity_check_result" in st.session_state:
        b, t = st.session_state.editor_baseline_check_result, st.session_state.editor_integrity_check_result
        st.divider()
        col1, col2 = st.columns(2)
        with col1: st.metric(f"Baseline: {b.resort_name}", f"{b.variance_percent:.2f}%")
        with col2: st.metric(f"Target: {t.resort_name}", f"{t.variance_percent:.2f}%", delta=f"{t.variance_percent - b.variance_percent:.2f}%")
        if t.status == "ERROR": st.error(f"{t.status_icon} {t.status_message}")
        else: st.success(f"{t.status_icon} {t.status_message}")

# ----------------------------------------------------------------------
# FILE & SIDEBAR OPERATIONS
# ----------------------------------------------------------------------

def handle_file_upload():
    st.sidebar.markdown("### 📤 File to Memory")
    with st.sidebar.expander("📤 Load", expanded=False):
        uploaded = st.file_uploader("Choose JSON", type="json", key="file_uploader")
        if uploaded:
            try:
                raw_data = json.load(uploaded)
                reset_state_for_new_file()
                st.session_state.data = raw_data
                st.toast("✅ File Loaded", icon="🚀")
                st.rerun()
            except Exception as e: st.error(f"❌ Error: {str(e)}")

def create_download_button_v2(data: Dict[str, Any]):
    st.sidebar.markdown("### 📥 Memory to File")
    with st.sidebar.expander("💾 Save & Download", expanded=True):
        filename = st.text_input("File name", value="resort_data_v2.json")
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        st.download_button("⬇️ DOWNLOAD JSON", data=json_data, file_name=filename, mime="application/json", type="primary")

# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------

def run():
    initialize_session_state()
    
    with st.sidebar:
        handle_file_upload()
        if st.session_state.data:
            create_download_button_v2(st.session_state.data)

    data = st.session_state.data
    if not data: 
        st.info("Load JSON file from the sidebar to begin.")
        return

    years = get_years_from_data(data)
    current_resort_id = st.session_state.current_resort_id
    
    working = load_resort(data, current_resort_id)
    if working:
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            ["📊 Overview", "📅 Season Dates", "💰 Room Points", "🎄 Holidays", "📋 Spreadsheet", "🔍 Data Quality"]
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
            render_reference_points_editor_v2(working, years, current_resort_id)
        with tab4:
            render_holiday_management_v2(working, years, current_resort_id, data)
        with tab5:
            with st.expander("📅 Edit Season Dates", expanded=False):
                render_season_dates_grid(working, current_resort_id)
            with st.expander("🎯 Edit Season Points", expanded=False):
                render_season_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)
            with st.expander("🎄 Edit Holiday Points", expanded=False):
                render_holiday_points_grid(working, BASE_YEAR_FOR_POINTS, current_resort_id)
            st.divider()
            render_excel_export_import(working, current_resort_id, data)
            
        with tab6:
            render_data_integrity_tab(data, current_resort_id)

    st.divider()
    render_global_settings_v2(data, years)

if __name__ == "__main__":
    run()
