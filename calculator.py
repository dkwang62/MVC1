import math
import json
import os
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from PIL import Image
import pytz

# ==============================================================================
# CONSOLIDATED SHARED HELPERS (formerly common/*)
# ==============================================================================

DEFAULT_DATA_PATH = "data_v2.json"


def load_data() -> Dict[str, Any]:
    if "data" not in st.session_state or st.session_state.data is None:
        try:
            with open(DEFAULT_DATA_PATH, "r") as f:
                st.session_state.data = json.load(f)
                st.session_state.uploaded_file_name = DEFAULT_DATA_PATH
        except FileNotFoundError:
            st.session_state.data = None
    return st.session_state.data


def ensure_data_in_session(auto_path: str = DEFAULT_DATA_PATH) -> None:
    if "data" not in st.session_state:
        st.session_state.data = None
    if "uploaded_file_name" not in st.session_state:
        st.session_state.uploaded_file_name = None

    if st.session_state.data is None:
        try:
            with open(auto_path, "r") as f:
                data = json.load(f)
            if "schema_version" in data and "resorts" in data:
                st.session_state.data = data
                st.session_state.uploaded_file_name = auto_path
                st.toast(
                    f"✅ Auto-loaded {len(data.get('resorts', []))} resorts from {auto_path}",
                    icon="✅",
                )
        except FileNotFoundError:
            pass
        except Exception as e:
            st.toast(f"⚠️ Auto-load error: {e}", icon="⚠️")


COMMON_TZ_ORDER = [
    "Pacific/Honolulu",
    "America/Anchorage",
    "America/Los_Angeles",
    "America/Mazatlan",
    "America/Denver",
    "America/Edmonton",
    "America/Chicago",
    "America/Winnipeg",
    "America/Cancun",
    "America/New_York",
    "America/Toronto",
    "America/Halifax",
    "America/Puerto_Rico",
    "America/St_Johns",
    "Europe/London",
    "Europe/Paris",
    "Europe/Madrid",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Makassar",
    "Asia/Tokyo",
    "Australia/Brisbane",
    "Australia/Sydney",
]

REGION_US_CARIBBEAN = 0
REGION_MEX_CENTRAL = 1
REGION_EUROPE = 2
REGION_ASIA_AU = 3
REGION_FALLBACK = 99

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
CA_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
CARIBBEAN_CODES = {"AW", "BS", "VI", "PR"}
MEX_CENTRAL_CODES = {"MX", "CR"}
EUROPE_CODES = {"ES", "FR", "GB", "UK", "PT", "IT", "DE", "NL", "IE"}
ASIA_AU_CODES = {"TH", "ID", "SG", "JP", "CN", "MY", "PH", "VN", "AU"}
_REF_DT = datetime(2025, 1, 15, 12, 0, 0)

TZ_TO_REGION = {
    "Pacific/Honolulu": "Hawaii",
    "America/Anchorage": "Alaska",
    "America/Los_Angeles": "US West Coast",
    "America/Mazatlan": "Mexico (Pacific)",
    "America/Denver": "US Mountain",
    "America/Edmonton": "Canada Mountain",
    "America/Chicago": "US Central",
    "America/Winnipeg": "Canada Central",
    "America/Cancun": "Mexico (Caribbean)",
    "America/New_York": "US East Coast",
    "America/Toronto": "Canada East",
    "America/Halifax": "Atlantic Canada",
    "America/Puerto_Rico": "Caribbean",
    "America/St_Johns": "Newfoundland",
    "Europe/London": "UK / Ireland",
    "Europe/Paris": "Western Europe",
    "Europe/Madrid": "Western Europe",
    "Asia/Bangkok": "SE Asia",
    "Asia/Singapore": "SE Asia",
    "Asia/Makassar": "Indonesia",
    "Asia/Tokyo": "Japan",
    "Australia/Brisbane": "Australia (QLD)",
    "Australia/Sydney": "Australia",
}


