"""Finding files that ship with the project (reference data, sample payloads).

The same lookup everywhere: the working directory first, which is the
repository root locally and /app inside the container, then the repository
layout for an editable install.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def project_file(relative: Path | str) -> Path:
    """Return the path of a file shipped with the project."""
    candidate = Path.cwd() / relative
    return candidate if candidate.exists() else REPO_ROOT / relative
