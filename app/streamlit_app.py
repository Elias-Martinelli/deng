"""Streamlit viewer for the Champions League Match Intelligence data product.

Architectural rule this app exists to demonstrate, and the one question it will
be asked about: **it never calls an external API.** Every number on screen is
read from our own curated tables, which the batch pipeline produced. Picking a
different fixture runs a SQL query, not an HTTP request.

The alternative - a frontend that calls football-data.org and Open-Meteo on each
click - would be faster to write and would make the whole pipeline pointless:
no reproducibility, no history, no point-in-time correctness, and a rate limit
shared with every visitor.

Run it with:  make app        (or: streamlit run app/streamlit_app.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st

# Allow `streamlit run app/streamlit_app.py` from the repository root without
# installing the package first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deng.config import get_settings  # noqa: E402

st.set_page_config(page_title="CL Match Intelligence", page_icon="⚽", layout="wide")


@st.cache_resource
def get_connection() -> psycopg.Connection:
    """One pooled connection for the session."""
    return psycopg.connect(get_settings().postgres_dsn, autocommit=True)


@st.cache_data(ttl=60)
def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame.

    Cached for a minute: the underlying data changes once a day, so re-querying
    on every widget interaction would only add latency.
    """
    with get_connection().cursor() as cursor:
        cursor.execute(sql, params)
        columns = [c.name for c in cursor.description or []]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


def data_is_available() -> bool:
    """True when the curated layer holds matches."""
    try:
        return int(query("SELECT count(*) AS n FROM curated.fact_match").iloc[0]["n"]) > 0
    except psycopg.Error:
        return False


def form_line(row: pd.Series, prefix: str) -> str:
    """Render a team's form as 'W-D-L over N matches'."""
    considered = int(row[f"{prefix}_n"])
    if considered == 0:
        return "no completed matches yet"
    return (
        f"{int(row[f'{prefix}_w'])}W–{int(row[f'{prefix}_d'])}D–{int(row[f'{prefix}_l'])}L "
        f"over {considered} match{'es' if considered != 1 else ''}"
    )


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

st.title("⚽ Champions League Match Intelligence")
st.caption(
    "Every figure comes from our own curated tables, produced by the batch pipeline. "
    "This app makes no API calls."
)

if not data_is_available():
    st.error(
        "The curated layer is empty. Fill it first:\n\n"
        "```bash\nmake up\nmake init\nmake run-samples\n```"
    )
    st.stop()

# --- Sidebar: freshness and pipeline health -------------------------------
with st.sidebar:
    st.header("Data freshness")
    # Only finished runs: a row still marked RUNNING is either in flight right
    # now or a leftover, and neither says anything about data freshness.
    runs = query(
        """
        SELECT pipeline_name, logical_date, status, finished_at
          FROM meta.pipeline_runs
         WHERE finished_at IS NOT NULL
         ORDER BY finished_at DESC LIMIT 5
        """
    )
    if runs.empty:
        st.info("No completed pipeline run recorded yet.")
    else:
        latest = runs.iloc[0]
        st.metric("Last completed run", str(latest["logical_date"]))
        st.write("✅ SUCCESS" if latest["status"] == "SUCCESS" else f"❌ {latest['status']}")
        st.dataframe(runs, hide_index=True, width="stretch")

    dq = query(
        """
        SELECT check_name, severity, passed, observed
          FROM meta.dq_results
         WHERE checked_at = (SELECT max(checked_at) FROM meta.dq_results)
         ORDER BY passed, check_name
        """
    )
    if not dq.empty:
        failed = int((~dq["passed"]).sum())
        st.subheader("Data quality")
        st.write(f"{len(dq) - failed}/{len(dq)} checks passed")
        st.dataframe(dq, hide_index=True, width="stretch")

# --- Fixture picker --------------------------------------------------------
fixtures = query(
    """
    SELECT m.match_id, m.utc_kickoff, m.matchday,
           h.short_name AS home, a.short_name AS away, h.venue
      FROM curated.fact_match m
      JOIN curated.dim_team h ON h.team_id = m.home_team_id
      JOIN curated.dim_team a ON a.team_id = m.away_team_id
     WHERE m.is_upcoming
     ORDER BY m.utc_kickoff
    """
)

if fixtures.empty:
    st.warning(
        "No upcoming matches in the data. The season's league phase may be over, or the "
        "ingestion has not run recently."
    )
    st.stop()

fixtures["label"] = (
    fixtures["utc_kickoff"].dt.strftime("%a %d %b %H:%M")
    + "  ·  "
    + fixtures["home"]
    + " vs "
    + fixtures["away"]
)

selected_label = st.selectbox(
    f"Upcoming fixture ({len(fixtures)} available)", options=fixtures["label"]
)
fixture = fixtures[fixtures["label"] == selected_label].iloc[0]
match_id = int(fixture["match_id"])

