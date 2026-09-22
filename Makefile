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
# The candidate must satisfy the version floor AND be able to build a venv.
# Checking `import venv` alone is not enough: on Debian/Ubuntu `python3.12`
# without the python3.12-venv package imports venv happily and then fails at
# creation time with "ensurepip is not available". Importing ensurepip is the
# check that matches what we actually do with the interpreter.
PYTHON ?= $(shell for c in python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$c >/dev/null 2>&1 && \
	$$c -c 'import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
	  2>/dev/null && \
	{ echo $$c; break; }; done)
PY := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)

.PHONY: help setup setup-app test test-integration lint format explore doctor clean \
        up down logs ps psql init ingest ingest-samples transform dq run run-samples \
        backfill verify docker-ingest docker-app reset app notebook \
        setup-orchestrator orchestrator dagster-dev dagster-backfill venues

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create a virtualenv and install the package with dev dependencies
	@if [ -z "$(PYTHON)" ]; then \
		echo "ERROR: no Python >= $(MIN_PYTHON) that can create a virtualenv was found."; \
		echo "  Interpreters on PATH:"; \
		for c in python3.13 python3.12 python3.11 python3.10 python3; do \
			command -v $$c >/dev/null 2>&1 && \
			echo "    $$c $$($$c --version 2>&1 | cut -d' ' -f2)$$( \
				$$c -c 'import venv, ensurepip' 2>/dev/null || echo '  <- venv/ensurepip missing')"; \
		done; \
		echo "  Debian/Ubuntu/WSL: sudo apt install python3-venv   (or python3.12-venv)"; \
		echo "  Already have one?  make setup PYTHON=/path/to/python3.12"; \
		exit 1; \
	fi
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

venues:  ## Rebuild data/reference/venues.csv from OpenStreetMap (once per season; review the diff)
	$(PY) scripts/build_venues.py

explore:  ## API exploration: fetch small samples from football-data.org (needs FOOTBALL_DATA_API_KEY)
	$(PY) scripts/explore_football_api.py

# --- Docker environment -----------------------------------------------------

up:  ## Start PostgreSQL and wait until it is healthy
	docker compose up -d postgres
	@echo "waiting for PostgreSQL to become healthy..."
	@for i in $$(seq 1 30); do \
		state=$$(docker inspect -f '{{.State.Health.Status}}' deng-postgres 2>/dev/null || echo starting); \
		[ "$$state" = "healthy" ] && { echo "PostgreSQL is healthy."; exit 0; }; \
		sleep 2; \
	done; echo "PostgreSQL did not become healthy - check: make logs"; exit 1

down:  ## Stop the containers (keeps the data volume)
	docker compose down

reset:  ## Stop the containers AND delete all data
	docker compose down -v

logs:  ## Follow the PostgreSQL logs
	docker compose logs -f postgres

ps:  ## Show container status
	docker compose ps

psql:  ## Open a psql shell in the database container
	docker compose exec postgres psql -U $${POSTGRES_USER:-deng} -d $${POSTGRES_DB:-cl_intelligence}

# --- Pipeline ---------------------------------------------------------------

init:  ## Create schemas and tables (idempotent)
	$(PY) -m deng.pipeline init

ingest:  ## Ingest today from the API (needs FOOTBALL_DATA_API_KEY)
	$(PY) -m deng.pipeline ingest

ingest-samples:  ## Ingest from the committed sample payloads (no API key needed)
	$(PY) -m deng.pipeline ingest --from-samples

transform:  ## raw -> staging -> curated for today
	$(PY) -m deng.pipeline transform

dq:  ## Run the data-quality checks and persist the results
	$(PY) -m deng.pipeline dq

run:  ## Full daily sequence from the API: ingest -> transform -> data quality
	$(PY) -m deng.pipeline run

run-samples:  ## Full daily sequence from the committed payloads (no API key needed)
	$(PY) -m deng.pipeline run --from-samples

backfill:  ## Re-run a date range: make backfill FROM=2026-09-01 TO=2026-09-10
	$(PY) -m deng.pipeline backfill --from $(FROM) --to $(TO)

verify:  ## Run the verification queries; non-zero exit when a check fails
	$(PY) -m deng.pipeline verify

docker-ingest:  ## Run init + ingestion inside the container image (proves the image works)
	docker compose run --rm pipeline init
	docker compose run --rm pipeline ingest --from-samples

docker-app:  ## Start the Streamlit viewer in a container on http://localhost:8501
	docker compose --profile app up -d --build app

test-integration:  ## Run only the tests that need PostgreSQL
	$(PY) -m pytest -v -m postgres

# --- Consumers of the data product -------------------------------------------

setup-orchestrator:  ## Install the Dagster extra into .venv (for dagster-dev and its tests)
	$(VENV)/bin/pip install -e ".[dev,orchestrator]"

orchestrator:  ## Start PostgreSQL + Dagster (webserver, daemon); UI on http://localhost:3000
	docker compose up -d --build postgres dagster-webserver dagster-daemon
	@echo "Dagster UI: http://localhost:$${DAGSTER_PORT:-3000}"

dagster-dev:  ## Run Dagster locally without Docker (needs setup-orchestrator and a reachable PostgreSQL)
	mkdir -p .dagster && DAGSTER_HOME=$(CURDIR)/.dagster $(VENV)/bin/dagster dev -m deng.orchestration.definitions

dagster-backfill:  ## Backfill through Dagster: make dagster-backfill FROM=2026-09-15 TO=2026-09-17
	docker compose exec dagster-webserver dagster job backfill -j daily_pipeline \
		--from $(FROM) --to $(TO) -w /opt/dagster/dagster_home/workspace.yaml --noprompt

setup-app:  ## Install the extras for Streamlit and Jupyter
	$(VENV)/bin/pip install -e ".[dev,app,notebook]"

app:  ## Start the Streamlit viewer (reads curated tables only)
	$(PY) -m streamlit run app/streamlit_app.py

notebook:  ## Start JupyterLab with the project environment
	$(PY) -m jupyterlab --notebook-dir=notebooks

clean:  ## Remove the virtualenv and caches (keeps .env and data/)
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
