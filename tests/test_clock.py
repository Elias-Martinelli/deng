"""The pipeline clock: a sample run replays its day instead of reading the wall clock."""

from datetime import date, datetime

import pytest

from deng import clock
from deng.config import get_settings
from deng.ingestion import runner
from deng.pipeline import default_date


def test_scheduled_moment_is_six_in_zurich():
    moment = clock.scheduled_moment(date(2026, 9, 23))
    assert moment.isoformat() == "2026-09-23T06:00:00+02:00"  # CEST
    assert clock.scheduled_moment(date(2026, 12, 1)).utcoffset().total_seconds() == 3600


def test_replaying_pins_now_and_today_and_restores_them():
    assert clock.pinned_moment() is None
    with clock.replaying(date(2026, 9, 23)) as pinned:
        assert clock.pipeline_now() == pinned == clock.pinned_moment()
        assert clock.pipeline_today() == date(2026, 9, 23)
        with clock.replaying(date(2026, 9, 30)):
            assert clock.pipeline_today() == date(2026, 9, 30)
        assert clock.pipeline_today() == date(2026, 9, 23)
    assert clock.pinned_moment() is None
    assert abs((clock.pipeline_now() - datetime.now(clock.PIPELINE_TZ)).total_seconds()) < 60


def test_replaying_restores_the_clock_after_an_error():
    with pytest.raises(RuntimeError), clock.replaying(date(2026, 9, 23)):
        raise RuntimeError
    assert clock.pinned_moment() is None


def test_a_sample_run_defaults_to_the_samples_day_not_today():
    assert default_date(None, from_samples=True) == clock.SAMPLES_DATE
    assert default_date(None, from_samples=False) == clock.pipeline_today()
    assert default_date(date(2026, 10, 1), from_samples=True) == date(2026, 10, 1)


def test_samples_day_comes_after_every_committed_sample():
    # The replayed 06:00 run must already "know" every sample, the newest being
    # the odds fetch of 22 Sep 08:00 UTC; and no fixture of the snapshot may be
    # due inside the 16-day weather horizon, for which no sample exists.
    assert clock.scheduled_moment(clock.SAMPLES_DATE) > datetime.fromisoformat(
        "2026-09-22T08:00:00+00:00"
    )


def test_a_sample_run_does_not_download_crests(monkeypatch):
    def no_download(*args, **kwargs):
        raise AssertionError("a sample run must not request a crest")

    monkeypatch.setattr(runner.club_crests, "fetch_crests", no_download)
    context = runner.Context(None, clock.SAMPLES_DATE, get_settings(), from_samples=True)
    result = runner._crests(context, run_id=None)
    assert result.summary.startswith("skipped")
    assert not result.failed
