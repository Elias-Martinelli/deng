"""Import licensed, dated team context without inventing historical knowledge.

CSV uses football-data.org team IDs as its explicit crosswalk. observed_at
means when the source made the information available, not the import date.
Retain source evidence for that timestamp. Missing values stay missing.
Football-data.org squads/coaches in the raw zone are parsed in SQL.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

REQUIRED_COLUMNS = {"team_id", "observed_at", "valid_from", "source", "source_url"}
COUNT_COLUMNS = {
    "squad_size",
    "squad_nationalities",
    "squad_foreign_players",
    "squad_goalkeepers",
    "squad_defenders",
    "squad_midfielders",
    "squad_attackers",
    "squad_unknown_positions",
    "squad_missing_birthdates",
}
AGE_COLUMNS = {"squad_avg_age", "squad_min_age", "squad_max_age"}
TEXT_COLUMNS = {"coach_namespace", "coach_id", "coach_name", "coach_nationality"}
DATE_COLUMNS = {"coach_birth_date", "coach_tenure_start"}
OPTIONAL_COLUMNS = (
    COUNT_COLUMNS
    | AGE_COLUMNS
    | TEXT_COLUMNS
    | DATE_COLUMNS
    | {"valid_until", "squad_market_value_eur"}
)


def _timestamp(value: str, field_name: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} requires a timezone, for example 2025-08-01T12:00:00Z")
    return parsed.astimezone(timezone.utc).isoformat()


def parse_csv(text: str) -> list[dict]:
    """Validate the whole CSV before writing; reject typos and duplicate snapshots."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)):
        raise ValueError("duplicate CSV column names")
    missing = REQUIRED_COLUMNS - set(fields)
    unknown = set(fields) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
    if missing or unknown:
        raise ValueError(f"CSV columns: missing={sorted(missing)}, unknown={sorted(unknown)}")
    result: list[dict] = []
    seen = set()
    for line, raw in enumerate(reader, start=2):
        try:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError("row length does not match the header")
            row = {key: value.strip() or None for key, value in raw.items()}
            if any(row.get(key) is None for key in REQUIRED_COLUMNS):
                raise ValueError("required values must not be empty")
            row["team_id"] = int(row["team_id"])
            if row["team_id"] <= 0:
                raise ValueError("team_id must be a positive football-data.org team ID")
            for key in ("observed_at", "valid_from", "valid_until"):
                if row.get(key):
                    row[key] = _timestamp(row[key], key)
            if row.get("valid_until") and row["valid_until"] <= row["valid_from"]:
                raise ValueError("valid_until must be later than valid_from")
            for key in COUNT_COLUMNS:
                if row.get(key) is not None:
                    row[key] = int(row[key])
                    if row[key] < 0:
                        raise ValueError(f"{key} cannot be negative")
            for key in AGE_COLUMNS | {"squad_market_value_eur"}:
                if row.get(key) is not None:
                    row[key] = float(row[key])
                    if not math.isfinite(row[key]) or row[key] < 0:
                        raise ValueError(f"{key} must be a finite nonnegative number")
                    if key in AGE_COLUMNS and not 10 <= row[key] <= 70:
                        raise ValueError(f"{key} must be between 10 and 70 years")
            size = row.get("squad_size")
            if size is not None:
                if size == 0:
                    raise ValueError("squad_size must be positive; use blank for an unknown squad")
                if any(row.get(key, 0) and row[key] > size for key in COUNT_COLUMNS):
                    raise ValueError("a squad count exceeds squad_size")
                positions = (
                    "squad_goalkeepers",
                    "squad_defenders",
                    "squad_midfielders",
                    "squad_attackers",
                    "squad_unknown_positions",
                )
                if sum(row.get(key) or 0 for key in positions) > size:
                    raise ValueError("position counts exceed squad_size")
            elif any(row.get(key) is not None for key in COUNT_COLUMNS | AGE_COLUMNS):
                raise ValueError("squad features require squad_size")
            for low, high in (
                ("squad_min_age", "squad_avg_age"),
                ("squad_avg_age", "squad_max_age"),
                ("squad_min_age", "squad_max_age"),
            ):
                if row.get(low) is not None and row.get(high) is not None and row[low] > row[high]:
                    raise ValueError(f"{low} exceeds {high}")
            for key in DATE_COLUMNS:
                if row.get(key):
                    row[key] = date.fromisoformat(row[key]).isoformat()
            if row.get("coach_id"):
                if not row.get("coach_namespace") or not row.get("coach_name"):
                    raise ValueError("coach_id requires coach_namespace and coach_name")
                row["coach_id"] = f"{row['coach_namespace']}:{row['coach_id']}"
            elif any(row.get(key) for key in TEXT_COLUMNS | DATE_COLUMNS):
                raise ValueError("coach details require coach_id and coach_namespace")
            if not any(
                row.get(key) is not None
                for key in ("squad_size", "coach_id", "squad_market_value_eur")
            ):
                raise ValueError("provide at least a squad, coach, or team valuation")
            identity = (row["team_id"], row["source"], row["observed_at"], row["valid_from"])
            if identity in seen:
                raise ValueError("duplicate team/source/observed_at/valid_from snapshot")
            seen.add(identity)
            result.append(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"team context CSV line {line}: {exc}") from exc
    return result


@dataclass
class IngestResult:
    """A raw CSV import, or an explicit optional-source skip."""

    stored: int = 0
    records: int = 0
    lines: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Describe the import for the pipeline runner."""
        return f"{self.stored} file(s), {self.records} dated team snapshot(s)"


def ingest(
    connection: psycopg.Connection,
    logical_date: date,
    run_id: uuid.UUID,
    csv_path: str | Path | None = None,
    from_samples: bool = False,
) -> IngestResult:
    """Preserve a validated CSV as an immutable, content-addressed raw import.

    Sample mode ignores external CSVs. Committed API samples still exercise the
    squad/coach transform without mixing in user imports. Identical files are
    no-ops across runs and logical dates.
    """
    if from_samples or not csv_path:
        reason = "sample mode" if from_samples else "TEAM_CONTEXT_CSV_PATH is not configured"
        return IngestResult(lines=[f"optional dated CSV skipped: {reason}"])
    path = Path(csv_path).expanduser().resolve(strict=True)
    raw_text = path.read_text(encoding="utf-8-sig")
    snapshots = parse_csv(raw_text)
    digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw.team_context_import
                (payload_hash, request_url, ingestion_date, run_id, csv_text, payload, record_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (payload_hash) DO NOTHING
            """,
            (
                digest,
                path.as_uri(),
                logical_date,
                run_id,
                raw_text,
                Jsonb({"snapshots": snapshots}),
                len(snapshots),
            ),
        )
        inserted = cursor.rowcount
    connection.commit()
    return IngestResult(inserted, len(snapshots), [f"sha256={digest[:12]} file={path.name}"])
