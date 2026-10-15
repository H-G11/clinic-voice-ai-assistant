# Progress — 15.10.2026

## Voice quality & natural dialogue — актуальная миссия
- Прочитано новое задание. Владелец ответил, что размеченных записей его голоса нет. Реальное улучшение качества на его голосе НЕ заявляется.
- Откат: `backups/voice-quality-20261015-105814` содержит исходный код, тесты, документы и снимки обеих SQLite. Baseline: **101 PASS, 31,587 с**, `data/voice-quality-baseline.log`.
- A: изучены реальные установленные Gradio Audio.preprocess/audio_from_file/audio_to_file и PyAV/faster-whisper. WAV filepath не усиливается и не обрезается Gradio, crop по умолчанию полный. Вход явно WAV, 16k mono decode без trim/gain. Действующий профиль small/CPU/int8/ru/beam5/noVAD. CUDA device определяется, но реальный small float16 падает на cublas64_12.dll. Драйверы/CUDA не трогались, CPU сохранён. Ollama отсутствует.
- B: ASR Benchmark в UI записывает 20 эталонных синтетических фраз голосом пользователя, хранит оригинал/эталон/транскрипт/модель/тайминги, сравнивает base/small на одних файлах, считает WER/CER и поля отдельно. Аудио/результаты игнорируются Git, не экспортируются в облако. Автоматический HTTP smoke использовал один явно synthetic_test fixture во временной папке; это НЕ человеческий benchmark.
- Дополнительные реальные прогоны на 20 синтетических Piper WAV: small+VAD 17/20 полей, WER 33,9%, CER 34,2%, медиана ASR 4,12 с; small+Excel prompt 17/20, WER 32,3%, CER 33,7%, 4,34 с. Работали параллельно с другой нагрузкой, задержки не сравниваем как controlled performance. Ни VAD, ни prompt не улучшили число верных полей, обычный профиль не меняли. Medium не скачивали. Доказательства: `docs/voice-quality-asr-evidence.json`.
- C: Meaning/Pydantic, детерминированные многопараметрические фразы, исправления даты/времени, after15:00, утро, выбор из последнего списка, остановка черновика, кабинет/стоимость без сброса. Опциональный loopback-only Ollama adapter выключен; ошибки/таймаут/неверный JSON → fallback+circuit. Фактическая LLM-инференция не проверена.
- Найден и исправлен опасный UX-дефект: недоступное исправленное время сохраняло старую готовую сводку. Теперь старое время/подтверждение инвалидируются. «Перенесите на понедельник» для новой незавершённой записи меняет черновик, не ищет несуществующий визит.
- D: stop-recording запускает ASR→ответ, TTS включён, текст исправляем. Эвристически неуверенный/пустой ASR требует проверки; критическое YES само не мутирует. Исправление транскрипта восстанавливает контекст именно той реплики, а не подаёт ФИО в ответ на следующий вопрос. Ручные поля подставляют известные данные. Диагностика в developer panel, максимум три быстрых времени, даты с днями недели.
- Общая очередь Gradio для голоса/текста/подтверждений, серверная история сессии защищает от устаревшего browser history; микрофон отключается на время обработки. HTTP-тест параллельных submissions проверяет сохранность всех реплик независимо от порядка завершения загрузок, не выдаёт simulated ASR за реальную точность.
- Поэтапно: прежние **101 PASS (43,286 с)** после основных изменений; **121 PASS (50,802 с)** с новыми сценариями; **122 PASS (38,769 с)** после дополнительной проверки некорректного времени. Расширенный сценарный файл: 14 PASS (16,525 с), включая исправление распознанного ФИО.
- Сохранность данных текущей миссии PASS: обе базы совпадают с её начальным снимком (`docs/voice-quality-preservation.json`); основная БД дополнительно проверяется до/после каждого HTTP-прогона. Прежняя отменённая запись не восстанавливалась, пользовательский сервер не завершался.
- **Финально: 123 теста PASS, 40,716 с, exit 0** (`data/voice-quality-final-tests.log`). HTTP-прогон PASS: полный жизненный цикл, реальный small ASR на синтетическом WAV, доставка Piper PCM, естественные реплики, очередь быстрых запросов с simulated ASR, UI benchmark на synthetic_test fixture. Основная БД до/после MATCH. Сервер теста 7861 закрыт. `data/voice-quality-ui.log`, `docs/ui-evidence.json`.
- Подробная инструкция: `docs/voice-quality.md`. Требуется ручная запись 20 фраз и прослушивание после перезапуска старого сервера; результаты человека пока не измерены. Тяжёлые модели/драйверы/системные настройки не устанавливались.

