"""Static checks on the SQL files - no database needed.

The transformation files are executed with bound parameters, so psycopg reads
every percent sign as the start of a placeholder - also inside a comment. A
single one breaks the whole transformation at run time; this test finds it
before that.
"""

import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

# A % that is neither doubled (%%) nor the start of a named parameter %(name)s.
STRAY_PERCENT = re.compile(r"(?<!%)%(?![%(])")


def test_parameterised_sql_has_no_stray_percent_sign():
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for path in sorted((SQL_DIR / "transform").glob("*.sql"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if STRAY_PERCENT.search(line.replace("%%", ""))
    ]
    assert offenders == [], "write %% instead of %:\n" + "\n".join(offenders)
