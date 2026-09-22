# ADR-004 – Scope: Champions League matches only, free tier only

Status: **ACCEPTED** (2026-09-21)

## Context

Team form can be built from Champions League matches alone or from every
match a club plays. football-data.org's `/teams/{id}/matches` would add
domestic games, but the free tier silently restricts it to its 12 competitions:
25 of the 36 league-phase clubs would get domestic matches, 11 would not
(evidence: `docs/evidence/api-exploration.md` §9). The app showed a warning for
those 11 - which implied the other 25 already had domestic form. They did not:
the endpoint was never ingested (backlog 2.4), so the warning was misleading.

## Decision

The data product covers **Champions League matches only**, from the
**free tier only**. Form, head-to-head and recent results are Champions League
figures for every club. Backlog 2.4 (team matches across competitions) is
dropped.

## Alternatives considered

| Option | Why not |
|---|---|
| Ingest `/teams/{id}/matches` for all 36 clubs | form of 25 clubs would include league games, of 11 would not - two definitions of "form" in one column, compared side by side in the app |
| Same, plus a flag per row | comparable only on paper; a user or model still compares a 5-league-games form with a 1-CL-game form |
| Paid tier | cost, and the course requires free sources |
| A second provider for the missing leagues | a third source to match team identities across, for a SHOULD item |

## Advantages

* One definition of form for all 36 clubs - comparable by construction.
* 36 fewer API calls per day (~4 minutes at 10 requests/minute).
* The UI needs no per-club caveat; one sentence states the scope.

## Disadvantages

* Small windows: at most 8 league-phase matches per club, so early in the
  season `matches_considered` is 0-2. Mitigated by showing the window size
  everywhere; historical seasons (backlog 1.9) are the lever if more depth is
  needed, and they are Champions League data as well.
* Domestic fatigue (a league game three days before) is invisible.
  `days_since_last_match` counts Champions League matches only.

## Consequences

* `dim_team.has_domestic_coverage` stays as a descriptive, measured attribute;
  nothing is derived from it.
* The architecture v0.1 sequence step `GET teams/{id}/matches (36×)` is removed
  in v0.2.
