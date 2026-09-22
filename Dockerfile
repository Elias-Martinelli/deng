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

# Dependency metadata first: this layer is cached as long as pyproject.toml is
# unchanged, so editing application code rebuilds in seconds.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY sql/ ./sql/
COPY scripts/ ./scripts/

# Run as a non-root user: a container that only reads an API and writes to
# PostgreSQL has no reason to hold root.
RUN useradd --create-home --uid 1000 pipeline && chown -R pipeline:pipeline /app
USER pipeline

# Default to the help output rather than a silent run, so `docker run` without
# arguments explains itself instead of doing something unexpected.
ENTRYPOINT ["python", "-m", "deng.pipeline"]
CMD ["--help"]

# --- Streamlit viewer -------------------------------------------------------
# A separate stage so the pipeline image stays small: a scheduled batch job has
# no reason to carry a web framework.
FROM pipeline AS app
USER root
RUN pip install --no-cache-dir ".[app]"
COPY app/ /app/app/
RUN chown -R pipeline:pipeline /app
USER pipeline
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
ENTRYPOINT []
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", \
     "-w", "/opt/dagster/dagster_home/workspace.yaml"]
