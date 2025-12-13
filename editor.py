# aggrid_editor.py
"""
AG Grid integration for MVC Editor - handles:
1. Global holiday dates (year-specific)
2. Resort season dates (year-specific)
3. Resort season points (applies to all years)
4. Resort holiday points (applies to all years)
"""

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
from typing import Dict, Any, List
from datetime import datetime
import copy

# ==============================================================================
# GLOBAL HOLIDAY DATES EDITOR
# ==============================================================================

def flatten_global_holidays_to_df(data: Dict[str, Any], years: List[str]) -> pd.DataFrame:
    """Convert global holidays to flat DataFrame."""
    rows = []
    
    # Enhanced debug output
    st.write("🔍 **DEBUG INFO:**")
    st.write(f"- Data type: {type(data)}")
    st.write(f"- Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
    
    global_holidays = data.get("global_holidays", {})
    st.write(f"- global_holidays type: {type(global_holidays)}")
    st.write(f"- global_holidays keys: {list(global_holidays.keys()) if isinstance(global_holidays, dict) else 'Not a dict'}")
    
    # Debug: Check what we're getting
    if not global_holidays:
        st.error("⚠️ No 'global_holidays' key found in data or it's empty")
        st.info("💡 Your JSON needs a structure like:")
        st.code('''
{
  "global_holidays": {
    "2025": {
      "New Year": {
        "start_date": "2024-12-27",
        "end_date": "2025-01-02",
        "type": "major",
        "regions": ["global"]
      }
    }
  }
}
        ''', language="json")
        return pd.DataFrame()
    
    # Get ALL years from global_holidays
    all_years = sorted(global_holidays.keys())
    st.write(f"- Years found: {all_years}")
    
    if not all_years:
        st.warning("⚠️ global_holidays exists but is empty")
        return pd.DataFrame()
    
    for year in all_years:
        year_holidays = global_holidays.get(year, {})
        st.write(f"- Holidays in {year}: {len(year_holidays)} entries")
        
        if not year_holidays:
            continue
            
        for holiday_name, holiday_data in sorted(year_holidays.items()):
            rows.append({
                "Year": str(year),
                "Holiday Name": holiday_name,
                "Start Date": holiday_data.get("start_date", ""),
                "End Date": holiday_data.get("end_date", ""),
                "Type": holiday_data.get("type", "other"),
                "Regions": ", ".join(holiday_data.get("regions", ["global"]))
            })
    
    df = pd.DataFrame(rows)
    
    # Final status
    if df.empty:
        st.error("⚠️ DataFrame is empty after processing all years")
    else:
        st.success(f"✅ Successfully loaded {len(df)} holiday entries from {len(df['Year'].unique())} year(s)")
    
    return df

def rebuild_global_holidays_from_df(df: pd.DataFrame, data: Dict[str, Any]):
    """Convert DataFrame back to nested global holidays structure."""
    global_holidays = {}
    
    for _, row in df.iterrows():
        year = str(row["Year"])
        holiday_name = str(row["Holiday Name"]).strip()
        
        if not holiday_name:
            continue
            
        if year not in global_holidays:
            global_holidays[year] = {}
        
        regions = [r.strip() for r in str(row["Regions"]).split(",") if r.strip()]
        if not regions:
            regions = ["global"]
        
        global_holidays[year][holiday_name] = {
            "start_date": str(row["Start Date"]),
            "end_date": str(row["End Date"]),
            "type": str(row["Type"]),
            "regions": regions
        }
    
    data["global_holidays"] = global_holidays

def render_global_holidays_grid(data: Dict[str, Any], years: List[str]):
    """Render AG Grid for global holiday dates."""
    st.markdown("### 🎅 Global Holiday Calendar (Year-Specific)")
    st.caption("Edit holiday dates for each year. These dates are referenced by all resorts.")
    
    # CRITICAL FIX: Use st.session_state.data directly if data is None or empty
    if not data or not isinstance(data, dict):
        st.error("⚠️ No data available. Please load data first.")
        return
    
    df = flatten_global_holidays_to_df(data, years)
    
    # Always show the grid, even if empty
    if df.empty:
        st.warning("⚠️ No global holidays found.")
        return
    
    # Show data preview
    st.caption(f"📊 Showing {len(df)} holiday entries")
    
    # DEBUG: Show first few rows
    with st.expander("🔍 Debug: Preview DataFrame", expanded=False):
        st.dataframe(df.head(10), use_container_width=True)
    
    try:
        # Configure AG Grid
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_default_column(editable=True, resizable=True, filterable=True, sortable=True)
        gb.configure_column("Year", editable=True, width=80)
        gb.configure_column("Holiday Name", editable=True, width=200)
        gb.configure_column("Start Date", editable=True, width=130)
        gb.configure_column("End Date", editable=True, width=130)
        gb.configure_column("Type", editable=True, width=100)
        gb.configure_column("Regions", editable=True, width=150)
        gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        gb.configure_grid_options(
            enableRangeSelection=True,
            enableFillHandle=True,
            suppressRowClickSelection=False,
            rowHeight=40
        )
        
        st.write("🔧 Attempting to render AG Grid...")
        
        grid_response = AgGrid(
            df,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            allow_unsafe_jscode=True,
            theme='streamlit',
            height=min(600, max(200, len(df) * 45 + 100)),
            reload_data=False,
            key=f"global_holidays_grid_{len(df)}"  # Dynamic key to force refresh
        )
        
        st.success("✅ Grid rendered successfully")
        edited_df = grid_response['data']
        
    except Exception as e:
        st.error(f"❌ AG Grid failed to render: {str(e)}")
        st.warning("Falling back to standard editable dataframe:")
        
        # Fallback: Use st.data_editor instead
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Year": st.column_config.TextColumn("Year", width="small"),
                "Holiday Name": st.column_config.TextColumn("Holiday Name", width="medium"),
                "Start Date": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD"),
                "End Date": st.column_config.DateColumn("End Date", format="YYYY-MM-DD"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Regions": st.column_config.TextColumn("Regions", width="medium"),
            },
            key="global_holidays_fallback"
        )
        st.info("💡 Using Streamlit's native data editor. Copy/paste works, but drag-fill doesn't.")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        if st.button("💾 Save Changes to Global Holidays", type="primary", use_container_width=True):
            try:
                rebuild_global_holidays_from_df(edited_df, data)
                st.success("✅ Global holidays saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving: {e}")
    
    with col2:
        if 'grid_response' in locals():
            selected_rows = grid_response.get('selected_rows', [])
            if selected_rows and st.button("🗑️ Delete Selected", use_container_width=True):
                selected_indices = [row['_selectedRowNodeInfo']['nodeRowIndex'] for row in selected_rows]
                edited_df = edited_df.drop(edited_df.index[selected_indices]).reset_index(drop=True)
                rebuild_global_holidays_from_df(edited_df, data)
                st.success(f"✅ Deleted {len(selected_rows)} holiday(s)")
                st.rerun()
    
    with col3:
        if st.button("🔄 Reset", use_container_width=True):
            st.rerun()

