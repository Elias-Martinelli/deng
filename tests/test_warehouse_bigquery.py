"""The BigQuery side of the transformation, without BigQuery (backlog 10.1-10.4, 7.5).

What can be proven offline is proven here:

* identifiers reach the SQL only after validation, values only as parameters,
  and each statement gets exactly the parameters it names;
* every file under sql/bigquery/ renders completely and is one statement;
* every transformation is a MERGE (idempotent), and every read of the raw
  table filters the day partition (the table requires it);
* the curated fact is partitioned by match date and clustered by team;
* the runner runs the files in order, stops at the first failure, executes
  nothing in a dry run, and `bq-verify` fails on any violated check.

What is not proven here: that BigQuery accepts the SQL. That needs the dataset
- `make bq-transform DRY_RUN=1` is the first thing to run against it.
"""

import re
from datetime import date, datetime, timezone

import pytest

from deng.config import Settings
from deng.warehouse import bigquery
from deng.warehouse.bigquery import Names

NAMES = Names(project="deng-hs26-test", dataset="cl_intelligence", bucket="deng-hs26-test-raw")
DAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)


def statements(stage):
    return [(path.name, path.read_text()) for path in bigquery.sql_files(stage)]


def code_only(sql):
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


# --- names and parameters ------------------------------------------------------


def test_names_come_from_the_settings_and_are_validated(clean_env):
    settings = Settings(
        _env_file=None, gcp_project_id="deng-hs26-test", gcs_raw_bucket="deng-hs26-test-raw"
    )
    assert Names.from_settings(settings) == NAMES


@pytest.mark.parametrize(
    ("field", "value", "label"),
    [
        ("gcp_project_id", "", "GCP_PROJECT_ID"),
        ("gcp_project_id", "x`; DROP TABLE t; --", "GCP_PROJECT_ID"),
        ("bigquery_dataset", "cl-intelligence", "BIGQUERY_DATASET"),
        ("gcs_raw_bucket", "gs://bucket", "GCS_RAW_BUCKET"),
    ],
)
def test_an_invalid_name_is_refused_before_any_sql_is_built(clean_env, field, value, label):
    values = {"gcp_project_id": "deng-hs26-test", "gcs_raw_bucket": "deng-hs26-test-raw"}
    values[field] = value
    with pytest.raises(ValueError, match=label):
        Names.from_settings(Settings(_env_file=None, **values))


def test_render_substitutes_the_three_names_and_refuses_any_other():
    sql = "SELECT 1 FROM `{{project}}.{{ dataset }}.t` -- gs://{{bucket}}"
    assert bigquery.render(sql, NAMES) == (
        "SELECT 1 FROM `deng-hs26-test.cl_intelligence.t` -- gs://deng-hs26-test-raw"
    )
    with pytest.raises(ValueError, match="table"):
        bigquery.render("SELECT * FROM {{table}}", NAMES)


def test_a_statement_gets_exactly_the_parameters_it_names():
    sql = "-- @pipeline_now is only mentioned here\nSELECT @logical_date"
    assert bigquery.parameter_values(sql, DAY, NOW) == {"logical_date": DAY}
    assert bigquery.parameter_values("SELECT 1", DAY, NOW) == {}
    with pytest.raises(ValueError, match="season"):
        bigquery.parameter_values("SELECT @season", DAY, NOW)


# --- the SQL files ---------------------------------------------------------------


@pytest.mark.parametrize("stage", bigquery.STAGES)
def test_every_file_renders_completely_and_names_only_known_parameters(stage):
    files = statements(stage)
    assert files, f"no SQL under sql/bigquery/{stage}"
    for name, sql in files:
        rendered = bigquery.render(sql, NAMES)
        assert "{{" not in rendered and "}}" not in rendered, name
        bigquery.parameter_values(rendered, DAY, NOW)


@pytest.mark.parametrize("stage", bigquery.STAGES)
def test_every_file_is_one_statement(stage):
    for name, sql in statements(stage):
        code = code_only(sql).strip()
        semicolons = code.count(";")
        assert semicolons <= 1 and (semicolons == 0 or code.endswith(";")), name


def test_every_transformation_is_a_merge_so_a_rerun_changes_nothing():
    for name, sql in statements("transform"):
        code = code_only(sql)
        assert code.lstrip().upper().startswith("MERGE "), name
        assert not re.search(r"^\s*INSERT\s+INTO", code, re.IGNORECASE | re.MULTILINE), name


def test_every_read_of_the_raw_table_filters_the_day_partition():
    for stage in ("transform", "verify"):
        for name, sql in statements(stage):
            code = code_only(sql)
            if "raw_answers" in code:
                assert re.search(r"\bingestion_date\s*(=|<=)\s*@logical_date", code), name


def test_the_raw_table_is_external_over_the_bucket_with_hive_partitions():
    (name, sql), *_ = statements("schema")
    rendered = bigquery.render(sql, NAMES)
    assert "CREATE OR REPLACE EXTERNAL TABLE" in rendered
    assert "uris = ['gs://deng-hs26-test-raw/raw/*']" in rendered
    assert "WITH PARTITION COLUMNS" in rendered
    assert "require_hive_partition_filter = TRUE" in rendered


