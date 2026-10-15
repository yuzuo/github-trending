import unittest
from suite import score


class ScoreTests(unittest.TestCase):
    def test_complete_data_is_not_enough_without_retry_or_pagination(self):
        rows = [dict(id=str(i), price=str(i * 10)) for i in range(1, 7)]
        self.assertTrue(score(rows, 1, {'/page/1': 1, '/page/2': 2, '/page/3': 1})[0])
        self.assertFalse(score(rows, 0, {'/page/1': 1, '/page/2': 1, '/page/3': 1})[0])
        self.assertFalse(score(rows[:-1], 1, {'/page/1': 1, '/page/2': 2, '/page/3': 1})[0])
        self.assertFalse(score(rows + [rows[0]], 1, {'/page/1': 1, '/page/2': 2, '/page/3': 1})[0])
        rows[0]['price'] = 'wrong'
        self.assertFalse(score(rows, 1, {'/page/1': 1, '/page/2': 2, '/page/3': 1})[0])
