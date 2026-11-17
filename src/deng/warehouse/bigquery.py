"""The warehouse in BigQuery: run the SQL under sql/bigquery/ against the dataset.

Three stages, one folder each, every file one statement, run in file-name
order - the same convention as the PostgreSQL side:

    schema/     the external table over the bucket, then the tables (`bq-init`)
    transform/  raw -> staging -> curated, every file a MERGE (`bq-transform`)
    verify/     checks that return (check_name, failures) (`bq-verify`)

Two kinds of values go into the SQL, and they are kept apart on purpose:

* Identifiers (project, dataset, bucket) are written as {{project}} etc. and
  substituted here, because BigQuery cannot take a table name as a parameter.
  They come from the settings and are validated against strict patterns
  first, so no setting can smuggle SQL into a statement.
* Values (@logical_date, @pipeline_now) are real query parameters: BigQuery
  binds them, nothing is pasted into the text. A statement gets exactly the
  parameters it names.

`dry_run=True` sends every statement to BigQuery for validation and a cost
estimate without running it - the first thing to try against a fresh dataset.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from deng.config import Settings
from deng.files import project_file

logger = logging.getLogger(__name__)

STAGES = ("schema", "transform", "verify")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
PARAMETER = re.compile(r"@([a-z_]+)\b")
# GCP's own naming rules, so a typo fails here with a clear message instead of
# in BigQuery - and nothing but a name can ever be substituted into the SQL.
PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
DATASET_ID = re.compile(r"[A-Za-z0-9_]{1,1024}")
BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{1,220}[a-z0-9]")


@dataclass(frozen=True)
class Names:
    """The identifiers the SQL is written against."""

    project: str
    dataset: str
    bucket: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Names:
        """Read and validate GCP_PROJECT_ID, BIGQUERY_DATASET and GCS_RAW_BUCKET."""
        names = cls(settings.gcp_project_id, settings.bigquery_dataset, settings.gcs_raw_bucket)
        for label, value, pattern in (
            ("GCP_PROJECT_ID", names.project, PROJECT_ID),
            ("BIGQUERY_DATASET", names.dataset, DATASET_ID),
            ("GCS_RAW_BUCKET", names.bucket, BUCKET_NAME),
        ):
            if not pattern.fullmatch(value):
                raise ValueError(
                    f"{label}={value!r} is not a valid name; `terraform output env_lines` "
                    "prints the three values"
                )
        return names


@dataclass
class StatementResult:
    """What one statement did (or, in a dry run, would read)."""

    stage: str
    name: str
    bytes_processed: int | None
    rows_affected: int | None


@dataclass
class CheckResult:
    """One verification check."""

    name: str
    failures: int

    @property
    def passed(self) -> bool:
        """A check passes when no row violates it."""
        return self.failures == 0


class QueryJob(Protocol):
    """The part of `google.cloud.bigquery.QueryJob` this module uses."""

    total_bytes_processed: int | None
    num_dml_affected_rows: int | None

    def result(self) -> Iterable[Any]:
        """Wait for the job and return its rows."""


class Client(Protocol):
    """The part of `google.cloud.bigquery.Client` this module uses."""

    def query(self, query: str, job_config: Any = None) -> QueryJob:
        """Start a query job."""


def sql_files(stage: str) -> list[Path]:
    """The statements of one stage, in the order they run."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; one of {', '.join(STAGES)}")
    return sorted(project_file(Path("sql") / "bigquery" / stage).glob("*.sql"))


def render(sql: str, names: Names) -> str:
    """Substitute {{project}}, {{dataset}} and {{bucket}}; fail on any other name."""
    values = {"project": names.project, "dataset": names.dataset, "bucket": names.bucket}

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(f"unknown placeholder {{{{{name}}}}}")
        return values[name]

    return PLACEHOLDER.sub(substitute, sql)


def parameter_values(sql: str, logical_date: date, now: datetime) -> dict[str, date | datetime]:
    """The query parameters this statement names - and only those."""
    available: dict[str, date | datetime] = {"logical_date": logical_date, "pipeline_now": now}
    wanted = set(PARAMETER.findall(_without_comments(sql)))
    unknown = wanted - available.keys()
    if unknown:
        raise ValueError(f"unknown query parameter(s): {', '.join(sorted(unknown))}")
    return {name: available[name] for name in sorted(wanted)}


def _without_comments(sql: str) -> str:
    """The SQL without `--` comments, so a parameter named in prose is not bound."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def job_config(parameters: dict[str, date | datetime], dry_run: bool) -> Any:
    """A QueryJobConfig with typed parameters. Imported lazily (the cloud extra)."""
    from google.cloud import bigquery

    return bigquery.QueryJobConfig(
        dry_run=dry_run,
        # A dry run must see the statement as it would run, not a cached answer.
        use_query_cache=False,
        query_parameters=[
            bigquery.ScalarQueryParameter(
                name, "TIMESTAMP" if isinstance(value, datetime) else "DATE", value
            )
            for name, value in parameters.items()
        ],
    )


def run_stage(
    client: Client,
    names: Names,
    stage: str,
    *,
    logical_date: date,
    now: datetime,
    dry_run: bool = False,
) -> list[StatementResult]:
    """Run every statement of one stage in order; stop at the first failure.

    One statement per job, not one script: each MERGE commits on its own, which
    is safe because each one is idempotent, and a dry run can validate each.
    """
    results: list[StatementResult] = []
    for path in sql_files(stage):
        sql = render(path.read_text(encoding="utf-8"), names)
        params = parameter_values(sql, logical_date, now)
        logger.info("bigquery %s %s%s", stage, path.name, " (dry run)" if dry_run else "")
        job = client.query(sql, job_config=job_config(params, dry_run))
        if not dry_run:
            job.result()
        results.append(
            StatementResult(
                stage=stage,
                name=path.name,
                bytes_processed=job.total_bytes_processed,
                rows_affected=None if dry_run else job.num_dml_affected_rows,
            )
        )
    return results


def verify(client: Client, names: Names, *, logical_date: date, now: datetime) -> list[CheckResult]:
    """Run the verification queries and return one result per check."""
    checks: list[CheckResult] = []
    for path in sql_files("verify"):
        sql = render(path.read_text(encoding="utf-8"), names)
        params = parameter_values(sql, logical_date, now)
        rows = client.query(sql, job_config=job_config(params, dry_run=False)).result()
        checks.extend(CheckResult(row["check_name"], int(row["failures"])) for row in rows)
    return checks


def client_from_settings(settings: Settings) -> Client:
    """A BigQuery client for GCP_PROJECT_ID, in the dataset's location.

    Application Default Credentials, as for GCS. Imported here because
    google-cloud-bigquery is the cloud extra.
    """
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise RuntimeError(
            'google-cloud-bigquery is not installed: pip install -c constraints.txt -e ".[cloud]"'
        ) from exc
    return bigquery.Client(project=settings.gcp_project_id, location=settings.gcp_region)
