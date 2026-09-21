-- Club crests, stored in the database so the viewer never loads images from a
-- third-party server at page view.
--
-- Raw zone, because the image is kept exactly as received - like every other
-- source payload. Grain: one row per crest URL. The URL identifies the image:
-- football-data.org publishes a changed crest under a new URL, so a URL that is
-- already stored is never fetched again (incremental, unlike the daily FULL
-- reload of the small JSON endpoints).

CREATE TABLE IF NOT EXISTS raw.team_crests (
    crest_url     TEXT        PRIMARY KEY,
    team_id       BIGINT      NOT NULL,
    content_type  TEXT        NOT NULL CHECK (content_type LIKE 'image/%'),
    image         BYTEA       NOT NULL,
    image_sha256  TEXT        NOT NULL,
    byte_size     INTEGER     NOT NULL CHECK (byte_size > 0),
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id        UUID        REFERENCES meta.pipeline_runs (run_id)
);

COMMENT ON TABLE raw.team_crests IS
    'Grain: one row per crest URL. Image bytes as received; fetched once per URL.';

-- What consumers read: the crest behind each team's *current* crest URL. A view
-- rather than a copy, because there is nothing to transform - only to select.
CREATE OR REPLACE VIEW curated.team_crest AS
SELECT d.team_id, c.content_type, c.image, c.image_sha256
  FROM curated.dim_team d
  JOIN raw.team_crests c ON c.crest_url = d.crest_url;

COMMENT ON VIEW curated.team_crest IS
    'Grain: one row per team that has a stored crest. Teams without one fall back to their TLA in the app.';
