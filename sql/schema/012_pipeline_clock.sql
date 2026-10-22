-- The pipeline's "now" for every decision the SQL makes about time: which
-- fixtures are still to come, whether a forecast was computed before kick-off,
-- whether the odds are fresh, when a forecast was fetched.
--
-- It is now() - unless the session pinned `deng.as_of`, which a sample replay
-- does (deng.clock.replaying, set in deng.database.connect). Without it the
-- September samples would be judged against the day someone happens to run
-- them, and the same command would give a different result every day.
--
-- Audit columns (loaded_at, updated_at, ...) keep now() on purpose: they record
-- when a row was really written, replay or not.

CREATE OR REPLACE FUNCTION meta.pipeline_now() RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT coalesce(nullif(current_setting('deng.as_of', true), '')::timestamptz, now())
$$;

COMMENT ON FUNCTION meta.pipeline_now() IS
    'now(), or the moment a sample replay pinned with set_config(''deng.as_of'', ...).';
