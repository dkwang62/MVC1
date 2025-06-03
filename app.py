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
from datetime import datetime

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
        # Determine day category dynamically
        possible_day_categories = ["Fri-Sat", "Sun", "Mon-Thu", "Sun-Thu"]
        available_day_categories = [cat for cat in possible_day_categories if cat in reference_points[resort][season]]
        st.session_state.debug_messages.append(f"Available day categories for {resort}, {season}: {available_day_categories}")

        if not available_day_categories:
            raise KeyError(f"No valid day categories found for {resort}, {season}")

        # Select appropriate day category
        if is_fri_sat and "Fri-Sat" in available_day_categories:
            normal_room_category = "Fri-Sat"
        elif is_sun and "Sun" in available_day_categories:
            normal_room_category = "Sun"
        elif not is_fri_sat and "Mon-Thu" in available_day_categories:
            normal_room_category = "Mon-Thu"
        elif "Sun-Thu" in available_day_categories:
            normal_room_category = "Sun-Thu"
        else:
            normal_room_category = available_day_categories[0]  # Fallback to first available
            st.session_state.debug_messages.append(f"Fallback to {normal_room_category} for {date_str}")

        st.session_state.debug_messages.append(f"Selected normal room category: {normal_room_category}")

        normal_room_types = list(reference_points[resort][season][normal_room_category].keys())
        st.session_state.debug_messages.append(f"Normal room types found for {normal_room_category}: {normal_room_types}")

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
        holiday_name = None
        if year in holiday_weeks.get(resort, {}):
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

        for display_room_type, room_type in display_to_internal.items():
            points = 0
            is_ap_room = room_type in ap_room_types

            if is_ap_room:
                points_ref = reference_points[resort]["AP Rooms"].get(ap_day_category, {})
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
                    points_ref = reference_points[resort][season][normal_room_category]
                    points = points_ref.get(room_type, 0)
                    st.session_state.debug_messages.append(f"Applying {season} {normal_room_category} points for {date_str} for {display_room_type}: {points}")

            entry[display_room_type] = points

        if is_holiday:
            entry["HolidayWeek"] = True
            entry["holiday_name"] = holiday_name
            if is_holiday_start:
                entry["HolidayWeekStart"] = True

        return entry, display_to_internal
    except KeyError as e:
        st.session_state.debug_messages.append(f"KeyError: {str(e)} for resort={resort}, season={season}, normal_room_category={normal_room_category}, ap_day_category={ap_day_category}")
        st.error(f"Error accessing reference points for {resort}, season {season}, day category {normal_room_category}. Check data.json.")
        raise    
    if not season:
        season = next(iter(season_blocks[resort][year].keys()), "Low Season")
        st.session_state.debug_messages.append(f"No season match found for {date_str}, defaulting to {season}")
    
    st.session_state.debug_messages.append(f"Final season determined for {date_str}: {season}")

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

        season_types = list(season_blocks[resort][year_str].keys())
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
                st.session_state.debug_messages.append(f"Added season: {season_type} {i}, Start: {start_date}, Finish: {end_date}")
    
        df = pd.DataFrame(gantt_data)
        if df.empty:
            st.session_state.debug_messages.append("Gantt DataFrame is empty")
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
    "Desert Springs Villas II": "Desert Springs Villas II",
    "Marriott's Bali Nusa Dua Terrace": "Marriott's Bali Nusa Dua Terrace",
    "Marriott's Bali Nusa Dua Gardens": "Marriott's Bali Nusa Dua Gardens",
    "Marriott's Phuket Beach Club": "Marriott's Phuket Beach Club",
    "The Westin Ka'anapali Ocean Resort Villas": "The Westin Ka'anapali Ocean Resort Villas" 
}
reverse_aliases = {v: k for k, v in resort_aliases.items()}
display_resorts = list(resort_aliases.values())

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
        else:
            return f"{discount}% Discount ({level}, Cost)"

    display_mode_select = st.selectbox(
        "Display and Discount Settings",
        options=range(len(display_options)),
        format_func=format_discount,
        index=0
    )

    discount_percent, display_mode = display_options[display_mode_select]
    rate_per_point = st.number_input("Maintenance Rate per Point ($)", min_value=0.0, value=0.81, step=0.01)
    capital_cost_per_point = st.number_input("Capital Cost per Point ($)", min_value=0.0, value=16.0, step=0.1)
    cost_of_capital_percent = st.number_input("Cost of Capital (%)", min_value=0.0, max_value=100.0, value=7.0, step=0.1)
    cost_of_capital = cost_of_capital_percent / 100
    st.caption(f"Cost calculation is based on {discount_percent}% discount.")