# ==============================================================================
# RESORT SEASON DATES EDITOR (Year-Specific)
# ==============================================================================

def flatten_season_dates_to_df(working: Dict[str, Any]) -> pd.DataFrame:
    """Convert season dates to flat DataFrame."""
    rows = []
    
    for year, year_obj in working.get("years", {}).items():
        for season in year_obj.get("seasons", []):
            season_name = season.get("name", "")
            for period_idx, period in enumerate(season.get("periods", []), 1):
                rows.append({
                    "Year": year,
                    "Season": season_name,
                    "Period #": period_idx,
                    "Start Date": period.get("start", ""),
                    "End Date": period.get("end", "")
                })
    
    return pd.DataFrame(rows)

def rebuild_season_dates_from_df(df: pd.DataFrame, working: Dict[str, Any]):
    """Convert DataFrame back to season dates structure - preserves day_categories."""
    # Build new periods, but preserve existing seasons structure
    new_periods_map = {}
    
    for _, row in df.iterrows():
        year = str(row["Year"])
        season_name = str(row["Season"]).strip()
        start = str(row["Start Date"])
        end = str(row["End Date"])
        
        if not season_name or not start or not end:
            continue
        
        key = (year, season_name)
        if key not in new_periods_map:
            new_periods_map[key] = []
        
        new_periods_map[key].append({
            "start": start,
            "end": end
        })
    
    # Update periods while preserving day_categories
    for year, year_obj in working.get("years", {}).items():
        for season in year_obj.get("seasons", []):
            season_name = season.get("name", "")
            key = (year, season_name)
            
            if key in new_periods_map:
                # Preserve existing day_categories
                existing_day_categories = season.get("day_categories", {})
                season["periods"] = new_periods_map[key]
                season["day_categories"] = existing_day_categories

