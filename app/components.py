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

# The stylesheet lives in app/style.py; this module only emits markup.


# frozen=True: these are value objects handed from the page to the render
# functions; making them immutable rules out a render function changing data
# another one later displays.
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
    # The team won if "home scored more" and "the team is the home side" are
    # both true or both false (i.e. away side and away scored more).
    team_won = (home_goals > away_goals) == (team_id == home_id)
    return "W" if team_won else "L"


# WMO weather interpretation codes as used by Open-Meteo, grouped.
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "Clear sky"),
    1: ("🌤", "Mainly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("🌫", "Fog"),
    48: ("🌫", "Rime fog"),
    51: ("🌦", "Light drizzle"),
    53: ("🌦", "Drizzle"),
    55: ("🌧", "Dense drizzle"),
    61: ("🌦", "Light rain"),
    63: ("🌧", "Rain"),
    65: ("🌧", "Heavy rain"),
    66: ("🌧", "Freezing rain"),
    67: ("🌧", "Heavy freezing rain"),
    71: ("🌨", "Light snow"),
    73: ("🌨", "Snow"),
    75: ("❄️", "Heavy snow"),
    77: ("🌨", "Snow grains"),
    80: ("🌦", "Rain showers"),
    81: ("🌧", "Heavy rain showers"),
    82: ("⛈", "Violent rain showers"),
    85: ("🌨", "Snow showers"),
    86: ("🌨", "Heavy snow showers"),
    95: ("⛈", "Thunderstorm"),
    96: ("⛈", "Thunderstorm with hail"),
    99: ("⛈", "Thunderstorm with heavy hail"),
}

WEATHER_REASONS: dict[str, str] = {
    "NOT_YET_AVAILABLE": "Forecasts reach 16 days ahead. Available from {available_from}.",
    "VENUE_UNKNOWN": (
        "No verified venue for this home side, so no forecast - rather than one for a "
        "guessed location."
    ),
    "NOT_CAPTURED": (
        "Played before the pipeline fetched a forecast for it. A forecast cannot be "
        "fetched after the fact."
    ),
    "MISSING": (
        "Inside the forecast horizon, but no forecast was fetched - a pipeline gap, "
        "flagged by the data-quality checks."
    ),
}


@dataclass(frozen=True)
class MatchWeather:
    """The weather row of one match, as the page shows it."""

    status: str
    temperature_c: float | None = None
    precipitation_probability: int | None = None
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None
    weather_code: int | None = None
    fetched_label: str | None = None
    lead_days: int | None = None
    available_from: str | None = None


def weather_card(weather: MatchWeather) -> str:
    """Forecast for the kick-off hour, or the reason there is none."""
    if weather.status != "AVAILABLE":
        reason = WEATHER_REASONS.get(weather.status, weather.status).format(
            available_from=weather.available_from or "16 days before kick-off"
        )
        return f'<div class="cl-card cl-empty">🌡 {escape(reason)}</div>'
    icon, label = WMO_CODES.get(weather.weather_code or -1, ("🌡", "Weather"))
    facts = [
        f"🌧 {weather.precipitation_probability} % rain"
        if weather.precipitation_probability is not None
        else None,
        f"💧 {weather.precipitation_mm:.1f} mm" if weather.precipitation_mm is not None else None,
        f"💨 {weather.wind_speed_kmh:.0f} km/h" if weather.wind_speed_kmh is not None else None,
    ]
    lead = (
        f" - {weather.lead_days} day{'s' if weather.lead_days != 1 else ''} before kick-off"
        if weather.lead_days is not None
        else ""
    )
    return (
        '<div class="cl-card"><div class="cl-weather">'
        f'<span class="cl-icon">{icon}</span>'
        f'<span class="cl-temp">{weather.temperature_c:.0f} °C</span>'
        f"<span>{escape(label)}</span>"
        '<span class="cl-facts">'
        + "".join(f"<span>{fact}</span>" for fact in facts if fact)
        + "</span></div>"
        f'<div class="cl-weather-note">Forecast for the kick-off hour, fetched '
        f"{escape(weather.fetched_label or '?')}{lead}. Open-Meteo, CC BY 4.0.</div>"
        "</div>"
    )


# --------------------------------------------------------------------------
# Model forecast against bookmaker odds
# --------------------------------------------------------------------------

# The four states a quote can be in on the page. Text and a mark carry the
# meaning; the colour only underlines it.
ODDS_STATES: dict[str, tuple[str, str, str]] = {
    "CURRENT": ("cl-ok", "✓", "current"),
    "STALE": ("cl-warn", "⏱", "stale - older than the expected refresh"),
    "WITHDRAWN": ("cl-bad", "✗", "not in the latest fetch - withdrawn or suspended"),
    "INCOMPLETE": ("cl-warn", "!", "incomplete - the bookmaker quoted fewer than 3 outcomes"),
}


