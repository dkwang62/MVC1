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
    # Shared CSS
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
        .main, [data-testid="stAppViewContainer"] {
            background-color: var(--bg-color);
            font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI",
                         Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
        }
        .section-header {
            font-size: 1.1rem;
            font-weight: 600;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 0.75rem;
        }
        .resort-card {
            background: var(--card-bg);
            border-radius: 0.75rem;
            padding: 1rem 1.25rem;
            border: 1px solid var(--border-color);
            box-shadow: 0 2px 4px rgba(15, 23, 42, 0.06);
            margin-bottom: 1rem;
        }
        .resort-card h2 {
            margin: 0;
            font-size: 1.4rem;
            font-weight: 700;
            color: var(--primary-color);
        }
        .resort-meta {
            margin-top: 0.35rem;
            font-size: 0.9rem;
            color: #4B5563;
        }
        section[data-testid="stSidebar"] {
            background-color: var(--card-bg);
            border-right: 1px solid var(--border-color);
        }
    </style>
    """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------
# Resort display components (shared by editor + calculator)
# ----------------------------------------------------------------------
def render_page_header(title: str, subtitle: str | None = None, icon: str | None = None, badge_color: str | None = None):
    icon_html = f"{icon} " if icon else ""
    if subtitle:
        if badge_color:
            subtitle_html = f'<div style="display: inline-block; background-color: {badge_color}; color: white; padding: 8px 16px; border-radius: 20px; font-weight: 600; font-size: 18px;">{subtitle}</div>'
        else:
            subtitle_html = f"<p style='color: #64748b; margin: 4px 0 0 0; font-size: 18px;'>{subtitle}</p>"
    else:
        subtitle_html = ""
    st.markdown(
        f"""
        <div style='display: flex; align-items: center; margin-bottom: 8px; margin-top: 0;'>
            <h1 style='color: #0f172a; margin: 0; font-size: 50px; margin-right: 12px;'>{icon_html}{title}</h1>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    
def render_resort_card(resort_name: str, timezone: str, address: str) -> None:
    """Standard resort info card."""
    st.markdown(
        f"""
        <div class="resort-card">
          <h2>🖖 {resort_name}</h2>
          <div class="resort-meta">🕒 Timezone: {timezone}</div>
          <div class="resort-meta">📍 {address}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_resort_grid(
    resorts: List[Dict[str, Any]],
    current_resort_key: Optional[str],
    *,
    title: str = "🏨 Resorts in Memory (West to East) 🖖 Select Resort",
) -> None:
    """
    Shared resort grid, sorted West → East, laid out COLUMN-first.
    `current_resort_key` may be:
      • resort["id"] (editor)
      • resort["display_name"] (calculator)
    On click, this sets BOTH:
      • st.session_state.current_resort_id
      • st.session_state.current_resort
    """
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    if not resorts:
        st.info("No resorts available.")
        return
    sorted_resorts = sort_resorts_west_to_east(resorts)
    num_cols = 6
    cols = st.columns(num_cols)
    num_resorts = len(sorted_resorts)
    num_rows = (num_resorts + num_cols - 1) // num_cols # ceil division (column-first)
    for col_idx, col in enumerate(cols):
        with col:
            for row in range(num_rows):
                idx = col_idx * num_rows + row
                if idx >= num_resorts:
                    continue
                resort = sorted_resorts[idx]
                rid = resort.get("id")
                name = resort.get("display_name", rid or f"Resort {idx+1}")
                tz = resort.get("timezone", "UTC")
                region = get_region_label(tz) # currently not displayed, but available
                is_current = current_resort_key in (rid, name)
                btn_type = "primary" if is_current else "secondary"
                if st.button(
                    f"🏨 {name}",
                    key=f"resort_btn_{rid or name}",
                    type=btn_type,
                    use_container_width=True,
# help=resort.get("address", f"{region} • {tz}"),
                ):
                    # Normalised selection for both apps
                    st.session_state.current_resort_id = rid
                    st.session_state.current_resort = name
                    if "delete_confirm" in st.session_state:
                        st.session_state.delete_confirm = False
                    st.rerun()
