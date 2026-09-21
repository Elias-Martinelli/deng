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

from components import (  # noqa: E402
    CSS,
    ResultRow,
    TeamForm,
    form_grid,
    match_hero,
    outcome_for,
    result_list,
    section,
    status_chips,
    title,
)

from deng.config import get_settings  # noqa: E402

# Kick-off times are stored in UTC and shown in the users' time zone: the use
# case speaks of "22 Oct 2026, 21:00 CEST", not of 19:00 UTC.
DISPLAY_TZ = "Europe/Zurich"

st.set_page_config(
    page_title="CL Match Intelligence",
    page_icon="⚽",
    layout="wide",
    # Diagnostics live in the sidebar; on a phone it would cover the page.
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)


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


def local_time(ts: pd.Timestamp, fmt: str) -> str:
    """Format a UTC timestamp in the display time zone, with its abbreviation."""
    return ts.tz_convert(DISPLAY_TZ).strftime(fmt)


def form_sequence(team_id: int, before: pd.Timestamp) -> list[str]:
    """The team's last five results before `before`, most recent first.

    Same window as curated.fact_team_match_form (finished, kick-off strictly
    before, at most five), so the badges always add up to `matches_considered`.
    """
    rows = query(
        """
        SELECT home_team_id, home_goals, away_goals
          FROM curated.fact_match
         WHERE is_finished
           AND (home_team_id = %s OR away_team_id = %s)
           AND utc_kickoff < %s
         ORDER BY utc_kickoff DESC
         LIMIT 5
        """,
        (team_id, team_id, before.to_pydatetime()),
    )
    return [
        outcome_for(team_id, int(r.home_team_id), int(r.home_goals), int(r.away_goals))
        for r in rows.itertuples()
    ]


def result_rows(frame: pd.DataFrame) -> list[ResultRow]:
    """Turn a result query into rows for `result_list`."""
    return [
        ResultRow(
            date_label=r.match_date.strftime("%d %b %Y"),
            home=r.home,
            away=r.away,
            home_goals=int(r.home_goals),
            away_goals=int(r.away_goals),
        )
        for r in frame.itertuples()
    ]


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

st.markdown(title("⚽ Champions League Match Intelligence"), unsafe_allow_html=True)

if not data_is_available():
    st.error(
        "The curated layer is empty. Fill it first:\n\n"
        "```bash\nmake up\nmake init\nmake run-samples\n```"
    )
    st.stop()

# Only finished runs: a row still marked RUNNING is either in flight right now
# or a leftover, and neither says anything about data freshness.
runs = query(
    """
    SELECT pipeline_name, logical_date, status, finished_at
      FROM meta.pipeline_runs
     WHERE finished_at IS NOT NULL
     ORDER BY finished_at DESC LIMIT 5
    """
)
dq = query(
    """
    SELECT check_name, severity, passed, observed
      FROM meta.dq_results
     WHERE checked_at = (SELECT max(checked_at) FROM meta.dq_results)
     ORDER BY passed, check_name
    """
)
dq_failed = dq[~dq["passed"]] if not dq.empty else dq
st.markdown(
    status_chips(
        last_run_date=None if runs.empty else str(runs.iloc[0]["logical_date"]),
        last_run_ok=not runs.empty and runs.iloc[0]["status"] == "SUCCESS",
        dq_passed=len(dq) - len(dq_failed),
        dq_total=len(dq),
        dq_critical_failed=int((dq_failed["severity"] == "CRITICAL").sum()) if len(dq) else 0,
    ),
    unsafe_allow_html=True,
)

# --- Sidebar: the details behind the status chips --------------------------
with st.sidebar:
    st.header("Pipeline")
    if runs.empty:
        st.info("No completed pipeline run recorded yet.")
    else:
        st.dataframe(runs, hide_index=True, width="stretch")
    if not dq.empty:
        st.subheader("Data quality")
        st.dataframe(dq, hide_index=True, width="stretch")
    st.caption(
        "Every figure comes from our own curated tables, produced by the batch pipeline. "
        "This app makes no API calls."
    )