def render_season_dates_grid(working: Dict[str, Any], resort_id: str):
    """Render AG Grid for season dates."""
    st.markdown("### 📅 Season Dates (Year-Specific)")
    st.caption("Edit date ranges for each season. Seasons and room types must be managed in other tabs.")
    
    df = flatten_season_dates_to_df(working)
    
    if df.empty:
        st.info("No season dates defined. Add seasons in the Season Dates tab first.")
        return
    
    # Configure AG Grid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Year", editable=False, width=80)
    gb.configure_column("Season", editable=False, width=150)
    gb.configure_column("Period #", editable=False, width=90)
    gb.configure_column("Start Date", editable=True, width=130)
    gb.configure_column("End Date", editable=True, width=130)
    gb.configure_grid_options(
        enableRangeSelection=True,
        enableFillHandle=True,
        rowHeight=35
    )
    
    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=400,
        reload_data=False
    )
    
    edited_df = grid_response['data']
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("💾 Save Season Dates", type="primary", use_container_width=True, key=f"save_dates_{resort_id}"):
            try:
                rebuild_season_dates_from_df(edited_df, working)
                st.success("✅ Season dates saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving: {e}")
    
    with col2:
        if st.button("🔄 Reset", use_container_width=True, key=f"reset_dates_{resort_id}"):
            st.rerun()

# ==============================================================================
# RESORT SEASON POINTS EDITOR (Applies to All Years)
# ==============================================================================

def flatten_season_points_to_df(working: Dict[str, Any], base_year: str) -> pd.DataFrame:
    """Convert season points to flat DataFrame using base year."""
    rows = []
    
    years_data = working.get("years", {})
    if base_year not in years_data:
        return pd.DataFrame()
    
    base_year_obj = years_data[base_year]
    
    for season in base_year_obj.get("seasons", []):
        season_name = season.get("name", "")
        day_categories = season.get("day_categories", {})
        
        for cat_key, cat_data in day_categories.items():
            day_pattern = ", ".join(cat_data.get("day_pattern", []))
            room_points = cat_data.get("room_points", {})
            
            for room_type, points in sorted(room_points.items()):
                rows.append({
                    "Season": season_name,
                    "Day Category": cat_key,
                    "Days": day_pattern,
                    "Room Type": room_type,
                    "Points": int(points) if points else 0
                })
    
    return pd.DataFrame(rows)

def rebuild_season_points_from_df(df: pd.DataFrame, working: Dict[str, Any], base_year: str):
    """Convert DataFrame back to season points - syncs to all years."""
    # Build new points structure
    season_points_map = {}
    
    for _, row in df.iterrows():
        season_name = str(row["Season"]).strip()
        cat_key = str(row["Day Category"]).strip()
        room_type = str(row["Room Type"]).strip()
        points = int(row["Points"]) if pd.notna(row["Points"]) else 0
        
        if not season_name or not cat_key or not room_type:
            continue
        
        key = (season_name, cat_key)
        if key not in season_points_map:
            season_points_map[key] = {}
        
        season_points_map[key][room_type] = points
    
    # Apply to base year first
    years_data = working.get("years", {})
    if base_year in years_data:
        for season in years_data[base_year].get("seasons", []):
            season_name = season.get("name", "")
            for cat_key, cat_data in season.get("day_categories", {}).items():
                key = (season_name, cat_key)
                if key in season_points_map:
                    cat_data["room_points"] = season_points_map[key]
    
    # Sync to all other years (same season name = same points)
    for year, year_obj in years_data.items():
        if year != base_year:
            for season in year_obj.get("seasons", []):
                season_name = season.get("name", "")
                for cat_key, cat_data in season.get("day_categories", {}).items():
                    key = (season_name, cat_key)
                    if key in season_points_map:
                        cat_data["room_points"] = copy.deepcopy(season_points_map[key])