discount_multiplier = 1 - (discount_percent / 100)

# Title and user input
st.title("Marriott Vacation Club Cost Calculator")

with st.expander("\U0001F334 How Cost Is Calculated"):
    st.markdown(f"""
    - Ordinary Membership do not have last minute discounts
    - Maintenance rate: ${rate_per_point:.2f} per point (user-defined)
    - Capital cost per point: ${capital_cost_per_point:.2f} (user-defined)
    - Cost of capital: {cost_of_capital_percent:.1f}% (user-defined)
    - Selected discount: {discount_percent}% (applied to points and cost calculations)
    - Cost of capital is calculated as (points * capital cost per point * cost of capital percentage)
    - Total cost is maintenance cost (points * maintenance rate) plus capital cost
    """)

resort_display = st.selectbox("Select Resort", options=display_resorts, index=display_resorts.index("Ko Olina Beach Club"), key="resort_select")
resort = reverse_aliases.get(resort_display, resort_display)

checkin_date = st.date_input("Check-in Date", min_value=datetime(2024, 12, 27).date(), max_value=datetime(2026, 12, 31).date(), value=datetime(2026, 7, 10).date())
num_nights = st.number_input("Number of Nights", min_value=1, max_value=30, value=7)

year_select = str(checkin_date.year)

sample_date = checkin_date
sample_entry, display_to_internal = generate_data(resort, sample_date)
room_types = sorted([k for k in sample_entry if k not in ("HolidayWeek", "HolidayWeekStart", "holiday_name")])
if not room_types:
    st.error(f"No room types found for {resort}.")
    st.session_state.debug_messages.append(f"No room types for {resort}")
    st.stop()

ap_room_types = []
ap_display_room_types = []
if resort == "Ko Olina Beach Club" and "AP Rooms" in reference_points[resort]:
    ap_room_types = list(reference_points[resort]["AP Rooms"]["Fri-Sat"].keys())
    ap_display_room_types = [get_display_room_type(rt) for rt in ap_room_types]
    for rt_display in ap_display_room_types:
        st.session_state.debug_messages.append(f"Added AP room type: {rt_display}")

room_type = st.selectbox("Select Room Type", options=room_types, key="room_type_select")
compare_rooms = st.multiselect("Compare With Other Room Types", options=[r for r in room_types if r != room_type])

original_checkin_date = checkin_date
checkin_date, adjusted_nights, was_adjusted = adjust_date_range(resort, checkin_date, num_nights)
if was_adjusted:
    st.info(f"Date range adjusted to include full holiday week: {checkin_date.strftime('%Y-%m-%d')} to {(checkin_date + timedelta(days=adjusted_nights - 1)).strftime('%Y-%m-%d')} ({adjusted_nights} nights).")
st.session_state.last_checkin_date = checkin_date

reference_entry, _ = generate_data(resort, sample_date)
reference_points_resort = {k: v for k, v in reference_entry.items() if k not in ("HolidayWeek", "HolidayWeekStart", "holiday_name")}