# --- Fixture picker --------------------------------------------------------
fixtures = query(
    """
    SELECT m.match_id, m.utc_kickoff, m.matchday,
           h.short_name AS home, a.short_name AS away
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
    fixtures["utc_kickoff"].dt.tz_convert(DISPLAY_TZ).dt.strftime("%a %d %b, %H:%M")
    + "  ·  "
    + fixtures["home"]
    + " – "
    + fixtures["away"]
)
selected_label = st.selectbox(
    f"Upcoming fixture · {len(fixtures)} available", options=fixtures["label"]
)
match_id = int(fixtures.loc[fixtures["label"] == selected_label, "match_id"].iloc[0])

detail = query(
    """
    SELECT m.utc_kickoff, m.matchday,
           h.team_id AS home_id, h.name AS home_name, h.tla AS home_tla, h.venue,
           h.has_domestic_coverage AS home_cov,
           a.team_id AS away_id, a.name AS away_name, a.tla AS away_tla,
           a.has_domestic_coverage AS away_cov,
           fh.matches_considered AS home_n, fh.goals_scored_last_5 AS home_gf,
           fh.goals_conceded_last_5 AS home_ga, fh.points_last_5 AS home_pts,
           fh.days_since_last_match AS home_rest,
           fa.matches_considered AS away_n, fa.goals_scored_last_5 AS away_gf,
           fa.goals_conceded_last_5 AS away_ga, fa.points_last_5 AS away_pts,
           fa.days_since_last_match AS away_rest
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
kickoff = detail["utc_kickoff"]

# --- Match header ----------------------------------------------------------
st.markdown(
    match_hero(
        home=detail["home_name"],
        home_tla=detail["home_tla"],
        away=detail["away_name"],
        away_tla=detail["away_tla"],
        kickoff_label=local_time(kickoff, "%a %d %b %Y · %H:%M %Z"),
        matchday=int(detail["matchday"]) if pd.notna(detail["matchday"]) else None,
        venue=detail["venue"],
    ),
    unsafe_allow_html=True,
)


def team_form(prefix: str) -> TeamForm:
    """Collect one side's form from the detail row."""
    rest = detail[f"{prefix}_rest"]
    return TeamForm(
        name=detail[f"{prefix}_name"],
        tla=detail[f"{prefix}_tla"],
        sequence=form_sequence(int(detail[f"{prefix}_id"]), kickoff),
        matches_considered=int(detail[f"{prefix}_n"]),
        points=int(detail[f"{prefix}_pts"]),
        goals_for=int(detail[f"{prefix}_gf"]),
        goals_against=int(detail[f"{prefix}_ga"]),
        days_rest=int(rest) if pd.notna(rest) else None,
        has_domestic_coverage=bool(detail[f"{prefix}_cov"]),
    )


# --- Form comparison -------------------------------------------------------
st.markdown(
    section(
        "Form going into this match",
        "Only matches finished before kick-off count, most recent first. A form built on one "
        "match is not comparable to one built on five - the window size is always shown.",
    )
    + form_grid(team_form("home"), team_form("away")),
    unsafe_allow_html=True,
)

RESULTS_SQL = """
    SELECT m.match_date, h.short_name AS home, m.home_goals, m.away_goals,
           a.short_name AS away
      FROM curated.fact_match m
      JOIN curated.dim_team h ON h.team_id = m.home_team_id
      JOIN curated.dim_team a ON a.team_id = m.away_team_id
     WHERE m.is_finished AND {condition}
     ORDER BY m.utc_kickoff DESC
     LIMIT {limit}
"""

# --- Head to head ----------------------------------------------------------
home_id, away_id = int(detail["home_id"]), int(detail["away_id"])
h2h = query(
    RESULTS_SQL.format(
        condition="((m.home_team_id = %s AND m.away_team_id = %s) "
        "OR (m.home_team_id = %s AND m.away_team_id = %s))",
        limit=10,
    ),
    (home_id, away_id, away_id, home_id),
)
st.markdown(
    section("Previous meetings")
    + result_list(
        result_rows(h2h),
        "No previous meeting in our data. We hold the current season; earlier seasons are "
        "available from the source but not ingested yet.",
    ),
    unsafe_allow_html=True,
)

# --- Recent results, one tab per team ---------------------------------------
st.markdown(section("Recent results"), unsafe_allow_html=True)
for tab, team_id, name in zip(
    st.tabs([detail["home_name"], detail["away_name"]]),
    (home_id, away_id),
    (detail["home_name"], detail["away_name"]),
    strict=True,
):
    with tab:
        recent = query(
            RESULTS_SQL.format(condition="(m.home_team_id = %s OR m.away_team_id = %s)", limit=5),
            (team_id, team_id),
        )
        st.markdown(
            result_list(result_rows(recent), f"{name} has not finished a match yet this season."),
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    f"Times in {DISPLAY_TZ.split('/')[1]} local time. Data: football-data.org (free tier). "
    "No line-ups, injuries or match statistics, and no domestic-league data for 11 of the "
    "36 clubs - see the README's known limitations."
)
