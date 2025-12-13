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
import copy


# ==============================================================================
# GLOBAL HOLIDAY DATES EDITOR
# ==============================================================================
def flatten_global_holidays_to_df(data: Dict[str, Any]) -> pd.DataFrame:
    """Convert global holidays to flat DataFrame. Pure function - no Streamlit calls."""
    rows = []
    global_holidays = data.get("global_holidays", {})

    if not isinstance(global_holidays, dict) or not global_holidays:
        return pd.DataFrame()

    for yearyear in sorted(global_holidays.keys()):
        year_holidays = global_holidays.get(year, {})
        if not isinstance(year_holidays, dict):
            continue
        for holiday_name, holiday_data in sorted(year_holidays.items()):
            if not isinstance(holiday_data, dict):
                continue
            rows.append({
                "Year": str(year),
                "Holiday Name": holiday_name,
                "Start Date": holiday_data.get("start_date", ""),
                "End Date": holiday_data.get("end_date", ""),
                "Type": holiday_data.get("type", "other"),
                "Regions": ", ".join(holiday_data.get("regions", ["global"]))
            })

    return pd.DataFrame(rows)


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

    if not data or not isinstance(data, dict):
        st.error("⚠️ No data available. Please load data first.")
        return

    df = flatten_global_holidays_to_df(data)

    with st.expander("🔍 Debug: Global Holidays Data", expanded=False):
        st.write("Raw global_holidays structure:", data.get("global_holidays"))
        if df.empty:
            st.warning("No holidays found in data.")
            st.info("Expected structure example:")
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
        else:
            st.write("Processed DataFrame preview:")
            st.dataframe(df.head(10))

    if df.empty:
        st.warning("⚠️ No global holidays defined yet.")
        return

    st.caption(f"📊 Showing {len(df)} holiday entries")

    try:
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

        grid_response = AgGrid(
            df,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            allow_unsafe_jscode=True,
            theme='streamlit',
            height=min(600, max(200, len(df) * 45 + 100)),
            reload_data=False,
            key=f"global_holidays_grid_{hash(str(df.to_dict()))}"  # More stable key
        )

        edited_df = grid_response['data']

    except Exception as e:
        st.error(f"❌ AG Grid rendering failed: {str(e)}")
        st.warning("Falling back to Streamlit's native data editor.")
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
            key="global_holidays_fallback_editor"
        )

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if st.button("💾 Save Changes to Global Holidays", type="primary", use_container_width=True):
            try:
                rebuild_global_holidays_from_df(edited_df, data)
                st.success("✅ Global holidays saved successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

    with col2:
        if 'grid_response' in locals() and grid_response.get('selected_rows'):
            if st.button("🗑️ Delete Selected Rows", use_container_width=True):
                selected_indices = [row['_selectedRowNodeInfo']['nodeRowIndex'] for row in grid_response['selected_rows']]
                edited_df = edited_df.drop(edited_df.index[selected_indices]).reset_index(drop=True)
                rebuild_global_holidays_from_df(edited_df, data)
                st.success(f"✅ Deleted {len(selected_indices)} row(s)")
                st.rerun()

    with col3:
        if st.button("🔄 Reset", use_container_width=True):
            st.rerun()


# ==============================================================================
# RESORT SEASON DATES EDITOR (Year-Specific)
# ==============================================================================
def flatten_season_dates_to_df(working: Dict[str, Any]) -> pd.DataFrame:
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
        new_periods_map[key].append({"start": start, "end": end})

    for year, year_obj in working.get("years", {}).items():
        for season in year_obj.get("seasons", []):
            season_name = season.get("name", "")
            key = (year, season_name)
            if key in new_periods_map:
                existing_day_categories = season.get("day_categories", {})
                season["periods"] = new_periods_map[key]
                season["day_categories"] = existing_day_categories


def render_season_dates_grid(working: Dict[str, Any], resort_id: str):
    st.markdown("### 📅 Season Dates (Year-Specific)")
    st.caption("Edit date ranges for each season.")

    df = flatten_season_dates_to_df(working)

    if df.empty:
        st.info("No season dates defined. Add seasons first in the relevant tab.")
        return

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Year", editable=False, width=80)
    gb.configure_column("Season", editable=False, width=150)
    gb.configure_column("Period #", editable=False, width=90)
    gb.configure_column("Start Date", editable=True, width=130)
    gb.configure_column("End Date", editable=True, width=130)
    gb.configure_grid_options(enableRangeSelection=True, enableFillHandle=True, rowHeight=35)

    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=400,
        reload_data=False,
        key=f"season_dates_{resort_id}"
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

    years_data = working.get("years", {})
    if base_year in years_data:
        for season in years_data[base_year].get("seasons", []):
            season_name = season.get("name", "")
            for cat_key, cat_data in season.get("day_categories", {}).items():
                key = (season_name, cat_key)
                if key in season_points_map:
                    cat_data["room_points"] = season_points_map[key]

    for year, year_obj in years_data.items():
        if year != base_year:
            for season in year_obj.get("seasons", []):
                season_name = season.get("name", "")
                for cat_key, cat_data in season.get("day_categories", {}).items():
                    key = (season_name, cat_key)
                    if key in season_points_map:
                        cat_data["room_points"] = copy.deepcopy(season_points_map[key])


def render_season_points_grid(working: Dict[str, Any], base_year: str, resort_id: str):
    st.markdown("### 🎯 Season Points (Applies to All Years)")
    st.caption(f"Edit nightly points. Changes apply to all years. Base year: {base_year}")

    df = flatten_season_points_to_df(working, base_year)

    if df.empty:
        st.info("No season points defined. Configure seasons and room types first.")
        return

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Season", width=150)
    gb.configure_column("Day Category", width=120)
    gb.configure_column("Days", width=200)
    gb.configure_column("Room Type", width=180)
    gb.configure_column("Points", editable=True, type=["numericColumn"], width=100)
    gb.configure_grid_options(enableRangeSelection=True, enableFillHandle=True, rowHeight=35)

    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=500,
        reload_data=False,
        key=f"season_points_{resort_id}"
    )

    edited_df = grid_response['data']

    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("💾 Save Season Points (All Years)", type="primary", use_container_width=True, key=f"save_points_{resort_id}"):
            try:
                rebuild_season_points_from_df(edited_df, working, base_year)
                st.success("✅ Season points saved and synced!")
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

    for year, year_obj in working.get("years", {}).items():
        for holiday in year_obj.get("holidays", []):
            global_ref = holiday.get("global_reference") or holiday.get("name", "")
            if global_ref in holiday_points_map:
                holiday["room_points"] = copy.deepcopy(holiday_points_map[global_ref])


