# Pipeline image.
#
# Pinned minor version so a rebuild in December produces the same interpreter as
# today; slim rather than alpine because psycopg ships manylinux wheels that
# alpine's musl cannot use, which would force a source build.
FROM python:3.12-slim-bookworm

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
