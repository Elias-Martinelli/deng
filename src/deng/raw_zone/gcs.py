"""The raw zone in Google Cloud Storage: one object per API answer per day.

The object name is a function of the same business key that makes the
PostgreSQL raw zone idempotent (`UNIQUE (source, endpoint, request_params,
ingestion_date)` on raw.football_data):

    raw/source=<source>/endpoint=<endpoint>/ingestion_date=<YYYY-MM-DD>/<key>.json

`<key>` is a hash of source, endpoint and request parameters. A rerun of the
same day therefore writes the same name and overwrites its own object; it can
never add a second one next to it.

Why not `<run_id>.json`, as ADR-003 first sketched: the run id is new on every
run, so a rerun would add a near-duplicate - exactly what the Postgres unique
key exists to prevent. The run id is still recorded, inside the object and in
its metadata; it just does not decide the name.

The directories are Hive-style partitions (`key=value`), which is what a
BigQuery external table or load job with hive partitioning reads, so a query
for one day or one endpoint only touches that prefix.

The body is one line of JSON - newline-delimited JSON, the format BigQuery
loads - holding the same envelope as a raw.football_data row: provenance, the
payload hash, the record count and the payload itself, unchanged.

No local intermediate: the bytes go from the parsed HTTP answer in memory into
one upload request. Nothing is written to disk on the way.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any, Protocol

from deng.database.raw_loader import LoadResult, count_records, hash_payload

logger = logging.getLogger(__name__)

OBJECT_PREFIX = "raw"
CONTENT_TYPE = "application/json"
# Anything else in a partition value is replaced: GCS would accept it, but a
# space or a parenthesis in a path is a quoting problem in every shell and in
# BigQuery's hive-partition parser.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class Blob(Protocol):
    """The part of `google.cloud.storage.Blob` this writer uses."""

    metadata: dict[str, str] | None

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        """Upload `data` as the object's whole content."""


class Bucket(Protocol):
    """The part of `google.cloud.storage.Bucket` this writer uses."""

    name: str

    def blob(self, blob_name: str) -> Blob:
        """A handle to an object; makes no request."""

    def get_blob(self, blob_name: str) -> Blob | None:
        """The object with its metadata, or None when it does not exist."""


def partition_value(value: str) -> str:
    """A path-safe form of a source or endpoint name.

    `competitions/CL/matches` -> `competitions.CL.matches` (a slash would open
    a new directory level), `football-data.org (sample)` ->
    `football-data.org-sample`. The exact value is kept in the object itself.
    """
    safe = _UNSAFE.sub("-", value.replace("/", ".")).strip("-.")
    if not safe:
        raise ValueError(f"cannot build a GCS partition value from {value!r}")
    return safe


def key_hash(source: str, endpoint: str, request_params: dict[str, Any]) -> str:
    """The object's file name: a hash of the business key without the date.

    Over the exact values, not the path-safe ones, so two keys that happen to
    share a partition value (`a/b` and `a.b`) still get two objects. Keys of
    `request_params` are sorted: `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` are
    the same question, as they are in the JSONB unique key.
    """
    canonical = json.dumps(
        {"source": source, "endpoint": endpoint, "request_params": request_params},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def object_name(
    source: str, endpoint: str, request_params: dict[str, Any], ingestion_date: date
) -> str:
    """Where one answer of one day lives in the bucket."""
    return (
        f"{OBJECT_PREFIX}"
        f"/source={partition_value(source)}"
        f"/endpoint={partition_value(endpoint)}"
        f"/ingestion_date={ingestion_date.isoformat()}"
        f"/{key_hash(source, endpoint, request_params)}.json"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GcsRawWriter:
    """Writes API payloads as objects into the raw-zone bucket.

    Same call and same result as `RawLoader.load`, so the ingestion does not
    know which raw zone it writes to (src/deng/raw_zone/writer.py).
    """

    def __init__(
        self,
        bucket: Bucket,
        source: str = "football-data.org",
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Create a writer for one bucket and one source."""
        self.bucket = bucket
        self.source = source
        self._now = now

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
        """Write one payload for one ingestion date; overwrite that day's object.

        Returns:
            INSERTED for a new object, UPDATED when the stored answer differed,
            UNCHANGED when it was the same answer again. As in Postgres, the
            object is written in every case, so it names the last run that saw it.

        Raises:
            google.api_core.exceptions.GoogleAPIError: when GCS refuses the write
                (missing bucket, missing permission) or keeps failing after the
                library's retries. The run fails; nothing is swallowed.
        """
        name = object_name(self.source, endpoint, request_params, ingestion_date)
        payload_hash = hash_payload(payload)
        record_count = count_records(payload)

        existing = self.bucket.get_blob(name)
        previous_hash = (existing.metadata or {}).get("payload_hash") if existing else None

        body = (
            json.dumps(
                {
                    "source": self.source,
                    "endpoint": endpoint,
                    "request_params": request_params,
                    "request_url": request_url,
                    "ingestion_date": ingestion_date.isoformat(),
                    "ingested_at": self._now().isoformat(),
                    "run_id": str(run_id),
                    "payload_hash": payload_hash,
                    "record_count": record_count,
                    "payload": payload,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )

        blob = self.bucket.blob(name)
        # Object metadata: what the next run compares against (and what
        # `gcloud storage objects describe` shows) without downloading the body.
        blob.metadata = {
            "source": self.source,
            "endpoint": endpoint,
            "ingestion_date": ingestion_date.isoformat(),
            "run_id": str(run_id),
            "payload_hash": payload_hash,
            "record_count": "" if record_count is None else str(record_count),
        }
        # One request with the whole body; the client library retries transient
        # errors (429, 5xx) by default. No generation precondition on purpose:
        # the write is idempotent (same name, that day's answer), so a retried or
        # concurrent write only replaces the object with an equally valid one -
        # while a precondition would turn the retry of an upload whose first
        # attempt did succeed into a false "412 Precondition Failed".
        blob.upload_from_string(body.encode("utf-8"), content_type=CONTENT_TYPE)

        inserted = existing is None
        unchanged = not inserted and previous_hash == payload_hash
        result = LoadResult(
            endpoint=endpoint,
            inserted=inserted,
            updated=not inserted and not unchanged,
            unchanged=unchanged,
            record_count=record_count,
            payload_hash=payload_hash,
        )
        logger.info(
            "gcs write gs://%s/%s %s (records=%s, hash=%s)",
            self.bucket.name,
            name,
            result.action,
            record_count,
            payload_hash[:12],
        )
        return result

    def existing_hash(
        self, endpoint: str, request_params: dict[str, Any], ingestion_date: date
    ) -> str | None:
        """The stored payload hash for that business key, if any (metadata only)."""
        blob = self.bucket.get_blob(
            object_name(self.source, endpoint, request_params, ingestion_date)
        )
        return (blob.metadata or {}).get("payload_hash") if blob else None


def bucket_from_settings(project_id: str, bucket_name: str) -> Bucket:
    """Open the raw-zone bucket with Application Default Credentials.

    Imported here, not at module level: google-cloud-storage is the `cloud`
    extra, and a local run without it must not fail on an import it never uses.
    No request is made until the first write.
    """
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise RuntimeError(
            "RAW_TARGETS includes gcs, but google-cloud-storage is not installed. "
            'Install the cloud extra: pip install -c constraints.txt -e ".[cloud]"'
        ) from exc
    client = storage.Client(project=project_id or None)
    return client.bucket(bucket_name)
