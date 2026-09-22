"""Fetch club crests into `raw.team_crests`.

Incremental on purpose: a crest URL that is already stored is never fetched
again (football-data.org publishes a changed crest under a new URL). After the
first run this step makes no request at all on a normal day.

Best effort on purpose: a missing crest costs the viewer a picture - it falls
back to the team's three-letter code - and must not fail the pipeline. Failures
are counted, logged and visible in the run log and the data-quality results,
never raised. A database error, by contrast, is raised: that is not a crest
problem.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field

import psycopg
import requests

logger = logging.getLogger(__name__)

# Anything larger is not a crest; refusing it bounds what a changed or
# compromised URL could push into the database.
MAX_BYTES = 1_000_000
# The images come from a CDN, but there is no reason to hit it in a burst.
PAUSE_SECONDS = 0.2


@dataclass
class CrestResult:
    """What one crest run did."""

    fetched: list[int] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """One line for logs and CLI output."""
        return f"{len(self.fetched)} fetched, {len(self.failed)} failed"


def missing_crests(connection: psycopg.Connection) -> list[tuple[int, str]]:
    """Teams whose current crest URL has no stored image yet."""
    # The NOT EXISTS anti-join *is* the incremental load: it returns only URLs
    # that are not stored yet, so a normal day returns nothing and makes no
    # request. A club that gets a new crest URL shows up here automatically.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT d.team_id, d.crest_url
              FROM curated.dim_team d
             WHERE d.crest_url IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM raw.team_crests c WHERE c.crest_url = d.crest_url)
             ORDER BY d.team_id
            """
        )
        return [(int(team_id), url) for team_id, url in cursor.fetchall()]


def download(session: requests.Session, url: str) -> tuple[str, bytes]:
    """GET one crest and check that it is a plausible image.

    Raises:
        ValueError: if the answer is not an image or is implausibly large.
        requests.RequestException: on HTTP or network errors.
    """
    response = session.get(url, timeout=20)
    response.raise_for_status()  # 4xx/5xx -> requests.HTTPError, a RequestException
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    if not content_type.startswith("image/"):
        raise ValueError(f"not an image: Content-Type {content_type!r}")
    body = response.content
    if not body or len(body) > MAX_BYTES:
        raise ValueError(f"implausible size: {len(body)} bytes")
    return content_type, body


def fetch_crests(
    connection: psycopg.Connection,
    run_id: uuid.UUID | None = None,
    session: requests.Session | None = None,
    pause_seconds: float = PAUSE_SECONDS,
) -> CrestResult:
    """Download every crest that is not stored yet; commit each one as it arrives."""
    session = session or requests.Session()
    result = CrestResult()
    for index, (team_id, url) in enumerate(missing_crests(connection)):
        if index:
            time.sleep(pause_seconds)
        try:
            content_type, body = download(session, url)
        except (requests.RequestException, ValueError) as exc:
            result.failed[team_id] = f"{type(exc).__name__}: {exc}"
            logger.warning("crest for team %s not stored (%s): %s", team_id, url, exc)
            continue
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO raw.team_crests
                    (crest_url, team_id, content_type, image, image_sha256, byte_size, run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (crest_url) DO NOTHING
                """,
                (
                    url,
                    team_id,
                    content_type,
                    body,
                    hashlib.sha256(body).hexdigest(),
                    len(body),
                    run_id,
                ),
            )
        # Commit per crest (unlike the daily payloads): the images are
        # independent of each other, so what arrived is kept even if a later
        # download fails - and the next run only fetches the rest.
        connection.commit()
        result.fetched.append(team_id)
    logger.info("crests: %s", result.summary)
    return result
