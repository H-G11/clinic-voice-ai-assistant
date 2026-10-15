# Приёмка — no-API миссия, 15.10.2026

PASS означает выполненный автоматический тест/локальный прогон, а не настоящую МИС.

Актуальное обновление: `docs/voice-quality.md`. Новые сценарии проверяют многопараметрическую
реплику, исправление даты/времени, выбор второго варианта, прерывания, неподтверждённый/пустой ASR,
редактирование ФИО после автоматического ответа, локальный benchmark и ошибки опциональной LLM.
HTTP-очередь быстрых голосовых запросов проверяется с явно simulated ASR; фактическая ASR отдельно — на Piper WAV.
Записей человека нет: качество на голосе владельца **NOT MEASURED**, инструмент готов к ручной проверке.
Актуальный финальный набор: **123 PASS, 40,716 с, exit 0**; Gradio HTTP PASS с MATCH основной базы до/после.

| Сценарий | Статус | Доказательство |
|---|---|---|
| Исходные 48 тестов | PASS | baseline перед новой миссией |
| 85 врачей / 136973 слота | PASS | import_clinic.py, test_clinic_schedule |
| Первая/последняя строка | PASS | S000001 / S136973; фактический конец 30 декабря |
| Excel serial dates / время-доля | PASS | test_clinic_schedule |
| Исходный занятой слот недоступен | PASS | test_clinic_schedule |
| Отпуск / выходной / неизвестный врач | PASS | test_clinic_schedule |
| 14 дней / 30 минут сегодня | PASS | test_clinic_schedule |
| Атомарная бронь / одна специальность | PASS | test_clinic_schedule |
| Отдельное подтверждение клиента | PASS | test_clinic_mutations |
| Нет раскрытия без идентификации | PASS | test_clinic_dialog / team isolation |
| Пустая база пациентов → регистрация → запись → статус → перенос → отмена → отменённый статус | PASS | test_user_journey, реальные HTTP callbacks: ui-evidence.json |
| Перенос сохраняет visit ID | PASS | demo-evidence.json / PATCH tests |
| Таймаут переноса удерживает оба слота | PASS | test_clinic_mutations |
| Отказ переноса сохраняет старую запись | PASS | test_clinic_mutations |
| Конкурентный перенос — один PATCH | PASS | test_clinic_mutations |
| Нет записи по неоднозначному согласию | PASS | test_safety_dialog / case flow |
| Направление/участок без данных → сотрудник | PASS | eligibility tests; источник проверки отсутствует |
| 50 старых и 51 регламентная safety-фраза | PASS | CSV regression fixtures; не гарантия полной семантической безопасности |
| A → 103/112, B вне часов → 103 | PASS | test_clinic_dialog |
| Третье непонимание → карточка демо | PASS | test_clinic_dialog |
| FAQ / ≤20 слов, ≤3 варианта | PASS | tests + transcript assertions |
| Swagger пагинация и изоляция команд | PASS | test_swagger_simulator |
| 400/401/404/409/429/500 и timeout | PASS | local HTTP tests, no live evidence |
| RealMIS на фиктивном транспорте | PASS | doctor paging/cache/occupancy tests |
| Локальный русский PCM, непустой сигнал | PASS | test_voice, check_voice.py |
| Настоящие HTTP callbacks Gradio / WAV | PASS | check_ui_e2e.py, ui-evidence.json |
| Прослушивание человеком в браузере | USER PASS | пользователь подтвердил слышимость Piper; WAV delivery проверена автоматически |
| ASR на 20 синтетических Piper WAV / WER / latency | PASS | asr-results.md, asr-evidence.json: четыре конфигурации, small 17/20 против исходной base 13/20 |
| ASR на живой речи пользователя | NOT RUN | нужна ручная запись 20 вымышленных фраз; синтетика не заменяет этот замер |
| ASR через Gradio HTTP с диагностикой | PASS | ui-evidence.json: small, фактическое аудио |
| Ручной ввод ФИО/даты через Gradio HTTP | PASS | ui-evidence.json, без предварительной отдельной формы |
| Распознанное «да» не выполняет мутацию | PASS | test_ui: регистрация/запись/отмена требуют кнопки или ручного подтверждения |
| 48k stereo → 16k mono, длина/края | PASS | test_asr: реальный PCM, сохранение длительности |
| Очередь P1/P2/P3, API только при подтверждённом client_id | PASS | test_operator_queue, HTTP operator_queue |
| Экстренный ответ при заблокированной базе | PASS | test_operator_queue: ответ <0,5 с, persistence в worker |
| Неопределённая регистрация не повторяет POST | PASS | test_user_journey: timeout, malformed ID, final persistence failure |
| Агрегаты исторических CSV | PASS | report.py, test_analysis, insights.md |
| Настоящий API / админка организаторов | NOT RUN | URL/токен не выданы |
| Прикрепление / реальные направления | NOT RUN | входных данных нет |
| Реальный перевод, SMS, напоминания | NOT RUN | не реализованы |

Архив предыдущей миссии: исходные 84 теста сохранены; тогда **101 тест PASS, 31,372 с, exit 0**.
Gradio HTTP: полный путь без скрытой подготовки, операторская очередь, ручные поля, small ASR и TTS — PASS (docs/ui-evidence.json).
Тестовые пациенты/брони создаются только в одноразовых копиях. Сверка исходного снимка честно фиксирует
смену статуса одной прежней clinic-записи на отменённую; источник изменения не установлен, автоматического восстановления нет.
Расписание, карточки и все legacy-записи совпали. Подробности: docs/preservation-evidence.json.
