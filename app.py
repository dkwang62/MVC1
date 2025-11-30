import streamlit as st
import json
import os

# Set page config first - before any other Streamlit command
st.set_page_config(
    page_title="MVC Tools",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Marriott Vacation Club – internal tools"},
)

from common.ui import setup_page
import editor
import calculator

def main():
    # Setup shared CSS (but not page config again)
    # setup_page() call removed here because set_page_config MUST be the first st command.
    # Instead, we manually inject the CSS that was in setup_page here or keep it in common/ui 
    # but call a css-only function. 
    # For safety with your current setup, I'll inject the CSS manually here or assume common.ui handles it via a different func.
    # Let's use the CSS injection from common.ui without set_page_config.
    
    # Inject CSS manually to ensure styling (since we moved set_page_config up)
    st.markdown(
        """
    <style>
        :root {
            --primary-color: #008080;
            --border-color: #E5E7EB;
            --card-bg: #FFFFFF;
            --bg-color: #F9FAFB;
            --text-color: #111827;
        }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        /* Allow header so sidebar toggle works */
        
        section[data-testid="stSidebar"] {
            background-color: var(--card-bg);
            border-right: 1px solid var(--border-color);
        }
        section[data-testid="stSidebar"] .block-container {
            gap: 0rem !important;
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }
        [data-testid="stExpander"] {
            margin-bottom: 0.5rem !important;
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            background-color: #ffffff;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        section[data-testid="stSidebar"] h3 {
            margin-top: 1.5rem !important;    
            margin-bottom: 0.5rem !important; 
            font-size: 1.0rem !important;
            font-weight: 600 !important;
            color: var(--primary-color) !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        section[data-testid="stSidebar"] hr {
            margin: 1.5rem 0 1rem 0 !important;
        }
        /* HIDE RADIO LABEL */
        div[role="radiogroup"] > label {
            display: none !important;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # --- SIDEBAR NAVIGATION ---
    with st.sidebar:
        st.markdown("### 🛠️ TOOLS")
        # Use label_visibility="collapsed" to hide the text "Choose tool"
        choice = st.radio(
            "Choose tool",
            ["Points & Rent Calculator", "Data Editor"],
            index=0,
            label_visibility="collapsed",  # <--- Hides the label
            horizontal=True # <--- Keeps buttons on one row
        )

    if choice == "Points & Rent Calculator":
        calculator.run()
    else:
        editor.run()

if __name__ == "__main__":
    main()