@dataclass(frozen=True)
class OutcomeRow:
    """One line of the comparison table: an outcome seen by the model and by one bookmaker."""

    label: str
    model_prob: float
    price: float | None = None
    fair_prob: float | None = None

    @property
    def model_odds(self) -> float:
        """Fair decimal odds implied by the model: 1 / probability."""
        return 1 / self.model_prob

    @property
    def deviation_pp(self) -> float | None:
        """Model minus market probability, in percentage points; None without a market."""
        return None if self.fair_prob is None else (self.model_prob - self.fair_prob) * 100


@dataclass(frozen=True)
class OddsComparison:
    """One bookmaker's newest quote next to the newest model forecast."""

    bookmaker: str
    state: str  # one of ODDS_STATES
    model_label: str  # when the forecast was computed
    odds_label: str  # the bookmaker's own timestamp
    fetched_label: str  # when the pipeline read it
    age_label: str  # "12 min ago"
    outcomes: Sequence[OutcomeRow]
    overround: float | None = None


def age_label(minutes: float | None) -> str:
    """Age in the coarsest unit that is still honest: minutes, hours or days."""
    if minutes is None:
        return "unknown age"
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{int(minutes)} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.0f} h ago"
    return f"{minutes / 1440:.0f} days ago"


def signed_pp(value: float | None) -> str:
    """A signed percentage-point figure, with a real minus sign."""
    if value is None:
        return "–"
    sign = "+" if value > 0 else ("−" if value < 0 else "±")
    return f"{sign}{abs(value):.1f} pp"


def odds_state_chip(state: str) -> str:
    """The state of a quote as a chip: mark and words, not colour alone."""
    cls, mark, words = ODDS_STATES.get(state, ("", "?", state.lower()))
    return f'<span class="cl-chip {cls}">{mark} {escape(words)}</span>'


def odds_comparison_card(comparison: OddsComparison) -> str:
    """Model forecast and one bookmaker's odds side by side, both timestamps visible."""
    rows = []
    for o in comparison.outcomes:
        if o.price is None:
            market = '<span class="cl-odds-na">–</span><span class="cl-odds-sub">not quoted</span>'
        else:
            fair = f"{o.fair_prob * 100:.0f} % fair" if o.fair_prob is not None else "no fair prob."
            market = f'{o.price:.2f}<span class="cl-odds-sub">{escape(fair)}</span>'
        rows.append(
            "<tr>"
            f"<td>{escape(o.label)}</td>"
            f"<td>{o.model_prob * 100:.0f} %"
            f'<span class="cl-odds-sub">{o.model_odds:.2f}</span></td>'
            f"<td>{market}</td>"
            f"<td>{escape(signed_pp(o.deviation_pp))}</td>"
            "</tr>"
        )
    margin = (
        f" · margin {comparison.overround * 100:.1f} %" if comparison.overround is not None else ""
    )
    return (
        '<div class="cl-card">'
        '<div class="cl-odds-head">'
        f'<span class="cl-odds-book">{escape(comparison.bookmaker)}</span>'
        f"{odds_state_chip(comparison.state)}"
        "</div>"
        '<div class="cl-odds-times">'
        f"Model forecast: {escape(comparison.model_label)}<br>"
        f"Odds: {escape(comparison.odds_label)} (bookmaker time) · read "
        f"{escape(comparison.fetched_label)}, {escape(comparison.age_label)}"
        "</div>"
        '<table class="cl-odds-table">'
        "<thead><tr><th>Outcome</th><th>Model<br>prob. · odds</th>"
        f"<th>{escape(comparison.bookmaker)}<br>odds · fair prob.</th>"
        "<th>Model<br>deviation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        '<div class="cl-odds-foot">1X2, regular time incl. stoppage time. Fair probability = '
        "the bookmaker's three prices with its margin removed. Deviation = model minus market, "
        f"in percentage points - a model deviation, not a betting edge{margin}.</div>"
        "</div>"
    )


def odds_comparison_grid(cards: Sequence[str]) -> str:
    """Bookmaker cards side by side; as many per row as fit 300 px each."""
    return '<div class="cl-odds-grid">' + "".join(cards) + "</div>"


def note(text: str, kind: str = "warn") -> str:
    """A short notice the reader must not miss: amber for caveats, blue for information."""
    cls = "cl-note cl-info" if kind == "info" else "cl-note"
    return f'<div class="{cls}">{escape(text)}</div>'
