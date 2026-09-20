# Only commands that work at the current project stage are listed here.
# New targets (up/down/ingest/transform/verify) are added together with the code they run.

.PHONY: help setup test lint format explore

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create a virtualenv and install the package with dev dependencies
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Done. Activate with: source .venv/bin/activate  – then fill in .env"

test:  ## Run the unit tests (no network, no database required)
	.venv/bin/python -m pytest

lint:  ## Static checks (ruff)
	.venv/bin/python -m ruff check .
	.venv/bin/python -m ruff format --check .

format:  ## Auto-format code
	.venv/bin/python -m ruff format .
	.venv/bin/python -m ruff check --fix .

explore:  ## Phase-12 API exploration: fetch small samples from football-data.org (needs FOOTBALL_DATA_API_KEY)
	.venv/bin/python scripts/explore_football_api.py
