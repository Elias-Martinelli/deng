"""HTML building blocks for the Streamlit viewer.

Why custom HTML instead of more `st.columns` and `st.dataframe`:
    Streamlit stacks columns on a phone, but nested columns (three metrics
    inside each of two team columns) end up as a long, cramped list, and a
    dataframe on a 390 px screen scrolls sideways. A few cards with one CSS
    grid and a media query read well on a desktop, an iPhone and an Android
    phone from the same code - no native app, no second frontend.

Why pure functions returning strings:
    They have no Streamlit dependency, so they are unit-tested like any other
    code (`tests/test_app_components.py`). Every value that comes from the data
    - team names, venues - passes through `html.escape`; it originates from an
    external API and must never be able to inject markup into the page.

No external resources: no web fonts, and crests are embedded from our own
database (`curated.team_crest`) as data URIs rather than linked to the API's
CDN. The page loads nothing that is not served by our own container.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from html import escape

# Colours are semi-transparent or paired with white text, so the cards work on
# Streamlit's light and dark theme alike.
CSS = """
<style>
  /* 3.75rem clears Streamlit's fixed header bar; less and it covers the title. */
  .block-container { padding-top: 3.75rem; padding-bottom: 3rem; max-width: 1100px; }
  .cl-hero {
    border-radius: 18px; padding: 1.4rem 1.2rem 1.1rem;
    background: linear-gradient(135deg, #0b1f4b 0%, #1a3a8f 60%, #2a56c6 100%);
    color: #fff; margin-bottom: 1rem;
  }
  .cl-hero .cl-meta { opacity: .85; font-size: .85rem; text-align: center;
    letter-spacing: .02em; }
  .cl-hero .cl-teams { display: grid; grid-template-columns: 1fr auto 1fr;
    align-items: start; gap: .75rem; margin: .9rem 0 .7rem; }
  .cl-hero .cl-team { display: flex; flex-direction: column; align-items: center;
    text-align: center; gap: .45rem; min-width: 0; }
  .cl-hero .cl-name { font-weight: 700; font-size: clamp(.95rem, 2.8vw, 1.35rem);
    line-height: 1.2; overflow-wrap: anywhere; }
  .cl-hero .cl-vs { font-weight: 800; opacity: .7; font-size: .9rem; margin-top: 1.1rem; }
  .cl-badge { width: 3.2rem; height: 3.2rem; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,.14); border: 2px solid rgba(255,255,255,.35);
    font-weight: 800; font-size: .85rem; letter-spacing: .04em; }
  .cl-badge.cl-crest { background: #fff; border-color: rgba(255,255,255,.6); padding: .35rem; }
  .cl-badge.cl-crest img { width: 100%; height: 100%; object-fit: contain; }
  .cl-hero .cl-venue { text-align: center; font-size: .85rem; opacity: .85; }
  .cl-mini { width: 1.5rem; height: 1.5rem; object-fit: contain; vertical-align: -.35rem;
    margin-right: .45rem; }

  .cl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .9rem; }
  @media (max-width: 640px) {
    .cl-grid { grid-template-columns: 1fr; }
    .cl-hero { padding: 1.1rem .8rem .9rem; border-radius: 14px; }
    .cl-badge { width: 2.6rem; height: 2.6rem; font-size: .75rem; }
    .cl-hero .cl-vs { margin-top: .8rem; }
    .block-container { padding-left: .8rem; padding-right: .8rem; }
  }

  .cl-card { border: 1px solid rgba(127,127,127,.25); border-radius: 14px;
    padding: 1rem 1rem .9rem; background: rgba(127,127,127,.05); }
  .cl-card .cl-team-name { margin: 0 0 .15rem; font-size: 1.05rem; font-weight: 700; }

  .cl-title { font-size: clamp(1.15rem, 4.2vw, 1.7rem); font-weight: 800;
    line-height: 1.2; margin: 0 0 .5rem; }
  .cl-section { font-size: 1.1rem; font-weight: 700; margin: 1.6rem 0 .2rem; }
  .cl-caption { font-size: .8rem; opacity: .7; margin: 0 0 .7rem; }
  .cl-sub { font-size: .8rem; opacity: .7; margin-bottom: .6rem; }
  .cl-pills { display: flex; gap: .3rem; margin: .2rem 0 .8rem; flex-wrap: wrap; }
  .cl-pill { width: 1.8rem; height: 1.8rem; border-radius: 7px; color: #fff;
    display: inline-flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: .8rem; }
  .cl-W { background: #1e8e3e; } .cl-D { background: #8a8f98; } .cl-L { background: #d93025; }
  .cl-empty { font-size: .85rem; opacity: .7; }
  .cl-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: .4rem;
    text-align: center; }
  .cl-stat .cl-val { font-size: 1.35rem; font-weight: 700; line-height: 1.1; }
  .cl-stat .cl-lbl { font-size: .72rem; opacity: .7; text-transform: uppercase;
    letter-spacing: .04em; }
  .cl-rest { margin-top: .6rem; font-size: .8rem; opacity: .75; }

  .cl-list { border: 1px solid rgba(127,127,127,.25); border-radius: 14px;
    overflow: hidden; }
  .cl-row { display: grid; grid-template-columns: 4.6rem 1fr auto 1fr;
    align-items: center; gap: .5rem; padding: .55rem .8rem;
    border-top: 1px solid rgba(127,127,127,.15); font-size: .9rem; }
  .cl-row:first-child { border-top: none; }
  .cl-row .cl-date { font-size: .75rem; opacity: .7; }
  .cl-row .cl-h { text-align: right; overflow-wrap: anywhere; }
  .cl-row .cl-a { overflow-wrap: anywhere; }
  .cl-row .cl-score { font-weight: 700; font-variant-numeric: tabular-nums;
    padding: .1rem .5rem; border-radius: 6px; background: rgba(127,127,127,.14); }
  .cl-row .cl-win { font-weight: 700; }
  @media (max-width: 420px) {
    .cl-row { grid-template-columns: 1fr auto 1fr; }
    .cl-row .cl-date { grid-column: 1 / -1; }
  }

  .cl-status { display: inline-flex; gap: .5rem; flex-wrap: wrap; margin: .1rem 0 1rem; }
  .cl-chip { font-size: .78rem; padding: .25rem .6rem; border-radius: 999px;
    border: 1px solid rgba(127,127,127,.3); }
  .cl-ok { border-color: rgba(30,142,62,.6); }
  .cl-bad { border-color: rgba(217,48,37,.7); }
  .cl-warn { border-color: rgba(242,153,0,.8); }
