# Контракты MVP (локальная версия)

- `BookingService.doctors(specialty: str='') -> list[dict]` — id/name/specialty
- `BookingService.free_slots(doctor_id: str, day: str, limit: int=8) -> list[str]` — `YYYY-MM-DDTHH:MM`
- `BookingService.create(patient: str, birthdate: str, doctor_id: str, slot: str) -> Result`
- `Result.kind` — `ok`, `rejected`, `uncertain`; `external_id`, `message`
- `MockMIS.create(local_id, doctor_id, slot, patient, birthdate) -> Result` — **only simulator**
- `RealMIS.create(...)` — Swagger-text adapter implemented; true organizer API not verified and UI LIVE remains disabled.
- `dialog.reply(message: str, state: dict|None, svc: BookingService) -> (text, state)`
- `BookingService.next_available_days(doctor_id, limit=3) -> list[str]` — future dates with free slots.
- `voice.synthesize(text) -> SpeechResult(path, message, seconds)` — local validated PCM WAV or explicit error; never raises engine errors into dialogue.
- `voice.speak(text) -> str|None` — compatibility wrapper.
- `voice.voice_diagnostics() -> dict` — locally installed SAPI voices and safe diagnostic message.
- `voice.transcribe_detailed(path, *, model_name=None, device=None, beam_size=None, vad_filter=None, legacy_decode=False) -> Transcription(text, load_seconds, asr_seconds, device, warning, model, beam_size, vad_filter, audio, decode_seconds)`; `transcribe(path)->str` retained. Optional fields have defaults. `legacy_decode` is for reproducing original prompt/default VAD in benchmarks. CPU int8; CUDA fallback uses cache only. No model loads at startup.
- Safety routing is in `core/safety.py`; `dialog.handoff` remains import-compatible. No real operator transfer. Corpus is a regression fixture, not proof of coverage of all medical language.
- Confirmation accepts only complete explicit agreement phrases. Corrections invalidate the selected value and require confirmation of a new summary.
- `HTTPClient(base_url, headers=None, limiter=None, timeout=8).request(method, path, payload=None, mutation_authorized=False) -> HTTPResult(kind,status,data,retry_after)` — transport only; no real MIS routes or response mapping. Mutation authorization is a caller gate, not a replacement for user consent to real test operations.
- HTTP kinds: `response` (including 4xx; adapter must interpret actual contract), `rate_limited` (no automatic retry), `uncertain` (mutation outcome unknown), `error` (read failed). A 2xx alone never confirms a booking.
- `cached_get(path, ttl=60)` caches only successful reference data; never use for appointment availability. `RateLimiter` defaults to a shared 8 attempts per rolling 60 seconds, one process only. All reads/writes/reconciliation must use the shared client.
- Service converts malformed adapter responses, missing external IDs and final persistence failures to uncertain; the pending reservation continues blocking the slot.
- `BookingService.create` also validates structured patient name, birthdate and selected slot; callers cannot bypass those checks through dialogue state.

`uncertain` blocks the local slot until human/API reconciliation. Never claim success for that status.

To connect live MIS: verify supplied text against actual server/OpenAPI, map doctor IDs and synthetic patients, obtain owner approval for one mutation and verify external ID/read/admin result. None of those live checks has occurred.

## Case Excel / no-API mission (supersedes synthetic-only scope)
- `import_clinic_excel(store,path)->dict` streams all seven supplied sheets, imports only into an empty separate DB, preserves source statuses and returns verified counts. Identical hash is a no-op; changed source requires reconciliation.
- Default case DB: `data/clinic_demo.sqlite3`; legacy `data/demo.sqlite3` is preserved.
- `doctors(specialty='',query='',limit=100,offset=0)` includes room/duration/department/patients from Excel. Source Dxxx IDs are not API numeric IDs.
- Clinic availability: only Свободен, calendar Р, no absence, future, today >=30 minutes, 14 calendar days including today. Uses actual GMT+4 clock, never Description!B5.
- Legacy synthetic template and existing tests remain supported separately.

