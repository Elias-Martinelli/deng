"""Explore the wide match dataset with bounded pages and feature coverage."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import psycopg
import streamlit as st

from deng.export import column_role


def render(query: Callable[..., pd.DataFrame]) -> None:
    """Show competition filters, labels, column groups and a bounded match page."""
    st.header("Training dataset · one row per match")
    st.caption(
        "Form, goals, rest, head-to-head, squad, coach, weather, odds and world ranking. "
        "The label is the result after 90 minutes. Missing values stay empty."
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
        st.error("The training dataset is not ready yet. Run the pipeline first.")
        return
    if summary.empty:
        st.info("There are no curated matches yet.")
        return

    metrics = st.columns(4)
    metrics[0].metric("Matches", f"{int(summary.matches.sum()):,}")
    metrics[1].metric("With a result", f"{int(summary.labelled.sum()):,}")
    metrics[2].metric("Competitions", summary.competition_code.nunique())
    metrics[3].metric("Columns", len(columns))
    leagues = st.multiselect(
        "Competitions",
        summary.competition_code.unique().tolist(),
        default=summary.competition_code.unique().tolist(),
    )
    season_options = (
        summary.loc[summary.competition_code.isin(leagues), "season_id"].unique().tolist()
    )
    seasons = st.multiselect("Provider season id", season_options, default=season_options)
    labelled = st.checkbox("Only finished matches with a 90-minute result")
    search = st.text_input("Search team or match id")
    if not leagues or not seasons:
        st.info("Select at least one competition and one season.")
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
    page = st.number_input("Page · 500 matches per page", min_value=1, max_value=pages, value=1)
    frame = query(
        f"SELECT * FROM curated.match_training_features WHERE {where} "
        "ORDER BY utc_kickoff DESC, match_id LIMIT 500 OFFSET %s",
        tuple(params + [(int(page) - 1) * 500]),
    )
    groups = {
        "All columns": lambda c: True,
        "Model features": lambda c: column_role(c) == "feature",
        "World ranking": lambda c: "world_rank" in c or "world_rating" in c,
        "Squad and coach": lambda c: any(x in c for x in ("squad", "coach", "market_value")),
        "Weather and odds": lambda c: any(
            x in c
            for x in (
                "weather",
                "temperature",
                "precipitation",
                "wind",
                "odds",
            )
        ),
        "Label and audit": lambda c: column_role(c) != "feature",
    }
    group = st.selectbox("Column group", list(groups))
    identity = [
        "match_id",
        "competition_code",
        "utc_kickoff",
        "audit_home_team_name",
        "audit_away_team_name",
        "label_outcome_90min",
    ]
    selected = list(dict.fromkeys(identity + [c for c in columns if groups[group](c)]))
    st.caption(
        f"{total:,} matching matches · page {page} of {pages} · "
        "source: curated.match_training_features"
    )
    st.dataframe(frame[selected], hide_index=True, width="stretch", height=600)
    st.download_button(
        "This page as CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name=f"matches-page-{page}.csv",
        mime="text/csv",
    )
    with st.expander("Completeness of this page"):
        coverage = pd.DataFrame(
            {
                "Column": columns,
                "Present": frame.notna().sum().reindex(columns).values,
                "Missing": frame.isna().sum().reindex(columns).values,
            }
        )
        st.dataframe(coverage, hide_index=True, width="stretch")
    st.caption(
        "Historical form counts only earlier matches of the loaded competitions. Squad, coach, "
        "market values, weather and odds need an observation before kick-off. For training, "
        "drop the label and audit columns and split by date."
    )
