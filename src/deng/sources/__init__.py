"""One module per data source, all with the same shape.

    football_data.py   fixtures, results, teams, standings   (football-data.org)
    open_meteo.py      hourly weather forecast               (Open-Meteo)
    the_odds_api.py    bookmaker 1X2 odds                    (The Odds API)
    openstreetmap.py   stadium coordinates                   (OpenStreetMap)
    club_crests.py     club crest images                     (football-data.org CDN)

Every module answers the same two questions:

    plan(...)    what should I fetch today?
    fetch(...)   how do I fetch one of those?

Storing the answer, logging the run and the order of the sources are not their
business - that is `deng.ingestion`. And no source reads staging or curated
tables: the ingestion runs before any transformation (tests/test_layering.py).
"""
