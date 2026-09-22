# Three images from one file (multi-stage build):
#   pipeline      the batch job itself - `python -m deng.pipeline <command>`
#   app           pipeline + Streamlit, the viewer
#   orchestrator  pipeline + Dagster, the scheduler
# Each later stage starts FROM the pipeline stage, so all three run the same
# code; only what is installed on top differs. Compose picks a stage with
# `target:`.
#
# Pipeline image.
#
# Pinned minor version so a rebuild in December produces the same interpreter as
# today; slim rather than alpine because psycopg ships manylinux wheels that
# alpine's musl cannot use, which would force a source build.
FROM python:3.12-slim-bookworm AS pipeline

# No .pyc files, unbuffered logs (so `docker compose logs` shows output live),
# and pip without its version-check noise.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Docker caches each instruction as a layer and re-runs it only when its inputs
# change. Because the package is installed from src/, any code change re-runs
# this pip install (about 20 s here, dependencies included). Separating the
# dependencies into their own layer would need a pinned requirements file - not
# worth it at this size, and it would be the first step if builds got slow.
# README.md is copied because pyproject.toml declares it as the package readme.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY sql/ ./sql/
# Reference data is part of the product (venue coordinates for the weather), unlike
# the sample payloads, which are mounted by Compose for offline runs only.
COPY data/reference/ ./data/reference/
COPY scripts/ ./scripts/

# Run as a non-root user: a container that only reads an API and writes to
# PostgreSQL has no reason to hold root.
# uid 1000 is the usual first user on Linux hosts, so files the container writes
# into a mounted folder stay editable by the developer.
RUN useradd --create-home --uid 1000 pipeline && chown -R pipeline:pipeline /app
USER pipeline

# Default to the help output rather than a silent run, so `docker run` without
# arguments explains itself instead of doing something unexpected.
# ENTRYPOINT is the fixed program, CMD the default arguments: `docker compose run
# pipeline ingest` replaces only CMD, so it runs `python -m deng.pipeline ingest`.
ENTRYPOINT ["python", "-m", "deng.pipeline"]
CMD ["--help"]

# --- Streamlit viewer -------------------------------------------------------
# A separate stage so the pipeline image stays small: a scheduled batch job has
# no reason to carry a web framework.
FROM pipeline AS app
# root only for installing; the last USER line switches back before anything runs
USER root
RUN pip install --no-cache-dir ".[app]"
COPY app/ /app/app/
# Theme and toolbar settings; Streamlit reads them from the working directory.
COPY .streamlit/config.toml /app/.streamlit/config.toml
RUN chown -R pipeline:pipeline /app
USER pipeline
# EXPOSE documents the port; publishing it to the host is Compose's `ports:`.
# 0.0.0.0: listen on all interfaces - 127.0.0.1 would be unreachable from
# outside the container.
EXPOSE 8501
ENTRYPOINT ["streamlit", "run", "app/streamlit_app.py", \
            "--server.address=0.0.0.0", "--server.port=8501", \
            "--browser.gatherUsageStats=false"]
CMD []

# --- Orchestrator (Dagster webserver and daemon) -----------------------------
# Built on the pipeline stage, so a scheduled run executes the very code the
# `pipeline` image runs by hand. Which process starts (webserver or daemon) is
# chosen by the Compose service.
FROM pipeline AS orchestrator
USER root
RUN pip install --no-cache-dir ".[orchestrator]"
ENV DAGSTER_HOME=/opt/dagster/dagster_home
COPY orchestrator/dagster.yaml orchestrator/workspace.yaml /opt/dagster/dagster_home/
RUN chown -R pipeline:pipeline /opt/dagster /app
USER pipeline
EXPOSE 3000
# Clears the pipeline stage's ENTRYPOINT: here the command is a whole program
# (webserver or daemon), set per service in docker-compose.yml.
ENTRYPOINT []
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", \
     "-w", "/opt/dagster/dagster_home/workspace.yaml"]
