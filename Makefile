# Only commands that work at the current project stage are listed here.
# New targets (up/down/ingest/transform/verify) are added together with the code they run.
#
# Two interpreter variables, because they answer two different questions:
#   PYTHON – which interpreter builds the virtualenv? The newest one on this
#            machine that satisfies our minimum (3.10). Overridable:
#            `make setup PYTHON=python3.12`.
#   PY     – which interpreter runs our code? The one inside .venv if it exists,
#            otherwise python3 (that is the case inside the Docker image, where
#            dependencies are installed system-wide).
# This keeps the targets working whether or not the venv is activated, and it
# stops an unrelated active environment (conda, pyenv) from being used by accident.

VENV := .venv
MIN_PYTHON := 3.10
PYTHON ?= $(shell for c in python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$c >/dev/null 2>&1 && \
	$$c -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null && \
	{ echo $$c; break; }; done)
PY := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)

.PHONY: help setup test lint format explore doctor clean

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create a virtualenv and install the package with dev dependencies
	@if [ -z "$(PYTHON)" ]; then \
		echo "ERROR: no Python >= $(MIN_PYTHON) found on PATH."; \
		echo "  Debian/Ubuntu/WSL: sudo apt install python3.12 python3.12-venv"; \
		echo "  pyenv:             pyenv install 3.12 && pyenv local 3.12"; \
		echo "  Already have one?  make setup PYTHON=/path/to/python3.12"; \
		exit 1; \
	fi
	@$(PYTHON) -c "import venv" 2>/dev/null || { \
		echo "ERROR: the venv module is missing for $(PYTHON)."; \
		echo "  Debian/Ubuntu/WSL: sudo apt install python3-venv"; exit 1; }
	@if [ -x $(VENV)/bin/python ] && ! $(VENV)/bin/python -c \
		'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then \
		echo "Existing $(VENV) uses an unsupported Python – recreating it."; rm -rf $(VENV); \
	fi
	@echo "Using $(PYTHON) ($$($(PYTHON) --version 2>&1))"
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Setup complete. Next:"
	@echo "  1. add your free key to .env  (FOOTBALL_DATA_API_KEY=...)"
	@echo "  2. make doctor   – check the environment"
	@echo "  3. make test     – run the unit tests (no network needed)"

doctor:  ## Check that the environment is ready (interpreter, package, .env, API key)
	@$(PY) scripts/doctor.py

test:  ## Run the unit tests (no network, no database required)
	$(PY) -m pytest

lint:  ## Static checks (ruff)
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:  ## Auto-format code
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

explore:  ## API exploration: fetch small samples from football-data.org (needs FOOTBALL_DATA_API_KEY)
	$(PY) scripts/explore_football_api.py

clean:  ## Remove the virtualenv and caches (keeps .env and data/)
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
