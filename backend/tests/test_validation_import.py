import unittest
from app.validation_import import validate_result, compare_results


def result(version='2.13.0'):
    return dict(version=version, suite='scrapy-pagination-v1', status='passed',
                metrics=dict(expected_records=6,actual_records=6,correct_records=6,duplicates=0,retry_requests=1,duration_seconds=1.2),
                evidence=dict(observed_version=version, fixture_sha256='a'*64, finish_reason='finished'))


class ValidationRulesTests(unittest.TestCase):
    def test_failed_counts_cannot_be_imported_as_passed(self):
        valid=result()
        self.assertEqual(validate_result(valid),valid)
        for key,value in [('actual_records',5),('duplicates',1),('retry_requests',0),('duration_seconds',float('nan'))]:
            invalid=result()
            invalid['metrics'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_result(invalid)

    def test_comparison_requires_two_versions_and_equal_tasks(self):
        old,new=result('2.13.0'),result('2.13.1')
        self.assertIsNone(compare_results([old]))
        self.assertFalse(compare_results([new,old])['regression'])
        new['status']='failed'
        self.assertTrue(compare_results([new,old])['regression'])
        new['metrics']['expected_records']=10
        self.assertIsNone(compare_results([new,old]))

    def test_rejects_wrong_runtime_and_different_fixture_comparison(self):
        invalid=result()
        invalid['evidence']['observed_version']='0.0.0'
        with self.assertRaises(ValueError):
            validate_result(invalid)
        old,new=result('2.18.0'),result('2.19.0')
        new['evidence']['fixture_sha256']='b'*64
        self.assertIsNone(compare_results([new,old]))
