"""Stream a consistent match dataset with its feature contract and coverage report."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg

PRODUCT = "curated.match_training_features"
TARGET = "label_outcome_90min"
IDENTIFIERS = {
    "match_id",
    "season_id",
    "utc_kickoff",
    "match_date",
    "home_team_id",
    "away_team_id",
    "home_team_name",
    "away_team_name",
}
AUDIT_WORDS = (
    "observed_at",
    "ingested_at",
    "computed_at",
    "updated_at",
    "fetched_at",
    "available_at",
    "source",
    "status",
    "cutoff",
    "provenance",
    "snapshot",
    "latest_history",
    "max_history",
    "label_available",
    "is_finished",
    "is_upcoming",
)


def column_role(name: str) -> str:
    """Keep targets, IDs and availability metadata out of the feature list."""
    if name.startswith("label_"):
        return "label"
    if name in IDENTIFIERS or name.endswith("_id") or name.endswith("_name"):
        return "identifier"
    if (
        name.startswith("audit_")
        or any(word in name for word in AUDIT_WORDS)
        or name.endswith("_at")
    ):
        return "audit"
    return "feature"


def export_dataset(
    connection: psycopg.Connection,
    output: Path,
    *,
    labelled_only: bool = False,
    compress: bool = True,
) -> dict:
    """Stream a repeatable-read snapshot; publish all files together on success."""
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Export already exists: {output}; choose a new directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        columns = connection.execute(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod),
                   col_description(a.attrelid, a.attnum)
              FROM pg_attribute a
             WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY a.attnum
            """,
            (PRODUCT,),
        ).fetchall()
        names = [row[0] for row in columns]
        if TARGET not in names:
            raise ValueError(f"{PRODUCT} has no {TARGET}; run init and transform first.")
        dictionary = [
            {
                "column": name,
                "postgres_type": kind,
                "role": column_role(name),
                "description": comment or name.replace("_", " "),
            }
            for name, kind, comment in columns
        ]
        nulls = dict.fromkeys(names, 0)
        labels: dict[str, int] = {}
        competitions: dict[str, int] = {}
        rows = 0
        earliest = latest = None
        filename = "matches.csv.gz" if compress else "matches.csv"
        where = f" WHERE {TARGET} IS NOT NULL" if labelled_only else ""
        with TemporaryDirectory(prefix=".deng-export-", dir=output.parent) as temporary:
            folder = Path(temporary)
            data_path = folder / filename
            opener = gzip.open if compress else open
            with opener(data_path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(names)
                with connection.cursor(name="match_training_export") as cursor:
                    cursor.execute(f"SELECT * FROM {PRODUCT}{where} ORDER BY utc_kickoff, match_id")
                    while batch := cursor.fetchmany(2000):
                        for row in batch:
                            record = dict(zip(names, row, strict=True))
                            writer.writerow(row)
                            rows += 1
                            for name, value in record.items():
                                if value is None:
                                    nulls[name] += 1
                            label = record[TARGET] or "UNLABELLED"
                            labels[label] = labels.get(label, 0) + 1
                            league = str(record["competition_code"])
                            competitions[league] = competitions.get(league, 0) + 1
                            kickoff = record["utc_kickoff"]
                            earliest = kickoff if earliest is None else min(earliest, kickoff)
                            latest = kickoff if latest is None else max(latest, kickoff)
            digest = hashlib.sha256()
            with data_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            coverage = [
                {
                    "column": name,
                    "present": rows - missing,
                    "missing": missing,
                    "coverage_percent": round(100 * (rows - missing) / rows, 2) if rows else None,
                }
                for name, missing in nulls.items()
            ]
            runs = connection.execute(
                """
                SELECT DISTINCT ON (pipeline_name) pipeline_name, run_id::text,
                       logical_date, finished_at
                  FROM meta.pipeline_runs WHERE status = 'SUCCESS'
                 ORDER BY pipeline_name, finished_at DESC
                """
            ).fetchall()
            quality = connection.execute(
                "SELECT check_name, severity, passed, observed FROM meta.dq_results "
                "WHERE checked_at = (SELECT max(checked_at) FROM meta.dq_results) "
                "ORDER BY check_name"
            ).fetchall()
            manifest = {
                "dataset": PRODUCT,
                "contract_version": 1,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "file": filename,
                "sha256": digest.hexdigest(),
                "rows": rows,
                "columns": len(names),
                "labelled_only": labelled_only,
                "target": TARGET,
                "labels": labels,
                "competitions": competitions,
                "first_kickoff": earliest,
                "last_kickoff": latest,
                "feature_columns": [d["column"] for d in dictionary if d["role"] == "feature"],
                "identifier_columns": [
                    d["column"] for d in dictionary if d["role"] == "identifier"
                ],
                "audit_columns": [d["column"] for d in dictionary if d["role"] == "audit"],
                "label_columns": [d["column"] for d in dictionary if d["role"] == "label"],
                "quality_results": [
                    dict(zip(("check", "severity", "passed", "observed"), q, strict=True))
                    for q in quality
                ],
                "source_attributions": [
                    {
                        "source": "FootballDatabase.com",
                        "url": "https://footballdatabase.com/ranking/world/1",
                        "license": "CC BY-SA 4.0",
                        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                        "scope": "World rank, rating points and their derived differences",
                        "changes": "Mapped club IDs; joined captured rankings to matches.",
                    }
                ],
                "latest_successful_runs": [
                    dict(zip(("pipeline", "run_id", "logical_date", "finished_at"), r, strict=True))
                    for r in runs
                ],
                "usage": {
                    "nulls": "Empty CSV fields are missing values; never impute labels.",
                    "split": "Use chronological train/validation/test cutoffs, never random rows.",
                    "prediction_time": "Immediately before kickoff, not N days ahead.",
                    "history": "Results reconstructed by event time with a three-hour completion "
                    "buffer; historical API availability is not guaranteed.",
                    "coverage": "Form covers only ingested competitions. Squad, coach, valuation, "
                    "weather, odds and world rankings require pre-kickoff observations.",
                    "feature_selection": "Use feature_columns; exclude labels, identifiers and "
                    "audit columns. Fit preprocessing on training dates only.",
                },
            }
            for name, value in (
                ("manifest.json", manifest),
                ("data_dictionary.json", dictionary),
                ("coverage.json", coverage),
            ):
                (folder / name).write_text(
                    json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8"
                )
            os.replace(folder, output)
    return manifest
