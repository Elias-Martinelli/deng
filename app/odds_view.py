"""The "model forecast vs. bookmaker odds" section of the viewer.

Kept apart from the page script so the page stays a readable sequence of
sections. Everything shown here is read from the curated tables; the odds
were fetched by the pipeline (`deng.sources.the_odds_api`) under its budget rules.
Nothing on this page can trigger a request to The Odds API - a reload runs SQL.

Two timestamps are always shown separately: when the model forecast was
computed and when the bookmaker last changed its quote (plus when the pipeline
read it). Pairing a forecast with odds from a different moment is exactly the
mistake this section exists to make visible rather than hide.
"""

from __future__ import annotations

from collections.abc import Callable

import altair as alt
import pandas as pd
import streamlit as st
from components import (
    OddsComparison,
    OutcomeRow,
    age_label,
    note,
    odds_comparison_card,
    odds_comparison_grid,
    section,
)

# Categorical palette, validated for adjacent-series colour-vision safety in
# both modes (dataviz reference palette, fixed slot order). Bookmakers keep
# their slot however the selection changes, so a colour follows the entity.
SERIES_LIGHT = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
]
SERIES_DARK = [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
]
INK_LIGHT, INK_DARK = "#52514e", "#c3c2b7"
MAX_BOOKMAKERS = len(SERIES_LIGHT)
OUTCOMES = ("Home win", "Draw", "Away win")
MODEL_SERIES = "Model"


def _theme_is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001 - older Streamlit or no browser context
        return False


