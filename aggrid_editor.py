import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode


def render_global_holidays_editor(data: dict) -> dict:
    """
    Renders the Global Holiday Calendar (Year-Specific) AG Grid.
    Returns updated data dict.
    """

    st.subheader("🎅 Global Holiday Calendar (Year-Specific)")
    st.caption("Edit holiday dates for each year. These dates are referenced by all resorts.")

    global_holidays = data.get("global_holidays", {})

    # Convert dict → DataFrame
    rows = []
    for year, dates in global_holidays.items():
        for d in dates:
            rows.append({
                "year": int(year),
                "date": d
            })

    if not rows:
        df = pd.DataFrame(columns=["year", "date"])
    else:
        df = pd.DataFrame(rows).sort_values(["year", "date"])

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True, resizable=True)
    gb.configure_column("year", type=["numericColumn"])
    gb.configure_column("date")
    gb.configure_grid_options(
        stopEditingWhenCellsLoseFocus=True
    )

    grid_response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        height=300,
        key="global_holidays_aggrid",  # 🔑 CRITICAL
    )

    updated_df = grid_response["data"]

    col1, col2 = st.columns([3, 1])

    with col1:
        if st.button("💾 Save Changes to Global Holidays"):
            new_global_holidays = {}

            for _, row in updated_df.iterrows():
                year = str(int(row["year"]))
                date = str(row["date"])

                new_global_holidays.setdefault(year, []).append(date)

            # Deduplicate + sort
            for year in new_global_holidays:
                new_global_holidays[year] = sorted(set(new_global_holidays[year]))

            data["global_holidays"] = new_global_holidays
            st.success("Global holidays updated.")

    with col2:
        if st.button("🔄 Reset"):
            st.experimental_rerun()

    return data


def render_season_dates_editor(resort_id: str, season_dates: dict) -> dict:
    """
    Example editor for resort season dates (uses unique keys per resort).
    """

    rows = []
    for season, ranges in season_dates.items():
        for r in ranges:
            rows.append({
                "season": season,
                "start": r["start"],
                "end": r["end"],
            })

    df = pd.DataFrame(rows)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True)
    gb.configure_column("season")
    gb.configure_column("start")
    gb.configure_column("end")

    response = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        height=250,
        key=f"season_dates_aggrid__{resort_id}",  # 🔑 UNIQUE
    )

    updated = {}
    for _, row in response["data"].iterrows():
        updated.setdefault(row["season"], []).append({
            "start": row["start"],
            "end": row["end"],
        })

    return updated
