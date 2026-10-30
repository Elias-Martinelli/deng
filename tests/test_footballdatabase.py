"""Ranking parser, identity and capture-time safeguards."""

from datetime import date

import pytest
from psycopg.types.json import Jsonb

from deng.config import Settings
from deng.sources.footballdatabase import ingest, parse_page, resolve_teams

HTML = """<h5>Updated after matches played on
<span itemprop="dateModified">11 October 2026</span></h5>
<table><tr><td class="rank">1</td><td><a href="/clubs-ranking/alpha">Alpha &amp; City</a>
<a href="/ranking/england/1">England</a></td><td>2000</td><td>9<div>1000</div></td></tr>
<tr><td>2</td><td><a href="/clubs-ranking/beta">Beta FC</a><a href="/ranking/spain/1">Spain</a>
</td><td>1900</td><td>2<div>1200</div></td></tr></table>"""


def test_parser_uses_current_points_and_decodes_entities():
    day, rows, last = parse_page(HTML, 1)
    assert day == date(2026, 10, 11) and last == 1
    assert rows[0] == dict(
        club_slug="alpha",
        club_name="Alpha & City",
        country="England",
        world_rank=1,
        rating_points=2000,
    )
    assert rows[1]["rating_points"] == 1900


@pytest.mark.parametrize(
    "html,page",
    [
        ("<html>Access denied</html>", 1),
        (HTML, 2),
        (HTML.replace("2000", "-5"), 1),
        (HTML.replace("/beta", "/alpha"), 1),
    ],
)
def test_parser_fails_closed_on_changed_layout_or_invalid_rows(html, page):
    with pytest.raises(ValueError):
        parse_page(html, page)


def test_mapping_requires_unique_exact_country_or_reviewed_identity():
    rankings = parse_page(HTML, 1)[1]
    clubs = [
        dict(team_id=1, name="Alpha & City FC", country="England"),
        dict(team_id=2, name="Beta FC", country="England"),
        dict(team_id=3, name="Other Club", country="Spain"),
    ]
    assert resolve_teams(clubs, rankings, {}, {}) == {1: ("alpha", "EXACT_COUNTRY")}
    assert resolve_teams(clubs, rankings, {3: "beta"}, {})[3] == ("beta", "REVIEWED")
    clubs.append(dict(team_id=4, name="Alpha & City", country="England"))
    assert resolve_teams(clubs, rankings, {}, {}) == {}
    with pytest.raises(ValueError, match="one team"):
        resolve_teams(clubs, rankings, {1: "alpha", 4: "alpha"}, {})


@pytest.mark.postgres
def test_same_day_rerun_reuses_pages_and_keeps_first_capture(connection, run_id, monkeypatch):
    monkeypatch.setattr("deng.sources.footballdatabase.pipeline_today", lambda: date(2026, 10, 16))

    class Response:
        status_code = 200
        text = HTML

    class Session:
        calls = 0

        def get(self, url, timeout):
            self.calls += 1
            return Response()

    session = Session()
    settings = Settings(_env_file=None, footballdatabase_max_pages=1)
    ingest(connection, date(2026, 10, 16), run_id, settings, session=session)
    before = connection.execute(
        "SELECT raw_id, observed_at FROM raw.footballdatabase_pages"
    ).fetchall()
    ingest(connection, date(2026, 10, 16), run_id, settings, session=session)
    assert session.calls == 1
    assert (
        connection.execute("SELECT raw_id, observed_at FROM raw.footballdatabase_pages").fetchall()
        == before
    )
    monkeypatch.setattr("deng.sources.footballdatabase.pipeline_today", lambda: date(2026, 10, 17))
    ingest(connection, date(2026, 10, 17), run_id, settings, session=session)
    assert session.calls == 2
    assert (
        connection.execute("SELECT raw_id, observed_at FROM raw.footballdatabase_pages").fetchall()
        == before
    )
    result = ingest(connection, date(2025, 1, 1), run_id, settings, session=session)
    assert "cannot backfill" in result.reason and session.calls == 2


@pytest.mark.postgres
def test_match_ranking_excludes_post_kickoff_and_stale_observations(connection, run_id):
    for team in [1, 2]:
        connection.execute(
            "INSERT INTO curated.dim_team(team_id,name,has_domestic_coverage) VALUES(%s,%s,true)",
            (team, f"Team {team}"),
        )
    kickoffs = ["2026-10-10T15:00Z", "2026-10-17T15:00Z", "2026-12-01T15:00Z"]
    for match, kickoff in enumerate(kickoffs, 1):
        connection.execute(
            """INSERT INTO staging.matches
            (match_id,season_id,competition_code,utc_kickoff,status,stage,
             home_team_id,away_team_id,ingestion_date)
            VALUES(%s,2026,'PL',%s,'TIMED','REGULAR_SEASON',1,2,'2026-10-16')""",
            (match, kickoff),
        )
    rows = parse_page(HTML, 1)[1]
    connection.execute(
        """INSERT INTO raw.footballdatabase_pages
        (page,ranking_date,observed_at,ingestion_date,request_url,payload_hash,html,payload,run_id)
        VALUES(1,'2026-10-11','2026-10-16T12:00Z','2026-10-16',%s,'test',%s,%s,%s)""",
        ("https://footballdatabase.com/ranking/world/1", HTML, Jsonb(rows), run_id),
    )
    for team, slug in [(1, "alpha"), (2, "beta")]:
        connection.execute(
            "INSERT INTO raw.footballdatabase_team_map VALUES(%s,%s,'REVIEWED',now())", (team, slug)
        )
    from deng.transformation.runner import run_transformations

    connection.commit()
    order = tuple(
        "transform/" + name
        for name in [
            "220_fact_match.sql",
            "460_team_world_ranking.sql",
            "500_match_training_features.sql",
        ]
    )
    run_transformations(connection, date(2026, 10, 16), order=order, counted=())
    result = connection.execute(
        "SELECT match_id,home_world_rank,away_world_rank,home_world_rating_points,"
        "world_rating_points_difference,world_rank_advantage_home "
        "FROM curated.match_training_features ORDER BY match_id"
    ).fetchall()
    assert result == [
        (1, None, None, None, None, None),
        (2, 1, 2, 2000, 100, 1),
        (3, None, None, None, None, None),
    ]
    # A later correction cannot overwrite a snapshot that was known before this match.
    connection.execute("UPDATE raw.footballdatabase_pages SET observed_at='2026-10-18T12:00Z'")
    connection.commit()
    run_transformations(connection, date(2026, 10, 18), order=order, counted=())
    assert (
        connection.execute(
            "SELECT count(*) FROM curated.match_training_features WHERE home_world_rank IS NOT NULL"
        ).fetchone()[0]
        == 0
    )
