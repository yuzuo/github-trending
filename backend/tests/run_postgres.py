"""Run isolated-schema integration tests in the dedicated *_test database."""
import os
import unittest

from sqlalchemy.engine import make_url
from app.config import Settings


if __name__ == '__main__':
    url = make_url(Settings.from_env().database_url).set(database='trending_test')
    os.environ['TEST_DATABASE_URL'] = url.render_as_string(hide_password=False)
    suite = unittest.defaultTestLoader.discover('tests')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