## Архив: исправление фактического пользовательского пути
- Полностью прочитан срочный запрос из вложения. Сохранён исходный код/документация в `backups/user-flow-20261015-103337`, затем снимки обеих SQLite. Исходные 84 теста PASS (31,693 с). Git отсутствует.
- Причина блокера: при неизвестном пациенте диалог сбрасывал идентификацию и отправлял к сотруднику; отдельная форма создания была скрыта. Поиск опирался на локальный реестр, который мог не содержать карточку API-симулятора.
- A: точная нормализованная идентификация по активной API-базе/команде; при отсутствии карточки явное предложение MOCK-регистрации через POST /clients. Подтверждение отдельно от записи, контекст сохранён, отказ/REAL не создают карточку. Guard pending/uncertain не допускает слепой повтор POST.
- B: новый пациент с пустых таблиц прошёл реальные HTTP callbacks Gradio до записи/статуса/переноса/отмены/статуса «Отменена». Перенос сохраняет API ID; дубли блокируются. A/B: 89 тестов PASS (31,685 с). Старые тестовые копии сначала наследовали ручные брони и давали шесть падений; исправлена очистка только одноразовых копий, основная база не очищалась.
- C: скачана только small в локальную папку проекта, с разрешением на сетевую загрузку весов; без облачного инференса и без CUDA/cuDNN/драйверов. Проведено четыре прогона по 20 реальным синтетическим Piper WAV: исходная base 13/20 полей, 0,87 с медиана; изменённая base/VAD 12/20, 0,89 с; base beam5/noVAD 13/20, 0,93 с; small beam5/noVAD 17/20, 2,98 с. Это НЕ точность человеческого микрофона. GPU probe перешёл на CPU после ошибки CUDA.
- UI использует кэшированную small/CPU/beam5/noVAD; быстрый профиль base, env overrides сохранены. Добавлены исходная частота/каналы, 16k mono, энергия у краёв, clipping, отдельные load/decode/ASR тайминги. Никакой ручной обрезки. Проверен 48k stereo WAV; распознанное YES не запускает критическую мутацию, доступны ручные поля и кнопка подтверждения.
- D: очередь оператору хранит причину, приоритет, контекст, статус «Требуется оператор». Для проверенного MOCK-клиента POST /escalations, анонимно — только локальный инцидент. Экстренная инструкция независима от patient DB/её блокировок. Телефонного перевода нет. C/D: 95 тестов PASS (39,188 с).
- E: HTTP-проверка дополнительно подтвердила ручные поля и реальное распознавание small с диагностикой. Piper PCM доставляется и для ответа о записи, и для проверки голоса. Пользователь ранее подтвердил слышимость Piper. Протокол `docs/ui-evidence.json`; ASR измерения `docs/asr-evidence.json`, описание и ручная процедура `docs/asr-results.md`.
- Финальный HTTP-прогон exit 0: все перечисленные сценарии PASS; контрольная сигнатура строк основной базы до/после собственного прогона MATCH. Тестовый сервер на 7861 закрыт; пользовательский процесс на 7860 не трогался. Лог `data/user-flow-ui-final.log`.
- Проверка сохранности: 85 врачей/136973 слота, календарь, отсутствия, обе API-карточки и старые три legacy-брони сохранены. Между снимком и итогом одна существовавшая clinic-бронь сменила status confirmed→cancelled, API status «Запланирована»→«Отменена» (updated_at 11:38 GMT+4). Источник изменения не установлен; запись не восстанавливалась/не удалялась. `docs/preservation-evidence.json` честно отмечает это различие. Сквозной тест дополнительно сравнивает содержимое основной базы до/после собственного прогона.
- Последовательные расширенные проверки: 99 тестов PASS (31,610 с), затем 100 PASS (32,859 с). **Окончательно: 101 тест PASS, 31,372 с, exit 0**, включая сбой финального сохранения регистрации без повторного POST. Лог `data/user-flow-final-tests.log`.
- README, contracts, demo_script, acceptance обновлены под путь без скрытой подготовки. Старый сервер требует Ctrl+C и нового запуска `start_windows.bat`; чужой процесс не завершался автоматически.
- Ограничения: живой стенд/API и телефония не подключены; участки/направления/прикрепление без подтверждённых данных; человеческий аудиокорпус не предоставлен. Все новые пациенты и опубликованные транскрипты вымышлены.

