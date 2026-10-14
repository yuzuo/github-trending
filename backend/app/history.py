from datetime import datetime
from hashlib import sha256

from sqlalchemy import select

from .models import Repository, TrendingSnapshot, utcnow
from .translation import TranslationError


def translation_complete(details):
    return (details['translation_status'] in ('translated', 'missing')
            and details['translated_hash'] == details['readme_hash']
            and (details['readme_original'] is None or details['readme_zh'] is not None)
            and (not details['description'] or details['description_zh'] is not None))


def save_trending_repository(sessions, metadata, original, readme_path, row, day, translator):
    with sessions.begin() as session:
        snapshot = session.scalar(select(TrendingSnapshot).where(
            TrendingSnapshot.repository_id == metadata['id'], TrendingSnapshot.date == day))
        if snapshot is None:
            now = utcnow()
            digest = sha256(original.encode()).hexdigest() if original is not None else None
            repo = session.get(Repository, metadata['id'])
            same_description = repo is not None and repo.description == metadata['description']
            if repo is None:
                repo = Repository(**metadata, first_fetched_at=now, translation_status='unconfigured')
                session.add(repo)
            else:
                for key, value in metadata.items():
                    setattr(repo, key, value)
            repo.last_fetched_at, repo.readme_original = now, original
            repo.readme_path, repo.readme_hash = readme_path, digest
            session.flush()
            details = {}
            for column in Repository.__table__.columns:
                value = getattr(repo, column.name)
                details[column.name] = value.isoformat() if isinstance(value, datetime) else value
            if not same_description or not translation_complete(details):
                if original is None and not metadata['description']:
                    details.update(translation_status='missing', translation_error=None,
                                   readme_zh=None, description_zh=None, translated_hash=None)
                else:
                    details.update(translation_status='pending' if translator else 'unconfigured',
                                   translation_error=None)
                for key in ('translation_status', 'translation_error', 'readme_zh', 'description_zh', 'translated_hash'):
                    setattr(repo, key, details[key])
            snapshot = TrendingSnapshot(repository_id=repo.id, date=day,
                stars=metadata['stars'], trending_rank=row.get('rank', row.get('trending_rank')),
                daily_stars=row['daily_stars'], fetched_at=now, details=details, details_origin='captured')
            session.add(snapshot)
        details = dict(snapshot.details)
        if not translation_complete(details) and translator:
            details.update(translation_status='pending', translation_error=None)
            snapshot.details = details
        session.flush()
        snapshot_id = snapshot.id

    if translation_complete(details) or not translator:
        return True
    try:
        translated = translator.translate(details['readme_original']) if details['readme_original'] is not None else None
        description_zh = translator.translate(details['description']) if details['description'] else None
        updates = dict(readme_zh=translated, description_zh=description_zh,
                       translated_hash=details['readme_hash'], translation_error=None,
                       translation_status='translated' if details['readme_original'] is not None else 'missing')
    except TranslationError as exc:
        updates = dict(translation_status='failed', translation_error=str(exc))
    with sessions.begin() as session:
        snapshot = session.get(TrendingSnapshot, snapshot_id)
        snapshot.details = {**snapshot.details, **updates}
        repo = session.get(Repository, metadata['id'])
        # Historical retries may only refresh the cache when it still represents this original.
        if repo.readme_original == details['readme_original'] and repo.description == details['description']:
            for key, value in updates.items():
                setattr(repo, key, value)
    return updates['translation_status'] != 'failed'