def render_season_points_grid(working: Dict[str, Any], base_year: str, resort_id: str):
    """Render AG Grid for season points."""
    st.markdown("### 🎯 Season Points (Applies to All Years)")
    st.caption(f"Edit nightly points. Changes apply to all years automatically. Base year: {base_year}")
    
    df = flatten_season_points_to_df(working, base_year)
    
    if df.empty:
        st.info("No season points defined. Add seasons and room types first.")
        return
    
    # Configure AG Grid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Season", width=150)
    gb.configure_column("Day Category", width=120)
    gb.configure_column("Days", width=200)
    gb.configure_column("Room Type", width=180)
    gb.configure_column("Points", editable=True, type=["numericColumn"], width=100)
    gb.configure_grid_options(
        enableRangeSelection=True,
        enableFillHandle=True,
        rowHeight=35
    )
    
    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=500,
        reload_data=False
    )
    
    edited_df = grid_response['data']
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("💾 Save Season Points (Applies to All Years)", type="primary", use_container_width=True, key=f"save_points_{resort_id}"):
            try:
                rebuild_season_points_from_df(edited_df, working, base_year)
                st.success("✅ Season points saved and synced to all years!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving: {e}")
    
    with col2:
        if st.button("🔄 Reset", use_container_width=True, key=f"reset_points_{resort_id}"):
            st.rerun()

# ==============================================================================
# RESORT HOLIDAY POINTS EDITOR (Applies to All Years)
# ==============================================================================

def flatten_holiday_points_to_df(working: Dict[str, Any], base_year: str) -> pd.DataFrame:
    """Convert holiday points to flat DataFrame using base year."""
    rows = []
    
    years_data = working.get("years", {})
    if base_year not in years_data:
        return pd.DataFrame()
    
    base_year_obj = years_data[base_year]
    
    for holiday in base_year_obj.get("holidays", []):
        holiday_name = holiday.get("name", "")
        global_ref = holiday.get("global_reference", holiday_name)
        room_points = holiday.get("room_points", {})
        
        for room_type, points in sorted(room_points.items()):
            rows.append({
                "Holiday": holiday_name,
                "Global Reference": global_ref,
                "Room Type": room_type,
                "Points": int(points) if points else 0
            })
    
    return pd.DataFrame(rows)

def rebuild_holiday_points_from_df(df: pd.DataFrame, working: Dict[str, Any], base_year: str):
    """Convert DataFrame back to holiday points - syncs to all years."""
    # Build new points structure
    holiday_points_map = {}
    
    for _, row in df.iterrows():
        global_ref = str(row["Global Reference"]).strip()
        room_type = str(row["Room Type"]).strip()
        points = int(row["Points"]) if pd.notna(row["Points"]) else 0
        
        if not global_ref or not room_type:
            continue
        
        if global_ref not in holiday_points_map:
            holiday_points_map[global_ref] = {}
        
        holiday_points_map[global_ref][room_type] = points
    
    # Apply to all years
    for year, year_obj in working.get("years", {}).items():
        for holiday in year_obj.get("holidays", []):
            global_ref = holiday.get("global_reference") or holiday.get("name", "")
            
            if global_ref in holiday_points_map:
                holiday["room_points"] = copy.deepcopy(holiday_points_map[global_ref])

def render_holiday_points_grid(working: Dict[str, Any], base_year: str, resort_id: str):
    """Render AG Grid for holiday points."""
    st.markdown("### 🎄 Holiday Points (Applies to All Years)")
    st.caption(f"Edit holiday points. Changes apply to all years automatically. Base year: {base_year}")
    
    df = flatten_holiday_points_to_df(working, base_year)
    
    if df.empty:
        st.info("No holidays defined. Add holidays in the Holidays tab first.")
        return
    
    # Configure AG Grid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Holiday", width=200)
    gb.configure_column("Global Reference", width=180)
    gb.configure_column("Room Type", width=180)
    gb.configure_column("Points", editable=True, type=["numericColumn"], width=100)
    gb.configure_grid_options(
        enableRangeSelection=True,
        enableFillHandle=True,
        rowHeight=35
    )
    
    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=400,
        reload_data=False
    )
    
    edited_df = grid_response['data']
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("💾 Save Holiday Points (Applies to All Years)", type="primary", use_container_width=True, key=f"save_hol_points_{resort_id}"):
            try:
                rebuild_holiday_points_from_df(edited_df, working, base_year)
                st.success("✅ Holiday points saved and synced to all years!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving: {e}")
    
    with col2:
        if st.button("🔄 Reset", use_container_width=True, key=f"reset_hol_points_{resort_id}"):
            st.rerun()
