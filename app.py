import streamlit as st
import os
import sys
import json
from datetime import datetime, timedelta

# Ensure local package imports work on Streamlit Cloud
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from common.ui import setup_page
import calculator
import editor

# Set page config first
setup_page()

# ==============================================================================
# GLOBAL STATE INITIALIZATION
# ==============================================================================
def initialize_session_state():
    """
    Initialize all session state variables and load settings file ONCE.
    This guarantees variables exist before any module tries to read them.
    """
    
    # 1. Define Defaults
    defaults = {
        # Preferences
        "pref_maint_rate": 0.83,
        "pref_purchase_price": 3.5,
        "pref_capital_cost_pct": 5.0,
        "pref_salvage_value": 3.0,
        "pref_useful_life": 20,
        "pref_discount_tier": "Ordinary",
        "pref_inc_m": True,
        "pref_inc_c": True,
        "pref_inc_d": False,
        
        # Renter
        "renter_rate_val": 0.83,
        "renter_discount_tier": "Ordinary",
        
        # App State
        "preferred_resort_id": None,
        "app_phase": "renter",
        
        # Calculator State
        "calc_checkin": datetime.now().date() + timedelta(days=1),
        "calc_initial_default": datetime.now().date() + timedelta(days=1),
        "calc_checkin_user_set": False
    }

    # 2. Apply Defaults (only if key is missing)
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # 3. Auto-load Local Settings (Only on first run)
    if "profile_auto_loaded" not in st.session_state:
        local_path = "mvc_owner_settings.json"
        if os.path.exists(local_path):
            try:
                with open(local_path, "r") as f:
                    data = json.load(f)
                    
                    # Safely map JSON keys to session keys
                    if "maintenance_rate" in data: st.session_state.pref_maint_rate = float(data["maintenance_rate"])
                    if "purchase_price" in data: st.session_state.pref_purchase_price = float(data["purchase_price"])
                    if "capital_cost_pct" in data: st.session_state.pref_capital_cost_pct = float(data["capital_cost_pct"])
                    if "salvage_value" in data: st.session_state.pref_salvage_value = float(data["salvage_value"])
                    if "useful_life" in data: st.session_state.pref_useful_life = int(data["useful_life"])
                    
                    if "discount_tier" in data:
                        t = str(data["discount_tier"])
                        if "Exec" in t: st.session_state.pref_discount_tier = "Executive"
                        elif "Pres" in t or "Chair" in t: st.session_state.pref_discount_tier = "Presidential"
                        else: st.session_state.pref_discount_tier = "Ordinary"
                    
                    if "include_maintenance" in data: st.session_state.pref_inc_m = bool(data["include_maintenance"])
                    if "include_capital" in data: st.session_state.pref_inc_c = bool(data["include_capital"])
                    if "include_depreciation" in data: st.session_state.pref_inc_d = bool(data["include_depreciation"])
                    
                    if "renter_rate" in data: st.session_state.renter_rate_val = float(data["renter_rate"])
                    
                    if "renter_discount_tier" in data:
                        t = str(data["renter_discount_tier"])
                        if "Exec" in t: st.session_state.renter_discount_tier = "Executive"
                        elif "Pres" in t or "Chair" in t: st.session_state.renter_discount_tier = "Presidential"
                        else: st.session_state.renter_discount_tier = "Ordinary"
                    
                    if "preferred_resort_id" in data:
                        val = str(data["preferred_resort_id"])
                        st.session_state.preferred_resort_id = val
                        # Only set current if not already set by user interaction
                        if "current_resort_id" not in st.session_state:
                            st.session_state.current_resort_id = val

                st.toast("Auto-loaded settings from file", icon="⚙️")
            except Exception as e:
                pass # Silent fail on auto-load
        
        # Mark as loaded so we don't overwrite user changes on refresh
        st.session_state.profile_auto_loaded = True

def main():
    # --- 1. RUN INITIALIZATION ---
    initialize_session_state()

    # --- 2. SIDEBAR NAVIGATION ---
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
        calculator.run(forced_mode="Renter")
        
    elif st.session_state.app_phase == "owner":
        calculator.run(forced_mode="Owner")
        
    elif st.session_state.app_phase == "editor":
        editor.run()

if __name__ == "__main__":
    main()
