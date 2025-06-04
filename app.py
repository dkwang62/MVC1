import streamlit as st
import math
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.figure_factory as ff
import json

with open("data.json", "r") as f:
    data = json.load(f)

season_blocks = data["season_blocks"]
holiday_weeks = data["holiday_weeks"]
room_view_legend = data["room_view_legend"]
reference_points = data["reference_points"]

# Initialize session state for debug messages
if "debug_messages" not in st.session_state:
    st.session_state.debug_messages = []

# Helper function to map room type keys to descriptive names
def get_display_room_type(room_key):
    if room_key in room_view_legend:
        return room_view_legend[room_key]

    parts = room_key.split()
    if not parts:
        return room_key

    base = parts[0]
    view = parts[-1]
    if len(parts) > 1 and view in room_view_legend:
        view_display = room_view_legend[view]
        return f"{base} {view_display}"
    
    if room_key in ["2BR", "1BR", "3BR"]:
        return room_key
    
    return room_key

# Helper function to map display name back to internal key
def get_internal_room_key(display_name):
    reverse_legend = {v: k for k, v in room_view_legend.items()}
    if display_name in reverse_legend:
        return reverse_legend[display_name]

    parts = display_name.split()
    if not parts:
        return display_name

    base_parts = []
    view_parts = []
    found_view = False
    for part in parts:
        if part in ["Mountain", "Ocean", "Penthouse", "Garden", "Front"] and not found_view:
            found_view = True
            view_parts.append(part)
        elif found_view:
            view_parts.append(part)
        else:
            base_parts.append(part)

    base = " ".join(base_parts)
    view_display = " ".join(view_parts)
    view = reverse_legend.get(view_display, view_display)

    return f"{base} {view}"

