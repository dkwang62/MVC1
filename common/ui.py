from typing import Any, Dict, List, Optional
import streamlit as st
from common.utils import sort_resorts_west_to_east, get_region_label

def setup_page() -> None:
    """Standard page configuration and shared CSS for MVC apps."""
    st.set_page_config(
        page_title="MVC Tools",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"About": "Marriott Vacation Club – internal tools"},
    )
    
    # Enhanced CSS with better spacing, colors, and visual hierarchy
    st.markdown(
        """<style>
        :root {
            --primary-color: #008080;
            --primary-hover: #006666;
            --secondary-color: #4B9FA5;
            --border-color: #E5E7EB;
            --card-bg: #FFFFFF;
            --bg-color: #F9FAFB;
            --text-color: #111827;
            --text-muted: #6B7280;
            --success-bg: #ECFDF5;
            --success-border: #10B981;
            --info-bg: #EFF6FF;
            --info-border: #3B82F6;
            --warning-bg: #FEF3C7;
            --warning-border: #F59E0B;
        }

        /* Hide default Streamlit UI elements */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* -------------------------------------------------------- */
        /* SIDEBAR STYLING - Clean and organized                    */
        /* -------------------------------------------------------- */
        
        section[data-testid="stSidebar"] {
            background-color: var(--card-bg);
            border-right: 1px solid var(--border-color);
        }

        section[data-testid="stSidebar"] .block-container {
            gap: 0rem !important;
            padding-top: 2rem !important;
            padding-bottom: 2rem !important;
        }

        /* Cleaner section headers in sidebar */
        section[data-testid="stSidebar"] h3 {
            margin-top: 1.5rem !important;    
            margin-bottom: 0.75rem !important; 
            font-size: 0.875rem !important;
            font-weight: 600 !important;
            color: var(--text-muted) !important;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        /* Better expander styling */
        [data-testid="stExpander"] {
            margin-bottom: 0.75rem !important;
            border: 1px solid var(--border-color);
            border-radius: 0.5rem;
            background-color: #ffffff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            transition: all 0.2s ease;
        }
        
        [data-testid="stExpander"]:hover {
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            border-color: var(--secondary-color);
        }

        /* Divider spacing */
        section[data-testid="stSidebar"] hr {
            margin: 1.5rem 0 !important;
            border-color: var(--border-color);
            opacity: 0.5;
        }

        /* Input and button spacing */
        section[data-testid="stSidebar"] .stTextInput,
        section[data-testid="stSidebar"] .stNumberInput,
        section[data-testid="stSidebar"] .stSelectbox {
            margin-bottom: 0.75rem !important;
        }

        /* -------------------------------------------------------- */
        /* MAIN CONTENT STYLING - More breathing room               */
        /* -------------------------------------------------------- */
        .main, [data-testid="stAppViewContainer"] {
            background-color: var(--bg-color);
            font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI",
                         Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
            color: var(--text-color);
        }

        /* Enhanced section headers */
        .section-header {
            font-size: 1.25rem;
            font-weight: 600;
            padding: 1rem 0 0.75rem 0;
            border-bottom: 2px solid var(--primary-color);
            margin-bottom: 1.5rem;
            color: var(--primary-color);
        }

        /* Improved resort card with better visual hierarchy */
        .resort-card {
            background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
            border-radius: 1rem;
            padding: 1.5rem 2rem;
            border: 1px solid var(--border-color);
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
            margin-bottom: 1.5rem;
            transition: all 0.3s ease;
        }
        
        .resort-card:hover {
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
            transform: translateY(-2px);
        }

        .resort-card h2 {
            margin: 0 0 0.75rem 0;
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--primary-color);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .resort-meta {
            margin-top: 0.5rem;
            font-size: 0.95rem;
            color: var(--text-muted);
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
        }
        
        .resort-meta span {
            display: flex;
            align-items: center;
            gap: 0.375rem;
        }
        
        /* Enhanced message boxes with icons */
        .success-box, .info-box, .error-box, .warning-box {
            padding: 1.25rem 1.5rem;
            border-radius: 0.75rem;
            margin: 1.5rem 0;
            border-left: 4px solid;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        
        .success-box { 
            background-color: var(--success-bg); 
            border-color: var(--success-border); 
            color: #065F46;
        }
        
        .info-box { 
            background-color: var(--info-bg); 
            border-color: var(--info-border); 
            color: #1E40AF;
        }
        
        .error-box { 
            background-color: #FEF2F2; 
            border-color: #EF4444; 
            color: #991B1B;
        }
        
        .warning-box {
            background-color: var(--warning-bg);
            border-color: var(--warning-border);
            color: #92400E;
        }

        /* Better metric cards */
        [data-testid="stMetric"] {
            background-color: white;
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid var(--border-color);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        /* Enhanced buttons */
        .stButton > button {
            transition: all 0.2s ease;
            border-radius: 0.5rem;
            font-weight: 500;
        }
        
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }

        /* Better data editor styling */
        [data-testid="stDataFrame"] {
            border-radius: 0.5rem;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }

        /* Improved tab styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.5rem;
            background-color: transparent;
        }

        .stTabs [data-baseweb="tab"] {
            padding: 0.75rem 1.5rem;
            border-radius: 0.5rem 0.5rem 0 0;
            background-color: white;
            border: 1px solid var(--border-color);
            border-bottom: none;
        }

        .stTabs [aria-selected="true"] {
            background-color: var(--primary-color);
            color: white;
            font-weight: 600;
        }

        /* Help text styling */
        .help-text {
            font-size: 0.875rem;
            color: var(--text-muted);
            font-style: italic;
            margin-top: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.375rem;
        }

        /* Caption improvements */
        .caption-text {
            font-size: 0.875rem;
            color: var(--text-muted);
            margin-bottom: 1rem;
            padding: 0.75rem;
            background-color: #F3F4F6;
            border-radius: 0.375rem;
            border-left: 3px solid var(--secondary-color);
        }
    </style>
    """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------
# Enhanced component functions
# ----------------------------------------------------------------------

def render_page_header(
    title: str, 
    subtitle: str | None = None, 
    icon: str | None = None, 
    badge_color: str | None = None,
    description: str | None = None
):
    """Enhanced page header with optional description."""
    # Build icon HTML
    icon_html = f'<span style="font-size: 2.5rem; margin-right: 0.5rem;">{icon}</span>' if icon else ''
    
    # Build subtitle/badge HTML
    subtitle_html = ''
    if subtitle and badge_color:
        subtitle_html = f'<span style="display: inline-block; background-color: {badge_color}; color: white; padding: 0.5rem 1rem; border-radius: 2rem; font-weight: 600; font-size: 1rem; margin-left: 1rem; vertical-align: middle;">{subtitle}</span>'
    elif subtitle:
        subtitle_html = f'<span style="color: #64748b; margin-left: 1rem; font-size: 1.125rem; vertical-align: middle;">{subtitle}</span>'
    
    # Build description HTML
    description_html = ''
    if description:
        description_html = f'<p style="color: #6B7280; font-size: 1rem; margin: 1rem 0 0 0; max-width: 800px; line-height: 1.6;">{description}</p>'
    
    # Render the complete header - all on one line to prevent string escaping issues
    html = f'<div style="margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid #E5E7EB;"><div style="display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem;">{icon_html}<h1 style="color: #0f172a; margin: 0; font-size: 2.5rem; display: inline;">{title}</h1>{subtitle_html}</div>{description_html}</div>'
    
    st.markdown(html, unsafe_allow_html=True)
    
def render_resort_card(resort_name: str, timezone: str, address: str) -> None:
    """Enhanced resort card with better visual hierarchy."""
    st.markdown(
        f"""
        <div class="resort-card">
          <h2>🏖️ {resort_name}</h2>
          <div class="resort-meta">
            <span>🕐 <strong>Timezone:</strong> {timezone}</span>
            <span>📍 <strong>Location:</strong> {address}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_resort_grid(
    resorts: List[Dict[str, Any]],
    current_resort_key: Optional[str],
    *,
    title: str = "🏨 Select a Resort",
) -> None:
    """Enhanced resort grid with better visual grouping by region."""

    # --- state: should we show the picker UI? ---
    if "show_resort_picker" not in st.session_state:
        # show it on first load; after a selection, we will set it False
        st.session_state.show_resort_picker = True

    slot = st.empty()

    # If hidden, show a small control to reopen it and exit early
    if not st.session_state.show_resort_picker:
        with slot.container():
            if st.button("Change resort", key="btn_change_resort"):
                st.session_state.show_resort_picker = True
                st.rerun()
        return

    # Otherwise render the expander (opened by default for selection)
    with slot.expander(title, expanded=True):
        if not resorts:
            st.info("No resorts available.")
            return

        sorted_resorts = sort_resorts_west_to_east(resorts)

        region_groups = {}
        for resort in sorted_resorts:
            tz = resort.get("timezone", "UTC")
            region_label = get_region_label(tz)

            if region_label in ["Mexico (Pacific)", "Mexico (Caribbean)", "Costa_Rica"]:
                region_label = "Central America"

            if region_label in ["SE Asia", "Indonesia", "Japan", "Australia (QLD)", "Australia"]:
                region_label = "Asia Pacific"

            region_groups.setdefault(region_label, []).append(resort)

        for region, region_resorts in region_groups.items():
            st.markdown(f"**{region}**")

            num_cols = min(6, len(region_resorts))
            cols = st.columns(num_cols)

            for idx, resort in enumerate(region_resorts):
                col = cols[idx % num_cols]
                with col:
                    rid = resort.get("id")
                    name = resort.get("display_name", rid or f"Resort {idx+1}")
                    is_current = current_resort_key in (rid, name)
                    btn_type = "primary" if is_current else "secondary"

                    if st.button(
                        name,
                        key=f"resort_btn_{rid or name}",
                        type=btn_type,
                        width="stretch",
                    ):
                        st.session_state.current_resort_id = rid
                        st.session_state.current_resort = name

                        if "delete_confirm" in st.session_state:
                            st.session_state.delete_confirm = False

                        # Hide picker (effectively “collapses” it by removing it)
                        st.session_state.show_resort_picker = False
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)


def render_info_callout(message: str, type: str = "info", icon: str = "ℹ️"):
    """Render a friendly callout box."""
    type_class = f"{type}-box"
    st.markdown(
        f"""
        <div class="{type_class}">
            <div style="display: flex; align-items: start; gap: 0.75rem;">
                <span style="font-size: 1.5rem;">{icon}</span>
                <div style="flex: 1;">
                    {message}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_help_text(text: str):
    """Render inline help text."""
    st.markdown(
        f'<div class="help-text">💡 {text}</div>',
        unsafe_allow_html=True,
    )

def render_section_caption(text: str):
    """Render a styled caption for sections."""
    st.markdown(
        f'<div class="caption-text">{text}</div>',
        unsafe_allow_html=True,
    )
