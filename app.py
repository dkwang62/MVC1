# app.py
import os
import sys

import streamlit as st

# Ensure local package imports work on Streamlit Cloud
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from common.ui import setup_page

# Set up base page config and styling
setup_page()

# --- Initialize Default Theme ---
if "ui_theme" not in st.session_state:
    st.session_state.ui_theme = "Light"

# --- App shell: choose which tool to run ---
st.sidebar.markdown("### 🧰 MVC Tools")
choice = st.sidebar.radio(
    "Choose Tool",
    ["Calc", "Edit"],
    index=0,
)

if choice == "Calc":
    import calculator

    calculator.run()
else:
    import editor

    editor.run()
