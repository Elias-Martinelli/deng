"""Show the complete curated feature dataset with one row per match."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import psycopg
import streamlit as st


def render(query: Callable[..., pd.DataFrame]) -> None:
    """Display all match features together, with optional season and text filters."""
    st.header("Curated dataset · one row per match")
    st.caption(
        "Teams, kick-off, result, both teams' form, weather, the baseline forecast and the "
        "market probabilities together in one table. Every column and every match is shown; "
        "scroll sideways for more columns."
    )
    try:
        frame = query("SELECT * FROM curated.model_features ORDER BY utc_kickoff DESC, match_id")
    except psycopg.Error:
        st.error("The curated dataset could not be loaded.")
        return
    if frame.empty:
        st.info("There are no curated matches yet.")
        return

    seasons = sorted(frame["season_id"].dropna().unique().tolist(), reverse=True)
    selected = st.multiselect("Season", seasons, default=seasons)
    search = st.text_input("Search the dataset", placeholder="Team, match id or any other value")
    filtered = frame[frame["season_id"].isin(selected)]
    if search:
        mask = (
            filtered.astype("string")
            .apply(lambda column: column.str.contains(search, case=False, regex=False, na=False))
            .any(axis=1)
        )
        filtered = filtered[mask]

    st.caption(
        f"{len(filtered):,} of {len(frame):,} matches · {len(frame.columns)} columns · "
        "source: curated.model_features"
    )
    st.dataframe(filtered, hide_index=True, width="stretch", height=650)
    st.caption(
        "An empty cell means the value is missing. Kick-off times are in UTC. The "
        "forecast is the newest one per match; the market probabilities are averaged "
        "over the newest bookmaker quotes."
    )
