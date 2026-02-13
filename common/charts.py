# common/charts.py
from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ======================================================================
# COLOUR MAP
# ======================================================================
COLOR_MAP: Dict[str, str] = {
    "Peak": "#D73027",
    "High": "#FC8D59",
    "Mid": "#FEE08B",
    "Low": "#1F78B4",
    "Holiday": "#D73027",
    "No Data": "#A6CEE3",
}

def _season_bucket(season_name: str) -> str:
    name = (season_name or "").strip().lower()
    if "peak" in name: return "Peak"
    if "high" in name: return "High"
    if "mid" in name or "shoulder" in name: return "Mid"
    if "low" in name: return "Low"
    return "No Data"

# ======================================================================
# CALCULATOR-SIDE GANTT
# ======================================================================
def create_gantt_chart_from_resort_data(
    resort_data: Any,
    year: str,
    global_holidays: Optional[Dict[str, Any]] = None,
    height: int = 500,
) -> go.Figure:
    """
    Build a season + holiday Gantt chart for the calculator app.
    """
    rows: List[Dict[str, Any]] = []

    # Safe attribute access for domain objects
    years_attr = getattr(resort_data, "years", {})
    if year not in years_attr:
        today = datetime.now()
        rows.append({"Task": "No Data", "Start": today, "Finish": today + timedelta(days=1), "Type": "No Data"})
    else:
        yd = years_attr[year]

        # Seasons
        for season in getattr(yd, "seasons", []):
            sname = getattr(season, "name", "(Unnamed)")
            bucket = _season_bucket(sname)
            for i, p in enumerate(getattr(season, "periods", []), 1):
                rows.append({
                    "Task": f"{sname} #{i}",
                    "Start": p.start,
                    "Finish": p.end,
                    "Type": bucket,
                })

        # Holidays
        for h in getattr(yd, "holidays", []):
            rows.append({
                "Task": getattr(h, "name", "(Unnamed)"),
                "Start": h.start_date,
                "Finish": h.end_date,
                "Type": "Holiday",
            })

    if not rows:
        today = datetime.now()
        rows.append({"Task": "No Data", "Start": today, "Finish": today + timedelta(days=1), "Type": "No Data"})

    df = pd.DataFrame(rows)
    
    # FIX: Remove emojis/special characters for the title to prevent 'tofu' boxes
    raw_name = getattr(resort_data, 'name', 'Resort')
    clean_name = "".join(c for c in raw_name if ord(c) < 128)

    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="Task",
        color="Type",
        title=f"{clean_name} – {year} Timeline",
        height=height if height is not None else max(400, len(df) * 35),
        color_discrete_map=COLOR_MAP,
    )

    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickformat="%d %b %Y")
    fig.update_layout(
        showlegend=True,
        xaxis_title="Date",
        yaxis_title="Period",
        font=dict(size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig
