# AGENTS.md — Project constraints

Build only the first checkpoint vertical slice: recording a **synthetic** patient into a test MIS with confirmed doctor/date/slot and no local double bookings.

- Language Python 3.11+; Windows, RTX 4060 Laptop 8GB, 16GB RAM.
- No external cloud services for personal data. No real patient data.
- Never give medical advice. Route medical, urgent, complaint, operator requests to a human (demo shows that handoff is simulated).
- LLM may only parse structured intent; real mutations live exclusively in `core/service.py`.
- Mock MIS is clearly labeled. Do not claim actual MIS integration until OpenAPI/token are verified.
- Schedule from Excel. Actual schema is NOT known; `core/schedule.py` expects only the synthetic template.
- API external limit 10 calls per minute shared; never blindly retry a POST after timeout.
- SQL uniqueness protects all pending/confirmed/uncertain bookings for same doctor+slot.
- Keep test suite green: `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
- Do not change interfaces without updating `docs/contracts.md` and tests.
- Do not touch production systems, secrets, other directories or privileged commands.