def render(
    query: Callable[..., pd.DataFrame],
    local_time: Callable[[pd.Timestamp, str], str],
    match_id: int,
    home: str,
    away: str,
    kickoff: pd.Timestamp,
    is_finished: bool,
    refresh_minutes: int,
    watch_hours: int,
    quota_reserve: int,
    has_key: bool,
) -> None:
    """Render the whole section for one match."""
    st.markdown(
        section(
            "Model forecast vs. bookmaker odds",
            "Our baseline model's HOME / DRAW / AWAY probabilities next to the 1X2 odds of "
            "real bookmakers (regular time incl. stoppage time), each with its own timestamp. "
            "The difference is a model deviation, not a betting edge.",
        ),
        unsafe_allow_html=True,
    )
    now = pd.Timestamp.now(tz="UTC")
    stamp = "%d %b %H:%M %Z"

    # --- the forecast ---------------------------------------------------------
    prediction = query(
        """
        SELECT model_version, predicted_at, is_pre_match, home_prob, draw_prob, away_prob,
               home_matches_considered, away_matches_considered, league_matches_considered
          FROM curated.match_prediction_latest
         WHERE match_id = %s
         ORDER BY model_version
         LIMIT 1
        """,
        (match_id,),
    )
    if prediction.empty:
        st.markdown(
            note("No model forecast for this match yet - run `make transform`.", "info"),
            unsafe_allow_html=True,
        )
        return
    p = prediction.iloc[0]
    model_label = f"{local_time(p['predicted_at'], stamp)} · {p['model_version']}"
    in_play = kickoff <= now and not is_finished
    if in_play:
        st.markdown(
            note(
                f"Kick-off was at {local_time(kickoff, stamp)}. What follows is the PRE-MATCH "
                f"forecast computed {local_time(p['predicted_at'], stamp)}, compared with the "
                "last odds read before or during the match. It is not a live forecast: a live "
                "comparison needs a model updated with the match state, which does not exist yet."
            ),
            unsafe_allow_html=True,
        )
    elif not p["is_pre_match"]:
        st.markdown(
            note(
                "This forecast was computed after kick-off from pre-match information only "
                "(the form window closes at kick-off). Usable for a retrospective comparison, "
                "not as what was known beforehand."
            ),
            unsafe_allow_html=True,
        )

    # --- the odds -------------------------------------------------------------
    odds = query(
        """
        SELECT bookmaker_key, bookmaker_title, source_updated_at, last_seen_at, latest_fetch_at,
               is_current, is_complete, overround, home_price, draw_price, away_price,
               home_prob_fair, draw_prob_fair, away_prob_fair
          FROM curated.bookmaker_odds_latest
         WHERE match_id = %s AND market_key = 'h2h'
         ORDER BY bookmaker_title
        """,
        (match_id,),
    )
    last_fetch = query(
        """
        SELECT ingested_at, requests_remaining, source
          FROM raw.odds_api
         ORDER BY ingested_at DESC
         LIMIT 1
        """
    )
    _fetch_status(last_fetch, now, local_time, stamp, quota_reserve, has_key)
    if odds.empty:
        st.markdown(
            note(
                "No bookmaker odds stored for this match. Bookmakers list a match a few weeks "
                "before kick-off; the pipeline fetches once a day and every "
                f"{refresh_minutes} min in the last {watch_hours} h before kick-off.",
                "info",
            ),
            unsafe_allow_html=True,
        )
        return

    # Expected freshness depends on where the match is relative to the watch
    # window: inside it the interval applies, outside it the daily fetch.
    hours_to_kickoff = (kickoff - now).total_seconds() / 3600
    expected_minutes = refresh_minutes if 0 < hours_to_kickoff <= watch_hours else 24 * 60
    stale_after = pd.Timedelta(minutes=2 * expected_minutes)

    # Slot colours are assigned over *every* bookmaker of the match, in a fixed
    # order, so the selection below never repaints the survivors.
    all_titles = list(odds["bookmaker_title"])
    default = [t for t, c in zip(all_titles, odds["is_current"], strict=True) if c][
        :4
    ] or all_titles[:4]
    selected = st.multiselect(
        "Bookmakers",
        options=all_titles,
        default=default,
        max_selections=MAX_BOOKMAKERS,
        help=(
            "Pick the platforms to compare side by side. Colours in the chart stay with "
            "the bookmaker."
        ),
    )
    chosen = odds[odds["bookmaker_title"].isin(selected)]
    if chosen.empty:
        st.info("Pick at least one bookmaker.")
        return

    cards = []
    for row in chosen.itertuples():
        age = now - row.last_seen_at
        if not row.is_current:
            state = "WITHDRAWN"
        elif not row.is_complete:
            state = "INCOMPLETE"
        elif age > stale_after:
            state = "STALE"
        else:
            state = "CURRENT"
        outcomes = [
            OutcomeRow(
                f"Home win · {home}",
                float(p["home_prob"]),
                _num(row.home_price),
                _num(row.home_prob_fair),
            ),
            OutcomeRow(
                "Draw", float(p["draw_prob"]), _num(row.draw_price), _num(row.draw_prob_fair)
            ),
            OutcomeRow(
                f"Away win · {away}",
                float(p["away_prob"]),
                _num(row.away_price),
                _num(row.away_prob_fair),
            ),
        ]
        cards.append(
            odds_comparison_card(
                OddsComparison(
                    bookmaker=row.bookmaker_title,
                    state=state,
                    model_label=model_label,
                    odds_label=local_time(row.source_updated_at, stamp),
                    fetched_label=local_time(row.last_seen_at, stamp),
                    age_label=age_label(age.total_seconds() / 60),
                    outcomes=outcomes,
                    overround=_num(row.overround),
                )
            )
        )
    st.markdown(odds_comparison_grid(cards), unsafe_allow_html=True)
    st.caption(
        f"Form windows behind the forecast: {home} {int(p['home_matches_considered'])}, "
        f"{away} {int(p['away_matches_considered'])} CL match(es); league rates from "
        f"{int(p['league_matches_considered'])} finished match(es) before kick-off."
    )

    # --- how both moved towards kick-off -------------------------------------
    with st.expander("How odds and forecast moved before kick-off"):
        _history_chart(query, match_id, all_titles, selected, kickoff, local_time)


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _fetch_status(last_fetch, now, local_time, stamp, quota_reserve, has_key) -> None:
    """One line on where the odds come from and how old the newest fetch is."""
    if last_fetch.empty:
        text = "No odds fetch stored yet. "
        text += (
            "Run `make odds` (real API) or `make run-samples` (committed samples)."
            if has_key
            else "ODDS_API_KEY is not set; `make run-samples` replays the committed sample fetches."
        )
        st.markdown(note(text, "info"), unsafe_allow_html=True)
        return
    f = last_fetch.iloc[0]
    age = age_label((now - f["ingested_at"]).total_seconds() / 60)
    text = (
        f"Newest odds fetch: {local_time(f['ingested_at'], stamp)} ({age}), source {f['source']}."
    )
    remaining = f["requests_remaining"]
    if remaining is not None and not pd.isna(remaining):
        text += f" API credits left this month: {int(remaining)}."
        if int(remaining) <= quota_reserve:
            st.markdown(
                note(
                    f"API quota reserve reached ({int(remaining)} credits left, reserve "
                    f"{quota_reserve}): fetching is paused, the state below is the last one "
                    f"read at {local_time(f['ingested_at'], stamp)} ({age})."
                ),
                unsafe_allow_html=True,
            )
    if not has_key and "sample" in str(f["source"]):
        text += " These are the committed sample fetches with fictional prices."
    st.caption(text)


