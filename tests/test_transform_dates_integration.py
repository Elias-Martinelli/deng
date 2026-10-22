"""`transform` must never "succeed" on a day that holds no answers.

A sample ingest stores its answers under the samples' own day (23 Sep), while a
plain `transform` defaults to today. Run one after the other, as the README
lists them, the transformation found nothing, wrote zero rows and still said
OK. These tests pin both halves of the fix: the empty day fails loudly, and the
sample steps run one by one give what `run --from-samples` gives.
"""

import pytest
import requests

from deng import clock, pipeline

pytestmark = pytest.mark.postgres


def scalar(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly on any HTTP request - a sample run must make none."""

    def refuse(self, request, **kwargs):
        raise AssertionError(f"a sample run requested {request.url}")

    monkeypatch.setattr(requests.Session, "send", refuse)


def test_transform_on_an_empty_day_fails_and_names_the_newest_day(connection, no_network, capsys):
    assert pipeline.command_ingest(clock.SAMPLES_DATE, from_samples=True) == 0

    assert pipeline.main(["transform", "--date", "2026-10-22"]) == 1

    error = capsys.readouterr().err
    assert "no football answers are stored for 2026-10-22" in error
    assert str(clock.SAMPLES_DATE) in error
    status, message = connection.execute(
        "SELECT status, error_message FROM meta.pipeline_runs "
        "WHERE pipeline_name = 'transform_curated' AND logical_date = '2026-10-22'"
    ).fetchone()
    # Visible, never silent: the run log carries the failure and its reason.
    assert status == "FAILED"
    assert "NothingToTransform" in message
    assert scalar(connection, "SELECT count(*) FROM curated.fact_match") == 0


def test_the_sample_steps_one_by_one_equal_the_one_step_run(connection, no_network):
    assert pipeline.main(["ingest", "--from-samples"]) == 0
    assert pipeline.main(["transform", "--from-samples"]) == 0
    assert pipeline.main(["dq", "--from-samples"]) == 0

    matches = scalar(connection, "SELECT count(*) FROM curated.fact_match")
    upcoming = scalar(connection, "SELECT count(*) FROM curated.fact_match WHERE is_upcoming")
    # The same figures test_sample_replay_integration asserts for `run
    # --from-samples`: 144 league-phase matches, 126 of them still to come on
    # the replayed 23 Sep - only true if transform ran on the replayed clock.
    assert (matches, upcoming) == (144, 126)
    failed = {
        row[0]
        for row in connection.execute(
            "SELECT check_name FROM meta.dq_results "
            "WHERE checked_at = (SELECT max(checked_at) FROM meta.dq_results) AND NOT passed"
        )
    }
    assert failed == {"form_window_is_well_populated", "every_team_has_a_crest"}