# Function to generate data structure
def generate_data(resort, date):
    date_str = date.strftime("%Y-%m-%d")
    year = date.strftime("%Y")
    day_of_week = date.strftime("%a")
    
    st.session_state.debug_messages.append(f"Processing date: {date_str}, Day: {day_of_week}, type(date): {type(date)}")
    
    is_fri_sat = day_of_week in ["Fri", "Sat"]
    is_sun = day_of_week == "Sun"
    day_category = "Fri-Sat" if is_fri_sat else "Sun-Thu"
    ap_day_category = "Fri-Sat" if is_fri_sat else ("Sun" if is_sun else "Mon-Thu")
    st.session_state.debug_messages.append(f"Default day category: {day_category}")
    st.session_state.debug_messages.append(f"Default AP day category: {ap_day_category}")

    entry = {}

    ap_room_types = []
    if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points[resort]:
        ap_room_types = list(reference_points[resort]["AP Rooms"].get(ap_day_category, {}).keys())
        st.session_state.debug_messages.append(f"AP Room types found: {ap_room_types}")

    # Season determination
    season = None
    holiday_name = None
    if year in season_blocks.get(resort, {}):
        for season_name, ranges in season_blocks[resort][year].items():
            for start_date, end_date in ranges:
                try:
                    start = datetime.strptime(start_date, "%Y-%m-%d").date()
                    end = datetime.strptime(end_date, "%Y-%m-%d").date()
                    if start <= date <= end:
                        season = season_name
                        break
                except ValueError as e:
                    st.session_state.debug_messages.append(f"Invalid date format in season_blocks: {e}")
            if season:
                break

    if season is None and year in holiday_weeks.get(resort, {}):
        for h_name, date_range in holiday_weeks[resort][year].items():
            try:
                start_date, end_date = date_range
                start = datetime.strptime(start_date, "%Y-%m-%d").date()
                end = datetime.strptime(end_date, "%Y-%m-%d").date()
                if start <= date <= end:
                    holiday_name = h_name
                    season = "Holiday Week"
                    break
            except ValueError as e:
                st.session_state.debug_messages.append(f"Invalid date format in holiday_weeks: {e}")

    if season is None:
        st.session_state.debug_messages.append(f"No season found for {resort} on {date_str}")
        st.error(f"No season defined for {resort} on {date_str}.")
        raise ValueError(f"No season defined for {resort} on {date_str}")

    st.session_state.debug_messages.append(f"Season determined: {season}, Holiday: {holiday_name if holiday_name else 'None'}")

    try:
        normal_room_category = None  # Initialize to avoid UnboundLocalError
        if season != "Holiday Week":
            # Determine day category dynamically for regular seasons
            possible_day_categories = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
            available_day_categories = [cat for cat in possible_day_categories if cat in reference_points[resort][season]]
            st.session_state.debug_messages.append(f"Available day categories for {resort}, {season}: {available_day_categories}")

            if not available_day_categories:
                raise KeyError(f"No valid day categories found for {resort}, {season}")

            if is_fri_sat and "Fri-Sat" in available_day_categories:
                normal_room_category = "Fri-Sat"
            elif is_sun and "Sun" in available_day_categories:
                normal_room_category = "Sun"
            elif not is_fri_sat and "Mon-Thu" in available_day_categories:
                normal_room_category = "Mon-Thu"
            elif "Sun-Thu" in available_day_categories:
                normal_room_category = "Sun-Thu"
            else:
                normal_room_category = available_day_categories[0]
                st.session_state.debug_messages.append(f"Fallback to {normal_room_category} for {date_str}")

            st.session_state.debug_messages.append(f"Selected normal room category: {normal_room_category}")

            normal_room_types = list(reference_points[resort][season][normal_room_category].keys())
            st.session_state.debug_messages.append(f"Normal room types found for {normal_room_category}: {normal_room_types}")
        else:
            # For Holiday Week, use holiday-specific room types
            if holiday_name not in reference_points[resort]["Holiday Week"]:
                raise KeyError(f"No points data for holiday {holiday_name} in {resort}")
            normal_room_types = list(reference_points[resort]["Holiday Week"][holiday_name].keys())
            st.session_state.debug_messages.append(f"Normal room types for Holiday Week {holiday_name}: {normal_room_types}")

        all_room_types = []
        all_display_room_types = []
        all_room_types.extend(normal_room_types)
        all_display_room_types.extend([get_display_room_type(rt) for rt in normal_room_types])
        if ap_room_types:
            all_room_types.extend(ap_room_types)
            all_display_room_types.extend([get_display_room_type(rt) for rt in ap_room_types])

        display_to_internal = dict(zip(all_display_room_types, all_room_types))
        st.session_state.debug_messages.append(f"Room type mappings: {display_to_internal}")

        # Populate entry
        is_holiday = False
        is_holiday_start = False
        holiday_name_entry = None
        if year in holiday_weeks.get(resort, {}):
            for h_name, [start, end] in holiday_weeks[resort][year].items():
                h_start = datetime.strptime(start, "%Y-%m-%d").date()
                h_end = datetime.strptime(end, "%Y-%m-%d").date()
                st.session_state.debug_messages.append(f"Checking holiday {h_name}: {start} to {end}")
                if h_start <= date <= h_end:
                    is_holiday = True
                    holiday_name_entry = h_name
                    if date == h_start:
                        is_holiday_start = True
                    st.session_state.debug_messages.append(f"Holiday match found: {holiday_name_entry} for {date_str}")
                    break

        for display_room_type, room_type in display_to_internal.items():
            points = 0
            is_ap_room = room_type in ap_room_types

            if is_ap_room:
                points_ref = reference_points[resort]["AP Rooms"].get(ap_day_category, {})
                points = points_ref.get(room_type, 0)
                st.session_state.debug_messages.append(f"Applying AP room points for {room_type} ({display_room_type}) on {date_str} ({ap_day_category}): {points}")
            else:
                if is_holiday and is_holiday_start:
                    points_ref = reference_points[resort]["Holiday Week"].get(holiday_name_entry, {})
                    points = points_ref.get(room_type, 0)
                    st.session_state.debug_messages.append(f"Applying Holiday Week points for {holiday_name_entry} on {date_str} for {display_room_type}: {points}")
                elif is_holiday and not is_holiday_start:
                    points = 0
                    st.session_state.debug_messages.append(f"Zero points for {date_str} (part of holiday week {holiday_name_entry}) for {display_room_type}")
                else:
                    points_ref = reference_points[resort][season][normal_room_category]
                    points = points_ref.get(room_type, 0)
                    st.session_state.debug_messages.append(f"Applying {season} {normal_room_category} points for {date_str} for {display_room_type}: {points}")

            entry[display_room_type] = points

        if is_holiday:
            entry["HolidayWeek"] = True
            entry["holiday_name"] = holiday_name_entry
            if is_holiday_start:
                entry["HolidayWeekStart"] = True

        return entry, display_to_internal
    except KeyError as e:
        st.session_state.debug_messages.append(f"KeyError: {str(e)} for resort={resort}, season={season}, normal_room_category={normal_room_category if 'normal_room_category' in locals() else 'Not set'}, ap_day_category={ap_day_category}")
        st.error(f"Error accessing reference points for {resort}, season {season}, day category {normal_room_category if 'normal_room_category' in locals() else 'Not set'}. Check data.json.")
        raise

# ... (rest of the original app.py remains unchanged)
