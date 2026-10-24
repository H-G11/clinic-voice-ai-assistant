# Публикация первого чекпоинта — 15.10.2026

> Historical author-supplied record. Performance, test counts and device checks below were not reproduced in the 2026-10-24 audit. See [current verification](verification.md) for actual results and blockers.

Публикуется текущий стабильный MOCK MVP; новых продуктовых функций при подготовке релиза не добавлено.
Адрес, предоставленный владельцем: https://github.com/H-G11/clinic-voice-ai-assistant.

- В текущем корне создан Git, основная ветка main; исходной Git-истории не было.
- Существующие базы, исходные материалы, модели, аудио, локальная конфигурация и backups сохранены на диске.
- `.gitignore` исключает `.env.*` (безопасная `.env.example` разрешена), окружение/кэши,
  все исходные Excel/CSV/Word, базы, журналы, benchmark/голос, модели и приватные настройки.
  В data разрешены только проверенные обезличенные aggregate JSON/PNG и код их построения.
  В tests разрешены только четыре проверенных CSV с синтетическими фразами.
- `scripts/audit_publication.py` проверяет кандидатов и реальные staged blobs: пути/размеры,
  бинарные БД, ключи/токены, подозрительные присваивания, email/телефоны. Значения находок не печатаются.
  Вместе с этим выполнен ручной просмотр состава, отчётов и происхождения синтетических транскриптов.
  Автоматический поиск признаков не является математической гарантией отсутствия любых секретов.
- Строка с email-подобным адресом в test_http_client — отрицательный тест URL `example.invalid`,
  а не действующие учётные данные. Единственный встроенный API-токен — публичный fixture local-demo-token.
- Для нового коммита локально выбрана GitHub noreply-идентичность; глобальные настройки Git не изменялись.
- Полный тестовый прогон: **123 PASS, 36,810 с, exit 0**, лог data/github-release-tests.log.
- `start_windows.bat --check`: **123 PASS, 36,910 с, exit 0**, лог data/github-release-launcher.log.
  Логи остаются локально и не публикуются.
- README дополнен схемой архитектуры, установкой зависимостей/моделей и порядком получения Excel
  отдельно у организаторов. Без закрытого Excel доступен ограниченный старый синтетический пример;
  полноценное case DEMO требует импорта. Настоящая МИС и телефония не подключены.

Повтор аудита перед коммитом:

```powershell
.\.venv\Scripts\python.exe scripts/audit_publication.py
git add -A
git diff --cached --name-only
.\.venv\Scripts\python.exe scripts/audit_publication.py --staged
```

Исходные пользовательские материалы не должны попадать ни в индекс, ни в Git-историю.
Force push, очистка пользовательских данных и reset --hard не применялись.
