# Interactive, speech and case setup

Use the virtual-environment Python created in the README: `.venv/bin/python` on Linux/macOS, `.\.venv\Scripts\python.exe` on Windows. Commands below use `python` as shorthand. Python 3.11/3.12 is the target; the available offline audit interpreter is 3.14.7. Clean installation and actual Gradio execution are still blocked in the restricted environment.

## Text UI

Install `requirements.txt`, run `python -m pip check`, then `python app.py` and open `http://127.0.0.1:7860`. Without a case workbook the app creates a small synthetic schedule for new bookings only. Enter a fictional name/birthdate, choose a genuinely available date/time, inspect the summary and explicitly confirm. Declining must create nothing.

`start_windows.bat` installs core/UI requirements and launches text mode; `--check` runs tests and needs the full test dependencies below. Configuration is via environment, **not an automatically loaded .env file**. `.env.example` documents defaults. Keep `MIS_MODE=mock`; live UI is disabled.

## Optional speech

```bash
python -m pip install -r requirements-voice.txt -r requirements-tts.txt
python scripts/download_asr_small.py
python -m piper.download_voices ru_RU-irina-medium --data-dir data/models
python app.py
```

Use `export NAME=value` in Bash or `$env:NAME="value"` in PowerShell. `ASR_DEVICE=cpu` uses int8; cached small is preferred by the UI. `ASR_LOCAL_ONLY=1` blocks implicit downloads. `TTS_ENGINE=piper` uses the local voice; `auto` can fall back to SAPI only on Windows; `DISABLE_TTS=1` disables output.

Review model and voice terms. Verify microphone capture, transcript correction, actual audibility and latencies on the target machine. Human ASR quality and a genuine voice/UI demo were not measured during this showcase run. Recognized agreement alone cannot mutate a record; use a manual confirmation after reviewing the summary.

## Authorized case workbook

Place exactly one authorized synthetic seven-sheet Excel in `data/source/`. `python scripts/import_clinic.py` uses a separate `data/clinic_demo.sqlite3`, records source hash and refuses replacing populated data with another workbook. Run `python app.py` afterward. [Schema and availability rules](contracts.md).

Current time is actual GMT+4, with a 14-calendar-day horizon and same-day 30-minute lead time. Never change the app clock to present expired slots as live availability. The service benchmark's fixed clock is isolated to its generated fixture. If no real slots remain in the finite case workbook, request an authorized updated fixture instead of inventing availability.

The case flow supports separately consented synthetic registration, owned booking status, same-ID move and cancellation. `scripts/check_ui_e2e.py` is an existing HTTP integration procedure requiring the imported case DB/models; it is not executable evidence from this restricted environment. No real MIS or telephone service is involved.
