import json
import unittest
from pathlib import Path


class TestHistoricalAggregates(unittest.TestCase):
    @unittest.skipUnless(Path('data/analysis/summary.json').exists(),'Run data/analysis/report.py')
    def test_source_counts_and_denominators(self):
        data=json.loads(Path('data/analysis/summary.json').read_text(encoding='utf-8'))
        c,v=data['calls'],data['visits']
        self.assertEqual((17772,3687,9,2414),(c['total'],c['missed'],c['peak_hour'],c['peak_count']))
        self.assertEqual(35470,v['total'])
        self.assertEqual(4079,v['statuses']['Неявка'])
        self.assertAlmostEqual(4079/(27080+4079),v['no_show_share_completed_or_missed'])
        self.assertGreater(v['no_show_share_completed_or_missed'],v['no_show_share_all'])
        self.assertEqual('2026-03',v['period'][0][:7])
        self.assertEqual('2026-09',v['period'][1][:7])
