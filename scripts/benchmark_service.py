"""Measure real local service calls against isolated synthetic SQLite fixtures."""

import argparse
import json
import math
import os
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.demo_local import run_demo


def summarize(samples):
    if not samples or any(not math.isfinite(x) or x < 0 for x in samples):
        raise ValueError('Require finite nonnegative latency samples')
    ordered = sorted(samples)
    return {'n': len(samples), 'median_ms': statistics.median(samples),
            'p95_ms': ordered[math.ceil(.95 * len(ordered)) - 1], 'samples_ms': samples}


def benchmark(repeats=30, warmup=3):
    if repeats < 2 or warmup < 0:
        raise ValueError('Require repeats >= 2 and warmup >= 0')
    samples = {}
    for iteration in range(warmup + repeats):
        result = run_demo(measure=True)
        if iteration >= warmup:
            for event in result['events']:
                samples.setdefault(event['action'], []).append(event['latency_ms'])
    cpu = platform.processor()
    cpuinfo = Path('/proc/cpuinfo')
    if not cpu and cpuinfo.is_file():
        cpu = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), '')
    return {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'Sequential local service calls including SQLite and in-process mock API. Not HTTP, ASR, TTS or production latency.',
            'source_kind': 'synthetic_generated_fixture', 'repeats': repeats, 'warmup': warmup,
            'clock': 'Fixed 2026-10-15 GMT+4 fixture',
            'hardware': {'cpu': cpu or 'unreported', 'logical_cpus': os.cpu_count(),
                         'platform': platform.platform(), 'python': platform.python_version()},
            'operations': {name: summarize(values) for name, values in samples.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path('docs/assets/service-benchmark.json'))
    args = parser.parse_args()
    try:
        report = benchmark(args.repeats, args.warmup)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({name: {k: v for k, v in row.items() if k != 'samples_ms'} for name, row in report['operations'].items()}, indent=2))
