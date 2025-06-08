import streamlit as st
import math
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import json
import traceback
from collections import defaultdict

# Load data and initialize
try:
    with open("data.json", "r") as f:
        data = json.load(f)
    season_blocks = data["season_blocks"]
    holiday_weeks = data["holiday_weeks"]
    room_view_legend = data["room_view_legend"]
    reference_points = data["reference_points"]

    # Automatically determine resorts with complete data
    season_resorts = set(season_blocks.keys())
    holiday_resorts = set(holiday_weeks.keys())
    reference_resorts = set(reference_points.keys())
    display_resorts = sorted(season_resorts & holiday_resorts & reference_resorts)
except Exception as e:
    st.error(f"Failed to load data.json: {str(e)}")
    st.session_state.debug_messages = [f"Data load error: {str(e)}"]
    st.stop()

# Initialize session state
if "debug_messages" not in st.session_state:
    st.session_state.debug_messages = []

# Helper functions
def get_display_room_type(room_key):
    if room_key in room_view_legend:
        return room_view_legend[room_key]
    parts = room_key.split()
    if not parts:
        return room_key
    base = parts[0]
    if room_key.startswith("AP_"):
        if room_key == "AP_Studio_MA":
            return "AP Studio Mountain"
        elif room_key == "AP_1BR_MA":
            return "AP 1BR Mountain"
        elif room_key == "AP_2BR_MA":
            return "AP 2BR Mountain"
        elif room_key == "AP_2BR_MK":
            return "AP 2BR Ocean"
    view = parts[-1]
    if len(parts) > 1 and view in room_view_legend:
        view_display = room_view_legend[view]
        return f"{base} {view_display}"
    if room_key in ["2BR", "1BR", "3BR"]:
        return room_key
    return room_key

def get_internal_room_key(display_name):
    reverse_legend = {v: k for k, v in room_view_legend.items()}
    if display_name in reverse_legend:
        return reverse_legend[display_name]
    if display_name.startswith("AP "):
        if display_name == "AP Studio Mountain":
            return "AP_Studio_MA"
        elif display_name == "AP 1BR Mountain":
            return "AP_1BR_MA"
        elif display_name == "AP 2BR Mountain":
            return "AP_2BR_MA"
        elif display_name == "AP 2BR Ocean":
            return "AP_2BR_MK"
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