def get_timezone_offset_minutes(tz_name: str) -> int:
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        return 0
    try:
        aware = tz.localize(_REF_DT)
        offset = aware.utcoffset()
        if offset is None:
            return 0
        return int(offset.total_seconds() // 60)
    except Exception:
        return 0


def _region_from_code(code: str) -> int:
    if not code:
        return REGION_FALLBACK
    code = code.upper()
    if code in US_STATE_CODES:
        return REGION_US_CARIBBEAN
    if code in CA_PROVINCES or code == "CA":
        return REGION_US_CARIBBEAN
    if code in CARIBBEAN_CODES:
        return REGION_US_CARIBBEAN
    if code in MEX_CENTRAL_CODES:
        return REGION_MEX_CENTRAL
    if code in EUROPE_CODES:
        return REGION_EUROPE
    if code in ASIA_AU_CODES:
        return REGION_ASIA_AU
    return REGION_FALLBACK


def _region_from_timezone(tz: str) -> int:
    if not tz:
        return REGION_FALLBACK
    if tz.startswith("America/"):
        if tz in ("America/Cancun", "America/Mazatlan"):
            return REGION_MEX_CENTRAL
        return REGION_US_CARIBBEAN
    if tz.startswith("Europe/"):
        return REGION_EUROPE
    if tz.startswith("Asia/") or tz.startswith("Australia/"):
        return REGION_ASIA_AU
    return REGION_FALLBACK


def get_region_priority(resort: Dict[str, Any]) -> int:
    code = (resort.get("code") or "").upper()
    tz = resort.get("timezone") or ""
    region = _region_from_code(code)
    if region != REGION_FALLBACK:
        return region
    return _region_from_timezone(tz)


def get_region_label(tz: str) -> str:
    if not tz:
        return "Unknown"
    return TZ_TO_REGION.get(tz, tz.split("/")[-1] if "/" in tz else tz)


def sort_resorts_by_timezone(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(r: Dict[str, Any]):
        region_prio = get_region_priority(r)
        tz = r.get("timezone") or "UTC"
        tz_index = COMMON_TZ_ORDER.index(tz) if tz in COMMON_TZ_ORDER else len(COMMON_TZ_ORDER)
        offset_minutes = get_timezone_offset_minutes(tz)
        name = r.get("display_name") or r.get("resort_name") or ""
        return (region_prio, tz_index, offset_minutes, name)

    return sorted(resorts, key=sort_key)


def sort_resorts_west_to_east(resorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sort_resorts_by_timezone(resorts)


def setup_page() -> None:
    st.set_page_config(
        page_title="MVC Tools",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"About": "Marriott Vacation Club - internal tools"},
    )
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
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        section[data-testid="stSidebar"] {
            background-color: var(--card-bg);
            border-right: 1px solid var(--border-color);
        }
        section[data-testid="stSidebar"] .block-container {
            gap: 0rem !important;
            padding-top: 2rem !important;
            padding-bottom: 2rem !important;
        }
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
        section[data-testid="stSidebar"] hr {
            margin: 1.5rem 0 !important;
            border-color: var(--border-color);
            opacity: 0.5;
        }
        section[data-testid="stSidebar"] .stTextInput,
        section[data-testid="stSidebar"] .stNumberInput,
        section[data-testid="stSidebar"] .stSelectbox {
            margin-bottom: 0.75rem !important;
        }
        .main, [data-testid="stAppViewContainer"] {
            background-color: var(--bg-color);
            font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI",
                         Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
            color: var(--text-color);
        }
        .section-header {
            font-size: 1.25rem;
            font-weight: 600;
            padding: 1rem 0 0.75rem 0;
            border-bottom: 2px solid var(--primary-color);
            margin-bottom: 1.5rem;
            color: var(--primary-color);
        }
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
        [data-testid="stMetric"] {
            background-color: white;
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid var(--border-color);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .stButton > button {
            transition: all 0.2s ease;
            border-radius: 0.5rem;
            font-weight: 500;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        [data-testid="stDataFrame"] {
            border-radius: 0.5rem;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }
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
        .help-text {
            font-size: 0.875rem;
            color: var(--text-muted);
            font-style: italic;
            margin-top: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.375rem;
        }
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


def render_page_header(
    title: str,
    subtitle: str | None = None,
    icon: str | None = None,
    badge_color: str | None = None,
    description: str | None = None,
):
    icon_html = f'<span style="font-size: 2.5rem; margin-right: 0.5rem;">{icon}</span>' if icon else ""
    subtitle_html = ""
    if subtitle and badge_color:
        subtitle_html = f'<span style="display: inline-block; background-color: {badge_color}; color: white; padding: 0.5rem 1rem; border-radius: 2rem; font-weight: 600; font-size: 1rem; margin-left: 1rem; vertical-align: middle;">{subtitle}</span>'
    elif subtitle:
        subtitle_html = f'<span style="color: #64748b; margin-left: 1rem; font-size: 1.125rem; vertical-align: middle;">{subtitle}</span>'
    description_html = ""
    if description:
        description_html = f'<p style="color: #6B7280; font-size: 1rem; margin: 1rem 0 0 0; max-width: 800px; line-height: 1.6;">{description}</p>'
    html = f'<div style="margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid #E5E7EB;"><div style="display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem;">{icon_html}<h1 style="color: #0f172a; margin: 0; font-size: 2.5rem; display: inline;">{title}</h1>{subtitle_html}</div>{description_html}</div>'
    st.markdown(html, unsafe_allow_html=True)


def render_resort_card(resort_name: str, timezone: str, address: str) -> None:
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
    show_change_button: bool = False,
    picker_state_key: Optional[str] = None,
    collapse_on_select: bool = False,
) -> None:
    picker_open = False
    if picker_state_key:
        if picker_state_key not in st.session_state:
            st.session_state[picker_state_key] = current_resort_key is None
        picker_open = bool(st.session_state[picker_state_key])

    if show_change_button and current_resort_key and picker_state_key:
        btn_label = "Done Selecting" if picker_open else "Change Resort"
        if st.button(btn_label, key=f"{picker_state_key}_change_btn", use_container_width=False):
            st.session_state[picker_state_key] = not picker_open
            st.rerun()
        if not picker_open:
            return

    with st.expander(title, expanded=picker_open if picker_state_key else False):
        if not resorts:
            st.info("No resorts available.")
            return
        sorted_resorts = sort_resorts_west_to_east(resorts)
        region_groups: Dict[str, List[Dict[str, Any]]] = {}
        for resort in sorted_resorts:
            tz = resort.get("timezone", "UTC")
            region_label = get_region_label(tz)
            if region_label in ["Mexico (Pacific)", "Mexico (Caribbean)", "Costa_Rica"]:
                region_label = "Central America"
            if region_label in ["SE Asia", "Indonesia", "Japan", "Australia (QLD)", "Australia"]:
                region_label = "Asia Pacific"
            if region_label not in region_groups:
                region_groups[region_label] = []
            region_groups[region_label].append(resort)

        for region, region_resorts in region_groups.items():
            st.markdown(f"**{region}**")
            num_cols = min(6, len(region_resorts))
            cols = st.columns(num_cols)
            for idx, resort in enumerate(region_resorts):
                col = cols[idx % num_cols]
                with col:
                    rid = resort.get("id")
                    name = resort.get("display_name", rid or f"Resort {idx + 1}")
                    is_current = current_resort_key in (rid, name)
                    btn_type = "primary" if is_current else "secondary"
                    if st.button(
                        name,
                        key=f"resort_btn_{rid or name}",
                        type=btn_type,
                        use_container_width=True,
                    ):
                        st.session_state.current_resort_id = rid
                        st.session_state.current_resort = name
                        if collapse_on_select and picker_state_key:
                            st.session_state[picker_state_key] = False
                        if "delete_confirm" in st.session_state:
                            st.session_state.delete_confirm = False
                        st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)


COLOR_MAP: Dict[str, str] = {
    "Peak": "#D73027",
    "High": "#FC8D59",
    "Mid": "#FEE08B",
    "Low": "#1F78B4",
    "Holiday": "#9C27B0",
    "No Data": "#A6CEE3",
}
GANTT_COLORS: Dict[str, str] = {
    "Peak": "#D73027",
    "High": "#FC8D59",
    "Mid": "#FEE08B",
    "Low": "#91BFDB",
    "Holiday": "#9C27B0",
}


def _season_bucket(season_name: str) -> str:
    name = (season_name or "").strip().lower()
    if "peak" in name:
        return "Peak"
    if "high" in name:
        return "High"
    if "mid" in name or "shoulder" in name:
        return "Mid"
    if "low" in name:
        return "Low"
    return "No Data"


def create_gantt_chart_from_working(
    working: Dict[str, Any],
    year: str,
    data: Dict[str, Any],
    height: Optional[int] = None,
) -> go.Figure:
    rows: List[Dict[str, Any]] = []
    year_obj = working.get("years", {}).get(year, {})
    for season in year_obj.get("seasons", []):
        sname = season.get("name", "(Unnamed)")
        bucket = _season_bucket(sname)
        for i, p in enumerate(season.get("periods", []), 1):
            try:
                start_dt = datetime.strptime(p.get("start"), "%Y-%m-%d")
                end_dt = datetime.strptime(p.get("end"), "%Y-%m-%d")
                if start_dt <= end_dt:
                    rows.append(
                        {
                            "Task": f"{sname} #{i}",
                            "Start": start_dt,
                            "Finish": end_dt,
                            "Type": bucket,
                        }
                    )
            except Exception:
                continue

    gh_year = data.get("global_holidays", {}).get(year, {})
    for h in year_obj.get("holidays", []):
        global_ref = h.get("global_reference") or h.get("name")
        if gh := gh_year.get(global_ref):
            try:
                start_dt = datetime.strptime(gh.get("start_date"), "%Y-%m-%d")
                end_dt = datetime.strptime(gh.get("end_date"), "%Y-%m-%d")
                if start_dt <= end_dt:
                    rows.append(
                        {
                            "Task": h.get("name", "(Unnamed)"),
                            "Start": start_dt,
                            "Finish": end_dt,
                            "Type": "Holiday",
                        }
                    )
            except Exception:
                continue

    if not rows:
        today = datetime.now()
        rows.append({"Task": "No Data", "Start": today, "Finish": today + timedelta(days=1), "Type": "No Data"})

    df = pd.DataFrame(rows)
    df["Start"] = pd.to_datetime(df["Start"])
    df["Finish"] = pd.to_datetime(df["Finish"])
    fig_height = height if height is not None else max(400, len(df) * 35)
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Task",
        color="Type",
        title=f"{working.get('display_name', 'Resort')} - {year} Timeline",
        height=fig_height,
        color_discrete_map=COLOR_MAP,
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickformat="%d %b %Y")
    fig.update_traces(
        hovertemplate="<b>%{y}</b><br>"
        "Start: %{base|%d %b %Y}<br>"
        "End: %{x|%d %b %Y}<extra></extra>"
    )
    fig.update_layout(
        showlegend=True,
        xaxis_title="Date",
        yaxis_title="Period",
        font=dict(size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _season_bucket_matplotlib(name: str) -> str:
    n = (name or "").lower()
    if "peak" in n:
        return "Peak"
    if "high" in n:
        return "High"
    if "mid" in n or "shoulder" in n:
        return "Mid"
    if "low" in n:
        return "Low"
    return "Low"


def create_gantt_chart_image(
    resort_data: Any,
    year: str,
    global_holidays: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
) -> Optional[Image.Image]:
    rows = []
    if not hasattr(resort_data, "years") or year not in resort_data.years:
        return None
    yd = resort_data.years[year]
    for season in getattr(yd, "seasons", []):
        name = getattr(season, "name", "Season")
        bucket = _season_bucket_matplotlib(name)
        for p in getattr(season, "periods", []):
            start = getattr(p, "start", None)
            end = getattr(p, "end", None)
            if isinstance(start, date) and isinstance(end, date) and start <= end:
                rows.append((name, start, end, bucket))
    for h in getattr(yd, "holidays", []):
        name = getattr(h, "name", "Holiday")
        start = getattr(h, "start_date", None)
        end = getattr(h, "end_date", None)
        if isinstance(start, date) and isinstance(end, date) and start <= end:
            rows.append((name, start, end, "Holiday"))
    if not rows:
        return None

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(10, max(3, len(rows) * 0.5)))
    for i, (label, start, end, typ) in enumerate(rows):
        duration = (end - start).days + 1
        ax.barh(
            i,
            duration,
            left=mdates.date2num(start),
            height=0.6,
            color=GANTT_COLORS.get(typ, "#999"),
            edgecolor="black",
            linewidth=0.5,
        )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([label for label, _, _, _ in rows])
    ax.invert_yaxis()
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(True, axis="x", alpha=0.3)
    resort_title = getattr(resort_data, "resort_name", None) or getattr(resort_data, "name", "Resort")
    ax.set_title(f"{resort_title} - {year}", pad=12, size=12)
    legend_elements = [
        plt.Rectangle((0, 0), 1, 1, facecolor=GANTT_COLORS[k], label=k)
        for k in GANTT_COLORS
        if any(t == k for _, _, _, t in rows)
    ]
    ax.legend(handles=legend_elements, loc="upper right", bbox_to_anchor=(1, 1))
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)

# ==============================================================================
# LAYER 1: DOMAIN MODELS
# ==============================================================================
class UserMode(Enum):
    RENTER = "Renter"
    OWNER = "Owner"

class DiscountPolicy(Enum):
    NONE = "None"
    EXECUTIVE = "within_30_days"  # 25%
    PRESIDENTIAL = "within_60_days"  # 30%

@dataclass
class Holiday:
    name: str
    start_date: date
    end_date: date
    room_points: Dict[str, int]

@dataclass
class DayCategory:
    days: List[str]
    room_points: Dict[str, int]

@dataclass
class SeasonPeriod:
    start: date
    end: date

@dataclass
class Season:
    name: str
    periods: List[SeasonPeriod]
    day_categories: List[DayCategory]

@dataclass
class ResortData:
    id: str
    name: str
    resort_name: str  # Full resort name for display
    years: Dict[str, "YearData"]

@dataclass
class YearData:
    holidays: List[Holiday]
    seasons: List[Season]

@dataclass
class CalculationResult:
    breakdown_df: pd.DataFrame
    total_points: int
    financial_total: float
    discount_applied: bool
    discounted_days: List[str]
    m_cost: float = 0.0
    c_cost: float = 0.0
    d_cost: float = 0.0

# ==============================================================================
# LAYER 2: REPOSITORY
# ==============================================================================
class MVCRepository:
    def __init__(self, raw_data: dict):
        self._raw = raw_data
        self._resort_cache: Dict[str, ResortData] = {}
        self._global_holidays = self._parse_global_holidays()

    def get_resort_list_full(self) -> List[Dict[str, Any]]:
        return self._raw.get("resorts", [])

    def _parse_global_holidays(self) -> Dict[str, Dict[str, Tuple[date, date]]]:
        parsed: Dict[str, Dict[str, Tuple[date, date]]] = {}
        for year, hols in self._raw.get("global_holidays", {}).items():
            parsed[year] = {}
            for name, data in hols.items():
                try:
                    parsed[year][name] = (
                        datetime.strptime(data["start_date"], "%Y-%m-%d").date(),
                        datetime.strptime(data["end_date"], "%Y-%m-%d").date(),
                    )
                except Exception:
                    continue
        return parsed

    def get_resort(self, resort_name: str) -> Optional[ResortData]:
        if resort_name in self._resort_cache:
            return self._resort_cache[resort_name]
        raw_r = next(
            (r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name),
            None,
        )
        if not raw_r:
            return None
        years_data: Dict[str, YearData] = {}
        for year_str, y_content in raw_r.get("years", {}).items():
            holidays: List[Holiday] = []
            for h in y_content.get("holidays", []):
                ref = h.get("global_reference")
                if ref and ref in self._global_holidays.get(year_str, {}):
                    g_dates = self._global_holidays[year_str][ref]
                    holidays.append(
                        Holiday(
                            name=h.get("name", ref),
                            start_date=g_dates[0],
                            end_date=g_dates[1],
                            room_points=h.get("room_points", {}),
                        )
                    )
            seasons: List[Season] = []
            for s in y_content.get("seasons", []):
                periods: List[SeasonPeriod] = []
                for p in s.get("periods", []):
                    try:
                        periods.append(
                            SeasonPeriod(
                                start=datetime.strptime(p["start"], "%Y-%m-%d").date(),
                                end=datetime.strptime(p["end"], "%Y-%m-%d").date(),
                            )
                        )
                    except Exception:
                        continue

                day_cats: List[DayCategory] = []
                for cat in s.get("day_categories", {}).values():
                    day_cats.append(
                        DayCategory(
                            days=cat.get("day_pattern", []),
                            room_points=cat.get("room_points", {}),
                        )
                    )
                seasons.append(Season(name=s["name"], periods=periods, day_categories=day_cats))

            years_data[year_str] = YearData(holidays=holidays, seasons=seasons)
        resort_obj = ResortData(
            id=raw_r["id"], 
            name=raw_r["display_name"], 
            resort_name=raw_r.get("resort_name", raw_r["display_name"]),
            years=years_data
        )
        self._resort_cache[resort_name] = resort_obj
        return resort_obj

    def get_resort_info(self, resort_name: str) -> Dict[str, str]:
        raw_r = next(
            (r for r in self._raw.get("resorts", []) if r["display_name"] == resort_name),
            None,
        )
        if raw_r:
            return {
                "full_name": raw_r.get("resort_name", resort_name),
                "timezone": raw_r.get("timezone", "Unknown"),
                "address": raw_r.get("address", "Address not available"),
            }
        return {
            "full_name": resort_name,
            "timezone": "Unknown",
            "address": "Address not available",
        }

# ==============================================================================
# LAYER 3: SERVICE
# ==============================================================================
class MVCCalculator:
    def __init__(self, repo: MVCRepository):
        self.repo = repo

    def _get_daily_points(self, resort: ResortData, day: date) -> Tuple[Dict[str, int], Optional[Holiday]]:
        year_str = str(day.year)
        if year_str not in resort.years:
            return {}, None

        yd = resort.years[year_str]

        # Check Holidays
        for h in yd.holidays:
            if h.start_date <= day <= h.end_date:
                return h.room_points, h

        # Check Seasons
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[day.weekday()]

        for s in yd.seasons:
            for p in s.periods:
                if p.start <= day <= p.end:
                    for cat in s.day_categories:
                        if dow in cat.days:
                            return cat.room_points, None
        return {}, None

    def calculate_breakdown(
        self, resort_name: str, room: str, checkin: date, nights: int,
        user_mode: UserMode, rate: float, discount_policy: DiscountPolicy = DiscountPolicy.NONE,
        owner_config: Optional[dict] = None,
    ) -> CalculationResult:
        resort = self.repo.get_resort(resort_name)
        if not resort:
            return CalculationResult(pd.DataFrame(), 0, 0.0, False, [])

        rate = round(float(rate), 2)
        rows: List[Dict[str, Any]] = []
        tot_eff_pts = 0
        tot_financial = 0.0
        tot_m = tot_c = tot_d = 0.0
        disc_applied = False
        disc_days: List[str] = []
        is_owner = user_mode == UserMode.OWNER
        processed_holidays: set[str] = set()
        i = 0

        while i < nights:
            d = checkin + timedelta(days=i)
            pts_map, holiday = self._get_daily_points(resort, d)

            if holiday and holiday.name not in processed_holidays:
                processed_holidays.add(holiday.name)
                raw = pts_map.get(room, 0)
                eff = raw
                holiday_days = (holiday.end_date - holiday.start_date).days + 1
                is_disc = False

                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                    if disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                        is_disc = True
                else:
                    renter_mul = (
                        0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL
                        else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE
                        else 1.0
                    )
                    if renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)
                        is_disc = True
                if is_disc:
                    disc_applied = True
                    for j in range(holiday_days):
                        disc_days.append((holiday.start_date + timedelta(days=j)).strftime("%Y-%m-%d"))

                cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else:
                    cost = math.ceil(eff * rate)

                row = {
                    "Date": f"{holiday.name} ({holiday.start_date.strftime('%b %d')} - {holiday.end_date.strftime('%b %d')}) [{holiday_days} nights]",
                    "Points": eff
                }

                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost

                rows.append(row)
                tot_eff_pts += eff
                i += holiday_days

            elif not holiday:
                raw = pts_map.get(room, 0)
                eff = raw
                is_disc = False

                if is_owner:
                    disc_mul = owner_config.get("disc_mul", 1.0) if owner_config else 1.0
                    if disc_mul < 1.0:
                        eff = math.floor(raw * disc_mul)
                        is_disc = True
                else:
                    renter_mul = (
                        0.7 if discount_policy == DiscountPolicy.PRESIDENTIAL
                        else 0.75 if discount_policy == DiscountPolicy.EXECUTIVE
                        else 1.0
                    )
                    if renter_mul < 1.0:
                        eff = math.floor(raw * renter_mul)
                        is_disc = True
                if is_disc:
                    disc_applied = True
                    disc_days.append(d.strftime("%Y-%m-%d"))

                cost = 0.0
                m = c = dp = 0.0
                if is_owner and owner_config:
                    m = math.ceil(eff * rate)
                    if owner_config.get("inc_c", False):
                        c = math.ceil(eff * owner_config.get("cap_rate", 0.0))
                    if owner_config.get("inc_d", False):
                        dp = math.ceil(eff * owner_config.get("dep_rate", 0.0))
                    cost = m + c + dp
                else:
                    cost = math.ceil(eff * rate)

                row = {"Date": d.strftime("%Y-%m-%d (%a)"), "Points": eff}

                if is_owner:
                    row["Maintenance"] = m
                    if owner_config.get("inc_c", False):
                        row["Capital Cost"] = c
                    if owner_config.get("inc_d", False):
                        row["Depreciation"] = dp
                    row["Total Cost"] = cost
                else:
                    row[room] = cost
                rows.append(row)
                tot_eff_pts += eff
                i += 1
            else:
                i += 1

        df = pd.DataFrame(rows)

        if user_mode == UserMode.RENTER:
            tot_financial = math.ceil(tot_eff_pts * rate)

        elif user_mode == UserMode.OWNER and owner_config:
            raw_maint = tot_eff_pts * rate
            raw_cap = 0.0
            if owner_config.get("inc_c", False):
                raw_cap = tot_eff_pts * owner_config.get("cap_rate", 0.0)
            raw_dep = 0.0
            if owner_config.get("inc_d", False):
                raw_dep = tot_eff_pts * owner_config.get("dep_rate", 0.0)
            tot_financial = math.ceil(raw_maint + raw_cap + raw_dep)

            tot_m = math.ceil(raw_maint)
            tot_c = math.ceil(raw_cap)
            tot_d = math.ceil(raw_dep)

        if not df.empty:
            fmt_cols = [c for c in df.columns if c not in ["Date", "Points"]]
            for col in fmt_cols:
                df[col] = df[col].apply(lambda x: f"${x:,.0f}" if isinstance(x, (int, float)) else x)

        return CalculationResult(df, tot_eff_pts, tot_financial, disc_applied, list(set(disc_days)), tot_m, tot_c, tot_d)

    def adjust_holiday(self, resort_name, checkin, nights):
        resort = self.repo.get_resort(resort_name)
        if not resort or str(checkin.year) not in resort.years:
            return checkin, nights, False

        end = checkin + timedelta(days=nights - 1)
        yd = resort.years[str(checkin.year)]
        overlapping = [h for h in yd.holidays if h.start_date <= end and h.end_date >= checkin]

        if not overlapping:
            return checkin, nights, False
        s = min(h.start_date for h in overlapping)
        e = max(h.end_date for h in overlapping)
        adj_s = min(checkin, s)
        adj_e = max(end, e)
        return adj_s, (adj_e - adj_s).days + 1, True

