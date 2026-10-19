"""A sample run is a replay: offline, and judged by its own day, not by today.

Before, `make run-samples` downloaded crests and compared the September
snapshot with the wall clock, so its data-quality result changed with the day
it was run. These tests would fail again on any day after the snapshot's next
kick-off (13 Oct 2026) if the replay read the wall clock.
"""

from datetime import date

import pytest
import requests

from deng import clock, pipeline
from deng.database import connect

pytestmark = pytest.mark.postgres


def scalar(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def test_pipeline_now_follows_the_replay_and_only_the_replay(connection):
    with clock.replaying(date(2026, 9, 23)) as pinned, connect() as replay:
        assert scalar(replay, "SELECT meta.pipeline_now()") == pinned
    with connect() as live:
        assert scalar(live, "SELECT meta.pipeline_now() = now()") is True
    # Another session is never affected by a replay.
    assert scalar(connection, "SELECT meta.pipeline_now() = now()") is True


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly on any HTTP request - a sample run must make none."""

    def refuse(self, request, **kwargs):
        raise AssertionError(f"a sample run requested {request.url}")

    monkeypatch.setattr(requests.Session, "send", refuse)


def test_a_sample_run_is_offline_and_judged_by_its_own_day(connection, no_network):
    assert pipeline.command_run(clock.SAMPLES_DATE, from_samples=True) == 0

    replayed = clock.scheduled_moment(clock.SAMPLES_DATE)
    upcoming = scalar(connection, "SELECT count(*) FROM curated.fact_match WHERE is_upcoming")
    stamped_elsewhen = scalar(
        connection,
        "SELECT count(*) FROM curated.fact_match_prediction WHERE predicted_at <> %s",
        (replayed,),
    )
    missing = scalar(
        connection,
        "SELECT count(*) FROM curated.fact_match_weather WHERE weather_status = 'MISSING'",
    )
    # Every unplayed fixture of the snapshot is still to come on 23 Sep, every
    # forecast is computed at the replayed 06:00, and nothing is due inside the
    # forecast horizon, so no forecast can be missing.
    assert (upcoming, stamped_elsewhen, missing) == (126, 0, 0)
    failed = {
        row[0]
        for row in connection.execute(
            "SELECT check_name FROM meta.dq_results "
            "WHERE checked_at = (SELECT max(checked_at) FROM meta.dq_results) AND NOT passed"
        )
    }
    # The two WARNINGs a sample run always has: an early-season form window,
    # and no crest images (no sample for an image, no download).
    assert failed == {"form_window_is_well_populated", "every_team_has_a_crest"}
