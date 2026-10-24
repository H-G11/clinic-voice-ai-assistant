# Showcase provenance and reproduction

All visual artifacts have light backgrounds, explicit titles/descriptions, restrained colors and text equivalents. No stock artwork or patient screenshots are used.

| Artifact | Source | Meaning |
| --- | --- | --- |
| service-demo.svg | Actual `service-trace.txt` stdout | Executed synthetic service report; not a Gradio screenshot |
| service-replay.gif | Progressive reveal of the same captured stdout | Prerecorded CLI result playback, not real-time speech/UI |
| service-results.svg | Actual `service-benchmark.json` samples | Median/p95 local service timing table; no ASR/HTTP claim |
| architecture.svg | app.py and core module boundaries | Authored implementation diagram, not measured output |

From the repository root:

```bash
python scripts/demo_local.py --trace > docs/assets/service-trace.txt
python scripts/benchmark_service.py --repeats 30 --warmup 3 --output docs/assets/service-benchmark.json
python scripts/build_showcase.py
```

Add `--gif` to the last command when `rsvg-convert` and `ffmpeg` are installed. The Python renderer itself needs no third-party package. Repeated benchmark runs will legitimately change timings; rerender from the new JSON/stdout rather than editing values by hand. SVG text mirrors actual stdout; the renderer does not create dialogue, patient interactions or a fictitious interface.

The source fixture uses a fixed clock solely to make operations repeatable and never changes the real app's clock. It uses a temporary DB removed after execution. No names, birthdates, audio, IDs or appointment records from a real patient database enter these assets.
