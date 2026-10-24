import unittest

from scripts.benchmark_service import summarize
from scripts.demo_local import run_demo


class DemoBenchmarkTests(unittest.TestCase):
    def test_demo_executes_actual_service_and_preserves_default_contract(self):
        report = run_demo()
        self.assertTrue(report['cancellation_verified'])
        self.assertEqual(2, report['free_slots_after_cancel'])
        self.assertEqual(9, len(report['events']))
        self.assertNotIn('latency_ms', report['events'][0])

    def test_trace_is_emitted_only_after_verified_operations(self):
        trace = []
        report = run_demo(measure=True, trace=trace.append)
        self.assertEqual(trace, report['events'])
        self.assertTrue(all(row['latency_ms'] >= 0 for row in trace))
        self.assertEqual('rejected', trace[0]['result'])
        self.assertEqual('ok', trace[-1]['result'])

    def test_quantiles_and_invalid_samples(self):
        stats = summarize(list(range(1, 21)))
        self.assertEqual(10.5, stats['median_ms'])
        self.assertEqual(19, stats['p95_ms'])
        for samples in ([], [float('nan')], [-1]):
            with self.assertRaises(ValueError):
                summarize(samples)
