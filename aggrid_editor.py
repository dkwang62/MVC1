import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode


def _build_gb(df: pd.DataFrame, editable: bool = True) -> GridOptionsBuilder:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=editable, resizable=True)
    gb.configure_grid_options(stopEditingWhenCellsLoseFocus=True)
    return gb


def render_global_holidays_grid(working: dict) -> None:
    """Edits working['global_holidays'] in-place (when Save clicked)."""

    st.markdown("## 🎅 Global Holiday Calendar (Year-Specific)")
    st.caption("Edit holiday dates for each year. These dates are referenced by all resorts.")

    global_holidays = (working.get("global_holidays") or {})

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
        key="global_holidays_aggrid",  # critical unique key
    )

    updated_df = grid["data"]

    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("💾 Save Changes to Global Holidays"):
            new_global_holidays: dict[str, list[str]] = {}
            for _, row in updated_df.iterrows():
                if pd.isna(row.get("year")) or pd.isna(row.get("date")):
                    continue
                year = str(int(row["year"]))
                date_str = str(row["date"]).strip()
                if not date_str:
                    continue
                new_global_holidays.setdefault(year, []).append(date_str)

            for y in list(new_global_holidays.keys()):
                new_global_holidays[y] = sorted(set(new_global_holidays[y]))

            working["global_holidays"] = new_global_holidays
            st.success("Global holidays updated.")

    with c2:
        if st.button("🔄 Reset"):
            st.rerun()


def render_season_dates_grid(working: dict, resort_id: str) -> None:
    """
    Reads/writes:
      working['resorts'][resort_id]['season_dates']
    (If your actual nesting differs, adjust the two getter lines below.)
    """
    resorts = working.get("resorts") or {}
    resort = resorts.get(resort_id) or {}
    season_dates = resort.get("season_dates") or {}

    if not isinstance(season_dates, dict):
        st.error(f"season_dates is not a dict for resort_id={resort_id}. Got: {type(season_dates)}")
        return

    rows = []
    for season, ranges in season_dates.items():
        for r in (ranges or []):
            rows.append(
                {"season": str(season),
                 "start": str(r.get("start", "")),
                 "end": str(r.get("end", ""))}
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
        key=f"season_dates_aggrid__{resort_id}",
    )

    updated = {}
    for _, row in grid["data"].iterrows():
        season = str(row.get("season", "")).strip()
        start = str(row.get("start", "")).strip()
        end = str(row.get("end", "")).strip()
        if not season or not start or not end:
            continue
        updated.setdefault(season, []).append({"start": start, "end": end})

    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("💾 Save Season Dates", key=f"save_season_dates__{resort_id}"):
            resort["season_dates"] = updated
            resorts[resort_id] = resort
            working["resorts"] = resorts
            st.success("Season dates updated.")
    with c2:
        if st.button("🔄 Reset", key=f"reset_season_dates__{resort_id}"):
            st.rerun()


def render_season_points_grid(working: dict, resort_id: str) -> None:
    """
    Reads/writes:
      working['resorts'][resort_id]['season_points']
    """
    resorts = working.get("resorts") or {}
    resort = resorts.get(resort_id) or {}
    season_points = resort.get("season_points") or {}

    if not isinstance(season_points, dict):
        st.error(f"season_points is not a dict for resort_id={resort_id}. Got: {type(season_points)}")
        return

    rows = []
    for season, points in season_points.items():
        points = points or {}
        rows.append(
            {"season": str(season),
             "Sun-Thu": points.get("Sun-Thu", ""),
             "Fri-Sat": points.get("Fri-Sat", "")}
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
        key=f"season_points_aggrid__{resort_id}",
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

    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("💾 Save Season Points", key=f"save_season_points__{resort_id}"):
            resort["season_points"] = updated
            resorts[resort_id] = resort
            working["resorts"] = resorts
            st.success("Season points updated.")
    with c2:
        if st.button("🔄 Reset", key=f"reset_season_points__{resort_id}"):
            st.rerun()


def render_holiday_points_grid(working: dict, resort_id: str) -> None:
    """
    Reads/writes:
      working['resorts'][resort_id]['holiday_points']
    """
    resorts = working.get("resorts") or {}
    resort = resorts.get(resort_id) or {}
    holiday_points = resort.get("holiday_points") or {}

    if not isinstance(holiday_points, dict):
        st.error(f"holiday_points is not a dict for resort_id={resort_id}. Got: {type(holiday_points)}")
        return

    rows = []
    for label, points in holiday_points.items():
        points = points or {}
        rows.append(
            {"label": str(label),
             "Sun-Thu": points.get("Sun-Thu", ""),
             "Fri-Sat": points.get("Fri-Sat", "")}
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
        key=f"holiday_points_aggrid__{resort_id}",
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

    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("💾 Save Holiday Points", key=f"save_holiday_points__{resort_id}"):
            resort["holiday_points"] = updated
            resorts[resort_id] = resort
            working["resorts"] = resorts
            st.success("Holiday points updated.")
    with c2:
        if st.button("🔄 Reset", key=f"reset_holiday_points__{resort_id}"):
            st.rerun()
