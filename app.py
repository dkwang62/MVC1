import streamlit as st
from aggrid_editor import (
    render_global_holidays_grid,
    render_season_dates_grid,
    render_season_points_grid,
    render_holiday_points_grid,
)

# Optional: if you have other modules like calculator
# from calculator import calculator

def main():
    st.set_page_config(page_title="MVC Editor", layout="wide")
    st.title("🏖️ MVC Resort Data Editor")

    # Initialize session state if not already done
    if "app_phase" not in st.session_state:
        st.session_state.app_phase = "editor"  # or "calculator", etc.
    if "data" not in st.session_state:
        st.session_state.data = {}
    if "current_resort" not in st.session_state:
        st.session_state.current_resort = None

    # Sidebar for navigation / phase selection (optional)
    with st.sidebar:
        st.header("Navigation")
        phase = st.radio(
            "Select Mode",
            options=["editor", "calculator", "other"],
            index=0 if st.session_state.app_phase == "editor" else 1
        )
        st.session_state.app_phase = phase

        st.divider()
        st.caption("MVC Data Editor • Global & Resort Configuration")

    # ======================================================================
    # EDITOR PHASE
    # ======================================================================
    if st.session_state.app_phase == "editor":
        st.header("📊 Data Editor Mode")

        # Ensure data is loaded
        if not st.session_state.data:
            st.warning("No data loaded yet.")
            uploaded_file = st.file_uploader("Upload your JSON data file", type=["json"])
            if uploaded_file:
                import json
                try:
                    st.session_state.data = json.load(uploaded_file)
                    st.success("Data loaded successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to load JSON: {e}")
            return

        data = st.session_state.data

        # Extract years for global holidays
        years = sorted(data.get("years", {}).keys())
        if not years:
            st.error("No years defined in data['years']. Please check your JSON structure.")
            return

        # Resort selection
        resorts = data.get("resorts", {})
        if not resorts:
            st.error("No resorts found in data['resorts'].")
            return

        resort_names = list(resorts.keys())
        selected_resort = st.selectbox(
            "Select Resort to Edit",
            options=resort_names,
            index=0 if st.session_state.current_resort not in resort_names else resort_names.index(st.session_state.current_resort)
        )
        st.session_state.current_resort = selected_resort

        working = resorts[selected_resort]
        base_year = years[0]  # You can make this configurable if needed

        st.subheader(f"Editing: **{selected_resort}** | Base Year: **{base_year}**")

        # ====================== Render All Editor Grids ======================
        render_global_holidays_grid(data, years)

        st.divider()

        render_season_dates_grid(working, selected_resort)

        st.divider()

        render_season_points_grid(working, base_year, selected_resort)

        st.divider()

        render_holiday_points_grid(working, base_year, selected_resort)

        # Optional: Save / Export button at the bottom
        st.divider()
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("💾 Download Updated JSON", type="primary", width="stretch"):
                import json
                json_str = json.dumps(data, indent=2)
                st.download_button(
                    label="Download JSON File",
                    data=json_str,
                    file_name=f"mvc_data_updated_{selected_resort}.json",
                    mime="application/json"
                )

    # ======================================================================
    # CALCULATOR PHASE (placeholder - replace with your actual code)
    # ======================================================================
    elif st.session_state.app_phase == "calculator":
        st.header("🧮 Points Calculator Mode")
        st.info("Calculator mode not implemented in this snippet.")
        # calculator.run(forced_mode="Owner")  # Uncomment and adjust if you have it

    else:
        st.header("Other Mode")
        st.write("This section can be customized.")

if __name__ == "__main__":
    main()
