# from data import season_blocks, holiday_weeks, room_view_legend, reference_points
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

    # Handle compound keys like "Studio IV", "1BR OF", etc.
    parts = room_key.split()
    if not parts:
        return room_key

    base = parts[0]  # e.g., "Studio", "1BR"
    view = parts[-1]  # e.g., "IV", "OF"
    if len(parts) > 1 and view in room_view_legend:
        view_display = room_view_legend[view]
        return f"{base} {view_display}"
    
    # Fallback for simple keys like "2BR"
    if room_key in ["2BR", "1BR", "3BR"]:
        return room_key
    
    return room_key  # Default to original key if no match

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
    
    st.session_state.debug_messages.append(f"Processing date: {date_str}, Day of week: {day_of_week}")
    
    # Determine day category for regular and AP rooms
    is_fri_sat = day_of_week in ["Fri", "Sat"]
    is_sun = day_of_week == "Sun"
    day_category = "Fri-Sat" if is_fri_sat else "Sun-Thu"  # For regular rooms
    ap_day_category = "Fri-Sat" if is_fri_sat else ("Sun" if is_sun else "Mon-Thu")  # For AP rooms
    st.session_state.debug_messages.append(f"Day category determined: {day_category} (is_fri_sat: {is_fri_sat})")
    st.session_state.debug_messages.append(f"AP day category determined: {ap_day_category}")

    entry = {}

    # Check if the resort has AP rooms and identify AP room types
    ap_room_types = []
    if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points[resort]:
        ap_room_types = list(reference_points[resort]["AP Rooms"]["Fri-Sat"].keys())
        st.session_state.debug_messages.append(f"AP room types found: {ap_room_types}")

    # Determine season for the specific date
    season = None
    try:
        # Dynamically get season types for the resort and year
        season_types = list(season_blocks[resort][year].keys())
        st.session_state.debug_messages.append(f"Available season types for {resort} in {year}: {season_types}")
        for s_type in season_types:
            for [start, end] in season_blocks[resort][year][s_type]:
                s_start = datetime.strptime(start, "%Y-%m-%d").date()
                s_end = datetime.strptime(end, "%Y-%m-%d").date()
                st.session_state.debug_messages.append(f"Checking season {s_type}: {start} to {end}")
                if s_start <= date <= s_end:
                    season = s_type
                    st.session_state.debug_messages.append(f"Season match found: {season} for {date_str}")
                    break
            if season:
                break
    except ValueError as e:
        st.session_state.debug_messages.append(f"Invalid season date in {resort}, {year}, {s_type}: {e}")
    except KeyError as e:
        st.session_state.debug_messages.append(f"KeyError in season_blocks for {resort}, {year}: {e}")
        raise

    if not season:
        # Default to the first available season type if none match
        season = next(iter(season_blocks[resort][year].keys()), "Low Season")
        st.session_state.debug_messages.append(f"No season match found for {date_str}, defaulting to {season}")
    
    st.session_state.debug_messages.append(f"Final season determined for {date_str}: {season}")

    # Check for holiday week
    is_holiday = False
    is_holiday_start = False
    holiday_name = None
    try:
        for h_name, [start, end] in holiday_weeks[resort][year].items():
            h_start = datetime.strptime(start, "%Y-%m-%d").date()
            h_end = datetime.strptime(end, "%Y-%m-%d").date()
            st.session_state.debug_messages.append(f"Checking holiday {h_name}: {start} to {end}")
            if h_start <= date <= h_end:
                is_holiday = True
                holiday_name = h_name
                if date == h_start:
                    is_holiday_start = True
                st.session_state.debug_messages.append(f"Holiday match found: {holiday_name} for {date_str}")
                break
    except ValueError as e:
        st.session_state.debug_messages.append(f"Invalid holiday date in {resort}, {year}, {h_name}: {e}")

    # Assign points based on room type
    all_room_types = []
    all_display_room_types = []
    normal_room_types = list(reference_points[resort][season][day_category].keys())
    normal_display_room_types = [get_display_room_type(rt) for rt in normal_room_types]
    all_room_types.extend(normal_room_types)
    all_display_room_types.extend(normal_display_room_types)
    if ap_room_types:
        all_room_types.extend(ap_room_types)
        all_display_room_types.extend([get_display_room_type(rt) for rt in ap_room_types])

    display_to_internal = dict(zip(all_display_room_types, all_room_types))
    st.session_state.debug_messages.append(f"Room type mappings: {display_to_internal}")

    for display_room_type, room_type in display_to_internal.items():
        points = 0
        is_ap_room = room_type in ap_room_types

        if is_ap_room:
            points_ref = reference_points[resort]["AP Rooms"][ap_day_category]
            points = points_ref.get(room_type, 0)
            st.session_state.debug_messages.append(f"Applying AP room points for {room_type} ({display_room_type}) on {date_str} ({ap_day_category}): {points}")
        else:
            if is_holiday and is_holiday_start:
                points_ref = reference_points[resort]["Holiday Week"].get(holiday_name, {})
                points = points_ref.get(room_type, 0)
                st.session_state.debug_messages.append(f"Applying Holiday Week points for {holiday_name} on {date_str} for {display_room_type}: {points}")
            elif is_holiday and not is_holiday_start:
                points = 0
                st.session_state.debug_messages.append(f"Zero points for {date_str} (part of holiday week {holiday_name}) for {display_room_type}")
            else:
                points_ref = reference_points[resort][season][day_category]
                points = points_ref.get(room_type, 0)
                st.session_state.debug_messages.append(f"Applying {season} {day_category} points for {date_str} for {display_room_type}: {points}")

        entry[display_room_type] = points

    # Add holiday info
    if is_holiday:
        entry["HolidayWeek"] = True
        entry["holiday_name"] = holiday_name
        if is_holiday_start:
            entry["HolidayWeekStart"] = True

    return entry, display_to_internal