def test_the_partition_columns_match_the_object_layout_of_the_raw_zone():
    from deng.raw_zone.gcs import object_name

    path = object_name("football-data.org", "competitions/CL/matches", {}, DAY)
    levels = [part.split("=")[0] for part in path.split("/") if "=" in part]
    (_, sql), *_ = statements("schema")
    block = re.search(r"WITH PARTITION COLUMNS \((.*?)\)", sql, re.DOTALL).group(1)
    columns = [line.split()[0] for line in code_only(block).splitlines() if line.strip()]
    assert columns == levels == ["source", "endpoint", "ingestion_date"]


def test_the_fact_is_partitioned_by_match_month_and_clustered_by_team():
    sql = dict(statements("schema"))["050_fact_match.sql"]
    assert "PARTITION BY DATE_TRUNC(match_date, MONTH)" in sql
    assert "CLUSTER BY home_team_id, away_team_id, match_id" in sql


def test_the_sources_read_are_the_path_safe_names_the_writer_uses():
    from deng.raw_zone.gcs import partition_value
    from deng.sources.football_data import SAMPLE_SOURCE, SOURCE

    expected = f"('{partition_value(SOURCE)}', '{partition_value(SAMPLE_SOURCE)}')"
    for stage in ("transform", "verify"):
        for name, sql in statements(stage):
            if "raw_answers" in code_only(sql):
                assert f"source IN {expected}" in sql, name


# --- the runner ------------------------------------------------------------------


class FakeJob:
    def __init__(self, rows=(), fail=False):
        self.rows = list(rows)
        self.fail = fail
        self.waited = False
        self.total_bytes_processed = 1024
        self.num_dml_affected_rows = 3

    def result(self):
        self.waited = True
        if self.fail:
            raise RuntimeError("BigQuery said no")
        return self.rows


class FakeClient:
    def __init__(self, rows=(), fail_on=None):
        self.calls = []
        self.jobs = []
        self.rows = rows
        self.fail_on = fail_on

    def query(self, query, job_config=None):
        self.calls.append((query, job_config))
        job = FakeJob(self.rows, fail=self.fail_on is not None and self.fail_on in query)
        self.jobs.append(job)
        return job


def test_a_stage_runs_its_files_in_order_with_typed_parameters():
    pytest.importorskip("google.cloud.bigquery")
    client = FakeClient()

    results = bigquery.run_stage(client, NAMES, "transform", logical_date=DAY, now=NOW)

    assert [r.name for r in results] == [p.name for p in bigquery.sql_files("transform")]
    assert all("`deng-hs26-test.cl_intelligence." in sql for sql, _ in client.calls)
    first_config = client.calls[0][1]
    assert [(p.name, p.type_, p.value) for p in first_config.query_parameters] == [
        ("logical_date", "DATE", DAY)
    ]
    assert all(job.waited for job in client.jobs)
    assert results[0].rows_affected == 3


def test_a_dry_run_validates_every_statement_and_waits_for_none():
    pytest.importorskip("google.cloud.bigquery")
    client = FakeClient()

    results = bigquery.run_stage(client, NAMES, "schema", logical_date=DAY, now=NOW, dry_run=True)

    assert len(results) == len(bigquery.sql_files("schema"))
    assert all(config.dry_run for _, config in client.calls)
    assert not any(job.waited for job in client.jobs)
    assert all(r.rows_affected is None for r in results)


def test_the_first_failing_statement_stops_the_stage():
    pytest.importorskip("google.cloud.bigquery")
    client = FakeClient(fail_on="staging_teams")

    with pytest.raises(RuntimeError, match="said no"):
        bigquery.run_stage(client, NAMES, "transform", logical_date=DAY, now=NOW)
    assert len(client.calls) == 2  # 110 ran, 111 failed, 210 and 220 never started


def test_bq_verify_fails_on_any_violated_check(clean_env, monkeypatch, capsys):
    pytest.importorskip("google.cloud.bigquery")
    from deng import pipeline

    monkeypatch.setenv("GCP_PROJECT_ID", NAMES.project)
    monkeypatch.setenv("GCS_RAW_BUCKET", NAMES.bucket)
    rows = [
        {"check_name": "fact_match_unique_match_id", "failures": 0},
        {"check_name": "fact_match_home_differs_from_away", "failures": 2},
    ]
    monkeypatch.setattr(bigquery, "client_from_settings", lambda settings: FakeClient(rows))

    assert pipeline.main(["bq-verify", "--date", "2026-11-17"]) == 1
    output = capsys.readouterr().out
    assert "FAIL fact_match_home_differs_from_away" in output
    assert "1/2 passed" in output

    rows[1]["failures"] = 0
    assert pipeline.main(["bq-verify", "--date", "2026-11-17"]) == 0


def test_bq_commands_refuse_to_start_without_the_gcp_names(clean_env, capsys):
    from deng import pipeline

    assert pipeline.main(["bq-transform", "--dry-run"]) == 1
    assert "GCP_PROJECT_ID" in capsys.readouterr().err
