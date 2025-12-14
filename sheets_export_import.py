# sheets_export_import.py
"""
Excel/Google Sheets Export/Import for Resort Data
Converts nested JSON to flat spreadsheet format and back
"""
import pandas as pd
import streamlit as st
from typing import Dict, Any, List
from datetime import datetime
import io
import copy


# ==============================================================================
# EXPORT: Resort → Excel (Multiple Sheets)
# ==============================================================================
def export_resort_to_excel(working: Dict[str, Any], resort_name: str) -> bytes:
    """
    Export a single resort to Excel workbook with multiple sheets:
    - Metadata (basic info)
    - Season_Dates (year × season × periods) → dates as real Excel dates
    - Season_Points (season × day_category × room_type)
    - Holiday_Points (holiday × room_type)
    """
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Metadata
        metadata_df = pd.DataFrame([{
            "resort_id": working.get("id", ""),
            "display_name": working.get("display_name", ""),
            "code": working.get("code", ""),
            "resort_name": working.get("resort_name", ""),
            "timezone": working.get("timezone", ""),
            "address": working.get("address", "")
        }])
        metadata_df.to_excel(writer, sheet_name="Metadata", index=False)

        # Sheet 2: Season Dates (Year-Specific) - Export as real Excel dates
        season_dates_rows = []
        for year, year_obj in working.get("years", {}).items():
            for season in year_obj.get("seasons", []):
                season_name = season.get("name", "")
                for idx, period in enumerate(season.get("periods", []), 1):
                    start_str = period.get("start", "")
                    end_str = period.get("end", "")

                    # Convert string dates to datetime.date if valid
                    start_date = pd.to_datetime(start_str, errors='coerce').date() if start_str else None
                    end_date = pd.to_datetime(end_str, errors='coerce').date() if end_str else None

                    season_dates_rows.append({
                        "Year": year,
                        "Season": season_name,
                        "Period_Num": idx,
                        "Start_Date": start_date,
                        "End_Date": end_date
                    })

        if season_dates_rows:
            season_dates_df = pd.DataFrame(season_dates_rows)

            # Ensure date columns are proper datetime for openpyxl
            season_dates_df["Start_Date"] = pd.to_datetime(season_dates_df["Start_Date"], errors='coerce')
            season_dates_df["End_Date"] = pd.to_datetime(season_dates_df["End_Date"], errors='coerce')

            season_dates_df.to_excel(writer, sheet_name="Season_Dates", index=False)

            # Force consistent YYYY-MM-DD display in Excel
            worksheet = writer.sheets["Season_Dates"]
            date_format = 'yyyy-mm-dd'
            for col_idx, col_name in enumerate(season_dates_df.columns, start=1):
                if col_name in ["Start_Date", "End_Date"]:
                    for row_idx in range(2, len(season_dates_df) + 2):  # Skip header row
                        cell = worksheet.cell(row=row_idx, column=col_idx)
                        cell.number_format = date_format

        # Sheet 3: Season Points (Master - Applies to All Years)
        base_year = sorted(working.get("years", {}).keys())[0] if working.get("years") else None

        if base_year:
            season_points_rows = []
            year_obj = working["years"][base_year]

            for season in year_obj.get("seasons", []):
                season_name = season.get("name", "")

                for cat_key, cat_data in season.get("day_categories", {}).items():
                    day_pattern = ", ".join(cat_data.get("day_pattern", []))
                    room_points = cat_data.get("room_points", {})

                    for room_type, points in sorted(room_points.items()):
                        season_points_rows.append({
                            "Season": season_name,
                            "Day_Category": cat_key,
                            "Days": day_pattern,
                            "Room_Type": room_type,
                            "Points": int(points) if points else 0
                        })

            if season_points_rows:
                season_points_df = pd.DataFrame(season_points_rows)
                season_points_df.to_excel(writer, sheet_name="Season_Points", index=False)

        # Sheet 4: Holiday Points (Master - Applies to All Years)
        if base_year:
            holiday_points_rows = []
            year_obj = working["years"][base_year]

            for holiday in year_obj.get("holidays", []):
                holiday_name = holiday.get("name", "")
                global_ref = holiday.get("global_reference", holiday_name)
                room_points = holiday.get("room_points", {})

                for room_type, points in sorted(room_points.items()):
                    holiday_points_rows.append({
                        "Holiday": holiday_name,
                        "Global_Reference": global_ref,
                        "Room_Type": room_type,
                        "Points": int(points) if points else 0
                    })

            if holiday_points_rows:
                holiday_points_df = pd.DataFrame(holiday_points_rows)
                holiday_points_df.to_excel(writer, sheet_name="Holiday_Points", index=False)

        # Sheet 5: Instructions
        instructions = pd.DataFrame([{
            "Instructions": "Edit the sheets and re-upload this file to update the resort data.",
            "Note_1": "Season_Dates: Edit date ranges per year/season",
            "Note_2": "Season_Points: Edit once, applies to all years automatically",
            "Note_3": "Holiday_Points: Edit once, applies to all years automatically",
            "Note_4": "Do not rename sheets or column headers",
            "Note_5": f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }])
        instructions.to_excel(writer, sheet_name="README", index=False)

    output.seek(0)
    return output.getvalue()


