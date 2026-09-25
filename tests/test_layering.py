"""The architecture rule, as a test.

    Ingestion may read the APIs, the files under data/ and the raw zone.
    It may never read what the transformation built (staging, curated).

That is what makes "ingest everything first, transform afterwards" true rather
than intended: if an ingestion step needed a curated table, the transformation
would have to run in the middle of ingestion - which is exactly the shape this
project moved away from.

The test greps the ingestion code for table names of the later layers. It is
deliberately dumb: a rule a reader can check by eye in three seconds is worth
more here than a clever import graph.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "deng"
INGESTION_DIRS = [SRC / "sources", SRC / "ingestion"]

# Table references of the transformed layers, e.g. "curated.fact_match".
FORBIDDEN = re.compile(r"\b(staging|curated)\.[a-z_]+")


def offending_lines() -> list[str]:
    hits = []
    for directory in INGESTION_DIRS:
        for path in sorted(directory.rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(SRC)}:{number}: {line.strip()}")
    return hits


def test_ingestion_never_reads_staging_or_curated():
    hits = offending_lines()
    assert hits == [], "ingestion must read only the APIs, data/ and the raw zone:\n" + "\n".join(
        hits
    )
