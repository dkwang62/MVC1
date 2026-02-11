Calculator.py Reorganization - Changes Summary
Overview
The calculator.py file has been reorganized to improve the user flow by showing all available room types first, then allowing users to select a room type to see detailed breakdowns.
Major Changes
1. Removed Features
A. Room Type Comparison Feature (Completely Removed)

Removed: ComparisonResult dataclass (lines 74-77)
Removed: compare_stays() method in MVCCalculator class (lines 367-460)
Removed: Room comparison UI section with charts (lines 928-938)
Removed: comp_rooms multiselect input widget
Removed: Comparison pivot table and charts display
Reasoning: The ALL room types table now serves as the comparison tool, making the separate comparison feature redundant

B. Removed Imports

Removed: from collections import defaultdict (no longer needed after removing compare_stays)

2. Simplified User Inputs
Before:

Check-in date
Number of nights
Room type selection (selectbox)
Compare with (multiselect for additional room types)

After:

Check-in date only
Number of nights only

Changed code (lines 694-730):

Removed c3 and c4 columns from the input layout
Changed from 4-column layout to 2-column layout
Removed room type selectbox widget
Removed "Compare With" multiselect widget
Added automatic room selection reset when check-in date or nights change

3. New User Flow
Step 1: Resort Selection & Basic Inputs
User selects resort, enters check-in date and number of nights (unchanged).
Step 2: Settings Expander
Configuration options (rates, discounts, costs) moved to collapsible expander at the top (unchanged functionality, just repositioned).
Step 3: ALL Room Types Table (NEW FIRST RESULTS)
New section (lines 743-789):

Displays a list of ALL available room types for the selected resort
Shows for each room type:

Room Type name
Total Points required
Total Cost/Rent
"Select" button


Calculations performed for all room types upfront
User clicks "Select" button to choose a room type
Selection is stored in st.session_state.selected_room_type

Step 4: Detailed Breakdown (Shown After Selection)
Modified section (lines 791-850):

Only displays when a room type has been selected
Shows detailed breakdown for the selected room type:

Settings caption with rate, purchase info, discount status
Metrics (Points, Cost, Maintenance, Capital, Depreciation)
Daily Breakdown (in expander)
Season and Holiday Calendar (in expander)



4. State Management Improvements
Session State Variables:

selected_room_type: Stores the currently selected room type
calc_nights: Stores the number of nights (persists across resort changes)

Live Update Behavior:
When user changes check-in date or number of nights:

The ALL room types table immediately recalculates and updates to show new costs/points
If a room type was previously selected, the detailed breakdown also immediately updates with the new dates
No reset - the selected room type remains selected, just with updated calculations
This allows users to see how costs change across dates without losing their room selection

Persistent Nights Value:
The nights input value is now stored in st.session_state.calc_nights:

Initialized to 7 on first load
Persists when user changes resorts - prevents reverting to default 7 nights
Updates whenever user changes the value
Ensures the ALL room types table always reflects the actual nights value selected by the user

5. Preserved Features
The following features remain completely unchanged:
✅ All calculation logic in calculate_breakdown() method
✅ Holiday adjustment logic
✅ Discount policy calculations
✅ Owner vs Renter mode differences
✅ Maintenance, Capital Cost, Depreciation calculations
✅ Settings save/load functionality
✅ Season and Holiday Calendar with Gantt chart
✅ 7-Night cost table for all seasons/holidays
✅ All data structures and repository methods
✅ Helper functions (get_all_room_types_for_resort, build_season_cost_table, etc.)
Code Structure Changes
Before:
1. Resort Selection
2. Inputs: Check-in, Nights, Room Type, Compare With
3. Settings Expander
4. Calculate for selected room → Show metrics
5. Daily Breakdown (expander)
6. All Room Types table (expander)
7. Comparison section (if comp_rooms selected)
8. Season/Holiday Calendar (expander)
After:
1. Resort Selection
2. Inputs: Check-in, Nights only
3. Settings Expander
4. ALL Room Types Table (with Select buttons) ← NEW FIRST RESULTS
5. IF room selected:
   - Detailed Breakdown for selected room
   - Metrics
   - Daily Breakdown (expander)
   - Season/Holiday Calendar (expander)
UI Improvements
Better User Experience:

Simpler initial inputs - Users don't need to know room types before seeing options
Visual comparison - ALL room types table shows all options at once
Informed selection - Users can see points and costs before selecting
Clear flow - Linear progression from broad overview to specific details
Automatic reset - Changing dates/nights returns user to room selection

Visual Layout:

Room types displayed in clean rows with columns for:

Room Type name (bold)
Points (formatted with commas)
Cost (formatted as currency)
Select button (full width in column)



Lines Changed Summary
SectionLinesChange TypeImports8Removed defaultdictDataclasses74-77Removed ComparisonResultMVCCalculator.compare_stays367-460Removed entire methodSession state defaults549-557Added calc_nights initializationNights input widget616-628Changed to use persistent session state valueMain inputs section594-628Simplified from 4-col to 2-col, added persistent nightsResults section743-850Complete reorganization: new ALL table + conditional detailed viewRemoved comparisonN/ARemoved comparison UI and charts
Testing Recommendations

Test room selection flow:

Select resort → Enter dates → See ALL rooms table → Select room → See details


Test live update behavior:

Select a room → Change check-in date → Verify ALL rooms table updates immediately
Verify detailed breakdown updates immediately with new calculations
Select a room → Change nights → Verify both ALL table and breakdown update instantly
Verify selected room type stays selected through date/night changes


Test both modes:

Verify Owner mode shows Maintenance, Capital, Depreciation
Verify Renter mode shows Rental costs


Test all room types:

Verify all room types calculate correctly in the ALL table
Verify each room type shows correct detailed breakdown when selected


Test settings:

Verify changing rates/discounts updates ALL rooms table
Verify changing rates/discounts updates detailed breakdown
Verify save/load settings still works



Migration Notes
If you have existing code that references:

ComparisonResult: This no longer exists
compare_stays(): This method has been removed
comp_rooms variable: This is no longer used

The ALL room types table functionality is built-in to the main flow and doesn't require any external references.