# Function to adjust date range for holiday weeks
def adjust_date_range(resort, checkin_date, num_nights):
    year_str = str(checkin_date.year)
    stay_end = checkin_date + timedelta(days=num_nights - 1)
    holiday_ranges = []
    
    st.session_state.debug_messages.append(f"Checking holiday overlap for {checkin_date} to {stay_end}")
    try:
        for h_name, [start, end] in holiday_weeks[resort][year_str].items():
            h_start = datetime.strptime(start, "%Y-%m-%d").date()
            h_end = datetime.strptime(end, "%Y-%m-%d").date()
            st.session_state.debug_messages.append(f"Evaluating holiday {h_name}: {h_start} to {h_end}")
            if (h_start <= stay_end) and (h_end >= checkin_date):
                holiday_ranges.append((h_start, h_end))
                st.session_state.debug_messages.append(f"Holiday overlap found with {h_name}")
            else:
                st.session_state.debug_messages.append(f"No overlap with {h_name}")
    except ValueError as e:
        st.session_state.debug_messages.append(f"Invalid holiday range in {resort}, {year_str}: {e}")

    if holiday_ranges:
        earliest_holiday_start = min(h_start for h_start, _ in holiday_ranges)
        latest_holiday_end = max(h_end for _, h_end in holiday_ranges)
        adjusted_start = min(checkin_date, earliest_holiday_start)
        adjusted_end = max(stay_end, latest_holiday_end)
        adjusted_nights = (adjusted_end - adjusted_start).days + 1
        st.session_state.debug_messages.append(f"Adjusted date range to include holiday week: {adjusted_start} to {adjusted_end} ({adjusted_nights} nights)")
        return adjusted_start, adjusted_nights, True
    st.session_state.debug_messages.append(f"No holiday week adjustment needed for {checkin_date} to {stay_end}")
    return checkin_date, num_nights, False

