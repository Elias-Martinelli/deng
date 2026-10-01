"""The viewer's stylesheet.

One `<style>` block, injected once in `app/streamlit_app.py`. It lives here and
not in `components.py` because that file is already at the project's 500-line
limit; nothing else imports it.

Two token blocks: `:root` carries the light values, a
`prefers-color-scheme: dark` block overrides them. That is the same signal
Streamlit's auto theme uses, so our panels and Streamlit's own chrome switch
together. Every colour is an opaque token - no `opacity:` on text - so every
contrast ratio is the ratio that actually renders.

The look this encodes: an operational surface, not a broadcast page. Flat
panels separated by hairlines instead of shadows, a 3 px radius, tabular
numerals for every figure, and exactly one accent colour, reserved for the
model column in the odds comparison - the one number the page argues about.

No external resources: system font stacks only, no `url(...)` anywhere.
"""

CSS = """
<style>
  /* ---------- tokens: light is the default ---------- */
  :root {
    --cl-bg-0: #EEF1F5;   /* page canvas          */
    --cl-bg-1: #FFFFFF;   /* panel surface        */
    --cl-bg-2: #E3E8EE;   /* header/table bands   */
    --cl-bg-3: #D6DCE4;   /* inline data plates   */
    --cl-line-1: #DAE0E7; /* inner hairline       */
    --cl-line-2: #BEC7D1; /* panel border, cuts   */
    --cl-line-ui: #78828F;/* Streamlit widgets    */
    --cl-text-0: #1B2129;
    --cl-text-1: #4C5663;
    --cl-text-2: #5C6875;
    --cl-accent: #1A3A8F;
    --cl-accent-line: #9AAAD2;
    --cl-accent-wash: #E8EBF4;
    --cl-ok: #146B45;
    --cl-warn: #8A5A00;
    --cl-bad: #B3261E;
    --cl-note-warn: #E2DFD8;
    --cl-note-info: #D5DBE9;
    --cl-plate: #FFFFFF;
    --cl-r: 3px;
    --cl-r-sm: 2px;
    --cl-pad-x: .9rem;
    --cl-pad-t: .7rem;
    --cl-pad-b: .8rem;
    --cl-font: system-ui, -apple-system, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif;
    --cl-font-num: ui-monospace, SFMono-Regular, "Cascadia Mono",
      "Segoe UI Mono", Menlo, Consolas, monospace;
  }

  /* ---------- tokens: dark, same names, same meanings ---------- */
  @media (prefers-color-scheme: dark) {
    :root {
      --cl-bg-0: #14181E;
      --cl-bg-1: #20252C;
      --cl-bg-2: #2A3038;
      --cl-bg-3: #343B45;
      --cl-line-1: #3A424D;
      --cl-line-2: #4E5866;
      --cl-line-ui: #7A8695;
      --cl-text-0: #E9EDF2;
      --cl-text-1: #B4BDC8;
      --cl-text-2: #98A3B0;
      --cl-accent: #63A2F7;
      --cl-accent-line: #3E6FA8;
      --cl-accent-wash: #273240;
      --cl-ok: #4CBB7B;
      --cl-warn: #E8AE41;
      --cl-bad: #F08A87;
      --cl-note-warn: #2D2A22;
      --cl-note-info: #1D2938;
      --cl-plate: #E9EDF2;
    }
  }

  /* 3.75rem clears Streamlit's fixed header bar; less and it covers the title.
     The background is the one safety net: if config.toml has not reached the
     container yet, our panels still sit on our own field instead of on
     Streamlit's default canvas. */
  .block-container {
    padding-top: 3.75rem; padding-bottom: 2.75rem; max-width: 1100px;
    background: var(--cl-bg-0);
  }
  .cl-title, .cl-section, .cl-caption, .cl-status, .cl-hero,
  .cl-card, .cl-list, .cl-note, .cl-empty { font-family: var(--cl-font); }

  /* ---------- masthead ---------- */
  .cl-title {
    font-size: clamp(1.1rem, 3.2vw, 1.5rem); font-weight: 600;
    letter-spacing: -.01em; line-height: 1.25; color: var(--cl-text-0);
    margin: 0 0 .35rem;
  }
  .cl-caption { font-size: .8125rem; line-height: 1.5; color: var(--cl-text-1);
    margin: 0 0 .7rem; }
  .cl-status {
    display: flex; gap: .4rem; flex-wrap: wrap; margin: .2rem 0 1.2rem;
    padding-bottom: .85rem; border-bottom: 1px solid var(--cl-line-2);
  }
  /* A rule above the heading, never below it: section() emits the caption as
     the heading's sibling, so a bottom border would cut the two apart. */
  .cl-section {
    font-size: .95rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .05em; color: var(--cl-text-0);
    border-top: 1px solid var(--cl-line-1); padding-top: .7rem;
    margin: 1.9rem 0 .35rem;
  }
  .cl-sub { font-size: .75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .05em; color: var(--cl-text-2); margin-bottom: .55rem; }

  /* ---------- hero: a record header, not a broadcast banner ---------- */
  .cl-hero {
    background: var(--cl-bg-1); border: 1px solid var(--cl-line-2);
    border-radius: var(--cl-r); color: var(--cl-text-0);
    padding: var(--cl-pad-t) var(--cl-pad-x) var(--cl-pad-b);
    margin-bottom: .9rem; overflow: hidden;
  }
  /* Header band: .cl-meta is the first child of .cl-hero (match_hero). */
  .cl-hero > .cl-meta {
    margin: calc(-1 * var(--cl-pad-t)) calc(-1 * var(--cl-pad-x)) .8rem;
    padding: .4rem var(--cl-pad-x); background: var(--cl-bg-2);
    border-bottom: 1px solid var(--cl-line-1); color: var(--cl-text-2);
    font-family: var(--cl-font-num); font-size: .75rem; text-align: center;
    text-transform: uppercase; letter-spacing: .06em;
  }
  .cl-hero .cl-teams { display: grid; grid-template-columns: 1fr auto 1fr;
    align-items: start; gap: .75rem; margin: 0 0 .7rem; }
  .cl-hero .cl-team { display: flex; flex-direction: column; align-items: center;
    text-align: center; gap: .45rem; min-width: 0; }
  .cl-hero .cl-name { font-weight: 600; font-size: clamp(.95rem, 2.6vw, 1.25rem);
    line-height: 1.25; overflow-wrap: anywhere; }
  .cl-hero .cl-vs { font-size: .75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .1em; color: var(--cl-text-2); margin-top: .8rem; }
  /* Footer band: .cl-venue is the last child when a venue is known. */
  .cl-hero > .cl-venue {
    margin: .7rem calc(-1 * var(--cl-pad-x)) calc(-1 * var(--cl-pad-b));
    padding: .4rem var(--cl-pad-x); background: var(--cl-bg-0);
    border-top: 1px solid var(--cl-line-1); color: var(--cl-text-2);
    font-size: .75rem; text-align: center;
  }
  .cl-badge {
    width: 2.6rem; height: 2.6rem; border-radius: var(--cl-r-sm);
    display: flex; align-items: center; justify-content: center;
    background: var(--cl-bg-3); border: 1px solid var(--cl-line-2);
    color: var(--cl-text-1); font-family: var(--cl-font-num);
    font-weight: 600; font-size: .75rem; letter-spacing: .05em;
  }
  .cl-badge.cl-crest { background: var(--cl-plate); border-color: var(--cl-line-2);
    padding: .3rem; }
  .cl-badge.cl-crest img { width: 100%; height: 100%; object-fit: contain; }
  .cl-mini { width: 1.25rem; height: 1.25rem; object-fit: contain;
    vertical-align: -.22rem; margin-right: .4rem; background: var(--cl-plate);
    border-radius: var(--cl-r-sm); padding: 1px; }

  /* ---------- panel primitive and its bands ---------- */
  .cl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; }
  .cl-card {
    background: var(--cl-bg-1); border: 1px solid var(--cl-line-2);
    border-radius: var(--cl-r); overflow: hidden;
    padding: var(--cl-pad-t) var(--cl-pad-x) var(--cl-pad-b);
  }
  /* Header band: first child of form_card (.cl-team-name) and of
     odds_comparison_card (.cl-odds-head). Verified against components.py. */
  .cl-card > .cl-team-name, .cl-card > .cl-odds-head {
    margin: calc(-1 * var(--cl-pad-t)) calc(-1 * var(--cl-pad-x)) .7rem;
    padding: .45rem var(--cl-pad-x); background: var(--cl-bg-2);
    border-bottom: 1px solid var(--cl-line-1);
  }
  /* Footer band: last child of form_card / weather_card / odds card. */
  .cl-card > .cl-rest, .cl-card > .cl-weather-note, .cl-card > .cl-odds-foot {
    margin: .7rem calc(-1 * var(--cl-pad-x)) calc(-1 * var(--cl-pad-b));
    padding: .45rem var(--cl-pad-x); background: var(--cl-bg-0);
    border-top: 1px solid var(--cl-line-1); color: var(--cl-text-2);
    font-size: .75rem; line-height: 1.5;
  }
  .cl-card .cl-team-name { margin: 0; font-size: .95rem; font-weight: 600;
    color: var(--cl-text-0); }
  .cl-empty { font-size: .8125rem; color: var(--cl-text-1); }

  /* ---------- form ---------- */
  .cl-pills { display: flex; gap: .3rem; margin: .2rem 0 .7rem; flex-wrap: wrap; }
  .cl-pill {
    width: 1.6rem; height: 1.6rem; border-radius: var(--cl-r-sm);
    display: inline-flex; align-items: center; justify-content: center;
    background: var(--cl-bg-2); border: 1px solid var(--cl-line-2);
    font-weight: 600; font-size: .78rem;
  }
  .cl-W { color: var(--cl-ok); border-color: var(--cl-ok); }
  .cl-D { color: var(--cl-text-1); }
  .cl-L { color: var(--cl-bad); border-color: var(--cl-bad); }
  .cl-stats {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
    text-align: left; margin: .7rem calc(-1 * var(--cl-pad-x)) 0;
    padding: .6rem var(--cl-pad-x) 0; border-top: 1px solid var(--cl-line-1);
  }
  .cl-stat { padding: 0 .55rem; }
  .cl-stat + .cl-stat { border-left: 1px solid var(--cl-line-1); }
  .cl-stats .cl-stat:first-child { padding-left: 0; }
  .cl-stat .cl-val { font-family: var(--cl-font-num);
    font-variant-numeric: tabular-nums; font-size: 1.25rem; font-weight: 600;
    line-height: 1.15; color: var(--cl-text-0); }
  .cl-stat .cl-lbl { font-size: .75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .05em; color: var(--cl-text-2); }

  /* ---------- result rows ---------- */
  .cl-list { background: var(--cl-bg-1); border: 1px solid var(--cl-line-2);
    border-radius: var(--cl-r); overflow: hidden; }
  /* date | home | score | away - the score column sizes to its content. */
  .cl-row { display: grid; grid-template-columns: 4.6rem 1fr auto 1fr;
    align-items: center; gap: .5rem; padding: .45rem var(--cl-pad-x);
    border-top: 1px solid var(--cl-line-1); font-size: .875rem;
    color: var(--cl-text-1); }
  .cl-row:first-child { border-top: none; }
  @media (hover: hover) { .cl-row:hover { background: var(--cl-bg-2); } }
  .cl-row .cl-date { font-family: var(--cl-font-num); font-size: .75rem;
    color: var(--cl-text-2); }
  .cl-row .cl-h { text-align: right; overflow-wrap: anywhere; }
  .cl-row .cl-a { overflow-wrap: anywhere; }
  .cl-row .cl-score {
    font-family: var(--cl-font-num); font-variant-numeric: tabular-nums;
    font-weight: 600; font-size: .8125rem; color: var(--cl-text-0);
    padding: .08rem .45rem; border-radius: var(--cl-r-sm);
    background: var(--cl-bg-3); border: 1px solid var(--cl-line-2);
  }
  .cl-row .cl-win { font-weight: 600; color: var(--cl-text-0); }

  /* ---------- weather ---------- */
  .cl-weather { display: flex; align-items: center; gap: .85rem; flex-wrap: wrap; }
  .cl-weather .cl-icon { font-size: 1.5rem; line-height: 1; }
  .cl-weather .cl-temp { font-family: var(--cl-font-num);
    font-variant-numeric: tabular-nums; font-size: 1.5rem; font-weight: 600;
    color: var(--cl-text-0); }
  .cl-weather .cl-facts { display: flex; gap: .9rem; flex-wrap: wrap;
    font-size: .875rem; color: var(--cl-text-1);
    font-variant-numeric: tabular-nums; }

  /* ---------- chips: words + mark + colour, one shape for both users ------- */
  .cl-chip {
    font-size: .75rem; padding: .22rem .5rem; border-radius: var(--cl-r-sm);
    background: var(--cl-bg-1); border: 1px solid var(--cl-line-2);
    color: var(--cl-text-1); font-variant-numeric: tabular-nums;
  }
  .cl-ok { color: var(--cl-ok); border-color: var(--cl-ok); }
  .cl-warn { color: var(--cl-warn); border-color: var(--cl-warn); }
  .cl-bad { color: var(--cl-bad); border-color: var(--cl-bad); }

  /* ---------- model vs. market: the one place the accent appears ---------- */
  .cl-odds-grid { display: grid; gap: .8rem;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); }
  .cl-odds-head { display: flex; justify-content: space-between;
    align-items: baseline; gap: .5rem; flex-wrap: wrap; }
  .cl-odds-book { font-weight: 600; font-size: .95rem; color: var(--cl-text-0); }
  .cl-odds-times { font-family: var(--cl-font-num); font-size: .75rem;
    line-height: 1.5; color: var(--cl-text-2); margin-bottom: .5rem; }
  .cl-odds-table { width: 100%; border-collapse: collapse; font-size: .8125rem;
    font-variant-numeric: tabular-nums; }
  .cl-odds-table th { font-weight: 600; font-size: .75rem; text-transform: uppercase;
    letter-spacing: .05em; color: var(--cl-text-2); text-align: right;
    padding: .3rem .35rem; background: var(--cl-bg-2);
    border-bottom: 1px solid var(--cl-line-2); overflow-wrap: anywhere; }
  .cl-odds-table td { text-align: right; padding: .38rem .35rem;
    vertical-align: top; color: var(--cl-text-0); font-family: var(--cl-font-num);
    border-top: 1px solid var(--cl-line-1); overflow-wrap: anywhere; }
  .cl-odds-table th:first-child, .cl-odds-table td:first-child { text-align: left; }
  .cl-odds-table td:first-child { font-family: var(--cl-font);
    color: var(--cl-text-1); }
  /* Column 2 is the model column (odds_comparison_card emits it second). */
  .cl-odds-table th:nth-child(2) { color: var(--cl-accent);
    box-shadow: inset 1px 0 0 var(--cl-accent-line); }
  .cl-odds-table td:nth-child(2) { color: var(--cl-accent);
    background: var(--cl-accent-wash);
    box-shadow: inset 1px 0 0 var(--cl-accent-line); }
  .cl-odds-table .cl-odds-sub { display: block; font-size: .75rem;
    font-weight: 400; color: var(--cl-text-2); }
  .cl-odds-table .cl-odds-na { color: var(--cl-text-2); }

  /* ---------- notices ---------- */
  .cl-note {
    border: 1px solid var(--cl-line-1); border-left: 2px solid var(--cl-warn);
    background: var(--cl-note-warn); color: var(--cl-text-0);
    border-radius: var(--cl-r-sm); padding: .5rem .7rem; font-size: .8125rem;
    line-height: 1.5; margin: .4rem 0 .8rem;
  }
  .cl-note.cl-info { border-left-color: var(--cl-accent);
    background: var(--cl-note-info); }

  /* ---------- phones ---------- */
  /* Must stay AFTER both token blocks: it redefines the padding tokens, and
     every band is written as calc(-1 * var(--cl-pad-x)), so the bands
     re-tighten by themselves. */
  @media (max-width: 640px) {
    :root { --cl-pad-x: .7rem; --cl-pad-t: .6rem; --cl-pad-b: .7rem; }
    .cl-grid { grid-template-columns: 1fr; gap: .6rem; }
    .cl-odds-grid { gap: .6rem; }
    .cl-badge { width: 2.2rem; height: 2.2rem; font-size: .68rem; }
    .cl-hero .cl-vs { margin-top: .5rem; }
    .cl-section { margin-top: 1.5rem; }
    .block-container { padding-left: .8rem; padding-right: .8rem; }
  }
  @media (max-width: 420px) {
    .cl-row { grid-template-columns: 1fr auto 1fr; }
    .cl-row .cl-date { grid-column: 1 / -1; }
    .cl-odds-table td, .cl-odds-table th { padding-left: .22rem;
      padding-right: .22rem; }
  }
</style>
"""
