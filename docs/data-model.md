# Data model and training contract

## World ranking update — 16 October 2026

The canonical match product now appends twelve world-ranking fields (304 columns total), backed by raw.footballdatabase_pages, raw.footballdatabase_team_map and staging.team_world_ranking. See [field definitions and temporal rules](world-ranking.md).

## Grains and joins

| Relation | Grain / role |
|---|---|
| raw.football_data | Provider, endpoint, request parameters and logical day; raw JSON + receipt time |
| raw.team_context_import | One immutable CSV file hash with original text and normalized rows |
| staging.matches | One provider match ID, typed fixture and separate 90-minute scores |
| staging.teams / curated.dim_team | One provider team ID; descriptive current attributes |
| staging.standings | Season, team, logical date; TOTAL tables only |
| staging.team_context_snapshot | One team observation from API or dated CSV |
| staging.team_player_snapshot | One player in one squad observation |
| curated.fact_match | One fixture; legacy result measures retained for dashboard compatibility |
| curated.match_team_history | Two appearances per fixture; indexed history and cumulative measures |
| curated.team_match_features | One team per fixture; 3/5/10 form, venue/competition form, season, H2H, load |
| curated.fact_match_team_context | One team per fixture; eligible squad, coach and value |
| curated.fact_match_weather | One fixture, forecast or explicit missing status |
| curated.fact_bookmaker_odds | One distinct bookmaker quote change for a fixture |
| curated.match_training_features | **One row per match: canonical data-science product** |
| curated.model_features | Legacy smaller dashboard view, not the canonical training contract |

Provider IDs link leagues, seasons and clubs. No fuzzy cross-provider player or
coach matching is used. A CSV must contain an explicit football-data.org team ID.
Coach IDs are namespaced.

## Feature families

Both teams have rolling 3/5/10 regular-time counts, wins/draws/losses, points,
goals, clean sheets, no-score counts, both-teams-scored and over-2.5 counts,
per-match rates; home/away and competition-specific last-five statistics;
within-competition season totals; prior five meetings; rest and 7/14/30-day load.
Difference columns compare the teams. Counts expose sample size; rates stay NULL
without observations.

Squad/coach/value, weather and odds are separate timestamp-constrained joins.
Their missingness is part of the product. Labels and audit fields are visibly
separated and excluded from the export feature list.

## Target and time

`label_outcome_90min` = HOME_WIN / DRAW / AWAY_WIN after 90 minutes plus stoppage
time. Extra time and shootouts are excluded. Unplayed or ambiguous fixtures have
NULL labels. Training code must filter labels explicitly.

History uses completed fixtures more than three hours before kickoff.
This completion proxy reconstructs prior results; it does not reconstruct their
original publication timestamps. Only ingested competitions contribute.

Observed context uses actual source availability/receipt time and validity.
A backfill run date never makes a current observation historical. Current team
names are identifiers/audit, not historical predictive attributes.

## Export contract

`manifest.json` declares target, feature_columns, identifier_columns,
audit_columns, label_columns, row counts, competitions, checksum and provenance.
`data_dictionary.json` exposes SQL types and column descriptions;
`coverage.json` exposes null counts for each field.
CSV columns retain SQL order; rows sort by UTC kickoff then match ID.

Use chronological splits. Do not random-split repeated team history, fit
preprocessing on the full dataset, or treat missing values as measured zero.
Fixed prediction-horizon snapshots and BigQuery partitioning remain planned.