## Swagger simulator and expanded service
- `MISClient` protocol: create/cancel/reschedule -> Result; MockMIS preserved for legacy tests; SwaggerMIS is the case simulator adapter; RealMIS is HTTP with mutation gate.
- `LocalAPI.request(method,'/api/v1/...',payload,headers,params)->HTTPResult`. Implements doctors, clients, visits, escalations as documented. Default fixture token local-demo-token is public test data. POST visit intentionally does not lock slots; service owns uniqueness.
- `HTTPClient.request(...,params=dict)` encodes only documented query filter names, never tokens. Existing inline query rejection remains. All default clients share a rolling 8/min budget in one process; no automatic mutation retry or redirects.
- API dates DD.MM.YYYY and DD.MM.YYYY HH:MM mean GMT+4, no offset. Source Dxxx is mapped by normalized full name+specialty, overrides explicit, unknown/ambiguous remains unmapped.
- `register_synthetic(full_name,birthdate,confirmed=False)->Result` is a separate MOCK-only service mutation through POST /clients. Failed lookup only proposes registration; `register_confirm` requires explicit consent. Requires surname/name/patronymic. Team+normalized identity guard commits before POST; pending/uncertain never blindly retries. Invalid response ID/final DB persistence failure yields uncertain. REAL registration is prohibited.
- `identify(full_name,birthdate)->int|None`: exact unique normalized synthetic identity. Local lookup reads authoritative api_clients in the active DB and LocalTransport token's team, including cards absent from the old synthetic_patients cache. NFKC, whitespace, comma-separated name, case, ё/е and date formats normalized; candidates never disclosed. `eligibility(...)` requires district/referral permission when applicable; no invented source permissions.
- `patient_bookings(full_name,birthdate,include_history=False)->list[dict]`: default returns verified patient's future active local records in current mis_mode; history includes cancelled/completed for status, excludes superseded reschedule rows. Cancelled status is verified by API GET, not inferred from UI text.
- `booking_status(full_name,birthdate,booking_id)->Result` verifies simulator/API GET response ID/client/doctor/time before reporting a status. Does not release uncertain reservations automatically.
- `cancel(full_name,birthdate,booking_id,confirmed=False)->Result` and `reschedule(full_name,birthdate,booking_id,doctor_id,slot,confirmed=False)->Result` verify ownership, explicit consent, future time and policy. Reschedule uses PATCH on same external visit ID.
- Before PATCH a pending lock is committed. On rejection old booking remains, target is released. Unknown move locks old+new slots. No blind retry. Patient/specialty uniqueness holds through the operation.
- `bookings.mis_mode` prevents MOCK external IDs from being patched in LIVE. RealMIS resolves API client IDs by actual synthetic identity rather than reusing MOCK IDs.
- Case dialogue is `core/clinic_dialog.py`, selected through existing `dialog.reply` when clinic_mode=True. Legacy interface stays available. Case assistant replies ≤20 words; ≤3 choices; fail #2 offers operator, #3 forms demo handoff.
- Regulation source RG-TEL-01; emergency category A -> 103/112, B -> staff/103 outside hours; no real phone transfer. FAQ describes conditional source, not current medical/price advice.
- Piper local CPU creates validated PCM WAV when downloaded model exists; no runtime downloads. Windows SAPI fallback retained. `scripts/check_voice.py` measures only synthesis/file, never human audibility.
- `parse_patient_birthdate` extends the case flow with unambiguous spoken/numeric birthdates; ambiguous two-digit years require clarification. Original conservative `parse_birthdate` contract preserved.
- Input audio cache is inside project and removed after ASR. Local metrics allow only timing/engine/success, no transcripts or patient identifiers.

Piper integration follows the [official Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md). The original developer recorded local synthesis/HTTP WAV checks and user-reported audible playback; those speech checks were not reproduced in the 2026-10-24 audit.

