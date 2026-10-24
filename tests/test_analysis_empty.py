import importlib.util
import tempfile
import unittest
from pathlib import Path


class EmptyAnalysis(unittest.TestCase):
    def test_empty_exports_are_valid_and_not_invented(self):
        source = Path(__file__).resolve().parents[1] / 'data/analysis/report.py'
        spec = importlib.util.spec_from_file_location('analysis_report', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            calls, visits = Path(directory) / 'calls.csv', Path(directory) / 'visits.csv'
            calls.write_text('datetime;result;wait_sec;duration_sec\n')
            visits.write_text('Статус;Специальность;Дата приёма\n', encoding='utf-8')
            report = module.analyze(calls, visits)
        self.assertEqual(0, report['calls']['total'])
        self.assertIsNone(report['calls']['peak_hour'])
        self.assertEqual([], report['calls']['period'])
        self.assertEqual([], report['visits']['period'])
