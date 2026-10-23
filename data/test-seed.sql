-- Run after application schema initialization. All writes target a temporary table.
\set ON_ERROR_STOP on
CREATE TEMP TABLE watch_projects (LIKE public.watch_projects INCLUDING ALL);
SET search_path = pg_temp, public;
\ir watch-projects.seed.sql
DO $$ BEGIN
    IF (SELECT count(*) FROM watch_projects) <> 200 OR
       (SELECT count(*) FROM watch_projects WHERE followed) <> 13 OR
       NOT EXISTS (SELECT 1 FROM watch_projects WHERE full_name = 'yt-dlp/yt-dlp' AND followed) THEN
        RAISE EXCEPTION 'Initial import mismatch';
    END IF;
END $$;
UPDATE watch_projects SET notes = 'preserve-existing-note', followed = false
WHERE full_name = 'yt-dlp/yt-dlp';
\ir watch-projects.seed.sql
DO $$ BEGIN
    IF (SELECT count(*) FROM watch_projects) <> 200 OR NOT EXISTS (
        SELECT 1 FROM watch_projects WHERE full_name = 'yt-dlp/yt-dlp'
        AND notes = 'preserve-existing-note' AND NOT followed
    ) THEN
        RAISE EXCEPTION 'Repeat import overwrote existing data';
    END IF;
END $$;
TRUNCATE watch_projects;
INSERT INTO watch_projects (id, full_name, details, discovered_by, manual, followed,
    hidden, review_status, notes, fetched_at)
VALUES (-1, 'test/existing', '{}', '[]', false, false, false, 'pending', '', now());
-- Expected capacity exception aborts the seed transaction; no partial import.
\set ON_ERROR_STOP off
\ir watch-projects.seed.sql
\set ON_ERROR_STOP on
DO $$ BEGIN
    IF (SELECT count(*) FROM watch_projects) <> 1 OR NOT EXISTS (
        SELECT 1 FROM watch_projects WHERE id = -1
    ) THEN
        RAISE EXCEPTION 'Capacity guard failed or import was partial';
    END IF;
END $$;
SELECT 'PASS: initial import, repeat import, preserved state, capacity rollback' AS result;