def _history_chart(query, match_id, all_titles, selected, kickoff, local_time) -> None:
    """Fair market probability (or decimal odds) per bookmaker and the model, over time."""
    unit = st.radio(
        "Show as",
        ("Probability (%)", "Decimal odds"),
        horizontal=True,
        label_visibility="collapsed",
    )
    as_odds = unit == "Decimal odds"
    quotes = query(
        """
        SELECT bookmaker_title, first_seen_at, last_seen_at,
               home_price, draw_price, away_price, home_prob_fair, draw_prob_fair, away_prob_fair
          FROM curated.fact_bookmaker_odds
         WHERE match_id = %s AND market_key = 'h2h' AND is_complete
         ORDER BY bookmaker_title, first_seen_at
        """,
        (match_id,),
    )
    forecasts = query(
        """
        SELECT predicted_at, home_prob, draw_prob, away_prob
          FROM curated.fact_match_prediction
         WHERE match_id = %s
         ORDER BY predicted_at
        """,
        (match_id,),
    )
    quotes = quotes[quotes["bookmaker_title"].isin(selected)]
    if quotes.empty:
        st.caption("No complete quotes for the selected bookmakers.")
        return

    frames = []
    for outcome, price_col, fair_col, prob_col in zip(
        OUTCOMES,
        ("home_price", "draw_price", "away_price"),
        ("home_prob_fair", "draw_prob_fair", "away_prob_fair"),
        ("home_prob", "draw_prob", "away_prob"),
        strict=True,
    ):
        q = quotes[["bookmaker_title", "first_seen_at", "last_seen_at", price_col, fair_col]].copy()
        q["value"] = q[price_col].astype(float) if as_odds else q[fair_col].astype(float) * 100
        # A quote holds from the fetch that first showed it; the newest one is
        # extended to the fetch that last confirmed it, so the line reaches the
        # last known state instead of stopping at the last change.
        starts = q.rename(columns={"first_seen_at": "at"})[["bookmaker_title", "at", "value"]]
        ends = (
            q.sort_values("last_seen_at")
            .groupby("bookmaker_title")
            .tail(1)
            .rename(columns={"last_seen_at": "at"})[["bookmaker_title", "at", "value"]]
        )
        part = pd.concat([starts, ends]).rename(columns={"bookmaker_title": "series"})
        part["outcome"] = outcome
        frames.append(part)
        m = forecasts[["predicted_at", prob_col]].rename(columns={"predicted_at": "at"})
        prob = m[prob_col].astype(float)
        m["value"] = (1 / prob) if as_odds else prob * 100
        m["series"] = MODEL_SERIES
        m["outcome"] = outcome
        frames.append(m[["series", "at", "value", "outcome"]])
    data = pd.concat(frames, ignore_index=True)
    data["at"] = pd.to_datetime(data["at"], utc=True).dt.tz_convert("Europe/Zurich")

    dark = _theme_is_dark()
    palette = SERIES_DARK if dark else SERIES_LIGHT
    domain = all_titles[:MAX_BOOKMAKERS] + [MODEL_SERIES]
    colours = palette[: len(all_titles[:MAX_BOOKMAKERS])] + [INK_DARK if dark else INK_LIGHT]
    y_title = "decimal odds" if as_odds else "probability, %"
    base = alt.Chart(data).encode(
        x=alt.X("at:T", title=None, axis=alt.Axis(format="%d %b %H:%M", labelAngle=0)),
        y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)),
        color=alt.Color(
            "series:N",
            scale=alt.Scale(domain=domain, range=colours),
            legend=alt.Legend(title=None, orient="bottom", columns=4),
        ),
        strokeDash=alt.StrokeDash(
            "series:N",
            scale=alt.Scale(domain=domain, range=[[1, 0]] * (len(domain) - 1) + [[6, 3]]),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("series:N", title="Series"),
            alt.Tooltip("outcome:N", title="Outcome"),
            alt.Tooltip("at:T", title="At", format="%d %b %H:%M"),
            alt.Tooltip("value:Q", title=y_title, format=".2f"),
        ],
    )
    lines = base.mark_line(interpolate="step-after", strokeWidth=2)
    points = base.mark_point(size=60, filled=True)
    chart = (
        alt.layer(lines, points)
        .properties(height=170)
        .facet(
            row=alt.Row(
                "outcome:N",
                sort=list(OUTCOMES),
                title=None,
                header=alt.Header(labelAngle=0, labelAlign="left"),
            )
        )
        .resolve_scale(y="independent")
        .configure_axis(gridColor="rgba(127,127,127,.25)", domainColor="rgba(127,127,127,.4)")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "Steps: a quote holds until the bookmaker changes it. Kick-off "
        f"{local_time(kickoff, '%d %b %H:%M %Z')}. Model points: one per pipeline run. "
        "Hover for values."
    )
    table = data.pivot_table(
        index=["at", "outcome"], columns="series", values="value"
    ).reset_index()
    table["at"] = table["at"].dt.strftime("%d %b %H:%M")
    with st.expander("Data table"):
        st.dataframe(table, hide_index=True, width="stretch")