def calculate_stay(resort, room_type, checkin_date, num_nights, discount_percent, discount_multiplier, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital):
    breakdown = []
    total_points = 0
    total_rent = 0
    total_capital_cost = 0
    for i in range(num_nights):
        date = checkin_date + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        entry, _ = generate_data(resort, date)
        
        points = entry.get(room_type, reference_points_resort.get(room_type, 0))
        st.session_state.debug_messages.append(f"Calculating for {date_str}: Points for {room_type} = {points}")
        discounted_points = math.floor(points * discount_multiplier)
        row = {
            "Date": date_str,
            "Day": date.strftime("%a"),
            "Points": discounted_points,
            "Holiday": entry.get("holiday_name", "No")
        }
        if display_mode == "both":
            maintenance_cost = math.ceil(discounted_points * rate_per_point)
            capital_cost = math.ceil(discounted_points * capital_cost_per_point * cost_of_capital)
            total_day_cost = maintenance_cost + capital_cost
            row["Cost"] = f"${total_day_cost}"
            row["Maintenance Cost"] = f"${maintenance_cost}"
            row["Capital Cost"] = f"${capital_cost}"
            total_rent += total_day_cost
            total_capital_cost += capital_cost
        if "HolidayWeek" in entry and entry.get("HolidayWeekStart", False):
            row["HolidayMarker"] = "\U0001F386"
        breakdown.append(row)
        total_points += discounted_points

    return breakdown, total_points, total_rent, total_capital_cost

def compare_room_types(resort, room_types, checkin_date, num_nights, discount_multiplier, discount_percent, ap_display_room_types, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital):
    compare_data = []
    chart_data = []
    
    all_dates = [checkin_date + timedelta(days=i) for i in range(num_nights)]
    stay_start = checkin_date
    stay_end = checkin_date + timedelta(days=num_nights - 1)
    
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
    
    total_points_by_room = {room: 0 for room in room_types}
    total_rent_by_room = {room: 0 for room in room_types}
    holiday_totals = {room: {} for room in room_types}
    
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
            is_holiday_date = any(h_start <= date <= h_end for h_start, h_end in holiday_ranges)
            holiday_name = holiday_names.get(date, None)
            if is_holiday_date and entry.get("HolidayWeekStart", False):
                current_holiday = holiday_name
                if current_holiday not in holiday_totals[room]:
                    h_start = min(h for h, _ in holiday_ranges if holiday_names.get(date) == current_holiday)
                    h_end = max(e for _, e in holiday_ranges if holiday_names.get(date) == current_holiday)
                    holiday_totals[room][current_holiday] = {"points": 0, "start": h_start, "end": h_end}
                if is_ap_room:
                    full_week_points = reference_points[resort]["AP Rooms"]["Full Week"].get(internal_room, 0)
                    full_week_discounted = math.floor(full_week_points * discount_multiplier)
                    holiday_totals[room][current_holiday]["points"] = full_week_discounted
                    st.session_state.debug_messages.append(f"AP Room {room} on {date_str}: Using full week points {full_week_points}")
                else:
                    holiday_totals[room][current_holiday]["points"] = discounted_points
                    st.session_state.debug_messages.append(f"Normal Room {room} on {date_str}: Using first-day points {points}")
            elif is_holiday_date and current_holiday and not is_ap_room:
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
                    total_day_cost = maintenance_cost + capital_cost
                    row["Rent"] = f"${total_day_cost}"
                    row["Maintenance Cost"] = f"${maintenance_cost}"
                    row["Capital Cost"] = f"${capital_cost}"
                    total_rent_by_room[room] += total_day_cost
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
                total_day_cost = maintenance_cost + capital_cost
                chart_row["Rent"] = f"${total_day_cost}"
                chart_row["RentValue"] = total_day_cost
                chart_row["Maintenance Cost"] = f"${maintenance_cost}"
                chart_row["Capital Cost"] = f"${capital_cost}"
            chart_data.append(chart_row)
            
            if not current_holiday or is_ap_room:
                total_points_by_room[room] += discounted_points
    
    total_row = {"Date": "Total Points (Non-Holiday)"}
    for room in room_types:
        total_row[room] = total_points_by_room[room]
    compare_data.append(total_row)
    
    if display_mode == "both":
        total_rent_row = {"Date": "Total Cost (Non-Holiday)"}
        for room in room_types:
            total_rent_row[room] = f"${total_rent_by_room[room]}"
        compare_data.append(total_rent_row)
    
    for room in room_types:
        for holiday_name, totals in holiday_totals[room].items():
            if totals["points"] > 0:
                start_str = totals["start"].strftime("%b %d")
                end_str = totals["end"].strftime("%b %d, %Y")
                row = {
                    "Date": f"{holiday_name} Holiday ({start_str} - {end_str})",
                    "Room Type": room,
                    "Points": totals["points"]
                }
                if display_mode == "both":
                    maintenance_cost = math.ceil(totals["points"] * rate_per_point)
                    capital_cost = math.ceil(totals["points"] * capital_cost_per_point * cost_of_capital)
                    total_holiday_cost = maintenance_cost + capital_cost
                    row["Rent"] = f"${total_holiday_cost}"
                    row["Maintenance Cost"] = f"${maintenance_cost}"
                    row["Capital Cost"] = f"${capital_cost}"
                compare_data.append(row)
    
    compare_df = pd.DataFrame(compare_data)
    compare_df_pivot = compare_df.pivot_table(
        index="Date",
        columns="Room Type",
        values=["Points"] if display_mode == "points" else ["Points", "Rent", "Maintenance Cost", "Capital Cost"],
        aggfunc="first"
    ).reset_index()
    compare_df_pivot.columns = ['Date'] + [f"{col[1]} {col[0]}" for col in compare_df_pivot.columns[1:]]
    chart_df = pd.DataFrame(chart_data)
    
    st.session_state.debug_messages.append(f"Comparing DataFrame columns: {chart_df.columns.tolist()}")
    st.session_state.debug_messages.append(f"Comparing Chart DataFrame to: {chart_df.head().to_dict()}")
    
    return chart_df, compare_df_pivot, holiday_totals

