"""Phase-12 API exploration: fetch a few small football-data.org payloads and profile them.

Usage (after `cp .env.example .env` and setting FOOTBALL_DATA_API_KEY):

    python scripts/explore_football_api.py

What it does:
    1. Calls a handful of endpoints for the configured competition (default: CL).
    2. Saves every raw response to `data/sample/football-data/<endpoint>.json`
       (small files; the fixtures file is the largest at roughly 100–200 KB).
    3. Prints a schema profile per endpoint: top-level keys, list lengths,
       field types of the first list element, null counts and candidate business keys.

Why a script and not a notebook?
    The output is deterministic, runs in CI-like fashion and the saved samples
    become test fixtures for the ingestion code. Nothing here writes to a database.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# Allow running the script without installing the package (`pip install -e .` also works).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deng.config import get_settings  # noqa: E402
from deng.ingestion.football_data_client import ApiError, FootballDataClient  # noqa: E402

SAMPLE_DIR = Path("data/sample/football-data")

# (name, path template, params). `{code}` is replaced by the competition code.
ENDPOINTS: list[tuple[str, str, dict[str, Any]]] = [
    ("competition", "competitions/{code}", {}),
    ("teams", "competitions/{code}/teams", {}),
    ("standings", "competitions/{code}/standings", {}),
    ("matches_all", "competitions/{code}/matches", {}),
    ("matches_scheduled", "competitions/{code}/matches", {"status": "SCHEDULED"}),
    ("matches_finished", "competitions/{code}/matches", {"status": "FINISHED"}),
]


def main() -> int:
    """Run the exploration and return a process exit code."""
    settings = get_settings()
    client = FootballDataClient(
        api_key=settings.require_football_api_key(), base_url=settings.football_data_base_url
    )
    code = settings.football_data_competition
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    for name, path_template, params in ENDPOINTS:
        path = path_template.format(code=code)
        print(f"\n=== {name}: GET /{path} {params or ''}")
        try:
            response = client.get(path, params=params)
        except ApiError as exc:
            print(f"  !! {exc}")
            continue

        target = SAMPLE_DIR / f"{name}.json"
        target.write_text(json.dumps(response.payload, indent=2, ensure_ascii=False))
        print(f"  saved -> {target} ({target.stat().st_size / 1024:.1f} KB)")
        print(
            f"  rate limit: {response.rate_limit.requests_available_minute} requests left, "
            f"reset in {response.rate_limit.counter_reset_seconds}s"
        )
        profile(response.payload)
        time.sleep(6.5)  # stay safely under 10 requests/minute on the free tier

    # One team-level call to see cross-competition match history (used for team form).
    first_team_id = _first_team_id(SAMPLE_DIR / "teams.json")
    if first_team_id is not None:
        path = f"teams/{first_team_id}/matches"
        print(f"\n=== team_matches: GET /{path} status=FINISHED")
        try:
            response = client.get(path, params={"status": "FINISHED", "limit": 20})
            target = SAMPLE_DIR / "team_matches.json"
            target.write_text(json.dumps(response.payload, indent=2, ensure_ascii=False))
            print(f"  saved -> {target}")
            profile(response.payload)
        except ApiError as exc:
            print(f"  !! {exc}")

    # Head-to-head for the first scheduled match (historical encounters across seasons).
    first_match_id = _first_match_id(SAMPLE_DIR / "matches_scheduled.json")
    if first_match_id is not None:
        time.sleep(6.5)
        path = f"matches/{first_match_id}/head2head"
        print(f"\n=== head2head: GET /{path}")
        try:
            response = client.get(path, params={"limit": 10})
            target = SAMPLE_DIR / "head2head.json"
            target.write_text(json.dumps(response.payload, indent=2, ensure_ascii=False))
            print(f"  saved -> {target}")
            profile(response.payload)
        except ApiError as exc:
            print(f"  !! {exc}")

    print("\nDone. Commit the small JSON samples in data/sample/ as test fixtures.")
    return 0


def profile(payload: dict[str, Any]) -> None:
    """Print a compact schema profile of a JSON payload."""
    print(f"  top-level keys: {sorted(payload.keys())}")
    for key, value in payload.items():
        if isinstance(value, list):
            print(f"  list '{key}': {len(value)} items")
            if value and isinstance(value[0], dict):
                _profile_records(value)


def _profile_records(records: list[dict[str, Any]]) -> None:
    """Describe field types, null counts and uniqueness for a list of records."""
    types: dict[str, Counter[str]] = {}
    nulls: Counter[str] = Counter()
    for record in records:
        for field_name, value in record.items():
            types.setdefault(field_name, Counter())[type(value).__name__] += 1
            if value is None:
                nulls[field_name] += 1
    print("    field                     types                 nulls")
    for field_name in sorted(types):
        type_summary = ",".join(f"{t}:{c}" for t, c in types[field_name].most_common())
        print(f"    {field_name:<25} {type_summary:<21} {nulls[field_name]}")
    if all("id" in r for r in records):
        ids = [r["id"] for r in records]
        unique = len(set(ids)) == len(ids)
        print(f"    business-key candidate 'id': {'UNIQUE' if unique else 'DUPLICATES FOUND'}")


def _first_team_id(teams_file: Path) -> int | None:
    """Return the id of the first team in a saved teams payload, if present."""
    if not teams_file.exists():
        return None
    teams = json.loads(teams_file.read_text()).get("teams", [])
    return teams[0]["id"] if teams else None


def _first_match_id(matches_file: Path) -> int | None:
    """Return the id of the first match in a saved matches payload, if present."""
    if not matches_file.exists():
        return None
    matches = json.loads(matches_file.read_text()).get("matches", [])
    return matches[0]["id"] if matches else None


if __name__ == "__main__":
    raise SystemExit(main())