</style>
"""


@dataclass(frozen=True)
class TeamForm:
    """One team's form going into a match, as the page shows it."""

    name: str
    tla: str
    crest_uri: str | None
    sequence: Sequence[str]  # most recent first, each "W", "D" or "L"
    matches_considered: int
    points: int
    goals_for: int
    goals_against: int
    days_rest: int | None


@dataclass(frozen=True)
class ResultRow:
    """A finished match in a result list."""

    date_label: str
    home: str
    away: str
    home_goals: int
    away_goals: int


def title(text: str) -> str:
    """Page title that scales with the screen instead of wrapping on a phone."""
    return f'<div class="cl-title">{escape(text)}</div>'


def section(heading: str, caption: str | None = None) -> str:
    """Section heading with consistent spacing, optionally with a caption."""
    note = f'<div class="cl-caption">{escape(caption)}</div>' if caption else ""
    return f'<div class="cl-section">{escape(heading)}</div>{note}'


def crest_uri(content_type: str | None, image: bytes | None) -> str | None:
    """Embed a stored crest as a data URI, or None when there is none.

    Only image types are accepted, and the URI is used in an <img> tag: an SVG
    loaded that way cannot run scripts, unlike inline SVG markup.
    """
    if not image or not content_type or not content_type.startswith("image/"):
        return None
    return f"data:{content_type};base64,{base64.b64encode(bytes(image)).decode('ascii')}"


def badge(tla: str | None, name: str, crest: str | None = None) -> str:
    """Round badge: the club crest when stored, otherwise the three-letter code."""
    if crest:
        return (
            f'<div class="cl-badge cl-crest"><img src="{escape(crest)}" '
            f'alt="{escape(name)} crest"></div>'
        )
    code = (tla or "".join(word[0] for word in name.split()[:3])).upper()[:3]
    return f'<div class="cl-badge">{escape(code)}</div>'


def _hero_team(tla: str | None, name: str, crest: str | None) -> str:
    return (
        f'<div class="cl-team">{badge(tla, name, crest)}'
        f'<div class="cl-name">{escape(name)}</div></div>'
    )


def match_hero(
    home: str,
    home_tla: str | None,
    away: str,
    away_tla: str | None,
    kickoff_label: str,
    matchday: int | None,
    venue: str | None,
    home_crest: str | None = None,
    away_crest: str | None = None,
) -> str:
    """The match header: both teams, kick-off, matchday and venue."""
    meta = escape(kickoff_label)
    if matchday is not None:
        meta += f" · Matchday {int(matchday)}"
    venue_html = f'<div class="cl-venue">🏟 {escape(venue)}</div>' if venue else ""
    return (
        '<div class="cl-hero">'
        f'<div class="cl-meta">{meta}</div>'
        '<div class="cl-teams">'
        f"{_hero_team(home_tla, home, home_crest)}"
        '<div class="cl-vs">VS</div>'
        f"{_hero_team(away_tla, away, away_crest)}"
        "</div>"
        f"{venue_html}"
        "</div>"
    )