# Generate data function with caching
def generate_data(resort, date, cache=None):
    if "data_cache" not in st.session_state:
        st.session_state.data_cache = {}
    if cache is None:
        cache = st.session_state.data_cache

    date_str = date.strftime("%Y-%m-%d")
    if date_str in cache:
        return cache[date_str]

    year = date.strftime("%Y")
    day_of_week = date.strftime("%a")
    
    st.session_state.debug_messages.append(f"Processing date: {date_str}, Day: {day_of_week}, Resort: {resort}")
    
    is_fri_sat = day_of_week in ["Fri", "Sat"]
    is_sun = day_of_week == "Sun"
    day_category = "Fri-Sat" if is_fri_sat else "Sun-Thu"
    ap_day_category = "Fri-Sat" if is_fri_sat else ("Sun" if is_sun else "Mon-Thu")
    st.session_state.debug_messages.append(f"Default day category: {day_category}, AP day_category: {ap_day_category}")

    entry = {}
    ap_room_types = []
    if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points.get(resort, {}):
        ap_room_types = list(reference_points[resort]["AP Rooms"].get(ap_day_category, {}).keys())
        st.session_state.debug_messages.append(f"AP Room types found for {resort}: {ap_room_types}")

    season = None
    holiday_name = None
    is_holiday = False
    is_holiday_start = False
    holiday_start_date = None
    holiday_end_date = None
    prev_year = str(int(year) - 1)

    # Check for year-end/beginning holiday assumption
    is_year_end_holiday = False
    if (date.month == 12 and date.day >= 26) or (date.month == 1 and date.day <= 1):
        holiday_start = datetime.strptime(f"{prev_year}-12-26", "%Y-%m-%d").date()
        holiday_end = datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date()
        if holiday_start <= date <= holiday_end:
            is_year_end_holiday = True
            holiday_name = "New Year's Holiday"
            season = "Holiday Week"
            is_holiday = True
            holiday_start_date = holiday_start
            holiday_end_date = holiday_end
            if date == holiday_start:
                is_holiday_start = True
            st.session_state.debug_messages.append(f"Assuming 7-day New Year's Holiday for {date_str} at {resort}")

    # Check other holidays
    if year in holiday_weeks.get(resort, {}) and not is_year_end_holiday:
        holiday_data_dict = holiday_weeks[resort][year]
        for h_name, holiday_data in holiday_data_dict.items():
            try:
                if len(holiday_data) >= 2:
                    start = datetime.strptime(holiday_data[0], "%Y-%m-%d").date()
                    end = datetime.strptime(holiday_data[1], "%Y-%m-%d").date()
                    st.session_state.debug_messages.append(f"Checking holiday {h_name} for {resort}: {start} to {end}")
                    if start <= date <= end:
                        is_holiday = True
                        holiday_name = h_name
                        season = "Holiday Week"
                        holiday_start_date = start
                        holiday_end_date = end
                        if date == start:
                            is_holiday_start = True
                        st.session_state.debug_messages.append(f"Holiday match for {resort}: {holiday_name} on {date_str}")
                        if len(holiday_data) > 2:
                            st.session_state.debug_messages.append(f"Warning: Extra values in holiday {h_name} data: {holiday_data[2:]}")
                        break
                else:
                    st.session_state.debug_messages.append(f"Invalid holiday data length for {h_name} in {resort}: {holiday_data}")
            except (IndexError, ValueError) as e:
                st.session_state.debug_messages.append(f"Invalid holiday data format for {h_name} in {resort}: {e}")

    # Season determination only if no holiday
    if not is_holiday:
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
                        st.session_state.debug_messages.append(f"Invalid date format in season_blocks for {resort}: {e}")
                if season:
                    break

        if season is None:
            st.session_state.debug_messages.append(f"No season or holiday found for {resort} on {date_str}")
            st.warning(f"No season or holiday defined for {resort} on {date_str}. Using default behavior.")
            season = "Default Season"

    st.session_state.debug_messages.append(f"Season for {resort}: {season}, Holiday: {holiday_name if holiday_name else 'None'}")

    try:
        normal_room_category = None
        normal_room_types = []
        if season != "Holiday Week":
            possible_day_categories = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
            available_day_categories = [cat for cat in possible_day_categories if reference_points.get(resort, {}).get(season, {}).get(cat)]
            st.session_state.debug_messages.append(f"Available day categories for {resort}, {season}: {available_day_categories}")

            if not available_day_categories:
                st.session_state.debug_messages.append(f"No valid day categories found for {resort}, {season}. Falling back to default points.")
                normal_room_types = list(reference_points_resort.keys()) if 'reference_points_resort' in globals() else []
            else:
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
                    st.session_state.debug_messages.append(f"Fallback to {normal_room_category} for {date_str} at {resort}")

                st.session_state.debug_messages.append(f"Selected normal room category for {resort}: {normal_room_category}")
                normal_room_types = list(reference_points[resort][season][normal_room_category].keys())
                st.session_state.debug_messages.append(f"Normal room types for {resort}, {normal_room_category}: {normal_room_types}")
        else:
            if not holiday_name or holiday_name not in reference_points.get(resort, {}).get("Holiday Week", {}):
                if is_year_end_holiday:
                    normal_room_types = list(reference_points_resort.keys()) if 'reference_points_resort' in globals() else []
                    st.session_state.debug_messages.append(f"Using default room types for assumed New Year's Holiday at {resort}: {normal_room_types}")
                else:
                    st.session_state.debug_messages.append(f"No points data for holiday {holiday_name or 'None'} in {resort}")
                    raise KeyError(f"No points data for holiday {holiday_name or 'None'} in {resort}")
            else:
                normal_room_types = list(reference_points[resort]["Holiday Week"][holiday_name].keys())
                st.session_state.debug_messages.append(f"Normal room types for Holiday Week {holiday_name} at {resort}: {normal_room_types}")

        all_room_types = normal_room_types + ap_room_types
        all_display_room_types = [get_display_room_type(rt) for rt in all_room_types]
        display_to_internal = dict(zip(all_display_room_types, all_room_types))
        st.session_state.debug_messages.append(f"Room type mappings for {resort}: {display_to_internal}")

        for display_room_type, room_type in display_to_internal.items():
            points = 0
            is_ap_room = room_type in ap_room_types
            if is_holiday and is_holiday_start:
                if is_ap_room:
                    points_ref = reference_points.get(resort, {}).get("AP Rooms", {}).get("Full Week", {})
                    points = points_ref.get(room_type, 0)
                    st.session_state.debug_messages.append(f"AP full-week points for {room_type} ({display_room_type}) on {date_str} (Holiday Week {holiday_name}) at {resort}: {points}")
                else:
                    if is_year_end_holiday and not holiday_name:
                        points = reference_points_resort.get(room_type, 0) if 'reference_points_resort' in globals() else 0
                        st.session_state.debug_messages.append(f"Assuming points for {display_room_type} on {date_str} (New Year's Holiday start) at {resort}: {points}")
                    else:
                        points_ref = reference_points.get(resort, {}).get("Holiday Week", {}).get(holiday_name, {})
                        points = points_ref.get(room_type, 0)
                        st.session_state.debug_messages.append(f"Holiday Week points for {holiday_name} on {date_str} for {display_room_type} ({room_type}) at {resort}: {points}")
            elif is_holiday and not is_holiday_start and holiday_start_date <= date <= holiday_end_date:
                points = 0  # Points are zero for days within holiday week after the start
                st.session_state.debug_messages.append(f"Zero points for {date_str} (part of holiday week {holiday_name}) for {display_room_type} at {resort}")
            else:
                if is_ap_room:
                    points_ref = reference_points.get(resort, {}).get("AP Rooms", {}).get(ap_day_category, {})
                    points = points_ref.get(room_type, 0)
                    st.session_state.debug_messages.append(f"AP room points for {room_type} ({display_room_type}) on {date_str} ({ap_day_category}) at {resort}: {points}")
                else:
                    if normal_room_category:
                        points_ref = reference_points.get(resort, {}).get(season, {}).get(normal_room_category, {})
                        points = points_ref.get(room_type, 0)
                        st.session_state.debug_messages.append(f"{season} {normal_room_category} points for {date_str} for {display_room_type} ({room_type}) at {resort}: {points}")
                    else:
                        points = reference_points_resort.get(room_type, 0) if 'reference_points_resort' in globals() else 0
                        st.session_state.debug_messages.append(f"Fallback points for {display_room_type} ({room_type}) on {date_str} at {resort}: {points}")

            entry[display_room_type] = points

        if is_holiday:
            entry["HolidayWeek"] = True
            entry["holiday_name"] = holiday_name
            entry["holiday_start"] = holiday_start_date
            entry["holiday_end"] = holiday_end_date
            if is_holiday_start:
                entry["HolidayWeekStart"] = True

        cache[date_str] = (entry, display_to_internal)
        st.session_state.data_cache = cache  # Update session state cache
        return entry, display_to_internal
    except Exception as e:
        st.session_state.debug_messages.append(f"Error in generate_data for {resort}: {str(e)}\n{traceback.format_exc()}")
        st.error(f"Failed to generate data for {resort} on {date_str}: {str(e)}")
        raise

