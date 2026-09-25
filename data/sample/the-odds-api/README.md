# The Odds API – sample fetches

Two fetches in the shape documented for The Odds API v4
(`GET /v4/sports/soccer_uefa_champs_league/odds?regions=eu&markets=h2h`), for
matchday 2 of the committed fixture list. Unlike the football-data.org and
Open-Meteo samples they were **not recorded from the live API**: registering
for a key is a personal step, so the files were generated from the documented
schema so that `make run-samples` and the tests exercise the full odds path
offline. **Every price is fictional** and must not be read as a market.

What the files deliberately contain:

* `…_2026-09-21T120000Z.json` – first fetch: 18 events, four bookmakers, all
  markets complete. The fetch time is in the file name; it becomes
  `raw.odds_api.ingested_at`, which keeps replays idempotent.
* `…_2026-09-22T080000Z.json` – second fetch, 20 h later: three events
  re-priced (their `last_update` moved), one bookmaker gone for one event
  (withdrawn market → `is_current = false`), one market with two outcomes
  (away price suspended → `is_complete = false`). Everything else unchanged, so the
  curated change history has both "same quote seen again" and "new quote".

Team names use bookmaker spellings on purpose ("Bayern Munich", "Inter
Milan", "Sporting Lisbon"), so the name matcher and
`data/reference/bookmaker_team_aliases.csv` are exercised.

A real key (free, 500 credits a month: <https://the-odds-api.com>) goes into
`.env` as `ODDS_API_KEY`; `make odds` then fetches a real state next to these.
