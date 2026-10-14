from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from .models import Base, SNAPSHOT_MODELS


def database(settings):
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize_database(engine):
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(719436521)'))
        connection.execute(text('SELECT pg_advisory_xact_lock(719436520)'))
        Base.metadata.create_all(connection)
        connection.execute(text("ALTER TABLE collection_runs ADD COLUMN IF NOT EXISTS source VARCHAR(24) NOT NULL DEFAULT 'trending'"))
        connection.execute(text("ALTER TABLE collection_runs ALTER COLUMN source SET DEFAULT 'search'"))
        if inspect(connection).has_table('daily_snapshots'):
            connection.execute(text("ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS source VARCHAR(24) NOT NULL DEFAULT 'trending'"))
            if connection.scalar(text("SELECT count(*) FROM daily_snapshots WHERE source NOT IN ('search', 'trending') OR source IS NULL")):
                raise RuntimeError('Unknown legacy snapshot source; migration rolled back')
            columns = 'repository_id, date, trending_rank, daily_stars, stars, fetched_at'
            for source, model in SNAPSHOT_MODELS.items():
                table = model.__tablename__
                connection.execute(text(f'INSERT INTO {table} ({columns}) SELECT {columns} FROM daily_snapshots WHERE source = :source ON CONFLICT (repository_id, date) DO NOTHING'), {'source': source})
                differences = connection.execute(text(f'SELECT {columns} FROM daily_snapshots WHERE source = :source EXCEPT SELECT {columns} FROM {table}'), {'source': source}).first()
                if differences:
                    raise RuntimeError('Snapshot migration mismatch; original data retained')
            connection.execute(text('DROP TABLE daily_snapshots'))
        connection.execute(text('ALTER TABLE collection_runs ADD COLUMN IF NOT EXISTS items JSONB'))
        connection.execute(text('ALTER TABLE search_snapshots ADD COLUMN IF NOT EXISTS details JSONB'))
        connection.execute(text("ALTER TABLE search_snapshots ADD COLUMN IF NOT EXISTS details_origin VARCHAR(24) NOT NULL DEFAULT 'captured'"))
        connection.execute(text("""UPDATE search_snapshots AS s
            SET details = to_jsonb(r) || jsonb_build_object('stars', s.stars, 'details_backfilled_at', CURRENT_TIMESTAMP),
                details_origin = 'legacy_backfill'
            FROM repositories AS r WHERE r.id = s.repository_id AND s.details IS NULL"""))

        connection.execute(text('ALTER TABLE trending_snapshots ADD COLUMN IF NOT EXISTS details JSONB'))
        connection.execute(text("ALTER TABLE trending_snapshots ADD COLUMN IF NOT EXISTS details_origin VARCHAR(24) NOT NULL DEFAULT 'captured'"))
        connection.execute(text("""UPDATE trending_snapshots AS s
            SET details = to_jsonb(r) || jsonb_build_object('stars', s.stars, 'details_backfilled_at', CURRENT_TIMESTAMP),
                details_origin = 'legacy_backfill'
            FROM repositories AS r WHERE r.id = s.repository_id AND s.details IS NULL"""))
        connection.execute(text("""UPDATE collection_runs AS c SET items = (
            SELECT jsonb_agg(jsonb_build_object('full_name', s.details->>'full_name',
                'rank', s.trending_rank, 'daily_stars', s.daily_stars, 'source', 'trending') ORDER BY s.trending_rank)
            FROM trending_snapshots AS s WHERE s.date = c.date)
            WHERE c.source = 'trending' AND c.items IS NULL
                AND NOT EXISTS (SELECT 1 FROM collection_runs AS saved
                    WHERE saved.source = 'trending' AND saved.date = c.date AND saved.items IS NOT NULL)
                AND EXISTS (SELECT 1 FROM trending_snapshots AS s
                    WHERE s.date = c.date AND s.details_origin = 'legacy_backfill')"""))
