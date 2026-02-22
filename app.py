import streamlit as st
import calculator
import editor

# Set page config first
calculator.setup_page()

def main():
    # --- 1. SESSION STATE FOR NAVIGATION ---
    # We use 'app_phase' to track: 'renter', 'owner', 'editor'
    if "app_phase" not in st.session_state:
        st.session_state.app_phase = "renter"

    # --- 2. SIDEBAR NAVIGATION CONTROLS ---
    with st.sidebar:
        st.header("Navigation")
        
        # LOGIC: RENTER MODE
        if st.session_state.app_phase == "renter":
            st.info("Currently: **Renter Mode**")
            st.markdown("---")
            if st.button("Go to Owner Mode ➡️", use_container_width=True):
                st.session_state.app_phase = "owner"
                st.rerun()

        # LOGIC: OWNER MODE
        elif st.session_state.app_phase == "owner":
            if st.button("⬅️ Back to Renter", use_container_width=True):
                st.session_state.app_phase = "renter"
                st.rerun()
            
            st.markdown("---")
            st.info("Currently: **Owner Mode**")
            st.markdown("---")
            
            if st.button("Go to Editor 🛠️", use_container_width=True):
                st.session_state.app_phase = "editor"
                st.rerun()

        # LOGIC: EDITOR MODE
        elif st.session_state.app_phase == "editor":
            if st.button("⬅️ Back to Calculator", use_container_width=True):
                st.session_state.app_phase = "owner"
                st.rerun()
            st.markdown("---")
            st.info("Currently: **Data Editor**")

    # --- 3. MAIN PAGE ROUTING ---
    if st.session_state.app_phase == "renter":
        # Run calculator in Renter Mode
        calculator.run(forced_mode="Renter")
        
    elif st.session_state.app_phase == "owner":
        # Run calculator in Owner Mode
        calculator.run(forced_mode="Owner")
        
    elif st.session_state.app_phase == "editor":
        editor.run()

if __name__ == "__main__":
    main()
