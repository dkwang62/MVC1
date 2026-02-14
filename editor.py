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
from dataclasses import dataclass # Grafted: Required for Audit Logic
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
# DATA INTEGRITY CHECKER - GRAFTED LOGIC
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
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        current_date = start_date
        
        # Iterate through every day of the year
        while current_date <= end_date:
            day_points = self._get_points_for_date(resort, year, current_date)
            total_points += sum(day_points.values())
            current_date += timedelta(days=1)
        
        return total_points
    
    def _get_points_for_date(self, resort: Dict, year: int, target_date: date) -> Dict[str, int]:
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
        
        baseline_name = baseline_resort.get('display_name', baseline_id) if baseline_resort else baseline_id
        target_name = target_resort.get('display_name', target_id) if target_resort else target_id
        
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
            status, icon, msg = "ERROR", "🚨", "Negative variance (2026 has fewer points than 2025)"
        elif diff > (tolerance_percent * 2):
            status, icon, msg = "ERROR", "🚨", f"Variance differs from baseline by {diff:.2f}%"
        elif diff > tolerance_percent:
            status, icon, msg = "WARNING", "⚠️", f"Variance differs from baseline by {diff:.2f}%"
        else:
            status, icon, msg = "NORMAL", "✅", "Variance within tolerance"
            
        target_result = ResortVarianceResult(target_name, t25, t26, tv, tp, status, icon, msg)
        return baseline_result, target_result

# ----------------------------------------------------------------------
# DATA INTEGRITY TAB RENDERER
# ----------------------------------------------------------------------
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
        col1, col2 = st.columns(2)
        with col1: st.metric(f"Baseline: {b.resort_name}", f"{b.variance_percent:.2f}%")
        with col2: st.metric(f"Target: {t.resort_name}", f"{t.variance_percent:.2f}%", delta=f"{t.variance_percent - b.variance_percent:.2f}%")
        if t.status == "ERROR": st.error(f"{t.status_icon} {t.status_message}")
        elif t.status == "WARNING": st.warning(f"{t.status_icon} {t.status_message}")
        else: st.success(f"{t.status_icon} {t.status_message}")

# ----------------------------------------------------------------------
# WIDGET KEY HELPER (RESORT-SCOPED)
# ----------------------------------------------------------------------
@lru_cache(maxsize=1024)
def rk(resort_id: str, *parts: str) -> str:
    """Build a unique Streamlit widget key scoped to a resort."""
    safe_resort = resort_id or "resort"
    return "__".join([safe_resort] + [str(p) for p in parts])

# [All Session State, Safe Date, and List Helpers from your file...]
# ... (Initializing, save_data, reset_state, etc.) ...

# ----------------------------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------------------------
def run():
    initialize_session_state()
    # (Your existing auto-load logic)
    
    # ... (Sidebar, Merge, Clone, and Resort Grid logic) ...

    data = st.session_state.data
    if not data: return
    
    # ... (Resort Switch logic) ...
    
    working = load_resort(data, st.session_state.current_resort_id)
    if working:
        render_resort_card(working.get("resort_name"), working.get("timezone"), working.get("address"))
        render_save_button_v2(data, working, st.session_state.current_resort_id)
        
        # GRAFTED: Updated Tabs to include the 6th Tab
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            [
                "📊 Overview",
                "📅 Season Dates",
                "💰 Room Points",
                "🎄 Holidays",
                "📋 Spreadsheet",
                "🔍 Data Quality",  # NEW
            ]
        )
        
        with tab1:
            edit_resort_basics(working, st.session_state.current_resort_id)
            render_seasons_summary_table(working)
            render_holidays_summary_table(working)
        with tab2:
            render_validation_panel_v2(working, data, get_years_from_data(data))
            render_gantt_charts_v2(working, get_years_from_data(data), data)            
            render_season_dates_editor_v2(working, get_years_from_data(data), st.session_state.current_resort_id)
        with tab3:
            render_seasons_summary_table(working) 
            st.markdown("---")
            render_reference_points_editor_v2(working, get_years_from_data(data), st.session_state.current_resort_id) 
        with tab4:
            render_holidays_summary_table(working) 
            st.markdown("---")
            render_holiday_management_v2(working, get_years_from_data(data), st.session_state.current_resort_id, data) 
        with tab5:
            st.markdown("## 📊 Spreadsheet-Style Editors")
            with st.expander("📅 Edit Season Dates", expanded=False):
                render_season_dates_grid(working, st.session_state.current_resort_id)
            with st.expander("🎯 Edit Season Points", expanded=False):
                render_season_points_grid(working, BASE_YEAR_FOR_POINTS, st.session_state.current_resort_id)
            with st.expander("🎄 Edit Holiday Points", expanded=False):
                render_holiday_points_grid(working, BASE_YEAR_FOR_POINTS, st.session_state.current_resort_id)
            st.markdown("---")
            render_excel_export_import(working, st.session_state.current_resort_id, data)
            
        with tab6:
            # GRAFTED: Render Integrity Tab
            render_data_integrity_tab(data, st.session_state.current_resort_id)

    st.divider()
    render_global_settings_v2(data, get_years_from_data(data))

if __name__ == "__main__":
    run()
