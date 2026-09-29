# Reference data

Small, versioned files the pipeline joins against. Reviewed like code.

## bookmaker_team_aliases.csv

Spellings the bookmakers use for a club, where they are too far from the club's
own name for the automatic matching (`deng.transformation.odds_matching`). One
row per alias, with the club id it belongs to. When the data-quality check
`odds_events_resolved_to_fixtures` reports an unmatched event, the fix is a new
row here - not a lower matching threshold.

## Stadium coordinates are no longer a file

They used to live in `venues.csv`, built by a script that was run by hand.
OpenStreetMap is now a source of the pipeline like any other
(`deng.sources.openstreetmap`): the answers are stored in `raw.osm_venues`, and
`sql/transform/305_staging_venues.sql` turns them into `staging.venues`.

* Look them up again (once per season): `make venues`
* Offline, and for peer reviewers without network: the committed answers in
  `data/sample/openstreetmap/` are replayed with `--from-samples`.
* Coordinates © OpenStreetMap contributors,
  [ODbL](https://opendatacommons.org/licenses/odbl/).