# Main Calculation
if st.button("Calculate"):
    st.session_state.debug_messages = []
    st.session_state.debug_messages.append("Starting new calculation...")

    breakdown, total_points, total_rent, total_capital_cost = calculate_stay(
        resort, room_type, checkin_date, adjusted_nights, discount_percent, discount_multiplier, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital
    )
    
    st.subheader("Stay Breakdown")
    if breakdown:
        df_breakdown = pd.DataFrame(breakdown)
        st.dataframe(df_breakdown, use_container_width=True)
    else:
        st.error("No data available for the selected period.")
    
    st.success(f"Total Points Used: {total_points}")
    if display_mode == "both":
        st.success(f"Estimated Total Cost: ${total_rent}")
        st.success(f"Total Capital Cost Component: ${total_capital_cost}")
    
    if breakdown:
        csv_data = df_breakdown.to_csv(index=False).encode('utf-8')
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
            discount_percent, ap_display_room_types, display_mode, rate_per_point, capital_cost_per_point, cost_of_capital
        )
        
        display_columns = ["Date"] + [col for col in compare_df_pivot.columns if "Points" in col or (display_mode == "both" and ("Rent" in col or "Maintenance Cost" in col or "Capital Cost" in col))]
        st.write(f"### {'Points' if display_mode == 'points' else 'Points, Rent, Maintenance, and Capital Costs'} Comparison")
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
                required_columns.extend(["Rent", "RentValue", "Maintenance Cost", "Capital Cost"])
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
                                total_holiday_cost = maintenance_cost + capital_cost
                                row["Rent"] = f"${total_holiday_cost}"
                                row["RentValue"] = total_holiday_cost
                                row["Maintenance Cost"] = f"${maintenance_cost}"
                                row["Capital Cost"] = f"${capital_cost}"
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
                    st.session_state.debug_messages.append("No holiday data to display for this period.")
            else:
                st.error("Chart DataFrame missing required columns.")
                st.session_state.debug_messages.append(f"Chart DataFrame columns: {chart_df.columns.tolist()}")
        else:
            st.info("No data available for comparison.")
            st.session_state.debug_messages.append("Chart DataFrame is empty.")
    
    st.subheader(f"Season and Holiday Calendar for {year_select}")
    gantt_fig = create_gantt_chart(resort, year_select)
    st.plotly_chart(gantt_fig, use_container_width=True)

# Debug Information
with st.expander("Debug Information"):
    if st.button("Clear Debug Messages"):
        st.session_state.debug_messages = []
        st.session_state.debug_messages.append("Debug messages cleared.")
    
    if st.session_state.debug_messages:
        for msg in st.session_state.debug_messages:
            st.write(msg)
    else:
        st.write("No debug messages available.")