# --- Match header ----------------------------------------------------------
detail = query(
    """
    SELECT m.utc_kickoff, m.matchday, m.stage,
           h.team_id AS home_id, h.name AS home_name, h.venue, h.country AS home_country,
           h.has_domestic_coverage AS home_cov,
           a.team_id AS away_id, a.name AS away_name, a.country AS away_country,
           a.has_domestic_coverage AS away_cov,
           fh.matches_considered AS home_n, fh.wins_last_5 AS home_w,
           fh.draws_last_5 AS home_d, fh.losses_last_5 AS home_l,
           fh.goals_scored_last_5 AS home_gf, fh.goals_conceded_last_5 AS home_ga,
           fh.points_last_5 AS home_pts, fh.days_since_last_match AS home_rest,
           fa.matches_considered AS away_n, fa.wins_last_5 AS away_w,
           fa.draws_last_5 AS away_d, fa.losses_last_5 AS away_l,
           fa.goals_scored_last_5 AS away_gf, fa.goals_conceded_last_5 AS away_ga,
           fa.points_last_5 AS away_pts, fa.days_since_last_match AS away_rest
      FROM curated.fact_match m
      JOIN curated.dim_team h ON h.team_id = m.home_team_id
      JOIN curated.dim_team a ON a.team_id = m.away_team_id
      JOIN curated.fact_team_match_form fh
        ON fh.match_id = m.match_id AND fh.team_id = m.home_team_id
      JOIN curated.fact_team_match_form fa
        ON fa.match_id = m.match_id AND fa.team_id = m.away_team_id
     WHERE m.match_id = %s
    """,
    (match_id,),
).iloc[0]

st.header(f"{detail['home_name']} vs {detail['away_name']}")
meta_left, meta_mid, meta_right = st.columns(3)
meta_left.metric("Kick-off (UTC)", detail["utc_kickoff"].strftime("%d %b %Y, %H:%M"))
meta_mid.metric("Matchday", int(detail["matchday"]) if pd.notna(detail["matchday"]) else "–")
meta_right.metric("Venue", detail["venue"] or "unknown")

# --- Form comparison -------------------------------------------------------
st.subheader("Form going into this match")
st.caption(
    "Built only from matches finished before kick-off. `matches` says how many games the "
    "window rests on — a one-match form is not comparable to a five-match form."
)

home_col, away_col = st.columns(2)
for column, prefix, name in (
    (home_col, "home", detail["home_name"]),
    (away_col, "away", detail["away_name"]),
):
    with column:
        st.markdown(f"**{name}**")
        st.write(form_line(detail, prefix))
        a, b, c = st.columns(3)
        a.metric("Points", int(detail[f"{prefix}_pts"]))
        b.metric("Goals for", int(detail[f"{prefix}_gf"]))
        c.metric("Goals against", int(detail[f"{prefix}_ga"]))
        rest = detail[f"{prefix}_rest"]
        st.caption(f"Days since last match: {int(rest)}" if pd.notna(rest) else "No previous match")
        if not detail[f"{prefix}_cov"]:
            st.warning(
                "The free API tier does not cover this club's domestic league, so its form "
                "rests on Champions League matches alone.",
                icon="⚠️",
            )

# --- Head to head ----------------------------------------------------------
st.subheader("Previous meetings in our data")
h2h = query(
    """
    SELECT m.match_date, h.short_name AS home, m.home_goals, m.away_goals,
           a.short_name AS away, m.outcome
      FROM curated.fact_match m
      JOIN curated.dim_team h ON h.team_id = m.home_team_id
      JOIN curated.dim_team a ON a.team_id = m.away_team_id
     WHERE m.is_finished
       AND ((m.home_team_id = %s AND m.away_team_id = %s)
         OR (m.home_team_id = %s AND m.away_team_id = %s))
     ORDER BY m.match_date DESC
    """,
    (
        int(detail["home_id"]),
        int(detail["away_id"]),
        int(detail["away_id"]),
        int(detail["home_id"]),
    ),
)
if h2h.empty:
    st.info(
        "No previous meeting in our data. We hold the current season; earlier seasons are "
        "available from the source but not ingested yet."
    )
else:
    st.dataframe(h2h, hide_index=True, width="stretch")

# --- Recent results of both teams -----------------------------------------
st.subheader("Recent results")
recent = query(
    """
    SELECT m.match_date, h.short_name AS home, m.home_goals, m.away_goals,
           a.short_name AS away, m.outcome
      FROM curated.fact_match m
      JOIN curated.dim_team h ON h.team_id = m.home_team_id
      JOIN curated.dim_team a ON a.team_id = m.away_team_id
     WHERE m.is_finished
       AND (m.home_team_id IN (%s, %s) OR m.away_team_id IN (%s, %s))
     ORDER BY m.utc_kickoff DESC
     LIMIT 10
    """,
    (
        int(detail["home_id"]),
        int(detail["away_id"]),
        int(detail["home_id"]),
        int(detail["away_id"]),
    ),
)
st.dataframe(recent, hide_index=True, width="stretch")

st.divider()
st.caption(
    "Data: football-data.org (free tier). Known limitations are documented in the repository's "
    "README — no line-ups, injuries or match statistics, and no domestic-league data for 11 of "
    "the 36 clubs."
)
