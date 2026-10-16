"""Explore the wide match dataset with bounded pages and feature coverage."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import psycopg
import streamlit as st

from deng.export import column_role


def render(query: Callable[..., pd.DataFrame]) -> None:
    """Show competition filters, labels, column groups and a bounded match page."""
    st.header("Trainingsdatensatz · eine Zeile pro Match")
    st.caption(
        "Form, Tore, Erholung, direkte Duelle, Kader, Trainer, Wetter, Quoten und Welt-Ranking. "
        "Das Ziel ist das Ergebnis nach 90 Minuten. Fehlende Daten bleiben leer."
    )
    try:
        summary = query(
            "SELECT competition_code, season_id, count(*) AS matches, "
            "count(label_outcome_90min) AS labelled "
            "FROM curated.match_training_features GROUP BY 1,2 ORDER BY 1,2 DESC"
        )
        columns = query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='curated' AND table_name='match_training_features' "
            "ORDER BY ordinal_position"
        )["column_name"].tolist()
    except psycopg.Error:
        st.error("Der Trainingsdatensatz ist noch nicht bereit. Bitte die Pipeline ausführen.")
        return
    if summary.empty:
        st.info("Es sind noch keine aufbereiteten Matches vorhanden.")
        return

    metrics = st.columns(4)
    metrics[0].metric("Matches", f"{int(summary.matches.sum()):,}")
    metrics[1].metric("Mit Ergebnis", f"{int(summary.labelled.sum()):,}")
    metrics[2].metric("Wettbewerbe", summary.competition_code.nunique())
    metrics[3].metric("Spalten", len(columns))
    leagues = st.multiselect(
        "Wettbewerbe",
        summary.competition_code.unique().tolist(),
        default=summary.competition_code.unique().tolist(),
    )
    season_options = (
        summary.loc[summary.competition_code.isin(leagues), "season_id"].unique().tolist()
    )
    seasons = st.multiselect("Saison-ID des Anbieters", season_options, default=season_options)
    labelled = st.checkbox("Nur abgeschlossene Matches mit 90-Minuten-Ergebnis")
    search = st.text_input("Team oder Match-ID suchen")
    if not leagues or not seasons:
        st.info("Mindestens einen Wettbewerb und eine Saison auswählen.")
        return
    where = "competition_code = ANY(%s) AND season_id = ANY(%s)"
    params: list = [leagues, [int(s) for s in seasons]]
    if labelled:
        where += " AND label_outcome_90min IS NOT NULL"
    if search:
        where += (
            " AND (audit_home_team_name ILIKE %s OR audit_away_team_name ILIKE %s "
            "OR match_id::text = %s)"
        )
        params.extend([f"%{search}%", f"%{search}%", search])
    total = int(
        query(
            f"SELECT count(*) AS n FROM curated.match_training_features WHERE {where}",
            tuple(params),
        ).iloc[0]["n"]
    )
    pages = max(1, (total + 499) // 500)
    page = st.number_input("Seite · 500 Matches pro Seite", min_value=1, max_value=pages, value=1)
    frame = query(
        f"SELECT * FROM curated.match_training_features WHERE {where} "
        "ORDER BY utc_kickoff DESC, match_id LIMIT 500 OFFSET %s",
        tuple(params + [(int(page) - 1) * 500]),
    )
    groups = {
        "Alle Spalten": lambda c: True,
        "Modellmerkmale": lambda c: column_role(c) == "feature",
        "Welt-Ranking": lambda c: "world_rank" in c or "world_rating" in c,
        "Kader und Trainer": lambda c: any(x in c for x in ("squad", "coach", "market_value")),
        "Wetter und Quoten": lambda c: any(
            x in c
            for x in (
                "weather",
                "temperature",
                "precipitation",
                "wind",
                "odds",
            )
        ),
        "Ergebnis und Nachweis": lambda c: column_role(c) != "feature",
    }
    group = st.selectbox("Spaltengruppe", list(groups))
    identity = [
        "match_id",
        "competition_code",
        "utc_kickoff",
        "audit_home_team_name",
        "audit_away_team_name",
        "label_outcome_90min",
    ]
    selected = list(dict.fromkeys(identity + [c for c in columns if groups[group](c)]))
    st.caption(f"{total:,} passende Matches · Seite {page} von {pages}")
    st.dataframe(frame[selected], hide_index=True, width="stretch", height=600)
    st.download_button(
        "Diese Seite als CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name=f"matches-page-{page}.csv",
        mime="text/csv",
    )
    with st.expander("Vollständigkeit dieser Seite"):
        coverage = pd.DataFrame(
            {
                "Spalte": columns,
                "Vorhanden": frame.notna().sum().reindex(columns).values,
                "Fehlend": frame.isna().sum().reindex(columns).values,
            }
        )
        st.dataframe(coverage, hide_index=True, width="stretch")
    st.caption(
        "Historische Formwerte enthalten nur frühere Spiele aus den geladenen Wettbewerben. "
        "Kader, Trainer, Marktwerte, Wetter und Quoten brauchen eine Beobachtung vor Anstoss. "
        "Für das Training Zielspalten und Nachweisspalten ausschliessen und nach Datum aufteilen."
    )
