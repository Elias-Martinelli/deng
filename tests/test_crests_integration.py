"""Crest ingestion against PostgreSQL, with a fake HTTP session (no network)."""

import pytest
import requests

from deng.ingestion.crests import fetch_crests

pytestmark = pytest.mark.postgres

PNG = b"\x89PNG\r\n\x1a\n fake image"


class FakeResponse:
    def __init__(self, status: int, content_type: str, body: bytes):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.content = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Answers per URL; records every request so tests can count them."""

    def __init__(self, answers: dict[str, FakeResponse]):
        self.answers = answers
        self.requested: list[str] = []

    def get(self, url, timeout):
        self.requested.append(url)
        return self.answers[url]


@pytest.fixture
def teams(connection):
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE raw.team_crests")
        cursor.executemany(
            "INSERT INTO curated.dim_team (team_id, name, crest_url, has_domestic_coverage) "
            "VALUES (%s, %s, %s, true)",
            [
                (1, "Good FC", "https://crests.example/1.png"),
                (2, "Broken FC", "https://crests.example/2.png"),
            ],
        )
    connection.commit()


def count(connection, sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


def test_stores_images_and_survives_a_bad_answer(connection, teams):
    session = FakeSession(
        {
            "https://crests.example/1.png": FakeResponse(200, "image/png", PNG),
            "https://crests.example/2.png": FakeResponse(200, "text/html", b"<html>"),
        }
    )
    result = fetch_crests(connection, session=session, pause_seconds=0)
    assert result.fetched == [1]
    assert "not an image" in result.failed[2]
    assert count(connection, "SELECT count(*) FROM curated.team_crest") == 1


def test_a_stored_crest_is_never_fetched_again(connection, teams):
    session = FakeSession(
        {
            "https://crests.example/1.png": FakeResponse(200, "image/png", PNG),
            "https://crests.example/2.png": FakeResponse(404, "text/plain", b""),
        }
    )
    fetch_crests(connection, session=session, pause_seconds=0)
    fetch_crests(connection, session=session, pause_seconds=0)
    # 1.png once; 2.png failed, so it is retried on the second run.
    assert session.requested.count("https://crests.example/1.png") == 1
    assert session.requested.count("https://crests.example/2.png") == 2