# Adjust date range function
def adjust_date_range(resort, checkin_date, num_nights):
    year_str = str(checkin_date.year)
    stay_end = checkin_date + timedelta(days=num_nights - 1)
    holiday_ranges = []
    
    st.session_state.debug_messages.append(f"Checking holiday overlap for {checkin_date} to {stay_end} at {resort}")
    try:
        for h_name, holiday_data in holiday_weeks.get(resort, {}).get(year_str, {}).items():
            try:
                if len(holiday_data) >= 2:
                    h_start = datetime.strptime(holiday_data[0], "%Y-%m-%d").date()
                    h_end = datetime.strptime(holiday_data[1], "%Y-%m-%d").date()
                    st.session_state.debug_messages.append(f"Evaluating holiday {h_name}: {holiday_data[0]} to {holiday_data[1]} at {resort}")
                    if (h_start <= stay_end) and (h_end >= checkin_date):
                        holiday_ranges.append((h_start, h_end))
                        st.session_state.debug_messages.append(f"Holiday overlap found with {h_name} at {resort}")
                    else:
                        st.session_state.debug_messages.append(f"No overlap with {h_name} at {resort}")
                else:
                    st.session_state.debug_messages.append(f"Invalid holiday data length for {h_name} at {resort}: {holiday_data}")
            except (IndexError, ValueError) as e:
                st.session_state.debug_messages.append(f"Invalid holiday range for {h_name} at {resort}: {e}")
    except ValueError as e:
        st.session_state.debug_messages.append(f"Invalid holiday range in {resort}, {year_str}: {e}")

    if holiday_ranges:
        earliest_holiday_start = min(h_start for h_start, _ in holiday_ranges)
        latest_holiday_end = max(h_end for _, h_end in holiday_ranges)
        adjusted_start = min(checkin_date, earliest_holiday_start)
        adjusted_end = max(stay_end, latest_holiday_end)
        adjusted_nights = (adjusted_end - adjusted_start).days + 1
        st.session_state.debug_messages.append(f"Adjusted date range to include holiday week: {adjusted_start} to {adjusted_end} ({adjusted_nights} nights) at {resort}")
        return adjusted_start, adjusted_nights, True
    st.session_state.debug_messages.append(f"No holiday week adjustment needed for {checkin_date} to {stay_end} at {resort}")
    return checkin_date, num_nights, False

# Create Gantt chart function
def create_gantt_chart(resort, year):
    gantt_data = []
    year_str = str(year)
    
    try:
        for h_name, holiday_data in holiday_weeks.get(resort, {}).get(year_str, {}).items():
            try:
                if len(holiday_data) >= 2:
                    start_date = datetime.strptime(holiday_data[0], "%Y-%m-%d").date()
                    end_date = datetime.strptime(holiday_data[1], "%Y-%m-%d").date()
                    gantt_data.append({
                        "Task": h_name,
                        "Start": start_date,
                        "Finish": end_date,
                        "Type": "Holiday"
                    })
                    st.session_state.debug_messages.append(f"Added holiday: {h_name}, Start: {start_date}, Finish: {end_date} for {resort}")
                else:
                    st.session_state.debug_messages.append(f"Invalid holiday data length for {h_name} at {resort}: {holiday_data}")
            except (IndexError, ValueError) as e:
                st.session_state.debug_messages.append(f"Invalid holiday data for {h_name} at {resort}: {e}")
        season_types = list(season_blocks.get(resort, {}).get(year_str, {}).keys())
        st.session_state.debug_messages.append(f"Available season types for Gantt chart in {resort}, {year}: {season_types}")
        
        for season_type in season_types:
            for i, [start, end] in enumerate(season_blocks[resort][year_str][season_type], 1):
                start_date = datetime.strptime(start, "%Y-%m-%d").date()
                end_date = datetime.strptime(end, "%Y-%m-%d").date()
                gantt_data.append({
                    "Task": f"{season_type} {i}",
                    "Start": start_date,
                    "Finish": end_date,
                    "Type": season_type
                })
                st.session_state.debug_messages.append(f"Added season: {season_type} {i}, Start: {start_date}, Finish: {end_date} for {resort}")
    
        df = pd.DataFrame(gantt_data)
        if df.empty:
            st.session_state.debug_messages.append(f"Gantt DataFrame is empty for {resort}")
            current_date = datetime.now().date()
            df = pd.DataFrame({
                "Task": ["No Data"],
                "Start": [current_date],
                "Finish": [current_date + timedelta(days=1)],
                "Type": ["No Data"]
            })

        color_palette = {
            "Holiday": "rgb(255, 99, 71)",
            "Low Season": "rgb(135, 206, 250)",
            "High Season": "rgb(255, 69, 0)",
            "Peak Season": "rgb(255, 215, 0)",
            "Shoulder": "rgb(50, 205, 50)",
            "Peak": "rgb(255, 69, 0)",
            "Summer": "rgb(255, 165, 0)",
            "Low": "rgb(70, 130, 180)",
            "Mid Season": "rgb(60, 179, 113)",
            "No Data": "rgb(128, 128, 128)",
            "Error": "rgb(128, 128, 128)"
        }
        
        types_present = df["Type"].unique()
        colors = {t: color_palette.get(t, "rgb(169, 169, 169)") for t in types_present}
        
        fig = px.timeline(
            df,
            x_start="Start",
            x_end="Finish",
            y="Task",
            color="Type",
            color_discrete_map=colors,
            title=f"{resort} Seasons and Holidays ({year})",
            height=600
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Period",
            showlegend=True
        )
        return fig
    except Exception as e:
        st.session_state.debug_messages.append(f"Error in create_gantt_chart for {resort}: {str(e)}")
        current_date = datetime.now().date()
        df = pd.DataFrame({
            "Task": ["Error"],
            "Start": [current_date],
            "Finish": [current_date + timedelta(days=1)],
            "Type": ["Error"]
        })
        colors = {"Error": "rgb(128, 128, 128)"}
        fig = px.timeline(
            df,
            x_start="Start",
            x_end="Finish",
            y="Task",
            color="Type",
            color_discrete_map=colors,
            title="Error Generating Gantt Chart",
            height=600
        )
        fig.update_yaxes(autorange="reversed")
        return fig