def form_pills(sequence: Iterable[str]) -> str:
    """W/D/L squares, most recent first. Letters, not only colour, carry the meaning."""
    labels = {"W": "Win", "D": "Draw", "L": "Loss"}
    pills = [
        f'<span class="cl-pill cl-{r}" title="{labels[r]}">{r}</span>'
        for r in sequence
        if r in labels
    ]
    if not pills:
        return '<div class="cl-empty">No completed match before kick-off yet.</div>'
    return '<div class="cl-pills">' + "".join(pills) + "</div>"


def form_card(team: TeamForm) -> str:
    """One team's form: sequence, window size, points, goals, days of rest."""
    n = team.matches_considered
    window = f"last {n} CL match{'es' if n != 1 else ''}" if n else "no CL match yet"
    rest = (
        f'<div class="cl-rest">{team.days_rest} days since last match</div>'
        if team.days_rest is not None
        else '<div class="cl-rest">No previous match this season</div>'
    )
    mini = f'<img class="cl-mini" src="{escape(team.crest_uri)}" alt="">' if team.crest_uri else ""
    stats = "".join(
        f'<div class="cl-stat"><div class="cl-val">{value}</div>'
        f'<div class="cl-lbl">{label}</div></div>'
        for value, label in (
            (team.points, "Points"),
            (team.goals_for, "Scored"),
            (team.goals_against, "Conceded"),
        )
    )
    return (
        '<div class="cl-card">'
        f'<div class="cl-team-name">{mini}{escape(team.name)}</div>'
        f'<div class="cl-sub">Form · {window}</div>'
        f"{form_pills(team.sequence)}"
        f'<div class="cl-stats">{stats}</div>'
        f"{rest}"
        "</div>"
    )


def form_grid(home: TeamForm, away: TeamForm) -> str:
    """Two form cards side by side; stacked below 640 px."""
    return f'<div class="cl-grid">{form_card(home)}{form_card(away)}</div>'


def result_list(rows: Sequence[ResultRow], empty_message: str) -> str:
    """Finished matches as compact rows; the winner is set in bold."""
    if not rows:
        return f'<div class="cl-card cl-empty">{escape(empty_message)}</div>'
    parts = []
    for row in rows:
        home_cls = " cl-win" if row.home_goals > row.away_goals else ""
        away_cls = " cl-win" if row.away_goals > row.home_goals else ""
        parts.append(
            '<div class="cl-row">'
            f'<span class="cl-date">{escape(row.date_label)}</span>'
            f'<span class="cl-h{home_cls}">{escape(row.home)}</span>'
            f'<span class="cl-score">{row.home_goals}&nbsp;:&nbsp;{row.away_goals}</span>'
            f'<span class="cl-a{away_cls}">{escape(row.away)}</span>'
            "</div>"
        )
    return '<div class="cl-list">' + "".join(parts) + "</div>"


def status_chips(
    last_run_date: str | None,
    last_run_ok: bool,
    dq_passed: int,
    dq_total: int,
    dq_critical_failed: int,
) -> str:
    """Freshness and data-quality summary, visible without opening the sidebar.

    Red only for what fails a run (a failed run, a CRITICAL check); a failed
    WARNING check is amber - visible, but the data is still usable.
    """
    chips = []
    if last_run_date:
        cls = "cl-ok" if last_run_ok else "cl-bad"
        mark = "✓" if last_run_ok else "✗"
        label = f"{mark} Data as of {escape(last_run_date)}"
        chips.append(f'<span class="cl-chip {cls}">{label}</span>')
    else:
        chips.append('<span class="cl-chip cl-bad">No completed pipeline run</span>')
    if dq_total:
        if dq_critical_failed:
            cls = "cl-bad"
        elif dq_passed < dq_total:
            cls = "cl-warn"
        else:
            cls = "cl-ok"
        chips.append(f'<span class="cl-chip {cls}">Quality {dq_passed}/{dq_total} checks</span>')
    return '<div class="cl-status">' + "".join(chips) + "</div>"


def outcome_for(team_id: int, home_id: int, home_goals: int, away_goals: int) -> str:
    """W/D/L from one team's point of view."""
    if home_goals == away_goals:
        return "D"
    team_won = (home_goals > away_goals) == (team_id == home_id)
    return "W" if team_won else "L"
