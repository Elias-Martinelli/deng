"""Pipeline run logging into `meta.pipeline_runs`.

Every execution opens a run row before doing any work and closes it afterwards
with its outcome. A failed run stays visible as FAILED with its error message
instead of disappearing - "the pipeline must make failures visible, not
silently continue" is a rubric requirement, and this is where that is enforced.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from types import TracebackType

import psycopg

logger = logging.getLogger(__name__)


class PipelineRun:
    """Context manager that records one pipeline execution.

    Usage:
        with PipelineRun(conn, "ingest_football", logical_date) as run:
            run.add_counts(extracted=144, loaded=1)

    On a clean exit the row is marked SUCCESS; on an exception it is marked
    FAILED with the exception text, and the exception is re-raised.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        pipeline_name: str,
        logical_date: date,
    ) -> None:
        """Prepare a run; the row is written when the context is entered."""
        self.connection = connection
        self.pipeline_name = pipeline_name
        self.logical_date = logical_date
        self.run_id = uuid.uuid4()
        self.rows_extracted = 0
        self.rows_loaded = 0
        self.rows_updated = 0

    def __enter__(self) -> PipelineRun:
        """Insert the RUNNING row and commit it so it is visible while the run works."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO meta.pipeline_runs (run_id, pipeline_name, logical_date, status)
                VALUES (%s, %s, %s, 'RUNNING')
                """,
                (self.run_id, self.pipeline_name, self.logical_date),
            )
        self.connection.commit()
        logger.info(
            "run %s started (pipeline=%s, logical_date=%s)",
            self.run_id,
            self.pipeline_name,
            self.logical_date,
        )
        return self

    def add_counts(self, extracted: int = 0, loaded: int = 0, updated: int = 0) -> None:
        """Accumulate row counts reported by the loader."""
        self.rows_extracted += extracted
        self.rows_loaded += loaded
        self.rows_updated += updated

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Close the run row with SUCCESS or FAILED; never swallow the exception."""
        status = "SUCCESS" if exc is None else "FAILED"
        message = None if exc is None else f"{exc_type.__name__}: {exc}"[:2000]
        try:
            # A failed run may have left the transaction broken - roll back first
            # so that writing the outcome itself cannot fail.
            if exc is not None:
                self.connection.rollback()
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE meta.pipeline_runs
                       SET finished_at = now(), status = %s, error_message = %s,
                           rows_extracted = %s, rows_loaded = %s, rows_updated = %s
                     WHERE run_id = %s
                    """,
                    (
                        status,
                        message,
                        self.rows_extracted,
                        self.rows_loaded,
                        self.rows_updated,
                        self.run_id,
                    ),
                )
            self.connection.commit()
        except psycopg.Error:  # pragma: no cover - only on a broken connection
            logger.exception("could not record the outcome of run %s", self.run_id)
        logger.info(
            "run %s finished: %s (extracted=%s, loaded=%s, updated=%s)",
            self.run_id,
            status,
            self.rows_extracted,
            self.rows_loaded,
            self.rows_updated,
        )
        return False  # never suppress the exception
