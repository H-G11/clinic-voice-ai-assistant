# Repository instructions

- Target Python 3.11/3.12. Run `python -m unittest discover -s tests -v`; record failures/skips and missing resources honestly. Do not weaken assertions to make an environment look green.
- Use synthetic patients and temporary demo databases only. Never upload patient records/audio or secrets to external services; do not add private case workbooks to Git.
- No medical advice or real telephone transfer claims. Preserve safety/operator routing and explicit mock labels.
- Appointment mutations belong in `core/service.py`. Speech/LLM output may suggest structured fields, not authorize an operation. Explicit UI consent remains required.
- Preserve pending/confirmed/uncertain reservation constraints, patient/specialty uniqueness, and owned-record/mode isolation. Unknown mutations keep locks; never blindly retry POST/PATCH after timeout.
- The default HTTP clients share a process-local rolling budget below the documented API limit. No real MIS access or live mutations without verified integration and explicit owner approval.
- Keep both legacy synthetic schedule and case-workbook flows. `core/schedule.py` documents their schemas; generated fixtures must identify themselves as synthetic, never as imported case data.
- Interface changes require matching contracts/tests. Check `docs/contracts.md` and `docs/workflows.md` for consent, state and transaction boundaries.
- Showcase images/GIFs must derive from actual execution or be explicitly labeled authored diagrams. Retain data/command provenance and disclose unexecuted ASR/UI paths.
- Historical AI-assisted development records remain under `docs/provenance/`. Preserve authorship and Git history; do not modify production systems or privileged networking.
