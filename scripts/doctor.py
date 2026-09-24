"""Environment self-check: is this clone ready to run the pipeline?

Run with `make doctor`. It prints one line per check and exits non-zero if
something that blocks the next step is missing. Written for peer reviewers:
every failure names the exact command that fixes it.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OK = "  OK   "
WARN = " WARN  "
FAIL = " FAIL  "


def main() -> int:
    """Run all checks and return 0 if nothing blocking is missing."""
    blocking = 0
    warnings = 0

    print(f"Environment check for {REPO_ROOT}\n")

    # 1. Python version
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    # noqa justification: this script may run under an older system python3
    # (that is exactly what it is meant to detect), so the check is not dead code.
    if sys.version_info >= (3, 10):  # noqa: UP036
        print(f"[{OK}] Python {version} ({sys.executable})")
    else:
        print(f"[{FAIL}] Python {version} – 3.10 or newer required; run: make setup")
        blocking += 1

    # 2. Virtualenv in use?
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        print(f"[{OK}] running inside a virtualenv")
    else:
        print(f"[{WARN}] not running inside a virtualenv – run 'make setup', then use make targets")
        warnings += 1

    # 3. Dependencies importable
    for module, hint in (("requests", "requests"), ("pydantic_settings", "pydantic-settings")):
        if importlib.util.find_spec(module) is None:
            print(f"[{FAIL}] dependency '{hint}' missing – run: make setup")
            blocking += 1
        else:
            print(f"[{OK}] dependency '{hint}' available")

    # 4. Package importable
    if importlib.util.find_spec("deng") is None:
        print(f"[{FAIL}] package 'deng' not importable – run: make setup")
        blocking += 1
        return _summary(blocking, warnings)
    print(f"[{OK}] package 'deng' importable")

    # 5. .env present
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        print(f"[{OK}] .env exists")
    else:
        print(f"[{FAIL}] .env missing – run: cp .env.example .env")
        blocking += 1

    # 5b. .env complete? An .env copied before a variable was added to the
    # template silently lacks it; Compose then refuses to start with an
    # interpolation error that does not point at the real cause.
    template = REPO_ROOT / ".env.example"
    if env_file.exists() and template.exists():
        missing = sorted(_env_keys(template) - _env_keys(env_file))
        if not missing:
            print(f"[{OK}] .env has every variable from .env.example")
        if "POSTGRES_PASSWORD" in missing:
            print(
                f"[{FAIL}] .env lacks POSTGRES_PASSWORD – Docker Compose will not start.\n"
                "         Copy the missing lines from .env.example (value: change-me)"
            )
            blocking += 1
            missing.remove("POSTGRES_PASSWORD")
        if missing:
            print(
                f"[{WARN}] .env lacks {len(missing)} variable(s) from .env.example "
                f"(defaults apply): {', '.join(missing)}"
            )
            warnings += 1

    # 6. Settings load and API key present
    from deng.config import get_settings  # imported late, after the checks above

    settings = get_settings()
    if settings.football_data_api_key.get_secret_value():
        print(f"[{OK}] FOOTBALL_DATA_API_KEY is set")
    else:
        print(
            f"[{WARN}] FOOTBALL_DATA_API_KEY not set – 'make test' and 'make lint' still work, "
            "'make explore' does not.\n"
            "         Free key: https://www.football-data.org/client/register"
        )
        warnings += 1
    if settings.odds_api_key.get_secret_value():
        print(f"[{OK}] ODDS_API_KEY is set")
    else:
        print(
            f"[{WARN}] ODDS_API_KEY not set – the odds step skips itself; 'make run-samples' "
            "replays committed sample fetches.\n"
            "         Free key: https://the-odds-api.com"
        )
        warnings += 1
    print(
        f"[{OK}] settings load: competition={settings.football_data_competition}, "
        f"postgres={settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )

    # 7. Secrets not tracked by git
    if (REPO_ROOT / ".git").exists():
        tracked = os.popen("git ls-files .env").read().strip()
        if tracked:
            print(f"[{FAIL}] .env is tracked by git – run: git rm --cached .env")
            blocking += 1
        else:
            print(f"[{OK}] .env is not tracked by git")

    return _summary(blocking, warnings)


def _env_keys(path: Path) -> set[str]:
    """Variable names defined in a dotenv file (comments and blank lines ignored)."""
    keys = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def _summary(blocking: int, warnings: int) -> int:
    """Print a closing summary and return the process exit code."""
    print()
    if blocking:
        print(f"{blocking} blocking problem(s), {warnings} warning(s). Fix the FAIL lines above.")
        return 1
    print(f"Ready. {warnings} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