# Calculate stay function
def calculate_stay(resort, room_type, checkin_date, num_nights, discount_percent, discount_multiplier, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital, useful_life, salvage_value):
    breakdown = []
    total_points = 0
    total_rent = 0
    total_capital_cost = 0
    total_depreciation_cost = 0
    current_holiday = None
    holiday_points = 0

    # Calculate depreciation cost per point using straight-line method
    depreciation_cost_per_point = (capital_cost_per_point - salvage_value) / useful_life

    for i in range(num_nights):
        date = checkin_date + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        try:
            entry, _ = generate_data(resort, date)
            points = entry.get(room_type, reference_points_resort.get(get_internal_room_key(room_type), 0))
            st.session_state.debug_messages.append(f"Calculating for {resort}, {date_str}: Points for {room_type} = {points}")
            discounted_points = math.floor(points * discount_multiplier)

            if entry.get("HolidayWeek", False):
                if entry.get("HolidayWeekStart", False):
                    current_holiday = entry.get("holiday_name")
                    holiday_start = entry.get("holiday_start")
                    holiday_end = entry.get("holiday_end")
                    holiday_points = discounted_points
                    row = {
                        "Date": f"{current_holiday} ({holiday_start.strftime('%b %d, %Y')} - {holiday_end.strftime('%b %d, %Y')})",
                        "Day": "",
                        "Points": holiday_points
                    }
                    if display_mode == "both":
                        maintenance_cost = math.ceil(holiday_points * rate_per_point)
                        capital_cost = math.ceil(holiday_points * capital_cost_per_point * cost_of_capital)
                        depreciation_cost = math.ceil(holiday_points * depreciation_cost_per_point)
                        total_day_cost = maintenance_cost + capital_cost + depreciation_cost
                        row["Cost"] = f"${total_day_cost}"
                        row["Maintenance Cost"] = f"${maintenance_cost}"
                        row["Capital Cost"] = f"${capital_cost}"
                        row["Depreciation Cost"] = f"${depreciation_cost}"
                        total_rent += total_day_cost
                        total_capital_cost += capital_cost
                        total_depreciation_cost += depreciation_cost
                    breakdown.append(row)
                elif current_holiday and date <= holiday_end:
                    continue  # Skip additional days within the holiday week
            else:
                row = {
                    "Date": date_str,
                    "Day": date.strftime("%a"),
                    "Points": discounted_points
                }
                if display_mode == "both":
                    maintenance_cost = math.ceil(discounted_points * rate_per_point)
                    capital_cost = math.ceil(discounted_points * capital_cost_per_point * cost_of_capital)
                    depreciation_cost = math.ceil(discounted_points * depreciation_cost_per_point)
                    total_day_cost = maintenance_cost + capital_cost + depreciation_cost
                    row["Cost"] = f"${total_day_cost}"
                    row["Maintenance Cost"] = f"${maintenance_cost}"
                    row["Capital Cost"] = f"${capital_cost}"
                    row["Depreciation Cost"] = f"${depreciation_cost}"
                    total_rent += total_day_cost
                    total_capital_cost += capital_cost
                    total_depreciation_cost += depreciation_cost
                breakdown.append(row)

            total_points += discounted_points
        except Exception as e:
            st.session_state.debug_messages.append(f"Error calculating for {resort}, {date_str}: {str(e)}")
            st.error(f"Failed to calculate for {resort}, {date_str}: {str(e)}")
            continue
    return pd.DataFrame(breakdown), total_points, total_rent, total_capital_cost, total_depreciation_cost

