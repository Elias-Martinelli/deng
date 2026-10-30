# Dated squad, coach and team-value context

## Current coverage and missing performance history

See [training-data-gaps.md](training-data-gaps.md) for measured squad/coach coverage and source requirements. Individual player match-performance statistics are not yet ingested; the context CSV accepts aggregate context, not those detailed statistics.

The current football-data.org team payloads provide squads/coaches when included
in the account response. Individual players are retained in
`staging.team_player_snapshot`; match rows contain aggregate characteristics.
Optional `FOOTBALL_DATA_TEAM_DETAILS=true` requests `/teams/{id}` for the distinct
current teams, costing one extra request per club. It does not unlock paid fields.

Source schema: [football-data.org team resource](https://docs.football-data.org/general/v4/team.html).

## Historical values

Today's squad or market value cannot safely fill a match in 2023. Supply a
licensed dated extract via `TEAM_CONTEXT_CSV_PATH`. The pipeline retains the CSV
and normalized records in `raw.team_context_import`, idempotently by SHA-256.

Required columns:

| Column | Meaning |
|---|---|
| team_id | Exact football-data.org team ID; resolve provider IDs explicitly |
| observed_at | When the information was available, with UTC offset |
| valid_from | When it became applicable, with UTC offset |
| source | Provider/archive name |
| source_url | Evidence or licensed source reference for this observation |

Optional columns: `valid_until`, `squad_size`, `squad_avg_age`,
`squad_min_age`, `squad_max_age`, `squad_nationalities`,
`squad_foreign_players`, `squad_goalkeepers`, `squad_defenders`,
`squad_midfielders`, `squad_attackers`, `squad_unknown_positions`,
`squad_missing_birthdates`, `coach_namespace`, `coach_id`, `coach_name`,
`coach_birth_date`, `coach_nationality`, `coach_tenure_start`,
`squad_market_value_eur`.

Use blank for missing, not zero. At least squad_size, coach_id or valuation is
required. Coach IDs require namespace and name. Dates use YYYY-MM-DD.
All timestamps need a timezone. EUR values must be finite and nonnegative.
Counts must fit the squad size. The entire file is validated before writing.

[Empty template](../data/reference/team_context_template.csv)

```bash
TEAM_CONTEXT_CSV_PATH=/path/to/licensed-snapshots.csv .venv/bin/python -m deng.pipeline ingest --only team-context
make transform
make dq
make export
```

Keep evidence for claimed historical observation timestamps; the importer cannot
independently verify a provider archive. No market-value provider or API key is
configured automatically, and no market value is fabricated.

## Join and coach statistics

Each match chooses the newest eligible squad, coach and valuation separately:
observed_at < kickoff, valid_from <= kickoff, kickoff < valid_until when supplied.
API observations use receipt time and exclude season-filtered team payloads.

A contract start month does not prove a coach appointment date. Exact tenure
requires coach_tenure_start; observed tenure is the lower bound since this coach
was first seen, after any observed different coach at that club.
Prior coach matches/rates use only covered games with an eligible pre-match
coach assignment and a known 90-minute result more than three hours earlier.
These are covered-history statistics, not full career statistics.

Missing values remain NULL. New sources can use this explicit dated contract;
an additional API is useful only if it supplies suitable coverage and provenance.

For Docker, place local extracts under ignored data/context/ and use a relative path such as data/context/licensed-snapshots.csv. Compose mounts that directory read-only; data/processed/ persists container exports.

New raw receipt times use the wall clock, even during long database transactions.
API squad/coach availability is conservatively bounded by the completed ingestion
batch, also protecting older raw rows written with transaction-start timestamps.
