"""The dataset panels: what the pipeline holds for a model.

This is the part of the viewer that answers the question the project exists
for: *could someone train a match-outcome model on this, and what exactly
would they get?* Three panels:

1. **Dataset** - how many matches, how many of them carry a label, per season.
2. **Feature coverage** - for how many matches each feature is present, and the
   honest reason when it is not (a forecast beyond 16 days does not exist).
3. **Leakage guarantees** - the three rules that make the features usable,
   each recomputed here instead of quoted from the pipeline.

Everything is read from `curated.model_features`, the same view a model would
read. Nothing here calls an API.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st
from components import section

# A feature, the column that carries it, and why it can legitimately be absent.
FEATURES: tuple[tuple[str, str, str], ...] = (
    ("Form, home side", "home_form_matches", "no completed match before this kick-off yet"),
    ("Form, away side", "away_form_matches", "no completed match before this kick-off yet"),
    ("Rest days, home", "home_rest_days", "first match of the season for that club"),
    ("Rest days, away", "away_rest_days", "first match of the season for that club"),
    ("Weather at kick-off", "temperature_c", "kick-off beyond the 16-day forecast horizon"),
    ("Bookmaker odds", "fair_prob_home", "no quote stored yet for that match"),
    ("Baseline forecast", "model_prob_home", "computed for every match by the pipeline"),
)


def render(query: Callable[..., pd.DataFrame]) -> None:
    """Draw the three dataset panels."""
    features = query("SELECT * FROM curated.model_features")
    if features.empty:
        st.info("No matches in the curated layer yet - run `make run-samples` first.")
        return

    _dataset(features)
    _coverage(features)
    _leakage(query)


def _dataset(features: pd.DataFrame) -> None:
    labelled = features["outcome"].notna()
    st.markdown(
        section(
            "The dataset",
            "One row per match. A row can be used for training once it carries a label, "
            "which is the result of the match.",
        ),
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns(3)
    left.metric("Matches", len(features))
    middle.metric("With a label (played)", int(labelled.sum()))
    right.metric("Seasons", int(features["season_id"].nunique()))

    per_season = (
        features.assign(label=labelled)
        .groupby("season_id")
        .agg(
            matches=("match_id", "count"),
            labelled=("label", "sum"),
            first=("match_date", "min"),
            last=("match_date", "max"),
        )
        .reset_index()
        .sort_values("season_id")
    )
    st.dataframe(per_season, hide_index=True, width="stretch")
    st.caption(
        "More seasons is the lever: one league phase has 144 matches, a finished season with "
        "the knockout rounds has up to 189. Which seasons are fetched is a setting "
        "(FOOTBALL_DATA_SEASONS), and each one costs a single request."
    )


def _coverage(features: pd.DataFrame) -> None:
    st.markdown(
        section(
            "Feature coverage",
            "For how many matches is each feature present? A gap is not a bug - it is "
            "recorded with its reason, which is what keeps a model from learning from a "
            "silently missing value.",
        ),
        unsafe_allow_html=True,
    )
    total = len(features)
    rows = []
    for label, column, reason in FEATURES:
        if column not in features:
            present = 0
        elif column.endswith("_form_matches"):
            # A form row always exists; it carries information only once the
            # window rests on at least one finished match.
            present = int((features[column].fillna(0) > 0).sum())
        else:
            present = int(features[column].notna().sum())
        rows.append(
            {
                "feature": label,
                "present": present,
                "share": f"{present / total:.0%}" if total else "-",
                "absent because": reason,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    if "weather_status" in features:
        states = features["weather_status"].value_counts().rename_axis("state").reset_index()
        states.columns = ["weather state", "matches"]
        st.caption("Why the weather is missing where it is missing:")
        st.dataframe(states, hide_index=True, width="stretch")


def _leakage(query: Callable[..., pd.DataFrame]) -> None:
    st.markdown(
        section(
            "Leakage guarantees",
            "The three rules that make these features usable for a model, each recomputed "
            "here from the tables - not quoted from the pipeline.",
        ),
        unsafe_allow_html=True,
    )
    checks = query(
        """
        WITH appearances AS (
            SELECT match_id, utc_kickoff, is_finished, home_team_id AS team_id
              FROM curated.fact_match
            UNION ALL
            SELECT match_id, utc_kickoff, is_finished, away_team_id
              FROM curated.fact_match
        ),
        recomputed AS (
            -- Count, independently of the pipeline, how many matches of that
            -- team were finished strictly before this kick-off (at most five).
            SELECT a.match_id, a.team_id,
                   (SELECT count(*) FROM (
                        SELECT 1 FROM appearances p
                         WHERE p.team_id = a.team_id
                           AND p.is_finished
                           AND p.utc_kickoff < a.utc_kickoff
                         ORDER BY p.utc_kickoff DESC
                         LIMIT 5) AS window_) AS expected
              FROM appearances a
        )
        SELECT 'Form uses only matches finished before kick-off' AS guarantee,
               (SELECT count(*)
                  FROM curated.fact_team_match_form f
                  JOIN recomputed r USING (match_id, team_id)
                 WHERE f.matches_considered <> r.expected) AS violations
        UNION ALL
        SELECT 'Weather was fetched before kick-off',
               (SELECT count(*)
                  FROM curated.fact_match_weather w
                  JOIN curated.fact_match m USING (match_id)
                 WHERE w.weather_status = 'AVAILABLE'
                   AND w.forecast_fetched_at >= m.utc_kickoff)
        UNION ALL
        SELECT 'Every match has exactly two form rows',
               (SELECT count(*)
                  FROM (SELECT match_id FROM curated.fact_team_match_form
                         GROUP BY match_id HAVING count(*) <> 2) AS bad)
        """
    )
    checks["result"] = checks["violations"].map(lambda n: "ok" if n == 0 else f"{n} violations")
    st.dataframe(checks[["guarantee", "result"]], hide_index=True, width="stretch")
    st.caption(
        "The first rule is enforced by the SQL window that builds the form table and is "
        "re-checked by the data-quality check `form_uses_no_future_matches` after every run."
    )


def download(features: pd.DataFrame) -> None:
    """Offer the feature table as CSV - what a data scientist would take away."""
    st.download_button(
        "Download the feature table (CSV)",
        features.to_csv(index=False).encode("utf-8"),
        file_name="model_features.csv",
        mime="text/csv",
    )
