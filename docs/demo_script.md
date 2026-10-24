# Demonstration procedure

## Executed service demonstration

From the repository root, run `python scripts/demo_local.py`. It uses only Python's standard library plus the existing core modules, a temporary SQLite database, fictional patient data and a generated two-slot schedule. The script sets a fixed GMT+4 clock solely to make this fixture reproducible; the application continues using its actual clock.

The script asserts the real results of registration without/with consent, creation, duplicate rejection, status, move without/with consent, same external ID after move, cancellation without/with consent, verified cancelled status and released slots. [demo-service.json](demo-service.json) is its captured output. It does not imitate a conversation, a microphone session or a production integration. No application database is changed.

## Interactive text demonstration

1. Install the core/UI dependencies as documented in the README and launch `python app.py`.
2. With no case workbook, use the small synthetic **new-booking** flow. Select an available doctor/date/time shown by the UI, enter a fictional name and birthdate, and inspect the summary.
3. Before explicit confirmation, inspect the mock records: no new appointment should exist. Reject the summary to demonstrate that nothing is created; repeat and explicitly confirm to create one synthetic appointment.
4. Request an operator or use the provided regression phrases to inspect the simulated handoff. No telephone connection is made.

The legacy small-schedule dialogue does not support the full case registration/move/cancel flow. Use the executed service demo above or an authorized case workbook for those paths. Case-dependent historical transcripts in `ui-evidence.json` were generated in the original author's environment and were not replayed during this audit.

## Optional case and voice demonstration — not reproduced here

Import one authorized synthetic seven-sheet workbook into the separate case database. Use dates actually offered under the current GMT+4 clock and the workbook's finite time range. Do not change the app clock to present expired slots as live availability. Enter a fictional three-part name and birthdate; registration needs separate consent. Review each booking/move/cancel summary before explicitly consenting. Check status through the simulator after each change.

Install local ASR/TTS dependencies and models only if testing voice. Record a clearly synthetic test phrase, review the transcript, correct names/dates, and verify that recognized agreement alone cannot mutate a record. Human microphone accuracy, latency and audible playback need actual recordings and hardware checks; no successful voice demo is claimed in the current audit.