# Compare room types function
def compare_room_types(resort, room_types, checkin_date, num_nights, discount_multiplier, discount_percent, ap_display_room_types, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital, useful_life, salvage_value):
    compare_data = []
    chart_data = []
    all_dates = [checkin_date + timedelta(days=i) for i in range(num_nights)]
    stay_start = checkin_date
    stay_end = checkin_date + timedelta(days=num_nights - 1)
    
    holiday_ranges = []
    holiday_names = {}
    for h_name, holiday_data in holiday_weeks.get(resort, {}).get(str(checkin_date.year), {}).items():
        try:
            if len(holiday_data) >= 2:
                h_start = datetime.strptime(holiday_data[0], "%Y-%m-%d").date()
                h_end = datetime.strptime(holiday_data[1], "%Y-%m-%d").date()
                if (h_start <= stay_end) and (h_end >= stay_start):
                    holiday_ranges.append((h_start, h_end))
                    for d in [h_start + timedelta(days=x) for x in range((h_end - h_start).days + 1)]:
                        if d in all_dates:
                            holiday_names[d] = h_name
                            st.session_state.debug_messages.append(f"Date {d} overlaps with holiday {h_name} ({h_start} to {h_end}) at {resort}")
            else:
                st.session_state.debug_messages.append(f"Invalid holiday data length for {h_name} at {resort}: {holiday_data}")
        except (IndexError, ValueError) as e:
            st.session_state.debug_messages.append(f"Invalid holiday date for {h_name} at {resort}: {e}")
    
    total_points_by_room = {room: 0 for room in room_types}
    total_rent_by_room = {room: 0 for room in room_types}
    total_depreciation_by_room = {room: 0 for room in room_types}
    holiday_totals = {room: defaultdict(dict) for room in room_types}
    
    # Calculate depreciation cost per point
    depreciation_cost_per_point = (capital_cost_per_point - salvage_value) / useful_life
    
    for room in room_types:
        internal_room = display_to_internal.get(room, room)
        st.session_state.debug_messages.append(f"Mapping for room {room}: Internal key = {internal_room} at {resort}")
        is_ap_room = room in ap_display_room_types
        current_holiday = None
        
        for date in all_dates:
            date_str = date.strftime("%Y-%m-%d")
            day_of_week = date.strftime("%a")
            try:
                entry, _ = generate_data(resort, date)
                points = entry.get(room, reference_points_resort.get(get_internal_room_key(room), 0))
                st.session_state.debug_messages.append(f"Points for {room} on {date_str} ({day_of_week}) at {resort}: {points}")
                discounted_points = math.floor(points * discount_multiplier)
                is_holiday_date = any(h_start <= date <= h_end for h_start, h_end in holiday_ranges)
                holiday_name = holiday_names.get(date, None)
                if is_holiday_date and entry.get("HolidayWeekStart", False):
                    current_holiday = holiday_name
                    if current_holiday not in holiday_totals[room]:
                        h_start = min(h for h, _ in holiday_ranges if holiday_names.get(date) == current_holiday)
                        h_end = max(e for _, e in holiday_ranges if holiday_names.get(date) == current_holiday)
                        holiday_totals[room][current_holiday] = {"points": 0, "start": h_start, "end": h_end}
                    holiday_totals[room][current_holiday]["points"] = discounted_points
                    st.session_state.debug_messages.append(f"Holiday week points for {room} on {date_str} at {resort}: {discounted_points}")
                elif is_holiday_date and current_holiday:
                    continue
                else:
                    current_holiday = None
                
                if not current_holiday or is_ap_room:
                    row = {
                        "Date": date_str,
                        "Room Type": room,
                        "Points": discounted_points
                    }
                    if display_mode == "both":
                        maintenance_cost = math.ceil(discounted_points * rate_per_point)
                        capital_cost = math.ceil(discounted_points * capital_cost_per_point * cost_of_capital)
                        depreciation_cost = math.ceil(discounted_points * depreciation_cost_per_point)
                        total_day_cost = maintenance_cost + capital_cost + depreciation_cost
                        row["Rent"] = f"${total_day_cost}"
                        row["Maintenance Cost"] = f"${maintenance_cost}"
                        row["Capital Cost"] = f"${capital_cost}"
                        row["Depreciation Cost"] = f"${depreciation_cost}"
                        total_rent_by_room[room] += total_day_cost
                        total_depreciation_by_room[room] += depreciation_cost
                    compare_data.append(row)
                
                chart_row = {
                    "Date": date,
                    "DateStr": date_str,
                    "Day": day_of_week,
                    "Room Type": room,
                    "Points": discounted_points,
                    "Holiday": entry.get("holiday_name", "No")
                }
                if display_mode == "both":
                    maintenance_cost = math.ceil(discounted_points * rate_per_point)
                    capital_cost = math.ceil(discounted_points * capital_cost_per_point * cost_of_capital)
                    depreciation_cost = math.ceil(discounted_points * depreciation_cost_per_point)
                    total_day_cost = maintenance_cost + capital_cost + depreciation_cost
                    chart_row["Rent"] = f"${total_day_cost}"
                    chart_row["RentValue"] = total_day_cost
                    chart_row["Maintenance Cost"] = f"${maintenance_cost}"
                    chart_row["Capital Cost"] = f"${capital_cost}"
                    chart_row["Depreciation Cost"] = f"${depreciation_cost}"
                chart_data.append(chart_row)
                
                if not current_holiday or is_ap_room:
                    total_points_by_room[room] += discounted_points
            
            except Exception as e:
                st.session_state.debug_messages.append(f"Error in compare for {date_str} at {resort}: {str(e)}")
                continue
        
        for holiday_name, totals in holiday_totals[room].items():
            if totals["points"] > 0:
                start_str = totals["start"].strftime("%b %d")
                end_str = totals["end"].strftime("%b %d, %Y")
                row = {
                    "Date": f"{holiday_name} ({start_str} - {end_str})",
                    "Room Type": room,
                    "Points": totals["points"]
                }
                if display_mode == "both":
                    maintenance_cost = math.ceil(totals["points"] * rate_per_point)
                    capital_cost = math.ceil(totals["points"] * capital_cost_per_point * cost_of_capital)
                    depreciation_cost = math.ceil(totals["points"] * depreciation_cost_per_point)
                    total_holiday_cost = maintenance_cost + capital_cost + depreciation_cost
                    row["Rent"] = f"${total_holiday_cost}"
                    row["Maintenance Cost"] = f"${maintenance_cost}"
                    row["Capital Cost"] = f"${capital_cost}"
                    row["Depreciation Cost"] = f"${depreciation_cost}"
                compare_data.append(row)
    
    total_row = {"Date": "Total Points (Non-Holiday)"}
    for room in room_types:
        total_row[room] = total_points_by_room[room]
    compare_data.append(total_row)
    
    if display_mode == "both":
        total_rent_row = {"Date": "Total Cost (Non-Holiday)"}
        total_depreciation_row = {"Date": "Total Depreciation Cost (Non-Holiday)"}
        for room in room_types:
            total_rent_row[room] = f"${total_rent_by_room[room]}"
            total_depreciation_row[room] = f"${total_depreciation_by_room[room]}"
        compare_data.append(total_rent_row)
        compare_data.append(total_depreciation_row)
    
    compare_df = pd.DataFrame(compare_data)
    compare_df_pivot = compare_df.pivot_table(
        index="Date",
        columns="Room Type",
        values=["Points"] if display_mode == "points" else ["Points", "Rent", "Maintenance Cost", "Capital Cost", "Depreciation Cost"],
        aggfunc="first"
    ).reset_index()
    compare_df_pivot.columns = ['Date'] + [f"{col[1]} {col[0]}" for col in compare_df_pivot.columns[1:]]
    chart_df = pd.DataFrame(chart_data)
    
    st.session_state.debug_messages.append(f"Compare DataFrame columns: {chart_df.columns.tolist()} at {resort}")
    st.session_state.debug_messages.append(f"Compare Chart DataFrame head: {chart_df.head().to_dict()} at {resort}")
    
    return chart_df, compare_df_pivot, holiday_totals