## User-flow correction, 15.10.2026
- Case state retains intent, specialty, doctor/day/time while proposing registration. Successful explicit registration saves client_id and resumes `_ask`; refusal creates nothing. Separate registration form and dialogue share the same service/DB/team.
- Gradio `submit_message` return shape stays five values. `recognize(audio_path,profile='Точнее: small')` adds an optional profile; `asr_settings` respects explicit environment overrides. UI defaults cached small/beam5/no VAD, falls back to cached base, sets ASR_LOCAL_ONLY=1 unless explicitly configured. Errors leave text/manual fields available.
- `prepare_audio(path)` returns 16k mono samples, source rate/channel/duration/peak/clipping fraction and near-edge flags. No implicit trimming; near-edge energy indicates risk, not proven truncation. PyAV decodes microphone/upload audio once. ASR diagnostics separate model load, audio decoding and inference.
- `send_recognized` never executes a critical registration/booking/move/cancel on recognized YES: user must confirm the shown summary with a button or manually typed YES. Editable transcript, manual identity/date fields and exact free-time dropdown remain available.
- `queue_handoff(state,reason,rule='R-02',priority='P3',kind='operator')->dict` immediately creates an in-process incident; service worker persists operator_incidents and, only for a verified MOCK client, POST /escalations. No real phone transfer. Anonymous incidents never invent client_id. Status is «Требуется оператор», connected=False.
- `handoff_queue()->list[dict]` merges persisted and memory incidents; `flush_handoffs(timeout=3)` joins workers for deterministic tests/CLI. Emergency/urgent=P1, complaint=P2, operator=P3. DB/API delays or failure cannot delay the safety instruction. Failed persistence remains visible in memory for this process only.
- `operator_queue()` exposes reason, priority, collected snapshot and API/persistence status in the local administrative section. Synthetic-only local demo; it is not a secured production operator console.
- `scripts/check_ui_e2e.py` runs real Gradio HTTP callbacks against an isolated empty-patient DB copied from the supplied Excel, with labelled fixed test clock. Covers inline registration, create/status/move/same ID/cancel/cancelled status, duplicate protection, operator queue and PCM delivery. Main user DB is never cleared.
- User reported audible Piper playback. Human microphone ASR accuracy remains unmeasured; synthetic corpus results and limitations are in asr-results.md.

## Voice quality / natural dialogue mission
- `Transcription` adds defaulted `needs_review:bool` and `confidence:dict`; `transcribe_detailed` adds optional initial_prompt for explicit experiments. Russian language fixed. Low avg_logprob/no_speech_prob and empty audio require review; confidence is heuristic, not calibrated accuracy. PCM is never trimmed/amplified implicitly.
- `voice_turn(audio,history,state,voice_enabled,profile)` yields nine UI values: history/state/transcript/audio/options/patient status/developer diagnostic/microphone update/send-button update. Microphone stop triggers it; uploads retain a manual trigger. Recording controls are disabled during processing. Empty/uncertain recognition never applies to dialogue and can produce a spoken review request; recognized critical YES never mutates.
- Existing submit_message/recognize return shapes retained. Gradio dialogue events share concurrency_id dialogue, limit 1. `_history` is session-local UI history, never a mutation input or operator snapshot field; it prevents stale queued browser history replacing recent turns.
- `send_corrected` restores `_voice_before` for an edited last auto-applied utterance; unchanged replay does nothing. The next regular text/button/voice turn invalidates this snapshot. It cannot replay an ASR consent as an authorized mutation.
- `core.understanding.Meaning` validates optional intent/date/period/after/time/choice/abort/room, rejects extra keys. Deterministic extraction is default. Optional loopback Ollama is opt-in via DIALOG_NLU_MODEL, never downloads models, requests CPU, bounded output/timeout, disables redirects/proxies; failures open a circuit and use deterministic fallback. Actual Ollama inference not verified.
- Natural corrections keep verified identity and doctor, invalidate old confirmation and revalidate actual slots. Spoken ordinal selection uses only the most recently offered choices. Draft move language changes a draft date; confirmed bookings use existing service PATCH path.
- `MicrophoneBenchmark.save/run` stores audio/reference/transcript/model/latencies and WER/CER/by-field scores in ignored data/asr_benchmark/<session>. Session IDs validated; per-run report files retained. UI uses fixed prepared synthetic references; no cloud. `source_kind=synthetic_test` explicitly labels automated tool tests; user microphone accuracy is not inferred from those tests.
- Diagnostic model/device/RMS/DC/peak/edge/latency data is in a developer panel. Patient UI preserves actual refusal reasons and labels all mutations as demo; internal API IDs are available in administrative records.

## Portfolio audit corrections — 2026-10-24

- `voice.synthesize` selects Piper on any OS; Windows-only SAPI is a fallback. Invalid engine names and missing local engines keep text usable. The Piper cache is keyed by the resolved model path.
- HTTP timeout/window values must be finite and positive (limiter window >=60); limit is an integer in 1..10.
- Unknown/malformed adapter transport results and mismatched registration identity remain `uncertain`, retaining reconciliation guards. A malformed nested doctor field cannot confirm status or a move.
- `booking_status` compares response client ID to the identity already resolved for this request; it does not make a second identity API call.
- Multiple source workbooks are rejected as ambiguous. `.env.example` documents process variables; `.env` is not loaded automatically.
- `scripts/demo_local.py` is an isolated, generated synthetic service/simulator demo, not a case import or voice evaluation. Its fixed clock is fixture-local.
