# Sample data

Small, committed API answers, one folder per source. The football ones come from
`make explore` (`scripts/explore_football_api.py`); the Open-Meteo and
OpenStreetMap ones are real answers kept from a live run, and the odds ones
follow the documented schema with fictional prices
([why](the-odds-api/README.md)). They document the real source schema, serve as
fixtures for unit tests, and are what `--from-samples` replays. Keep every file well below 1 MB; full raw data
lives in `data/raw/` (git-ignored) locally and in Google Cloud Storage in the
final architecture.