# ==============================================================================
# HELPER: SEASON COST TABLE
# ==============================================================================
def get_all_room_types_for_resort(resort_data: ResortData) -> List[str]:
    rooms = set()
    for year_obj in resort_data.years.values():
        for season in year_obj.seasons:
            for cat in season.day_categories:
                rooms.update(cat.room_points.keys())
        for holiday in year_obj.holidays:
            rooms.update(holiday.room_points.keys())
    return sorted(rooms)

def build_season_cost_table(
    resort_data: ResortData,
    year: int,
    rate: float,
    discount_mul: float,
    mode: UserMode,
    owner_params: Optional[dict] = None
) -> Optional[pd.DataFrame]:
    yd = resort_data.years.get(str(year))
    if not yd:
        return None

    room_types = get_all_room_types_for_resort(resort_data)
    if not room_types:
        return None

    rows = []

    # Seasons
    for season in yd.seasons:
        name = season.name.strip() or "Unnamed Season"
        weekly = {}
        has_data = False

        for dow in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            for cat in season.day_categories:
                if dow in cat.days:
                    rp = cat.room_points
                    for room in room_types:
                        pts = rp.get(room, 0)
                        if pts:
                            has_data = True
                        weekly[room] = weekly.get(room, 0) + pts
                    break

        if has_data:
            row = {"Season": name}
            for room in room_types:
                raw_pts = weekly.get(room, 0)
                eff_pts = math.floor(raw_pts * discount_mul) if discount_mul < 1 else raw_pts
                if mode == UserMode.RENTER:
                    cost = math.ceil(eff_pts * rate)
                else:
                    m = math.ceil(eff_pts * rate) if owner_params.get("inc_m", False) else 0
                    c = math.ceil(eff_pts * owner_params.get("cap_rate", 0.0)) if owner_params.get("inc_c", False) else 0
                    d = math.ceil(eff_pts * owner_params.get("dep_rate", 0.0)) if owner_params.get("inc_d", False) else 0
                    cost = m + c + d
                row[room] = f"${cost:,}"
            rows.append(row)

    # Holidays
    for h in yd.holidays:
        name = h.name.strip() or "Holiday"
        rp = h.room_points
        row = {"Season": f"Holiday – {name}"}
        for room in room_types:
            raw = rp.get(room, 0)
            if not raw:
                row[room] = "—"
                continue
            eff = math.floor(raw * discount_mul) if discount_mul < 1 else raw
            if mode == UserMode.RENTER:
                cost = math.ceil(eff * rate)
            else:
                m = math.ceil(eff * rate) if owner_params.get("inc_m", False) else 0
                c = math.ceil(eff * owner_params.get("cap_rate", 0.0)) if owner_params.get("inc_c", False) else 0
                d = math.ceil(eff * owner_params.get("dep_rate", 0.0)) if owner_params.get("inc_d", False) else 0
                cost = m + c + d
            row[room] = f"${cost:,}"
        rows.append(row)

    return pd.DataFrame(rows, columns=["Season"] + room_types) if rows else None

