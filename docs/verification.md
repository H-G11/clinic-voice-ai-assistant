# Local verification — 2026-10-24

Environment: Linux x86_64, CPython 3.14.7. This is not the original Windows developer environment. Internet and loopback TCP socket creation are denied (`Operation not permitted`); host Throne networking is not implicated. A separate workspace venv with pip was bootstrapped from bundled ensurepip. Offline package resolution found no openpyxl wheel; no project package installation completed.

| Check | Actual result |
| --- | --- |
| Original full discovery before changes | 56 discovered/run, 30 passed, 2 assertion failures, 11 errors, 13 skips |
| Current full discovery | 72 discovered/run, 50 passed, 0 assertion failures, 11 errors, 13 skips |
| New SQLite service safeguard tests | 15 passed; real in-process mock adapter, no Excel or sockets |
| Voice tests (existing + portable regressions) | 6 passed, 2 existing skips (Windows SAPI / real Piper model) |
| `python scripts/demo_local.py` | Passed; actual output in demo-service.json |
| Python compilation | Passed |
| Whitespace formatting and `git diff --check` | Passed; no broad code formatter run |
| Ruff, Bandit, pip-audit | BLOCKED: packages/advisory access unavailable |
| Complete clean installation / Gradio HTTP / actual ASR/TTS | BLOCKED: missing packages/models and socket restriction |
| GitHub Actions | YAML parsed locally; remote execution not performed |

[verification-results.json](verification-results.json) records actual counts, exception types, skips, Python/platform and installed/missing dependency versions. The initial two assertion failures came from a Windows-only guard that prevented Piper selection and bypassed useful text-mode diagnostics on Linux. Those failures are fixed without weakening their assertions.

Eight module-import errors stem from missing openpyxl (and further Pydantic/Gradio dependencies will be required once imports progress). Two ASR preprocessing errors require NumPy/voice dependencies; one simulator HTTP test cannot create sockets: total 11. Do not interpret missing modules as passing or silently skip them.

The source originally defines 123 `test_*` methods. Static counting is not a test run; unavailable imports prevent complete discovery. The edited tree defines 148 methods after 25 additional regressions. The earlier statement of 123 PASS remains historical and unverified in this environment. Existing Excel/model-dependent skips were preserved.

## Confirmed fixes

- Local Piper selection now works independently of Windows. SAPI is platform-specific; failures keep text usable. Cached Piper voices are reloaded when the model path changes; truncated WAVs are handled.
- Invalid/nonfinite limiter windows and HTTP timeouts are rejected before attempting transport.
- Malformed/unknown mutation responses remain uncertain. A registration whose patronymic conflicts with the returned existing card retains its reconciliation guard instead of permitting another POST.
- Malformed doctor/status payloads produce uncertainty without releasing reservations; status verification uses the already identified client instead of an extra lookup.
- An ambiguous directory containing multiple case workbooks is rejected instead of silently choosing one.
- Explicit booking refusal (including «не записывайте меня») invalidates the draft rather than being mistaken for recording control. The UI no longer claims to disable call recording through an unused state flag. Two dependency-free regressions passed; the Pydantic case-flow regression remains blocked with the rest of that module.
- Empty historical CSV exports no longer crash aggregate calculation or invent a peak/period.
- Pydantic is an explicit core dependency; XML hardening is included; speech requirements no longer duplicate the Piper dependency. Full lock resolution is blocked.
- Windows setup no longer relies on a stale `.deps_installed` sentinel or runs resource-dependent tests on every normal UI launch.

## Security and licensing

Offline secret/credential/PII pattern scanning covered all 4 original reachable commits (91 distinct blobs) and the working tree. Two location records refer to the same historical/current **synthetic credential-URL rejection fixture** in `tests/test_http_client.py`; it is not a confirmed credential exposure and requires no rotation. No other scanned pattern matches were found. Test identities are explicitly synthetic. This limited scan does not prove the absence of secrets, unrecognized PII or vulnerable packages.

Four binary blobs (aggregate PNGs and the presentation) require separate manual content/licensing review. PDF text was checked locally by the workspace audit; no credential/email/phone pattern matches were found. This does not establish image-level privacy or redistribution rights. Author metadata was preserved, not published in audit reports. Raw case files, patient/audio databases and secrets remain excluded. An explicit project license and permission to redistribute original case-derived presentation/assets remain owner decisions; no license was invented.

The existing `python scripts/audit_publication.py` gate was also executed: exit 1, two `unexpected_binary` findings (`docs/presentation/clinic-voice-ai-pitch.pdf` and `docs/presentation/cover.png`). These retained presentation assets are not approved by its narrow binary allowlist. The gate was not weakened to hide them. Publication stays blocked until their content/rights are reviewed and an explicit asset policy is recorded; they were not deleted or replaced.

Full dependency vulnerability scanning and remote CI remain blocked. Do not call the prototype production-ready or connect real patient systems based on these checks.

## Showcase implementation follow-up

A cancel/move Result naming the wrong external visit now becomes uncertain; two additional regression tests verify that the original/target locks remain. New UI copy derives actual doctor/slot counts and mode-specific capabilities from the loaded schedule, replacing misleading hardcoded case counts and policies in legacy mode. That helper has a passing offline regression; actual Gradio rendering remains blocked.

The actual synthetic service demo was extended with optional per-operation timing and a verified-event trace, preserving its default JSON contract. Three tests cover real demo execution, trace correspondence and sample quantiles. `benchmark_service.py` ran 30 repetitions after 3 warmups: create/move/cancel medians 2.303/2.105/1.312 ms on AMD Ryzen 7 7735H, 16 logical CPUs, Linux/Python 3.14.7. Raw samples and scope are in `assets/service-benchmark.json`; these are neither speech nor HTTP timings.

`build_showcase.py` rendered captured stdout into a static SVG and an 11-frame, 11-second GIF replay (1040×480, about 309 KiB), plus a measured timing table and an authored architecture diagram. This is actual CLI-result playback, not an invented Gradio screen. SVGs were rasterized for inspection; ffprobe checked GIF dimensions/frame count. The asset validator passed source-text/JSON correspondence, accessible SVG metadata, absence of executable/external SVG content and GIF bounds.

The publication gate explicitly permits the reviewed generated synthetic CLI GIF by exact path/signature/size policy; unrelated binaries still fail. Its current result remains exit 1 for the pre-existing presentation PDF and cover PNG. The original block is not hidden. Actual browser/speech recording, model evaluation, Ruff/Bandit/pip-audit and remote CI remain blocked.
