"""Show the complete curated feature dataset with one row per match."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import psycopg
import streamlit as st


def render(query: Callable[..., pd.DataFrame]) -> None:
    """Display all match features together, with optional season and text filters."""
    st.header("Curated Dataset · eine Zeile pro Match")
    st.caption(
        "Teams, Spieltermin, Ergebnis, Form beider Teams, Wetter, Modellprognose und "
        "Marktwahrscheinlichkeiten gemeinsam in einer Tabelle. Alle Spalten und Matches "
        "werden angezeigt; weitere Spalten erreichst du durch horizontales Scrollen."
    )
    try:
        frame = query("SELECT * FROM curated.model_features ORDER BY utc_kickoff DESC, match_id")
    except psycopg.Error:
        st.error("Der aufbereitete Datensatz konnte nicht geladen werden.")
        return
    if frame.empty:
        st.info("Es sind noch keine aufbereiteten Matches vorhanden.")
        return

    seasons = sorted(frame["season_id"].dropna().unique().tolist(), reverse=True)
    selected = st.multiselect("Saison", seasons, default=seasons)
    search = st.text_input("Datensatz durchsuchen", placeholder="Team, Match-ID oder anderer Wert")
    filtered = frame[frame["season_id"].isin(selected)]
    if search:
        mask = (
            filtered.astype("string")
            .apply(lambda column: column.str.contains(search, case=False, regex=False, na=False))
            .any(axis=1)
        )
        filtered = filtered[mask]

    st.caption(
        f"{len(filtered):,} von {len(frame):,} Matches · {len(frame.columns)} Spalten · "
        "Quelle: curated.model_features"
    )
    st.dataframe(filtered, hide_index=True, width="stretch", height=650)
    st.caption(
        "Leere Werte bedeuten, dass die entsprechende Information fehlt. "
        "Anstosszeiten sind in UTC. Die Modellprognose ist die neueste pro Match; "
        "Marktwahrscheinlichkeiten sind über die neuesten Buchmacherquoten gemittelt."
    )
