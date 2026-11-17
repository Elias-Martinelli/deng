"""One interface for every raw zone: PostgreSQL locally, GCS in the cloud.

The ingestion asks for a writer and calls `load(...)`; which raw zones the
answer lands in is configuration (`RAW_TARGETS`), not code:

    RAW_TARGETS=postgres        the local raw zone only (default)
    RAW_TARGETS=postgres,gcs    the same answer also goes to the bucket

Why PostgreSQL stays in every combination for now: the sources after football
plan their work from the raw zone (raw.match_calendar, raw.team_catalog), and
the transformation reads it. Both are PostgreSQL today. A GCS-only run would
store the football answers and then find no matches to ask the weather about.
Once the BigQuery path reads the raw zone from GCS (backlog EPIC 10), GCS on
its own becomes a valid target and the check in config.py goes.

Order and failure: PostgreSQL first, inside the run's transaction, then GCS.
A GCS failure raises, so the run fails and the transaction rolls back - a
configured raw zone that silently misses answers would be worse than a failed
run. The reverse case (objects written, then the commit fails) leaves GCS with
answers PostgreSQL does not have; the rerun writes the same object names again,
so the two converge without duplicates.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Protocol

import psycopg

from deng.config import Settings
from deng.database.raw_loader import LoadResult, RawLoader
from deng.raw_zone import gcs


class RawWriter(Protocol):
    """What the ingestion needs from a raw zone."""

    def load(
        self,
        *,
        run_id: uuid.UUID,
        endpoint: str,
        request_params: dict[str, Any],
        request_url: str,
        payload: dict[str, Any],
        ingestion_date: date,
    ) -> LoadResult:
        """Store one answer for one day, idempotently."""


class FanOutWriter:
    """Writes every answer to a primary raw zone and to its mirrors.

    The primary's result is the one reported, because the primary is what the
    rest of the run reads. Each mirror logs its own action.
    """

    def __init__(self, primary: RawWriter, *mirrors: RawWriter) -> None:
        """Combine one primary writer with any number of mirrors."""
        self.primary = primary
        self.mirrors = mirrors

    def load(self, **kwargs: Any) -> LoadResult:
        """Store the answer in the primary, then in every mirror."""
        result = self.primary.load(**kwargs)
        for mirror in self.mirrors:
            mirror.load(**kwargs)
        return result


def open_raw_writer(
    connection: psycopg.Connection,
    settings: Settings,
    source: str,
    *,
    bucket: gcs.Bucket | None = None,
) -> RawWriter:
    """The writer for the raw zones `settings.raw_target_list` names.

    Args:
        connection: The run's connection; the PostgreSQL writer never commits.
        settings: Reads RAW_TARGETS, GCP_PROJECT_ID and GCS_RAW_BUCKET.
        source: Provenance of the answers, part of the business key.
        bucket: A bucket to write to instead of opening GCS_RAW_BUCKET (tests).
    """
    postgres = RawLoader(connection, source=source)
    if "gcs" not in settings.raw_target_list:
        return postgres
    if bucket is None:
        bucket = gcs.bucket_from_settings(settings.gcp_project_id, settings.gcs_raw_bucket)
    return FanOutWriter(postgres, gcs.GcsRawWriter(bucket, source=source))


def open_mirror(settings: Settings, *, bucket: gcs.Bucket | None = None) -> gcs.GcsRawZone | None:
    """The GCS raw zone the other sources mirror their rows into, or None.

    Weather, odds and stadium answers have their own tables and business keys,
    so they keep their own SQL and call `mirror.put(...)` next to it, with the
    same key. The caller opens the mirror once per run and passes it on; None
    (RAW_TARGETS=postgres) means "PostgreSQL only", which is every source's default.
    """
    if "gcs" not in settings.raw_target_list:
        return None
    if bucket is None:
        bucket = gcs.bucket_from_settings(settings.gcp_project_id, settings.gcs_raw_bucket)
    return gcs.GcsRawZone(bucket)
