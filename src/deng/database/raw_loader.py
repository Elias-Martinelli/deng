"""Idempotent loading of API payloads into the raw zone.

The central property, and the one most likely to be asked about in the defence:
running the same pipeline twice for the same day must not change the result.
This is achieved with a business key rather than with "delete everything first":

    UNIQUE (source, endpoint, request_params, ingestion_date)

and `INSERT ... ON CONFLICT DO UPDATE`. A second run for the same day therefore
overwrites that day's payload in place; it never appends a near-duplicate and
never leaves a window in which the table is empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

# Keys under which the football-data.org endpoints carry their main list. Used
# only to record how many records a payload contained - never to reshape it.
RECORD_LIST_KEYS = ("matches", "teams", "standings", "seasons", "resultSet")


@dataclass
class LoadResult:
    """Outcome of loading a single payload.

    Exactly one of `inserted`, `updated`, `unchanged` is true: a new day, a
    changed answer for a day already stored, or the identical answer again.
    """

    endpoint: str
    inserted: bool
    updated: bool
    unchanged: bool
    record_count: int | None
    payload_hash: str

    @property
    def action(self) -> str:
        """Human-readable action for logging and evidence output."""
        if self.inserted:
            return "INSERTED"
        return "UPDATED" if self.updated else "UNCHANGED"


class RawLoader:
    """Writes API payloads into `raw.football_data`.

    The loader never commits: the caller decides the transaction boundary, so a
    whole run's payloads land together or not at all (see command_ingest).
    """

    def __init__(self, connection: psycopg.Connection, source: str = "football-data.org") -> None:
        """Create a loader bound to an open connection."""
        self.connection = connection
        self.source = source

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
        """Insert or update one payload for one ingestion date.

        Args:
            run_id: The run this write belongs to (foreign key into meta.pipeline_runs).
            endpoint: Path of the endpoint, e.g. `competitions/CL/matches`.
            request_params: Query parameters; part of the business key.
            request_url: Full URL, kept for traceability.
            payload: The parsed JSON document, stored unchanged.
            ingestion_date: Logical date of the run.

        Returns:
            A `LoadResult` describing whether the row was inserted, updated, or
            left unchanged because the payload was byte-identical.
        """
        payload_hash = hash_payload(payload)
        record_count = count_records(payload)

        # Jsonb(...) wraps dicts so psycopg sends them as JSONB. request_params is
        # compared as JSONB in the unique key, where {"a":1,"b":2} equals
        # {"b":2,"a":1} - key order cannot create a false "new" row.

        with self.connection.cursor() as cursor:
            # `xmax = 0` is true for a freshly inserted row and non-zero for one
            # that was updated by the conflict clause. It is the cheapest way to
            # learn which branch fired without a second query.
            #
            # The CTE `previous` reads the hash stored *before* this statement:
            # every part of one SQL statement sees the same snapshot, so it cannot
            # see the row the INSERT is about to write. Comparing it with the new
            # hash tells "the source changed today" (UPDATED) apart from "same
            # answer again" (UNCHANGED) - in the same round trip.
            cursor.execute(
                """
                WITH previous AS (
                    SELECT payload_hash
                      FROM raw.football_data
                     WHERE source = %s AND endpoint = %s
                       AND request_params = %s AND ingestion_date = %s
                )
                INSERT INTO raw.football_data
                    (source, endpoint, request_params, request_url, ingestion_date,
                     run_id, payload, payload_hash, record_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, endpoint, request_params, ingestion_date)
                DO UPDATE SET
                    payload      = EXCLUDED.payload,
                    payload_hash = EXCLUDED.payload_hash,
                    record_count = EXCLUDED.record_count,
                    request_url  = EXCLUDED.request_url,
                    run_id       = EXCLUDED.run_id,
                    ingested_at  = now()
                RETURNING (xmax = 0) AS was_inserted,
                          (SELECT payload_hash FROM previous) AS previous_hash
                """,
                (
                    self.source,
                    endpoint,
                    Jsonb(request_params),
                    ingestion_date,
                    self.source,
                    endpoint,
                    Jsonb(request_params),
                    request_url,
                    ingestion_date,
                    run_id,
                    Jsonb(payload),
                    payload_hash,
                    record_count,
                ),
            )
            row = cursor.fetchone()

        was_inserted = bool(row[0])
        unchanged = not was_inserted and row[1] == payload_hash
        result = LoadResult(
            endpoint=endpoint,
            inserted=was_inserted,
            updated=not was_inserted and not unchanged,
            unchanged=unchanged,
            record_count=record_count,
            payload_hash=payload_hash,
        )
        logger.info(
            "raw load %s %s (records=%s, hash=%s)",
            endpoint,
            result.action,
            record_count,
            payload_hash[:12],
        )
        return result

    def existing_hash(
        self, endpoint: str, request_params: dict[str, Any], ingestion_date: date
    ) -> str | None:
        """Return the stored payload hash for that business key, if any.

        Lets a caller detect "the source did not change today" without writing.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload_hash
                  FROM raw.football_data
                 WHERE source = %s AND endpoint = %s
                   AND request_params = %s AND ingestion_date = %s
                """,
                (self.source, endpoint, Jsonb(request_params), ingestion_date),
            )
            row = cursor.fetchone()
        return row[0] if row else None


def hash_payload(payload: dict[str, Any]) -> str:
    """Return a stable sha256 over the payload.

    Keys are sorted so that two semantically identical documents hash equally
    regardless of the order in which the API happened to serialise them.
    """
    # separators without spaces and ensure_ascii=False: one canonical byte
    # representation, so the hash depends on the content only - not on
    # whitespace or on how non-ASCII names (Bodø, Fenerbahçe) are escaped.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def count_records(payload: dict[str, Any]) -> int | None:
    """Return the length of the payload's main list, or None if there is none.

    Purely informational: it makes `SELECT endpoint, record_count` a useful
    verification query without having to open the JSON.
    """
    for key in RECORD_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return None
