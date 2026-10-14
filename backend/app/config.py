from dataclasses import dataclass
import os
from urllib.parse import urlsplit

from sqlalchemy import URL


@dataclass
class Settings:
    database_url: str | URL = ''
    github_token: str = ''
    translation_base_url: str = ''
    translation_model: str = ''
    translation_api_key: str = ''
    collect_hour: int = 1
    schedule_enabled: bool = True
    app_origin: str = 'http://localhost:8080'
    search_limit: int = 100
    trending_collect_hour: int = 1

    @classmethod
    def from_env(cls):
        base_url = os.getenv('TRANSLATION_BASE_URL', '').rstrip('/')
        if base_url:
            url = urlsplit(base_url)
            if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('TRANSLATION_BASE_URL must be an HTTP(S) API base URL without credentials or query')
        hour = int(os.getenv('COLLECT_HOUR', '1'))
        if not 0 <= hour <= 23:
            raise ValueError('COLLECT_HOUR must be between 0 and 23')
        search_limit = int(os.getenv('SEARCH_LIMIT', '100'))
        trending_hour = int(os.getenv('TRENDING_COLLECT_HOUR', '1'))
        if not 0 <= trending_hour <= 23:
            raise ValueError('TRENDING_COLLECT_HOUR must be between 0 and 23')
        if not 1 <= search_limit <= 1000:
            raise ValueError('SEARCH_LIMIT must be between 1 and 1000')
        database_url = os.getenv('DATABASE_URL') or URL.create(
            'postgresql+psycopg', username=os.getenv('DB_USER', 'trending'),
            password=os.getenv('DB_PASSWORD', ''), host=os.getenv('DB_HOST', 'db'),
            port=int(os.getenv('DB_PORT', '5432')), database=os.getenv('DB_NAME', 'trending'))
        return cls(database_url, os.getenv('GITHUB_TOKEN', ''), base_url,
                   os.getenv('TRANSLATION_MODEL', ''), os.getenv('TRANSLATION_API_KEY', ''), hour,
                   os.getenv('SCHEDULE_ENABLED', 'true').lower() == 'true',
                   os.getenv('APP_ORIGIN', 'http://localhost:8080').rstrip('/'), search_limit, trending_hour)

    @property
    def translation_enabled(self):
        return bool(self.translation_base_url and self.translation_model and self.translation_api_key)