## Архив: no-API mission — baseline and Excel stage
- Read CODEX_NO_API_MISSION.md completely; explicit expanded scope supersedes old first-slice restrictions. Live access still absent.
- Baseline PASS 48 tests. Source/SQLite rollback in backups/no-api-baseline-*; source documents copied to ignored data/source/. No Git repository.
- Streamed actual case workbook into separate clinic_demo.sqlite3: verified 85 doctors, 136973 slots. Original demo database preserved.
- Source workbook explicitly labels schedules/statuses as generated hackathon data; no claim of real clinical bookings.
- Added original statuses/room/duration, calendar/absence checks, GMT+4 clock, 14-day horizon and 30-minute same-day lead time. Extended tests and UI search/pagination.
- Excel-stage checks: fixed connection cleanup in copied test DB and corrected assumed end date to actual 30.12.2026 (no 31.12 slots generated). PASS 53 tests.
- API-compatible simulator/adapter stage: PASS 63 tests. Includes doctors pagination, team isolation, clients 200/201, visit PATCH/status/409 and shared read/write rate limit. Local HTTP only.
- Dialogue/regulation stage: a reset-to-intent regression was found and fixed; PASS 69 tests. Synthetic identity comes first; registration is separate and explicitly confirmed. Missing district/referral goes to a demo handoff.
- TTS stage: installed Piper 1.8.0 and one ru_RU-irina-medium local voice with network permission. Real Russian PCM WAV generated (22050 Hz, mono, 6.86 s audio); browser audibility NOT RUN. No cloud inference or driver changes.
- Full suite after TTS/analytics fixes: PASS 72 tests. Extended mutation/timeout/isolation checks: PASS 77 tests. Latest date review run pending.
- CSV totals verified: 17772 calls / 3687 missed / 09:00 peak 2414; 35470 visits / 4079 no-shows / 27080 completed / 4311 cancelled. Local aggregates/PNGs in data/analysis; insights/economics generated. Historical baselines, not measured bot KPIs.
- Reference-sheet provenance migration is additive; source Excel all seven sheets preserved locally. Actual API access remains absent and no live request/mutation has been made.
- Final case corrections: current-day 30-minute cutoff rounds upward; Unicode doctor search is case-insensitive; cancellation corrections cannot accidentally create a new booking. Spoken birthdate extension preserves legacy parser tests and rejects ambiguous years.
- Captured docs/demo-evidence.json from an isolated copy (fixed test clock explicitly labelled): booking/status/same-ID PATCH move/cancel, duplicate refusal, operator/emergency and real Piper WAV PASS.
- scripts/check_ui_e2e.py: actual local HTTP Gradio registration, dialogue and WAV delivery PASS; source main database not mutated. Rechecking booking-reply voice delivery after final UI review.
- Baseline database counts unchanged: 3 doctors, 720 slots, 3 bookings, 3 mock records. New case DB: 85 doctors, 136973 slots, 0 user bookings (tests use copies).
- Fixtures verified: 38 ASR / 50 legacy handoff / 51 regulation phrases. Submission 3119 chars (<8000). Piper model 63201294 bytes, CPU only, ignored in Git.
- Final unit/integration run: PASS 84 tests (32.654 s). Includes a conflicting free-slot fault injected only in a disposable copy: calendar/absence still override the free status.
- `cmd /c start_windows.bat --check` also passed after final API error-code/UI timezone review: 84 tests, 26.804 s, exit 0.
- Final Gradio HTTP acceptance: PASS booking AND actual booking-reply PCM delivery, plus voice diagnostic WAV. Evidence in docs/ui-evidence.json; browser audibility remains NOT RUN.
- No raw CSV callers, hashes or source tables exported. .gitignore covers sources/root source filenames, DBs, logs, models, cache and audio. No Git repository/staged diff/push exists.
- Remaining blockers only: real API URL/token + explicit live mutation approval; source district/referral/attachment verification; human listening and audio-corpus ASR measurement. Local independent work completed; no real MIS integration claimed.
- Logs remain local under data/*.log (ignored). Test product clocks use actual GMT+4; fixed 15.10.2026 09:00 exists only in isolated acceptance fixtures.

## Archived preceding mission (before source materials were supplied)

## Baseline
- Read CODEX_MISSION.md, AGENTS.md, contracts and existing source/tests.
- `git status --short`: no Git repository. No git init, commit or push performed.
- Source rollback copy: `backups/baseline-*`; original data remains in place.
- `.venv\Scripts\python.exe -m unittest discover -s tests -v`: PASS, 14 tests.
- Environment: Python 3.14.6. Real OpenAPI, actual Excel schema and test API authorization absent.
- Initial System.Speech voice enumeration failed with NullReferenceException.

## A — local speech
- Added System.Speech → SAPI COM fallback, Russian voice selection, PCM WAV validation and explicit UI warnings.
- Added voice diagnostic/playback button; TTS enabled by default; existing callback return shapes preserved.
- Changed core/voice.py, app.py, tests/test_voice.py, docs/contracts.md.
- Automated checks: PASS, 18 tests. Real COM enumeration sees Microsoft Irina (Russian).
- Actual synthesis: FAIL, System.Speech NullReferenceException; COM synthesis HRESULT 0x80045040.
- WinRT and 32-bit engine probes also failed. No system changes attempted. Browser audibility NOT RUN.
- A system speech blocker remains; text works and the UI now displays errors. Moving to B per time budget.
- No cloud speech, driver changes, model downloads or live API mutations.

## B — recognition and dialogue
- Extracted boundary-aware handoff rules; 50 labelled regression phrases, including false-positive hospital cases.
- Added 38 phrases for manual ASR evaluation; these are NOT measured ASR accuracy.
- Strict confirmation, date/time/specialty corrections, global reset/operator exits, maximum three spoken slot suggestions.
- ASR exposes load/inference timing, configurable beam/VAD and cached CPU fallback; no larger models installed.
- First regression run found a message compatibility failure (сотрудника); fixed. Final B verification: PASS 27 tests, including mock ASR timing/CPU fallback.
- Blockers: no actual audio recordings for ASR measurement, no OpenAPI/real Excel; Windows speech failure from A remains.

## C — preparation only
- Contract-neutral stdlib HTTP client: shared 8/min limiter, timeout, 429 cooldown, no retry/redirect, reference cache and explicit mutation gate.
- Hardened BookingService handling of malformed adapter output/missing ID/final DB failure.
- Local HTTP fixture covers success, 400/401/403/404/409, 429, 5xx, invalid body, timeout POST and no retries; concurrency and rate window tested.
- Changed core/http_client.py, core/service.py, tests/test_http_client.py, contracts and api-notes.
- RealMIS/live and actual Excel adaptation BLOCKED on missing materials; no test server mutation performed.

## D — local handover preparation
- Prepared architecture, demo script, acceptance checklist, README and submission text; actual voice/live blockers stated explicitly.
- Added UI callback end-to-end test: mock booking completes despite TTS failure; diagnostic status/player wiring tested.
- `scripts/smoke_local.py`: PASS, local Gradio HTTP page and config, own server closed; no booking created.
- Python 3.14/Gradio produced ResourceWarning/WinError 10054 on event-loop/connection shutdown; HTTP probe passed. No dependency upgrades attempted.
- Windows launcher `cmd /c start_windows.bat --check`: PASS (46 tests at that run), exit 0 without launching GUI.
- Main database compared to backup: counts unchanged (3 bookings, 3 mock records, 3 doctors, 720 slots).
- Submission text 2290 characters (<8000); fixture counts verified: 38 ASR, 50 handoff.
- Final review added explicit tests for doctor change, past-date rejection and unsupported/approximate time clarification.
- FINAL: `.venv\Scripts\python.exe -m unittest discover -s tests -v` — PASS, 48 unique tests, 6.369 s, exit 0. Non-failing Gradio/Python event-loop ResourceWarning remains documented above.
- Next priority: actual OpenAPI/Excel integration immediately on receipt; one real synthetic mutation requires explicit owner approval. No live requests made.
- Read-only environment check: faster-whisper 1.2.1, ctranslate2 4.8.3, RTX 4060 Laptop 8 GB, driver 580.88. CUDA/cuDNN execution NOT RUN; no model downloads.
- `.gitignore` reviewed; backups/audio/databases/.env/.venv excluded. No Git repository, therefore no staged diff/commit exists. Secrets were not read.
- No full voice release claim: actual TTS FAIL, browser playback/actual ASR corpus/live API NOT RUN.