# ==============================================================================
# MAIN PAGE LOGIC
# ==============================================================================
TIER_NO_DISCOUNT = "No Discount"
TIER_EXECUTIVE = "Executive (25% off within 30 days)"
TIER_PRESIDENTIAL = "Presidential / Chairman (30% off within 60 days)"
TIER_OPTIONS = [TIER_NO_DISCOUNT, TIER_EXECUTIVE, TIER_PRESIDENTIAL]

def get_unique_years_from_data(data: Dict[str, Any]) -> List[str]:
    """Helper to get years from both resorts and global holidays for date picker."""
    years = set()
    for resort in data.get("resorts", []):
        years.update(resort.get("years", {}).keys())
    if "global_holidays" in data:
        years.update(data["global_holidays"].keys())
    return sorted([y for y in years if y.isdigit() and len(y) == 4])

def apply_settings_from_dict(user_data: dict):
    try:
        if "maintenance_rate" in user_data: st.session_state.pref_maint_rate = float(user_data["maintenance_rate"])
        if "purchase_price" in user_data: st.session_state.pref_purchase_price = float(user_data["purchase_price"])
        if "capital_cost_pct" in user_data: st.session_state.pref_capital_cost = float(user_data["capital_cost_pct"])
        if "salvage_value" in user_data: st.session_state.pref_salvage_value = float(user_data["salvage_value"])
        if "useful_life" in user_data: st.session_state.pref_useful_life = int(user_data["useful_life"])

        if "discount_tier" in user_data:
            raw = str(user_data["discount_tier"])
            if "Executive" in raw: st.session_state.pref_discount_tier = TIER_EXECUTIVE
            elif "Presidential" in raw or "Chairman" in raw: st.session_state.pref_discount_tier = TIER_PRESIDENTIAL
            else: st.session_state.pref_discount_tier = TIER_NO_DISCOUNT

        if "include_capital" in user_data: st.session_state.pref_inc_c = bool(user_data["include_capital"])
        if "include_depreciation" in user_data: st.session_state.pref_inc_d = bool(user_data["include_depreciation"])

        if "renter_rate" in user_data:
            st.session_state.renter_rate_val = float(user_data["renter_rate"])

        if "renter_discount_tier" in user_data:
            raw_r = str(user_data["renter_discount_tier"])
            if "Executive" in raw_r: st.session_state.renter_discount_tier = TIER_EXECUTIVE
            elif "Presidential" in raw_r or "Chairman" in raw_r: st.session_state.renter_discount_tier = TIER_PRESIDENTIAL
            else: st.session_state.renter_discount_tier = TIER_NO_DISCOUNT

        if "preferred_resort_id" in user_data:
            rid = str(user_data["preferred_resort_id"])
            st.session_state.pref_resort_id = rid
            st.session_state.current_resort_id = rid

    except Exception as e:
        st.error(f"Error applying settings: {e}")

