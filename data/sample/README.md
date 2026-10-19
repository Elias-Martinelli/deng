# Sample data

Small, committed API answers, one folder per source. The football ones come from
`make explore` (`scripts/explore_football_api.py`); the Open-Meteo and
OpenStreetMap ones are real answers kept from a live run, and the odds ones
follow the documented schema with fictional prices
([why](the-odds-api/README.md)). They document the real source schema, serve as
fixtures for unit tests, and are what `--from-samples` replays. Keep every file well below 1 MB; full raw data
lives in `data/raw/` (git-ignored) locally and in Google Cloud Storage in the
final architecture.

## Replaying them

The answers are a snapshot from 20-22 September 2026: the football payloads
from 20 Sep, the forecast from 21 Sep, the odds fetches from 21 and 22 Sep. A
sample run therefore replays the scheduled 06:00 run of **23 September 2026**
(`deng.clock.SAMPLES_DATE`), the first one that already knows every sample.
Its clock is pinned to that moment for the whole `run --from-samples`, in Python
and in SQL (`meta.pipeline_now()`), so the result does not depend on the day
someone runs it. `--date` replays another day; `make ingest-samples` followed
by a separate `make transform` judges the replayed answers by today's clock.

There are no crest images here: a sample run downloads nothing, so the crest
check stays a WARNING and the dashboard shows the three-letter codes.