# ==============================================================================
# IMPORT: Excel → Resort
# ==============================================================================
def import_resort_from_excel(uploaded_file, working: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """
    Import Excel file and update working resort data.
    Returns: (updated_working, validation_messages)
    """
    messages = []

    try:
        # Read all sheets
        excel_file = pd.ExcelFile(uploaded_file)
        sheets = {sheet: pd.read_excel(uploaded_file, sheet_name=sheet) for sheet in excel_file.sheet_names}

        messages.append(f"✅ Read {len(sheets)} sheets: {', '.join(sheets.keys())}")

        # 1. Update Metadata
        if "Metadata" in sheets:
            meta_df = sheets["Metadata"]
            if not meta_df.empty:
                row = meta_df.iloc[0]
                working["id"] = str(row.get("resort_id", working.get("id", "")))
                working["display_name"] = str(row.get("display_name", working.get("display_name", "")))
                working["code"] = str(row.get("code", working.get("code", "")))
                working["resort_name"] = str(row.get("resort_name", working.get("resort_name", "")))
                working["timezone"] = str(row.get("timezone", working.get("timezone", "")))
                working["address"] = str(row.get("address", working.get("address", "")))
                messages.append("✅ Updated metadata")

        # 2. Update Season Dates (Year-Specific)
        if "Season_Dates" in sheets:
            dates_df = sheets["Season_Dates"]

            # Rebuild periods for each year/season
            new_periods_map = {}
            for _, row in dates_df.iterrows():
                if pd.isna(row.get("Year")) or pd.isna(row.get("Season")):
                    continue

                year = str(row["Year"])
                season_name = str(row["Season"]).strip()

                # Handle real Excel dates or string dates safely
                start_raw = row.get("Start_Date")
                end_raw = row.get("End_Date")

                # Convert to YYYY-MM-DD string
                try:
                    if pd.isna(start_raw):
                        continue
                    start_str = pd.to_datetime(start_raw).strftime('%Y-%m-%d')
                except:
                    start_str = str(start_raw).strip()
                    if start_str.lower() in ['nat', 'nan', '']:
                        continue

                try:
                    if pd.isna(end_raw):
                        continue
                    end_str = pd.to_datetime(end_raw).strftime('%Y-%m-%d')
                except:
                    end_str = str(end_raw).strip()
                    if end_str.lower() in ['nat', 'nan', '']:
                        continue

                key = (year, season_name)
                if key not in new_periods_map:
                    new_periods_map[key] = []

                new_periods_map[key].append({
                    "start": start_str,
                    "end": end_str
                })

            # Apply new periods while preserving day_categories
            for year, year_obj in working.get("years", {}).items():
                for season in year_obj.get("seasons", []):
                    season_name = season.get("name", "")
                    key = (year, season_name)

                    if key in new_periods_map:
                        existing_day_categories = season.get("day_categories", {})
                        season["periods"] = new_periods_map[key]
                        season["day_categories"] = existing_day_categories

            messages.append(f"✅ Updated {len(new_periods_map)} season date ranges")

        # 3. Update Season Points (Master - Applies to All Years)
        if "Season_Points" in sheets:
            points_df = sheets["Season_Points"]

            season_points_map = {}
            for _, row in points_df.iterrows():
                if pd.isna(row.get("Season")) or pd.isna(row.get("Day_Category")) or pd.isna(row.get("Room_Type")):
                    continue

                season_name = str(row["Season"]).strip()
                cat_key = str(row["Day_Category"]).strip()
                room_type = str(row["Room_Type"]).strip()
                points = int(row["Points"]) if pd.notna(row["Points"]) else 0

                key = (season_name, cat_key)
                if key not in season_points_map:
                    season_points_map[key] = {}

                season_points_map[key][room_type] = points

            # Apply to ALL years
            for year, year_obj in working.get("years", {}).items():
                for season in year_obj.get("seasons", []):
                    season_name = season.get("name", "")
                    for cat_key, cat_data in season.get("day_categories", {}).items():
                        key = (season_name, cat_key)
                        if key in season_points_map:
                            cat_data["room_points"] = copy.deepcopy(season_points_map[key])

            messages.append(f"✅ Updated season points and synced to all years")

        # 4. Update Holiday Points (Master - Applies to All Years)
        if "Holiday_Points" in sheets:
            holiday_df = sheets["Holiday_Points"]

            holiday_points_map = {}
            for _, row in holiday_df.iterrows():
                if pd.isna(row.get("Global_Reference")) or pd.isna(row.get("Room_Type")):
                    continue

                global_ref = str(row["Global_Reference"]).strip()
                room_type = str(row["Room_Type"]).strip()
                points = int(row["Points"]) if pd.notna(row["Points"]) else 0

                if global_ref not in holiday_points_map:
                    holiday_points_map[global_ref] = {}

                holiday_points_map[global_ref][room_type] = points

            # Apply to ALL years
            for year, year_obj in working.get("years", {}).items():
                for holiday in year_obj.get("holidays", []):
                    global_ref = holiday.get("global_reference") or holiday.get("name", "")

                    if global_ref in holiday_points_map:
                        holiday["room_points"] = copy.deepcopy(holiday_points_map[global_ref])

            messages.append(f"✅ Updated holiday points and synced to all years")

        messages.append("🎉 Import completed successfully!")

    except Exception as e:
        messages.append(f"❌ Error during import: {str(e)}")
        import traceback
        messages.append(f"Debug: {traceback.format_exc()}")

    return working, messages


# ==============================================================================
# STREAMLIT UI COMPONENTS
# ==============================================================================
def render_excel_export_import(working: Dict[str, Any], resort_id: str, data: Dict[str, Any]):
    """Render Excel export/import UI."""

    st.markdown("### 📊 Excel Export/Import")
    st.info("""
    **💡 Workflow:**
    1. **Export** → Download Excel file with 4 editable sheets
    2. **Edit in Excel/Google Sheets** → Modify data in familiar spreadsheet interface
    3. **Import** → Upload the edited file to update resort data

    **✨ What gets exported:**
    - Season Dates (year-specific) – dates are real Excel dates (sortable & formatted)
    - Season Points (applies to all years)
    - Holiday Points (applies to all years)
    - Resort Metadata
    """)

    resort_name = working.get("display_name", resort_id)

    # Export Section
    st.markdown("#### ⬇️ Export to Excel")

    col1, col2 = st.columns([3, 1])

    with col1:
        st.caption("Download this resort's data as an Excel workbook with multiple sheets.")

    with col2:
        try:
            excel_data = export_resort_to_excel(working, resort_name)
            safe_filename = f"{working.get('id', 'resort')}_{datetime.now().strftime('%Y%m%d')}.xlsx"

            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name=safe_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary"
            )
        except Exception as e:
            st.error(f"Export error: {e}")

    st.markdown("---")

    # Import Section
    st.markdown("#### ⬆️ Import from Excel")
    st.caption("Upload a previously exported (and edited) Excel file to update this resort's data.")

    uploaded_file = st.file_uploader(
        "Choose Excel file",
        type=["xlsx", "xls"],
        key=f"excel_upload_{resort_id}",
        help="Upload the Excel file you downloaded and edited"
    )

    if uploaded_file:
        st.success(f"✅ File loaded: {uploaded_file.name}")

        col1, col2, col3 = st.columns([2, 2, 1])

        with col1:
            if st.button("🔍 Preview Changes", use_container_width=True, key=f"preview_{resort_id}"):
                with st.spinner("Analyzing file..."):
                    excel_file = pd.ExcelFile(uploaded_file)
                    st.write("**Sheets found:**", ", ".join(excel_file.sheet_names))

                    for sheet in ["Season_Dates", "Season_Points", "Holiday_Points"]:
                        if sheet in excel_file.sheet_names:
                            df = pd.read_excel(uploaded_file, sheet_name=sheet)
                            with st.expander(f"📋 Preview: {sheet} ({len(df)} rows)"):
                                st.dataframe(df.head(10), use_container_width=True)

        with col2:
            if st.button("💾 Import & Apply", type="primary", use_container_width=True, key=f"import_{resort_id}"):
                with st.spinner("Importing data..."):
                    updated_working, messages = import_resort_from_excel(uploaded_file, working)

                    for msg in messages:
                        if "✅" in msg or "🎉" in msg:
                            st.success(msg)
                        elif "❌" in msg:
                            st.error(msg)
                        else:
                            st.info(msg)

                    if "🎉" in " ".join(messages):
                        st.session_state.working_resorts[resort_id] = updated_working
                        st.success("🎉 Data imported! Changes are in memory. Remember to commit to save.")

                        if st.button("💾 Commit to Memory Now", key=f"commit_after_import_{resort_id}"):
                            from editor import commit_working_to_data_v2
                            commit_working_to_data_v2(data, updated_working, resort_id)
                            st.success("✅ Committed to memory!")
                            st.rerun()

        with col3:
            if st.button("❌ Cancel", use_container_width=True, key=f"cancel_import_{resort_id}"):
                st.rerun()

    st.markdown("---")
    st.caption("💡 **Tip:** For Google Sheets, download as Excel (.xlsx) before uploading here.")