def render_holiday_points_grid(working: Dict[str, Any], base_year: str, resort_id: str):
    st.markdown("### 🎄 Holiday Points (Applies to All Years)")
    st.caption(f"Edit holiday points. Changes apply to all years. Base year: {base_year}")

    df = flatten_holiday_points_to_df(working, base_year)

    if df.empty:
        st.info("No holidays defined yet. Add them in the Holidays tab first.")
        return

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False, resizable=True, filterable=True, sortable=True)
    gb.configure_column("Holiday", width=200)
    gb.configure_column("Global Reference", width=180)
    gb.configure_column("Room Type", width=180)
    gb.configure_column("Points", editable=True, type=["numericColumn"], width=100)
    gb.configure_grid_options(enableRangeSelection=True, enableFillHandle=True, rowHeight=35)

    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        allow_unsafe_jscode=True,
        theme='streamlit',
        height=400,
        reload_data=False,
        key=f"holiday_points_{resort_id}"
    )

    edited_df = grid_response['data']

    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("💾 Save Holiday Points (All Years)", type="primary", use_container_width=True, key=f"save_hol_points_{resort_id}"):
            try:
                rebuild_holiday_points_from_df(edited_df, working, base_year)
                st.success("✅ Holiday points saved and synced!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving: {e}")
    with col2:
        if st.button("🔄 Reset", use_container_width=True, key=f"reset_hol_points_{resort_id}"):
            st.rerun()