# Main UI
try:
    with st.sidebar:
        st.header("Cost Parameters")
        display_options = [
            (0, "both"), (25, "both"), (30, "both"),
            (0, "points"), (25, "points"), (30, "points")
        ]

        def format_discount(i):
            discount, mode = display_options[i]
            level = (
                "Presidential" if discount == 30 else
                "Executive" if discount == 25 else
                "Ordinary"
            )
            if mode == "points":
                return f"{discount}% Discount ({level}, Points)"
            return f"{discount}% Discount ({level}, Cost)"

        display_mode_select = st.selectbox(
            "Display and Discount Settings",
            options=range(len(display_options)),
            format_func=format_discount,
            index=0
        )

        discount_percent, display_mode = display_options[display_mode_select]
        rate_per_point = st.number_input("Maintenance Rate per Point ($)", min_value=0.0, value=0.81, step=0.01)
        capital_cost_per_point = st.number_input("Purchase Price per Point ($)", min_value=0.0, value=16.0, step=0.1)
        cost_of_capital_percent = st.number_input("Cost of Capital (%)", min_value=0.0, max_value=100.0, value=7.0, step=0.1)
        useful_life = st.number_input("Useful Life (Years)", min_value=1, value=15, step=1)
        salvage_value = st.number_input("Salvage Value per Point ($)", min_value=0.0, value=3.0, step=0.1)
        cost_of_capital = cost_of_capital_percent / 100
        st.caption(f"Cost calculation based on {discount_percent}% discount.")

    discount_multiplier = 1 - (discount_percent / 100)

    st.title("Marriott Vacation Club Cost Calculator")

    with st.expander("\U0001F334 How Cost Is Calculated"):
        st.markdown(f"""
        - Authored by Desmond Kwang https://www.facebook.com/dkwang62
        - Maintenance rate: ${rate_per_point:.2f} per point
        - Purchase price per point: ${capital_cost_per_point:.2f}
        - Cost of capital: {cost_of_capital_percent:.1f}%
        - Useful Life: {useful_life} years
        - Salvage Value: ${salvage_value:.2f} per point
        - Depreciation cost per point: ${(capital_cost_per_point - salvage_value) / useful_life:.2f} (calculated as (Capital Cost per Point - Salvage Value) / Useful Life)
        - Selected discount: {discount_percent}%
        - Cost of capital calculated as (points * capital cost per point * cost of capital percentage)
        - Total cost is maintenance cost plus capital cost plus depreciation cost
        """)

    resort = st.selectbox("Select Resort", options=display_resorts, index=display_resorts.index("Ko Olina Beach Club"))

    # Track resort changes in session state
    if "last_resort" not in st.session_state:
        st.session_state.last_resort = resort
    if st.session_state.last_resort != resort:
        # Clear previous room type data when resort changes
        if "room_types" in st.session_state:
            del st.session_state.room_types
        if "display_to_internal" in st.session_state:
            del st.session_state.display_to_internal
        if "data_cache" in st.session_state:
            st.session_state.data_cache.clear()  # Clear cache to avoid stale data
        st.session_state.last_resort = resort
        st.session_state.debug_messages.append(f"Resort changed to {resort}. Cleared room type data and cache.")

    checkin_date = st.date_input("Check-in Date", min_value=datetime(2024, 12, 27).date(), max_value=datetime(2026, 12, 31).date(), value=datetime(2026, 7, 8).date())
    num_nights = st.number_input("Number of Nights", min_value=1, max_value=30, value=7)

    year_select = str(checkin_date.year)

    # Compute room types only if not already in session state
    if "room_types" not in st.session_state:
        sample_date = checkin_date
        st.session_state.debug_messages.append(f"Generating room types for {resort} on {sample_date}")
        sample_entry, display_to_internal = generate_data(resort, sample_date)
        room_types = sorted([k for k in sample_entry if k not in ["HolidayWeek", "HolidayWeekStart", "holiday_name", "holiday_start", "holiday_end"]])
        if not room_types:
            st.error(f"No room types found for {resort}.")
            st.session_state.debug_messages.append(f"No room types for {resort}")
            st.stop()
        st.session_state.room_types = room_types
        st.session_state.display_to_internal = display_to_internal
        st.session_state.debug_messages.append(f"Room types for {resort}: {room_types}")
    else:
        room_types = st.session_state.room_types
        display_to_internal = st.session_state.display_to_internal

    room_type = st.selectbox("Select Room Type", options=room_types, key="room_type_select")
    compare_rooms = st.multiselect("Compare With Other Room Types", options=[r for r in room_types if r != room_type])

    original_checkin_date = checkin_date
    checkin_date, adjusted_nights, was_adjusted = adjust_date_range(resort, checkin_date, num_nights)
    if was_adjusted:
        st.info(f"Date range adjusted to include full holiday week: {checkin_date.strftime('%Y-%m-%d')} to {(checkin_date + timedelta(days=adjusted_nights - 1)).strftime('%Y-%m-%d')} ({adjusted_nights} nights).")
    st.session_state.last_checkin_date = checkin_date

    reference_entry, _ = generate_data(resort, checkin_date)
    reference_points_resort = {k: v for k, v in reference_entry.items() if k not in ["HolidayWeek", "HolidayWeekStart", "holiday_name", "holiday_start", "holiday_end"]}

    ap_room_types = []
    ap_display_room_types = []
    if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points.get(resort, {}):
        ap_room_types = list(reference_points[resort]["AP Rooms"].get("Fri-Sat", {}).keys())
        ap_display_room_types = [get_display_room_type(rt) for rt in ap_room_types]
        for rt_display in ap_display_room_types:
            st.session_state.debug_messages.append(f"Added AP room type: {rt_display} for {resort}")

    if st.button("Calculate"):
        st.session_state.debug_messages.append("Starting new calculation...")
        try:
            breakdown, total_points, total_rent, total_capital_cost, total_depreciation_cost = calculate_stay(
                resort, room_type, checkin_date, adjusted_nights, discount_percent, discount_multiplier, display_mode, 
                rate_per_point, capital_cost_per_point, cost_of_capital, useful_life, salvage_value
            )
            st.subheader("Stay Breakdown")
            if not breakdown.empty:
                st.dataframe(breakdown, use_container_width=True)
            else:
                st.error("No data available for the selected period.")
            
            st.success(f"Total Points Used: {total_points}")
            if display_mode == "both":
                st.success(f"Estimated Total Cost: ${total_rent}")
                st.success(f"Total Capital Cost Component: ${total_capital_cost}")
                st.success(f"Total Depreciation Cost: ${total_depreciation_cost}")
            
            if not breakdown.empty:
                csv_data = breakdown.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download Breakdown as CSV",
                    data=csv_data,
                    file_name=f"{resort}_stay_breakdown.csv",
                    mime="text/csv"
                )
            
            if compare_rooms:
                st.subheader("Room Type Comparison")
                st.info("Note: Non-holiday weeks are compared day-by-day; holiday weeks are compared as total points for the week.")
                all_rooms = [room_type] + compare_rooms
                chart_df, compare_df_pivot, holiday_totals = compare_room_types(
                    resort, all_rooms, checkin_date, adjusted_nights, discount_multiplier, 
                    discount_percent, ap_display_room_types, display_mode, rate_per_point, 
                    capital_cost_per_point, cost_of_capital, useful_life, salvage_value
                )
                
                display_columns = ["Date"] + [col for col in compare_df_pivot.columns if "Points" in col or (display_mode == "both" and ("Rent" in col or "Maintenance Cost" in col or "Capital Cost" in col or "Depreciation Cost" in col))]
                st.write(f"### {'Points' if display_mode == 'points' else 'Points, Rent, Maintenance, Capital, and Depreciation Costs'} Comparison")
                st.dataframe(compare_df_pivot[display_columns], use_container_width=True)
                
                compare_csv = compare_df_pivot.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download Room Comparison as CSV",
                    data=compare_csv,
                    file_name=f"{resort}_room_comparison.csv",
                    mime="text/csv"
                )
                
                if not chart_df.empty:
                    required_columns = ["Date", "Room Type", "Points", "Holiday"]
                    if display_mode == "both":
                        required_columns.extend(["Rent", "RentValue", "Maintenance Cost", "Capital Cost", "Depreciation Cost"])
                    if all(col in chart_df.columns for col in required_columns):
                        non_holiday_df = chart_df[chart_df["Holiday"] == "No"]
                        holiday_data = []
                        for room in all_rooms:
                            for holiday_name, totals in holiday_totals[room].items():
                                if totals["points"] > 0:
                                    row = {
                                        "Holiday": holiday_name,
                                        "Room Type": room,
                                        "Points": totals["points"],
                                        "Start": totals["start"],
                                        "End": totals["end"]
                                    }
                                    if display_mode == "both":
                                        maintenance_cost = math.ceil(totals["points"] * rate_per_point)
                                        capital_cost = math.ceil(totals["points"] * capital_cost_per_point * cost_of_capital)
                                        depreciation_cost = math.ceil(totals["points"] * ((capital_cost_per_point - salvage_value) / useful_life))
                                        total_holiday_cost = maintenance_cost + capital_cost + depreciation_cost
                                        row["Rent"] = f"${total_holiday_cost}"
                                        row["RentValue"] = total_holiday_cost
                                        row["Maintenance Cost"] = f"${maintenance_cost}"
                                        row["Capital Cost"] = f"${capital_cost}"
                                        row["Depreciation Cost"] = f"${depreciation_cost}"
                                    holiday_data.append(row)
                        holiday_df = pd.DataFrame(holiday_data)
                        
                        if not non_holiday_df.empty:
                            start_date = non_holiday_df["Date"].min()
                            end_date = non_holiday_df["Date"].max()
                            start_date_str = start_date.strftime("%b %d")
                            end_date_str = end_date.strftime("%b %d, %Y")
                            title = f"Points Comparison (Non-Holiday, {start_date_str} - {end_date_str})"
                            st.subheader(title)
                            day_order = ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]
                            fig = px.bar(
                                non_holiday_df,
                                x="Day",
                                y="Points",
                                color="Room Type",
                                barmode="group",
                                title=title,
                                labels={"Points": "Points", "Day": "Day of Week"},
                                height=600,
                                text="Points",
                                text_auto=True,
                                category_orders={"Day": day_order}
                            )
                            fig.update_traces(texttemplate="%{text}", textposition="auto")
                            fig.update_xaxes(
                                ticktext=day_order,
                                tickvals=[0, 1, 2, 3, 4, 5, 6],
                                tickmode="array"
                            )
                            fig.update_layout(
                                legend_title_text="Room Type",
                                bargap=0.2,
                                bargroupgap=0.1
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        
                        if not holiday_df.empty:
                            start_date = holiday_df["Start"].min()
                            end_date = holiday_df["End"].max()
                            start_date_str = start_date.strftime("%b %d")
                            end_date_str = end_date.strftime("%b %d, %Y")
                            title = f"Points Comparison (Holiday Weeks, {start_date_str} - {end_date_str})"
                            st.subheader(title)
                            fig = px.bar(
                                holiday_df,
                                x="Holiday",
                                y="Points",
                                color="Room Type",
                                barmode="group",
                                title=title,
                                labels={"Points": "Points", "Holiday": "Holiday Week"},
                                height=600,
                                text="Points",
                                text_auto=True
                            )
                            fig.update_traces(texttemplate="%{text}", textposition="auto")
                            fig.update_layout(
                                legend_title_text="Room Type",
                                bargap=0.2,
                                bargroupgap=0.1
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.session_state.debug_messages.append(f"No holiday data to display for this period at {resort}.")
                    else:
                        st.error("Chart DataFrame missing required columns.")
                        st.session_state.debug_messages.append(f"Chart DataFrame columns: {chart_df.columns.tolist()} at {resort}")
                else:
                    st.info("No data available for comparison.")
                    st.session_state.debug_messages.append(f"Chart DataFrame is empty at {resort}.")
            
            st.subheader(f"Season and Holiday Calendar for {year_select}")
            gantt_fig = create_gantt_chart(resort, year_select)
            st.plotly_chart(gantt_fig, use_container_width=True)

        except Exception as e:
            st.error(f"Calculation failed: {str(e)}")
            st.session_state.debug_messages.append(f"Calculation error: {str(e)}\n{traceback.format_exc()}")
except Exception as e:
    st.error(f"Application failed to initialize: {str(e)}")
    st.session_state.debug_messages.append(f"Initialization error: {str(e)}\n{traceback.format_exc()}")

# Debug Information
with st.expander("Debug Information"):
    try:
        if st.button("Clear Debug Messages"):
            st.session_state.debug_messages = []
            st.session_state.debug_messages.append("Debug messages cleared.")
        if st.session_state.debug_messages:
            for msg in st.session_state.debug_messages:
                st.write(msg)
        else:
            st.write("No debug messages available.")
    except Exception as e:
        st.error(f"Error in debug section: {str(e)}")
        st.session_state.debug_messages.append(f"Debug section error: {str(e)}\n{traceback.format_exc()}")