def main(forced_mode: str = "Renter") -> None:
    # --- 0. INIT STATE ---
    if "current_resort" not in st.session_state: st.session_state.current_resort = None
    if "current_resort_id" not in st.session_state: st.session_state.current_resort_id = None
    
    ensure_data_in_session()

    # --- 1. AUTO-LOAD LOCAL FILE ON STARTUP ---
    if "settings_auto_loaded" not in st.session_state:
        local_settings = "mvc_owner_settings.json"
        if os.path.exists(local_settings):
            try:
                with open(local_settings, "r") as f:
                    data = json.load(f)
                    apply_settings_from_dict(data)
                    st.toast("Auto-loaded local settings!", icon="Settings")
            except Exception:
                pass
        st.session_state.settings_auto_loaded = True

    # --- 2. DEFAULTS ---
    if "pref_maint_rate" not in st.session_state: st.session_state.pref_maint_rate = 0.55
    if "pref_purchase_price" not in st.session_state: st.session_state.pref_purchase_price = 18.0
    if "pref_capital_cost" not in st.session_state: st.session_state.pref_capital_cost = 5.0
    if "pref_salvage_value" not in st.session_state: st.session_state.pref_salvage_value = 3.0
    if "pref_useful_life" not in st.session_state: st.session_state.pref_useful_life = 10
    if "pref_discount_tier" not in st.session_state: st.session_state.pref_discount_tier = TIER_NO_DISCOUNT

    st.session_state.pref_inc_m = True
    if "pref_inc_c" not in st.session_state: st.session_state.pref_inc_c = True
    if "pref_inc_d" not in st.session_state: st.session_state.pref_inc_d = True

    if "renter_rate_val" not in st.session_state: st.session_state.renter_rate_val = 0.50
    if "renter_discount_tier" not in st.session_state: st.session_state.renter_discount_tier = TIER_NO_DISCOUNT

    today = datetime.now().date()
    initial_default = today + timedelta(days=1)
    if "calc_initial_default" not in st.session_state:
        st.session_state.calc_initial_default = initial_default
        st.session_state.calc_checkin = initial_default
        st.session_state.calc_checkin_user_set = False
    
    # Initialize nights default
    if "calc_nights" not in st.session_state:
        st.session_state.calc_nights = 7

    if not st.session_state.data:
        st.warning("Please open the Editor and upload/merge data_v2.json first.")
        return

    repo = MVCRepository(st.session_state.data)
    calc = MVCCalculator(repo)
    resorts_full = repo.get_resort_list_full()

    # Determine mode from arg
    mode = UserMode(forced_mode)

    render_page_header("Calc", f"{mode.value} Mode", icon="🏨", badge_color="#059669" if mode == UserMode.OWNER else "#2563eb")

    # --- MAIN PAGE: CONFIGURATION EXPANDER (Moved from Sidebar) ---
    owner_params = None
    policy = DiscountPolicy.NONE
    rate_to_use = 0.50
    disc_mul = 1.0

    # --- RESORT SELECTION ---
    if resorts_full and st.session_state.current_resort_id is None:
        if "pref_resort_id" in st.session_state and any(r.get("id") == st.session_state.pref_resort_id for r in resorts_full):
            st.session_state.current_resort_id = st.session_state.pref_resort_id
        else:
            st.session_state.current_resort_id = resorts_full[0].get("id")

    render_resort_grid(
        resorts_full,
        st.session_state.current_resort_id,
        title="🏨 Select Resort",
        show_change_button=True,
        picker_state_key="calc_show_resort_picker",
        collapse_on_select=True,
    )
    resort_obj = next((r for r in resorts_full if r.get("id") == st.session_state.current_resort_id), None)

    if not resort_obj: return

    r_name = resort_obj.get("display_name")
    
    # Clear room type selection if resort has changed
    if "last_resort_id" not in st.session_state:
        st.session_state.last_resort_id = st.session_state.current_resort_id
    
    if st.session_state.last_resort_id != st.session_state.current_resort_id:
        # Resort changed - clear room selection so ALL rooms table expands
        if "selected_room_type" in st.session_state:
            del st.session_state.selected_room_type
        st.session_state.last_resort_id = st.session_state.current_resort_id
    
    info = repo.get_resort_info(r_name)
    render_resort_card(info["full_name"], info["timezone"], info["address"])
    
    # --- CALCULATOR INPUTS: Check-in, Nights, and calculated Checkout ---
    c1, c2, c3 = st.columns([2, 1, 2])
    with c1:
        # Get available years for the date picker
        available_years = get_unique_years_from_data(st.session_state.data)
        min_date = datetime.now().date()
        max_date = datetime.now().date() + timedelta(days=365*2)
        
        if available_years:
            min_y = int(available_years[0])
            max_y = int(available_years[-1])
            min_date = date(min_y, 1, 1)
            max_date = date(max_y, 12, 31)
            
        checkin = st.date_input(
            "Check-in", 
            value=st.session_state.calc_checkin, 
            min_value=min_date,
            max_value=max_date,
            key="calc_checkin_widget"
        )
        
        # Update session state with new check-in date
        st.session_state.calc_checkin = checkin

    if not st.session_state.calc_checkin_user_set and checkin != st.session_state.calc_initial_default:
        st.session_state.calc_checkin_user_set = True
        
    with c2:
        nights = st.number_input(
            "Nights", 
            min_value=1, 
            max_value=60, 
            value=st.session_state.calc_nights,
            key="nights_input",
            step=1
        )
        
        # Update session state immediately
        st.session_state.calc_nights = nights
    
    with c3:
        # Calculate checkout date - recalculates on every render based on current inputs
        checkout_date = checkin + timedelta(days=nights)
        
        # Display as a disabled date_input
        # Using hash of date as key to force update when value changes
        st.date_input(
            "Check-out",
            value=checkout_date,
            disabled=True,
            key="checkout_display"
        )

    # Always adjust for holidays when dates overlap
    adj_in, adj_n, adj = calc.adjust_holiday(r_name, checkin, nights)

    if adj:
        # Holiday adjustment occurred - show prominent alert
        original_checkout = checkin + timedelta(days=nights - 1)
        adjusted_checkout = adj_in + timedelta(days=adj_n - 1)
        
        # Determine what changed
        date_changed = checkin != adj_in
        nights_changed = nights != adj_n
        
        # Build detailed message
        changes = []
        if date_changed:
            changes.append(f"Check-in moved from **{checkin.strftime('%b %d')}** to **{adj_in.strftime('%b %d')}**")
        if nights_changed:
            changes.append(f"Stay extended from **{nights} nights** to **{adj_n} nights**")
        
        change_text = " and ".join(changes)
        
        st.warning(
            f"🎉 **Holiday Period Detected!**\n\n"
            f"Your dates overlap with a holiday period. To get holiday pricing, your reservation has been adjusted:\n\n"
            f"{change_text}\n\n"
            f"**New stay:** {adj_in.strftime('%b %d, %Y')} - {adjusted_checkout.strftime('%b %d, %Y')} ({adj_n} nights)",
            icon="⚠️"
        )

    # Get all available room types for this resort
    pts, _ = calc._get_daily_points(calc.repo.get_resort(r_name), adj_in)
    if not pts:
        rd = calc.repo.get_resort(r_name)
        if rd and str(adj_in.year) in rd.years:
             yd = rd.years[str(adj_in.year)]
             if yd.seasons: pts = yd.seasons[0].day_categories[0].room_points

    room_types = sorted(pts.keys()) if pts else []
    if not room_types:
        st.error("No room data available for this resort.")
        return

    st.divider()

    # --- SETTINGS EXPANDER ---
    with st.expander("⚙️ Settings", expanded=False):
        if mode == UserMode.OWNER:
            c1, c2 = st.columns(2)
            with c1:
                current_val = st.session_state.get("pref_maint_rate", 0.55)
                val_rate = st.number_input(
                    "Maintenance ($/point)",
                    value=current_val,
                    key="widget_maint_rate",
                    step=0.01, min_value=0.0
                )
                if val_rate != current_val:
                    st.session_state.pref_maint_rate = val_rate
                rate_to_use = val_rate

            with c2:
                current_tier = st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT)
                try: t_idx = TIER_OPTIONS.index(current_tier)
                except ValueError: t_idx = 0
                opt = st.radio("Discount Tier:", TIER_OPTIONS, index=t_idx, key="widget_discount_tier")
                st.session_state.pref_discount_tier = opt

            col_chk2, col_chk3 = st.columns(2)
            inc_m = True
            with col_chk2:
                inc_c = st.checkbox("Include Capital Cost", value=st.session_state.get("pref_inc_c", True), key="widget_inc_c")
                st.session_state.pref_inc_c = inc_c
            with col_chk3:
                inc_d = st.checkbox("Include Depreciation", value=st.session_state.get("pref_inc_d", True), key="widget_inc_d")
                st.session_state.pref_inc_d = inc_d

            cap, coc, life, salvage = 18.0, 0.06, 15, 3.0
            
            if inc_c or inc_d:
                st.markdown("---")
                rc1, rc2, rc3, rc4 = st.columns(4)
                with rc1:
                    val_cap = st.number_input("Purchase ($/pt)", value=st.session_state.get("pref_purchase_price", 18.0), key="widget_purchase_price", step=1.0)
                    st.session_state.pref_purchase_price = val_cap
                    cap = val_cap
                with rc2:
                    if inc_c:
                        val_coc = st.number_input("Cost of Capital (%)", value=st.session_state.get("pref_capital_cost", 5.0), key="widget_capital_cost", step=0.5)
                        st.session_state.pref_capital_cost = val_coc
                        coc = val_coc / 100.0
                with rc3:
                    if inc_d:
                        val_life = st.number_input("Useful Life (yrs)", value=st.session_state.get("pref_useful_life", 10), key="widget_useful_life", min_value=1)
                        st.session_state.pref_useful_life = val_life
                        life = val_life
                with rc4:
                    if inc_d:
                        val_salvage = st.number_input("Salvage ($/pt)", value=st.session_state.get("pref_salvage_value", 3.0), key="widget_salvage_value", step=0.5)
                        st.session_state.pref_salvage_value = val_salvage
                        salvage = val_salvage

            owner_params = {
                "disc_mul": 1.0, "inc_m": inc_m, "inc_c": inc_c, "inc_d": inc_d,
                "cap_rate": cap * coc, "dep_rate": (cap - salvage) / life if life > 0 else 0.0,
            }
            
            # Save/Load UI inside Settings Expander
            st.markdown("---")
            sl_col1, sl_col2 = st.columns([3, 1])
            with sl_col1:
                config_file = st.file_uploader("Load Saved Settings (JSON)", type="json", key="user_cfg_upload_main")
                if config_file:
                      file_sig = f"{config_file.name}_{config_file.size}"
                      if "last_loaded_cfg" not in st.session_state or st.session_state.last_loaded_cfg != file_sig:
                          config_file.seek(0)
                          data = json.load(config_file)
                          apply_settings_from_dict(data)
                          st.session_state.last_loaded_cfg = file_sig
                          st.rerun()
            with sl_col2:
                current_pref_resort = st.session_state.current_resort_id if st.session_state.current_resort_id else ""
                current_settings = {
                    "maintenance_rate": st.session_state.get("pref_maint_rate", 0.55),
                    "purchase_price": st.session_state.get("pref_purchase_price", 18.0),
                    "capital_cost_pct": st.session_state.get("pref_capital_cost", 5.0),
                    "salvage_value": st.session_state.get("pref_salvage_value", 3.0),
                    "useful_life": st.session_state.get("pref_useful_life", 10),
                    "discount_tier": st.session_state.get("pref_discount_tier", TIER_NO_DISCOUNT),
                    "include_maintenance": True,
                    "include_capital": st.session_state.get("pref_inc_c", True),
                    "include_depreciation": st.session_state.get("pref_inc_d", True),
                    "renter_rate": st.session_state.get("renter_rate_val", 0.50),
                    "renter_discount_tier": st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT),
                    "preferred_resort_id": current_pref_resort
                }
                st.download_button("💾 Save Profile", json.dumps(current_settings, indent=2), "mvc_owner_settings.json", "application/json", use_container_width=True)

        else:
            # RENTER MODE CONFIG
            c1, c2 = st.columns(2)
            with c1:
                curr_rent = st.session_state.get("renter_rate_val", 0.50)
                renter_rate_input = st.number_input("Rental Cost per Point ($)", value=curr_rent, step=0.01, key="widget_renter_rate")
                if renter_rate_input != curr_rent: st.session_state.renter_rate_val = renter_rate_input
                rate_to_use = renter_rate_input

            with c2:
                curr_r_tier = st.session_state.get("renter_discount_tier", TIER_NO_DISCOUNT)
                try: r_idx = TIER_OPTIONS.index(curr_r_tier)
                except ValueError: r_idx = 0
                opt = st.radio("Discount tier available:", TIER_OPTIONS, index=r_idx, key="widget_renter_discount_tier")
                st.session_state.renter_discount_tier = opt

            if "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL
            elif "Executive" in opt: policy = DiscountPolicy.EXECUTIVE

        # Common Logic for Discount Multiplier
        if mode == UserMode.OWNER:
             if "Executive" in opt: policy = DiscountPolicy.EXECUTIVE
             elif "Presidential" in opt or "Chairman" in opt: policy = DiscountPolicy.PRESIDENTIAL

        disc_mul = 0.75 if "Executive" in opt else 0.7 if "Presidential" in opt or "Chairman" in opt else 1.0
        if owner_params: owner_params["disc_mul"] = disc_mul

    # --- ROOM TYPE SELECTION/DISPLAY ---
    # Determine if we should expand the ALL rooms table
    has_selection = "selected_room_type" in st.session_state and st.session_state.selected_room_type is not None
    is_single_room_resort = len(room_types) == 1
    
    # Auto-select if single room type and no selection yet
    if is_single_room_resort and not has_selection:
        st.session_state.selected_room_type = room_types[0]
        has_selection = True
    
    # Calculate costs for all room types (needed for both display modes)
    all_room_data = []
    for rm in room_types:
        room_res = calc.calculate_breakdown(r_name, rm, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
        cost_label = "Total Rent" if mode == UserMode.RENTER else "Total Cost"
        all_room_data.append({
            "Room Type": rm,
            "Points": room_res.total_points,
            cost_label: room_res.financial_total,
            "_select": rm
        })
    
    # Only show room selection UI if multiple room types exist
    if not is_single_room_resort:
        with st.expander("🏠 All Room Types", expanded=not has_selection):
            st.caption(f"Comparing all room types for {adj_n}-night stay from {adj_in.strftime('%b %d, %Y')}")
            
            # Display the table with select buttons
            for idx, row in enumerate(all_room_data):
                is_selected = has_selection and st.session_state.selected_room_type == row['Room Type']
                
                cols = st.columns([3, 2, 2, 1.5])
                with cols[0]:
                    # Add visual indicator for selected room
                    if is_selected:
                        st.write(f"**✓ {row['Room Type']}** (Selected)")
                    else:
                        st.write(f"**{row['Room Type']}**")
                with cols[1]:
                    st.write(f"{row['Points']:,} points")
                with cols[2]:
                    cost_label = "Total Rent" if mode == UserMode.RENTER else "Total Cost"
                    st.write(f"${row[cost_label]:,.0f}")
                with cols[3]:
                    # Button with calendar icon and "Dates" text
                    if is_selected:
                        st.button("📅 Dates", key=f"select_{row['_select']}", use_container_width=True, type="primary", disabled=True)
                    else:
                        if st.button("📅 Dates", key=f"select_{row['_select']}", use_container_width=True, type="secondary"):
                            st.session_state.selected_room_type = row['Room Type']
                            st.rerun()
    
    # --- DETAILED BREAKDOWN (Only shown when room type is selected) ---
    if has_selection:
        room_sel = st.session_state.selected_room_type
        
        # Header with calendar icon and room type description, Change Room button on right
        col_header, col_clear = st.columns([4, 1])
        with col_header:
            # Show info note for single room resorts
            if is_single_room_resort:
                st.markdown(f"### 📅 {room_sel}")
                st.caption("ℹ️ This resort has only one room type")
            else:
                st.markdown(f"### 📅 {room_sel}")
        with col_clear:
            # Only show Change Room button if multiple room types exist
            if not is_single_room_resort:
                if st.button("↩️ Change Room", use_container_width=True):
                    del st.session_state.selected_room_type
                    st.rerun()
        
        # Calculate the breakdown for selected room
        res = calc.calculate_breakdown(r_name, room_sel, adj_in, adj_n, mode, rate_to_use, policy, owner_params)
        
        # Build enhanced settings caption
        discount_display = "None"
        if disc_mul < 1.0:
            pct = int((1.0 - disc_mul) * 100)
            policy_label = "Executive" if disc_mul == 0.75 else "Presidential/Chairman" if disc_mul == 0.7 else "Custom"
            discount_display = f"✅ {pct}% Off points ({policy_label})"

        rate_label = "Maintenance " if mode == UserMode.OWNER else "Rental Rate"

        settings_parts = []
        settings_parts.append(f"{rate_label}: ${rate_to_use:.2f}/pt")

        if mode == UserMode.OWNER:
            purchase_per_pt = st.session_state.get("pref_purchase_price", 18.0)
            total_purchase = purchase_per_pt * res.total_points
            useful_life = st.session_state.get("pref_useful_life", 10)

            settings_parts.append(f"Purchase USD {total_purchase:,.0f}")
            settings_parts.append(f"Useful Life: **{useful_life} yrs**")

        settings_parts.append(f"**{discount_display}**")

        st.caption(f"⚙️ Settings: " + " • ".join(settings_parts))

        # Display metrics
        if mode == UserMode.OWNER:
            cols = st.columns(5)
            cols[0].metric("Total Points", f"{res.total_points:,}")
            cols[1].metric("Total Cost", f"${res.financial_total:,.0f}")
            cols[2].metric("Maintenance", f"${res.m_cost:,.0f}")
            if inc_c: cols[3].metric("Capital Cost", f"${res.c_cost:,.0f}")
            if inc_d: cols[4].metric("Depreciation", f"${res.d_cost:,.0f}")
        else:
            cols = st.columns(2)
            cols[0].metric("Total Points", f"{res.total_points:,}")
            cols[1].metric("Total Rent", f"${res.financial_total:,.0f}")
            if res.discount_applied: st.success(f"✨ Discount Applied: {len(res.discounted_days)} nights")

        # Daily Breakdown - displayed directly without subtitle (self-explanatory)
        st.dataframe(res.breakdown_df, use_container_width=True, hide_index=True)
    
    # --- SEASON AND HOLIDAY CALENDAR (Always available, independent of selection) ---
    st.divider()
    year_str = str(adj_in.year)
    res_data = calc.repo.get_resort(r_name)
    if res_data and year_str in res_data.years:
        with st.expander("📅 Season & Holiday Calendar", expanded=False):
            # Render Gantt chart as static image using function from charts.py
            gantt_img = create_gantt_chart_image(res_data, year_str, st.session_state.data.get("global_holidays", {}))
            
            if gantt_img:
                st.image(gantt_img, use_container_width=True)
            else:
                st.info("No season or holiday calendar data available for this year.")

            cost_df = build_season_cost_table(res_data, int(year_str), rate_to_use, disc_mul, mode, owner_params)
            if cost_df is not None:
                title = "7-Night Rental Costs" if mode == UserMode.RENTER else "7-Night Ownership Costs"
                note = " — Discount applied" if disc_mul < 1 else ""
                st.markdown(f"**{title}** @ ${rate_to_use:.2f}/pt{note}")
                st.dataframe(cost_df, use_container_width=True, hide_index=True)
            else:
                st.info("No season or holiday pricing data for this year.")

def run(forced_mode: str = "Renter") -> None:
    main(forced_mode)
