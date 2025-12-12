import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode


def _build_gb(df: pd.DataFrame, editable: bool = True) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=editable, resizable=True)
    gb.configure_grid_options(stopEditingWhenCellsLoseFocus=True)
    return gb


def render_global_holidays_grid(data: dict) -> dict:
    """
    Global Holiday Calendar (Year-Specific).
    Expects: data["global_holidays"] = { "2025": ["2025-12-25", ...], "2026": [...] }
    Returns updated data dict (only when user clicks Save).
    """
    st.markdown("## 🎅 Global Holiday Calendar (Year-Specific)")
    st.caption("Edit holiday dates for each year. These dates are referenced by all resorts.")

    global_holidays = data.get("global_holidays", {}) or {}

    rows = []
    for year, dates in global_holidays.items():
        try:
            y = int(year)
        except Exception:
            continue
        for d in (dates or []):
            rows.append({"year": y, "date": str(d)})

    df = pd.DataFrame(rows, columns=["year", "date"])
    if not df.empty:
        df = df.sort_values(["year", "date"]).reset_index(drop=True)

    gb = _build_gb(df, editable=True)
    gb.configure_column("year", type=["numericColumn"])
    gb.configure_column("date")

    grid = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        height=320,
        allow_unsafe_jscode=True,
        key="global_holidays_aggrid",  # IMPORTANT: unique key
    )

    updated_df = grid["data"]

    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("💾 Save Changes to Global Holidays"):
            new_global_holidays = {}
            for _, row in updated_df.iterrows():
                if pd.isna(row.get("year")) or pd.isna(row.get("date")):
                    continue
                year = str(int(row["year"]))
                date_str = str(row["date"]).strip()
                if not date_str:
                    continue
                new_global_holidays.setdefault(year, []).append(date_str)

            # de-dupe and sort
            for y in list(new_global_holidays.keys()):
                new_global_holidays[y] = sorted(set(new_global_holidays[y]))

            data["global_holidays"] = new_global_holidays
            st.success("Global holidays updated.")

    with c2:
        if st.button("🔄 Reset"):
            st.rerun()

    return data


def render_season_dates_grid(resort_id: str, season_dates: dict) -> dict:
    """
    Expects season_dates like:
    {
      "Low": [{"start":"2025-01-01","end":"2025-02-01"}, ...],
      "High": [...]
    }
    Returns updated structure in same format.
    """
    rows = []
    season_dates = season_dates or {}
    for season, ranges in season_dates.items():
        for r in (ranges or []):
            rows.append(
                {
                    "season": str(season),
                    "start": str(r.get("start", "")),
                    "end": str(r.get("end", "")),
                }
            )

    df = pd.DataFrame(rows, columns=["season", "start", "end"])

    gb = _build_gb(df, editable=True)
    gb.configure_column("season")
    gb.configure_column("start")
    gb.configure_column("end")

    grid = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        height=260,
        key=f"season_dates_aggrid__{resort_id}",  # unique per resort
    )

    updated = {}
    for _, row in grid["data"].iterrows():
        season = str(row.get("season", "")).strip()
        start = str(row.get("start", "")).strip()
        end = str(row.get("end", "")).strip()
        if not season or not start or not end:
            continue
        updated.setdefault(season, []).append({"start": start, "end": end})

    return updated


def render_season_points_grid(resort_id: str, season_points: dict) -> dict:
    """
    Expects season_points like:
    {
      "Low": {"Sun-Thu": 1000, "Fri-Sat": 1200},
      "High": {"Sun-Thu": 1500, "Fri-Sat": 1800}
    }
    Returns same structure.
    """
    season_points = season_points or {}
    rows = []
    for season, points in season_points.items():
        points = points or {}
        rows.append(
            {
                "season": str(season),
                "Sun-Thu": points.get("Sun-Thu", ""),
                "Fri-Sat": points.get("Fri-Sat", ""),
            }
        )

    df = pd.DataFrame(rows, columns=["season", "Sun-Thu", "Fri-Sat"])

    gb = _build_gb(df, editable=True)
    gb.configure_column("season", editable=False)
    gb.configure_column("Sun-Thu", type=["numericColumn"])
    gb.configure_column("Fri-Sat", type=["numericColumn"])

    grid = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        height=240,
        key=f"season_points_aggrid__{resort_id}",  # unique per resort
    )

    updated = {}
    for _, row in grid["data"].iterrows():
        season = str(row.get("season", "")).strip()
        if not season:
            continue
        updated[season] = {
            "Sun-Thu": row.get("Sun-Thu", ""),
            "Fri-Sat": row.get("Fri-Sat", ""),
        }

    return updated


def render_holiday_points_grid(resort_id: str, holiday_points: dict) -> dict:
    """
    Optional helper, in case editor.py imports it.
    Expects holiday_points like:
    {
      "Holiday": {"Sun-Thu": 2000, "Fri-Sat": 2400}
    }
    Returns same structure.
    """
    holiday_points = holiday_points or {}
    rows = []
    for label, points in holiday_points.items():
        points = points or {}
        rows.append(
            {
                "label": str(label),
                "Sun-Thu": points.get("Sun-Thu", ""),
                "Fri-Sat": points.get("Fri-Sat", ""),
            }
        )

    df = pd.DataFrame(rows, columns=["label", "Sun-Thu", "Fri-Sat"])

    gb = _build_gb(df, editable=True)
    gb.configure_column("label", editable=False)
    gb.configure_column("Sun-Thu", type=["numericColumn"])
    gb.configure_column("Fri-Sat", type=["numericColumn"])

    grid = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        height=220,
        key=f"holiday_points_aggrid__{resort_id}",  # unique per resort
    )

    updated = {}
    for _, row in grid["data"].iterrows():
        label = str(row.get("label", "")).strip()
        if not label:
            continue
        updated[label] = {
            "Sun-Thu": row.get("Sun-Thu", ""),
            "Fri-Sat": row.get("Fri-Sat", ""),
        }

    return updated
