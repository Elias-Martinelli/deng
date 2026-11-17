# ADR-007: Cloud path, with the raw zone mirrored to GCS and read in BigQuery as an external table

Status: **PROPOSED** (2026-11-17). Implemented and tested offline (commits on
`feat/gcs-raw-writer`). It becomes ACCEPTED with the first run against the
team's GCP project: `terraform apply`, a mirrored ingest, then
`make bq-transform`.

## Context

The final milestone needs four things:

* a cloud storage layer and a cloud warehouse;
* a production path from source to GCS with no local intermediate file;
* BigQuery tables built with `MERGE`, with justified partitioning and clustering;
* Terraform for the resources.

The local pipeline already works and has been assessed. PostgreSQL is its raw
zone (ADR-003). The sources after football plan their work from that raw zone:
`raw.match_calendar` and `raw.venue_coordinates` tell the weather source which
venues to ask about, and the transformation reads it too.

ADR-003 sketched the GCS layout as
`raw/source=/endpoint=/ingestion_date=/<run_id>.json` and claimed that reruns
overwrite. The run id is new on every run, so that name would add a duplicate
on every rerun.

## Decision

1. **Mirror, don't replace.** `RAW_TARGETS=postgres,gcs` writes every answer to
   PostgreSQL and, in the same run, to GCS (`src/deng/raw_zone/`). PostgreSQL
   is required in every combination for now.
   * Football goes through one writer interface (`FanOutWriter`).
   * Weather, odds and stadium lookups keep their own SQL and call
     `mirror.put(...)` next to it.
   * A GCS failure fails the run and rolls back that run's PostgreSQL writes.
2. **The object name is a function of the business key.** The path is
   `.../ingestion_date=<day>/<hash of source, endpoint, key>.json`, and the key
   is the PostgreSQL table's key: request parameters for football, the venue
   for weather, request and fetch time for odds, the club for stadiums.
   * A rerun overwrites its own object.
   * The run id lives in the body and the metadata.
   * Bucket versioning keeps an overwritten answer for 30 days.
3. **BigQuery reads the bucket in place.** `raw_answers` is one external table
   over `gs://<bucket>/raw/*`, with the three path levels as hive partition
   columns. It has an explicit schema, with the payload as JSON text, and
   `require_hive_partition_filter`.
4. **Staging and curated are native tables built with `MERGE`.** They are
   ports of `sql/transform/110`–`220` with the same rules.
   * `fact_match` is partitioned by month of `match_date` and clustered by
     `home_team_id, away_team_id, match_id`.
   * Staging and `dim_team` are clustered only.
5. **Least privilege, no keys.** The service account gets `storage.objectUser`
   on the bucket, `bigquery.dataEditor` on the dataset and `bigquery.jobUser`
   on the project. Operators impersonate it, so no key file exists anywhere.
6. **One schedule.** The daily Dagster job carries a `bigquery/warehouse` asset.
   It is a no-op without the gcs target, and runs `bq-init`, `bq-transform`
   and `bq-verify` with it.

## Alternatives considered

| Alternative | Why not |
|---|---|
| GCS as the only raw zone now | The later sources' planning reads and the whole transformation are PostgreSQL. Moving them at the same time means a second, untested pipeline weeks before the freeze. Mirroring keeps the assessed path and adds the cloud one beside it. |
| Write to GCS after the PostgreSQL commit (outbox) | Exactly-once across two systems needs a queue or an outbox table. A deterministic object name gets the same end state more cheaply: the rerun converges. |
| `<run_id>.json` names, as ADR-003 sketched | A rerun adds a duplicate. Deduplication would then move into every BigQuery query. |
| Load jobs into a native raw table | This needs a copy step and its own idempotency (partition-level `WRITE_TRUNCATE`). Selecting one day across `source=*/endpoint=*` levels also needs wildcards in the middle of the URI. The external table reads the same objects in place. |
| Payload as a JSON object (autodetected schema) | Every source has a different shape, so one table cannot hold them all with one detected schema. JSON text with an explicit schema works for all sources. |
| Daily partitions for `fact_match` | Three to ten matches per partition means thousands of tiny partitions. A month keeps pruning for date ranges. |
| A service-account key in `.env` | It is a long-lived secret on a laptop and in the Terraform state. Impersonation gives the same permissions with short-lived tokens. |

## Advantages

* The assessed local pipeline is unchanged when `RAW_TARGETS=postgres`, which
  is the default. Every existing test runs that way.
* Reruns are idempotent in both raw zones for the same reason: the key decides
  where an answer lands.
* No raw data is duplicated into BigQuery. A new endpoint needs no DDL.
* A query that forgets the day fails instead of scanning all history.
* Permissions are testable on a laptop: the impersonating login uses exactly
  the service account's roles.

## Disadvantages

* The two raw zones can briefly disagree. If GCS writes succeed and the
  PostgreSQL commit then fails, the bucket has answers that PostgreSQL does
  not. The next rerun writes the same names again.
* External-table queries are slower than native tables. That is acceptable
  for the raw layer, which only the `MERGE` statements read.
* Only the football chain exists in BigQuery so far. Weather, odds and the
  training tables follow the same pattern.
* Crest images, the world ranking and the licensed team-context CSV are not
  mirrored. They are dashboard-only, optional, or not ours to upload.

## Consequences

* `make bq-transform DRY_RUN=1` comes first against a fresh dataset. The SQL
  parses as BigQuery SQL, apart from the external-table DDL, which the parser
  does not cover. None of it has run against BigQuery yet.
* GCS becomes a valid target on its own once the planning reads and the
  transformation read the BigQuery raw zone. The check in `config.py` then
  goes.
* `fact_match_snapshot` (backlog 6.5) gets the same treatment, partitioned by
  `snapshot_date`.