# Function to create Gantt chart
def create_gantt_chart(resort, year):
    gantt_data = []
    year_str = str(year)
    
    try:
        # Add holidays
        for h_name, [start, end] in holiday_weeks[resort][year_str].items():
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
            gantt_data.append({
                "Task": h_name,
                "Start": start_date,
                "Finish": end_date,
                "Type": "Holiday"
            })
            st.session_state.debug_messages.append(f"Added holiday: {h_name}, Start: {start_date}, Finish: {end_date}")

        # Dynamically get season types for the resort and year
        season_types = list(season_blocks[resort][year_str].keys())
        st.session_state.debug_messages.append(f"Available season types for Gantt chart in {resort}, {year}: {season_types}")
        
        # Add seasons
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
                st.session_state.debug_messages.append(f"Added season: {season_type} {i}, Start: {start_date}, Finish: {end_date}")
    
        df = pd.DataFrame(gantt_data)
        if df.empty:
            st.session_state.debug_messages.append("Gantt DataFrame is empty")
            # Create a valid fallback DataFrame for px.timeline
            current_date = datetime.now().date()
            df = pd.DataFrame({
                "Task": ["No Data"],
                "Start": [current_date],
                "Finish": [current_date + timedelta(days=1)],
                "Type": ["No Data"]
            })

        # Define a color palette for different season types
        color_palette = {
            "Holiday": "rgb(255, 99, 71)",  # Tomato for Holiday
            "Low Season": "rgb(135, 206, 250)",  # SkyBlue for Low Season
            "High Season": "rgb(255, 69, 0)",  # RedOrange High Season
            "Peak Season": "rgb(255, 215, 0)",  # Gold for Peak Season
            "Shoulder": "rgb(50, 205, 50)",  # LimeGreen for Shoulder
            "Peak": "rgb(255, 69, 0)",  # RedOrange for Peak
            "Summer": "rgb(255, 165, 0)",  # Orange for Summer
            "Low": "rgb(70, 130, 180)",  # SteelBlue for Low
            "Mid Season": "rgb(60, 179, 113)",  # MediumSeaGreen for Mid Season
            "No Data": "rgb(128, 128, 128)",  # Grey for No Data
            "Error": "rgb(128, 128, 128)"  # Grey for Error
        }
        
        # Create a color map based on the types present in the data
        types_present = df["Type"].unique()
        colors = {t: color_palette.get(t, "rgb(169, 169, 169)") for t in types_present}  # Default to DarkGrey if type not in palette
        
        fig = px.timeline(
            df,
            x_start="Start",
            x_end="Finish",
            y="Task",
            color="Type",
            color_discrete_map=colors,
            title=f"{resort_aliases.get(resort, resort)} Seasons and Holidays ({year})",
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
        st.session_state.debug_messages.append(f"Error in create_gantt_chart: {str(e)}")
        # Create a valid fallback DataFrame for px.timeline
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

# Resort display name mapping
resort_aliases = {
    "Sheraton Kauai": "Sheraton Kauai",
    "Kauai Beach Club": "Kauai Beach Club",
    "Ko Olina Beach Club": "Ko Olina Beach Club",
    "Grande Vista": "Grande Vista",
    "Newport Coast Villas": "Newport Coast Villas",
    "Crystal Shores": "Crystal Shores",
    "Maui Ocean Club": "Maui Ocean Club",
    "Shadow Ridge": "Shadow Ridge",
    "Desert Springs Villas II": "Desert Springs Villas II"
}
reverse_aliases = {v: k for k, v in resort_aliases.items()}
display_resorts = list(resort_aliases.values())

# Sidebar for discount
with st.sidebar:
    discount_percent = st.selectbox(
        "Apply Points Discount",
        options=[0, 25, 30],
        index=0,
        format_func=lambda x: f"{x}%" if x else "No Discount"
    )
    st.caption("Discount is for my use only. Rent is based on FULL undiscounted points.")

discount_multiplier = 1 - (discount_percent / 100)

# Title and user input
st.title("Marriott Vacation Club Rent Calculator")

with st.expander("\U0001F334 How Rent Is Calculated"):
    st.markdown("""
    - **Rent is based on FULL (un-discounted) points only.**
    - $0.81 per FULL point for dates in **2025**
    - $0.86 per FULL point for dates in **2026 and beyond**
    - **Holiday weeks**: For days within a holiday week, please contact me for quotes.
    """)

# User input for resort, room type, check-in date, and number of nights
resort_display = st.selectbox("Select Resort", options=display_resorts, index=display_resorts.index("Ko Olina Beach Club"), key="resort_select")
resort = reverse_aliases.get(resort_display, resort_display)

checkin_date = st.date_input("Check-in Date", min_value=datetime(2024, 12, 27).date(), max_value=datetime(2026, 12, 31).date(), value=datetime(2026, 7, 10).date())
num_nights = st.number_input("Number of Nights", min_value=1, max_value=30, value=7)

# Derive year from check-in date
year_select = str(checkin_date.year)

# Get room types and AP room types
sample_date = checkin_date  # Use check-in date for room types
sample_entry, display_to_internal = generate_data(resort, sample_date)
room_types = sorted([k for k in sample_entry if k not in ("HolidayWeek", "HolidayWeekStart", "holiday_name")])
if not room_types:
    st.error(f"No room types found for {resort}.")
    st.session_state.debug_messages.append(f"No room types for {resort}")
    st.stop()

# Reset AP room types for non-Ko Olina resorts
ap_room_types = []
ap_display_room_types = []
if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points[resort]:
    ap_room_types = list(reference_points[resort]["AP Rooms"]["Fri-Sat"].keys())
    ap_display_room_types = [get_display_room_type(rt) for rt in ap_room_types]
    for rt_display in ap_display_room_types:
        st.session_state.debug_messages.append(f"Added AP room type: {rt_display}")

room_type = st.selectbox("Select Room Type", options=room_types, key="room_type_select")
compare_rooms = st.multiselect("Compare With Other Room Types", options=[r for r in room_types if r != room_type])

# Adjust date range for holidays
original_checkin_date = checkin_date
checkin_date, adjusted_nights, was_adjusted = adjust_date_range(resort, checkin_date, num_nights)
if was_adjusted:
    st.info(f"Date range adjusted to include full holiday week: {checkin_date.strftime('%Y-%m-%d')} to {(checkin_date + timedelta(days=adjusted_nights - 1)).strftime('%Y-%m-%d')} ({adjusted_nights} nights).")
st.session_state.last_checkin_date = checkin_date

# Set reference points for calculations
reference_entry, _ = generate_data(resort, sample_date)
reference_points_resort = {k: v for k, v in reference_entry.items() if k not in ("HolidayWeek", "HolidayWeekStart", "holiday_name")}

# Functions for calculating stay details
def calculate_stay(resort, room_type, checkin_date, num_nights, discount_multiplier, discount_percent):
    """
    Calculate the breakdown, total points, and estimated rent for a given stay.
    
    Args:
        resort (str): The selected resort.
        room_type (str): The selected room type.
        checkin_date (date): The check-in date.
        num_nights (int): Number of nights.
        discount_multiplier (float): Discount multiplier for points.
        discount_percent (int): Discount percentage applied.
    
    Returns:
        tuple: (breakdown_list, total_points, total_rent)
    """
    breakdown = []
    total_points = 0
    total_rent = 0
    # Set rate per point based on year
    rate_per_point = 0.81 if checkin_date.year == 2025 else 0.86
    for i in range(num_nights):
        date = checkin_date + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        entry, _ = generate_data(resort, date)
        
        points = entry.get(room_type, reference_points_resort.get(room_type, 0))
        st.session_state.debug_messages.append(f"Calculating for {date_str}: Points for {room_type} = {points}")
        discounted_points = math.floor(points * discount_multiplier)
        rent = math.ceil(points * rate_per_point)  # Rent based on full points
        breakdown.append({
            "Date": date_str,
            "Day": date.strftime("%a"),
            "Points": discounted_points,  # Use discounted points here
            "Rent": f"${rent}",
            "Holiday": entry.get("holiday_name", "No")
        })
        if "HolidayWeek" in entry and entry.get("HolidayWeekStart", False):
            breakdown[-1]["HolidayMarker"] = "\U0001F386"  # Correct Unicode for 🎆
        total_points += discounted_points
        total_rent += rent

    return breakdown, total_points, total_rent

def compare_room_types(resort, room_types, checkin_date, num_nights, discount_multiplier, discount_percent, ap_display_room_types):
    """
    Compare rents across multiple room types for the stay.
    
    Args:
        resort (str): The selected resort.
        room_types (list): List of room types to compare.
        checkin_date (date): Check-in date.
        num_nights (int): Number of nights.
        discount_multiplier (float): Discount multiplier for points.
        discount_percent (int): Discount percentage applied.
        ap_display_room_types (list): List of AP room display names.
    
    Returns:
        tuple: (chart_df, compare_df_pivot, holiday_totals)
    """
    rate_per_point = 0.81 if checkin_date.year == 2025 else 0.86
    compare_data = []
    chart_data = []
    
    # Collect all relevant dates
    all_dates = [checkin_date + timedelta(days=i) for i in range(num_nights)]
    stay_start = checkin_date
    stay_end = checkin_date + timedelta(days=num_nights - 1)
    
    # Identify holidays that overlap with the stay
    holiday_ranges = []
    holiday_names = {}
    for h_name, [start, end] in holiday_weeks[resort][str(checkin_date.year)].items():
        h_start = datetime.strptime(start, "%Y-%m-%d").date()
        h_end = datetime.strptime(end, "%Y-%m-%d").date()
        if (h_start <= stay_end) and (h_end >= stay_start):
            holiday_ranges.append((h_start, h_end))
            for d in [h_start + timedelta(days=x) for x in range((h_end - h_start).days + 1)]:
                if d in all_dates:
                    holiday_names[d] = h_name
                    st.session_state.debug_messages.append(f"Date {d} overlaps with holiday {h_name} ({h_start} to {h_end})")
    
    total_rent_by_room = {room: 0 for room in room_types}  # Track total rent for non-holiday days
    holiday_totals = {room: {} for room in room_types}  # Track holiday week totals
    
    for room in room_types:
        internal_room = display_to_internal.get(room, room)
        st.session_state.debug_messages.append(f"Mapping for room {room}: Internal key = {internal_room}")
        is_ap_room = room in ap_display_room_types
        current_holiday = None
        
        for date in all_dates:
            date_str = date.strftime("%Y-%m-%d")
            day_of_week = date.strftime("%a")
            entry, _ = generate_data(resort, date)
            
            points = entry.get(room, reference_points_resort.get(room, 0))
            st.session_state.debug_messages.append(f"Points for {room} on {date_str} ({day_of_week}): {points}")
            discounted_points = math.floor(points * discount_multiplier)
            rent = math.ceil(points * rate_per_point)
            rent_str = f"${rent}"
            
            # Check if this date is within a holiday week
            is_holiday_date = any(h_start <= date <= h_end for h_start, h_end in holiday_ranges)
            holiday_name = holiday_names.get(date, None)
            if is_holiday_date and entry.get("HolidayWeekStart", False):
                current_holiday = holiday_name
                if current_holiday not in holiday_totals[room]:
                    h_start = min(h for h, _ in holiday_ranges if holiday_names.get(date) == current_holiday)
                    h_end = max(e for _, e in holiday_ranges if holiday_names.get(date) == current_holiday)
                    holiday_totals[room][current_holiday] = {"points": 0, "rent": 0, "start": h_start, "end": h_end}
                if is_ap_room:
                    # Use full-week points for AP rooms during holiday weeks
                    full_week_points = reference_points[resort]["AP Rooms"]["Full Week"].get(internal_room, 0)
                    full_week_discounted = math.floor(full_week_points * discount_multiplier)
                    holiday_totals[room][current_holiday]["points"] = full_week_discounted
                    holiday_totals[room][current_holiday]["rent"] = math.ceil(full_week_points * rate_per_point)
                    st.session_state.debug_messages.append(f"AP Room {room} on {date_str}: Using full week points {full_week_points}, rent = ${holiday_totals[room][current_holiday]['rent']}")
                else:
                    # For normal rooms, use first-day points
                    holiday_totals[room][current_holiday]["points"] = discounted_points
                    holiday_totals[room][current_holiday]["rent"] = rent
                    st.session_state.debug_messages.append(f"Normal Room {room} on {date_str}: Using first-day points {points}, rent = ${rent}")
            elif is_holiday_date and current_holiday and not is_ap_room:
                # Skip adding to compare_data for normal rooms after holiday week start
                continue
            else:
                current_holiday = None
            
            # Add to comparison data only for non-holiday days or AP rooms
            if not current_holiday or is_ap_room:
                compare_data.append({
                    "Date": date_str,
                    "Room Type": room,
                    "Rent": rent_str,
                })
                total_rent_by_room[room] += rent
            
            chart_data.append({
                "Date": date,
                "DateStr": date_str,
                "Day": day_of_week,
                "Room Type": room,
                "Rent": rent_str,
                "RentValue": rent,
                "Points": discounted_points,
                "Holiday": entry.get("holiday_name", "No")
            })
    
    # Add total rent row for non-holiday periods
    total_row = {"Date": "Total Rent (Non-Holiday)"}
    for room in room_types:
        total_row[room] = f"${total_rent_by_room[room]}"
    compare_data.append(total_row)
    
    # Add holiday week totals with date ranges
    for room in room_types:
        for holiday_name, totals in holiday_totals[room].items():
            if totals["rent"] > 0:
                start_str = totals["start"].strftime("%b %d")
                end_str = totals["end"].strftime("%b %d, %Y")
                compare_data.append({
                    "Date": f"{holiday_name} Holiday ({start_str} - {end_str})",
                    "Room Type": room,
                    "Rent": f"${totals['rent']}",
                })
    
    compare_df = pd.DataFrame(compare_data)
    compare_df_pivot = compare_df.pivot_table(
        index="Date",
        columns="Room Type",
        values=["Rent"],
        aggfunc="first"
    ).reset_index()
    compare_df_pivot.columns = ['Date'] + [f"{col[1]} {col[0]}" for col in compare_df_pivot.columns[1:]]
    chart_df = pd.DataFrame(chart_data)
    
    st.session_state.debug_messages.append(f"Comparing DataFrame columns: {chart_df.columns.tolist()}")
    st.session_state.debug_messages.append(f"Comparing Chart DataFrame to: {chart_df.head().to_dict()}")
    
    return chart_df, compare_df_pivot, holiday_totals

# Main Calculation
if st.button("Calculate"):
    # Clear debug messages before starting a new calculation
    st.session_state.debug_messages = []
    st.session_state.debug_messages.append("Starting new calculation...")

    # Calculate stay details
    breakdown, total_points, total_rent = calculate_stay(
        resort, room_type, checkin_date, adjusted_nights, discount_multiplier, discount_percent
    )
    
    # Display stay breakdown
    st.subheader("Stay Breakdown")
    if breakdown:
        df_breakdown = pd.DataFrame(breakdown)
        st.dataframe(df_breakdown, use_container_width=True)
    else:
        st.error("No data available for the selected period.")
    
    st.success(f"Total Points Used: {total_points}")
    st.success(f"Estimated Total Rent: ${total_rent}")
    
    # Provide download button for breakdown
    if breakdown:
        csv_data = df_breakdown.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Breakdown as CSV",
            data=csv_data,
            file_name=f"{resort}_stay_breakdown.csv",
            mime="text/csv"
        )
    
    # Display room type comparison if selected
    if compare_rooms:
        st.subheader("Room Type Comparison")
        st.info("Note: Non-holiday weeks are compared day-by-day; holiday weeks are compared as total rent for the week.")
        all_rooms = [room_type] + compare_rooms
        chart_df, compare_df_pivot, holiday_totals = compare_room_types(
            resort, all_rooms, checkin_date, adjusted_nights, discount_multiplier, 
            discount_percent, ap_display_room_types
        )
        
        rent_columns = ["Date"] + [col for col in compare_df_pivot.columns if "Rent" in col]
        st.write("### Estimated Rent ($)")
        st.dataframe(compare_df_pivot[rent_columns], use_container_width=True)
        
        # Download comparison data
        compare_csv = compare_df_pivot.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Room Comparison as CSV",
            data=compare_csv,
            file_name=f"{resort}_room_comparison.csv",
            mime="text/csv"
        )
        
        # Generate comparison charts
        if not chart_df.empty:
            required_columns = ["Date", "Room Type", "Rent", "RentValue", "Points", "Holiday"]
            if all(col in chart_df.columns for col in required_columns):
                # Non-Holiday data
                non_holiday_df = chart_df[chart_df["Holiday"] == "No"]
                holiday_data = []
                for room in all_rooms:
                    for holiday_name, totals in holiday_totals[room].items():
                        if totals["rent"] > 0:
                            holiday_data.append({
                                "Holiday": holiday_name,
                                "Room Type": room,
                                "Rent": f"${totals['rent']}",
                                "RentValue": totals["rent"],
                                "Start": totals["start"],
                                "End": totals["end"]
                            })
                holiday_df = pd.DataFrame(holiday_data)
                
                if not non_holiday_df.empty:
                    start_date = non_holiday_df["Date"].min()
                    end_date = non_holiday_df["Date"].max()
                    start_date_str = start_date.strftime("%b %d")
                    end_date_str = end_date.strftime("%b %d, %Y")
                    title = f"Rent Comparison (Non-Holiday, {start_date_str} - {end_date_str})"
                    st.subheader(title)
                    # Ensure correct day order starting from July 10, 2026 (Friday)
                    day_order = ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]
                    fig = px.bar(
                        non_holiday_df,
                        x="Day",
                        y="RentValue",
                        color="Room Type",
                        barmode="group",
                        title=title,
                        labels={"RentValue": "Estimated Rent ($)", "Day": "Day of Week"},
                        height=600,
                        text="Rent",
                        text_auto=True,
                        category_orders={"Day": day_order}
                    )
                    fig.update_traces(texttemplate="$%{text}", textposition="auto")
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
                    # Calculate the overall date range for holidays
                    start_date = holiday_df["Start"].min()
                    end_date = holiday_df["End"].max()
                    start_date_str = start_date.strftime("%b %d")
                    end_date_str = end_date.strftime("%b %d, %Y")
                    title = f"Rent Comparison (Holiday Weeks, {start_date_str} - {end_date_str})"
                    st.subheader(title)
                    fig = px.bar(
                        holiday_df,
                        x="Holiday",
                        y="RentValue",
                        color="Room Type",
                        barmode="group",
                        title=title,
                        labels={"RentValue": "Estimated Rent ($)", "Holiday": "Holiday Week"},
                        height=600,
                        text="Rent",
                        text_auto=True
                    )
                    fig.update_traces(texttemplate="$%{text}", textposition="auto")
                    fig.update_layout(
                        legend_title_text="Room Type",
                        bargap=0.2,
                        bargroupgap=0.1
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.session_state.debug_messages.append("No holiday data to display for this period.")
            else:
                st.error("Chart DataFrame missing required columns.")
                st.session_state.debug_messages.append(f"Chart DataFrame columns: {chart_df.columns.tolist()}")
        else:
            st.info("No data available for comparison.")
            st.session_state.debug_messages.append("Chart DataFrame is empty.")
    
    # Display Gantt chart after all calculations
    st.subheader(f"Season and Holiday Calendar for {year_select}")
    gantt_fig = create_gantt_chart(resort, year_select)
    st.plotly_chart(gantt_fig, use_container_width=True)

# Debug Information
with st.expander("Debug Information"):
    # Add a button to manually clear debug messages
    if st.button("Clear Debug Messages"):
        st.session_state.debug_messages = []
        st.session_state.debug_messages.append("Debug messages cleared.")
    
    if st.session_state.debug_messages:
        for msg in st.session_state.debug_messages:
            st.write(msg)
    else:
        st.write("No debug messages available.")
