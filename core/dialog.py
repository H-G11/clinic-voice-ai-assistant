"""Deterministic, safer, friendly demo dialogue. Intent model is NOT required."""
from __future__ import annotations

import re
from datetime import date, datetime
from .service import BookingService
from .parse_ru import parse_day, parse_time, parse_birthdate, is_booking_abort
from .safety import handoff, HANDOFF_MESSAGE

SPECIALTIES = {
    "терапевт": ("терапевт", "терапевту", "терапевта", "терапии"),
    "невролог": ("невролог", "неврологу", "невролога"),
    "хирург": ("хирург", "хирургу", "хирурга"),
    "кардиолог": ("кардиолог", "кардиологу", "кардиолога"),
    "офтальмолог": ("офтальмолог", "окулист", "окулисту"),
    "лор": ("лор", "отоларинголог", "ухо горло нос"),
    "педиатр": ("педиатр", "педиатру", "педиатра"),
}
WEEKDAYS = ("понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье")


def extract_specialty(text: str) -> str | None:
    t = text.lower().replace("ё", "е")
    for specialty, forms in SPECIALTIES.items():
        if any(re.search(rf"(?<![а-я]){re.escape(form)}(?![а-я])", t) for form in forms):
            return specialty
    return None


def extract_day(text: str) -> str | None:
    return parse_day(text)


def extract_time(text: str) -> str | None:
    return parse_time(text)


def extract_birthdate(text: str) -> str | None:
    return parse_birthdate(text)


def new_state() -> dict:
    return {"step": "start", "specialty": None, "day": None, "time": None,
            "doctor_id": None, "doctor_name": None, "patient": None, "birthdate": None}


def _friendly_date(value: str) -> str:
    d = date.fromisoformat(value)
    return f"{d.strftime('%d.%m.%Y')} ({WEEKDAYS[d.weekday()]})"


def _next_days(svc: BookingService, doctor_id: str) -> str:
    days = svc.next_available_days(doctor_id, limit=3)
    if not days:
        return "В загруженном расписании пока нет других свободных дат."
    return "Ближайшие варианты: " + ", ".join(_friendly_date(d) for d in days) + "."


def _ask_next(s: dict, svc: BookingService) -> str:
    if not s.get("specialty"):
        s["step"] = "specialty"
        specs = sorted({doc["specialty"] for doc in svc.doctors()})
        return ("Конечно, помогу записаться. К какому специалисту вам нужно? "
                + ("В расписании есть: " + ", ".join(specs) + "." if specs else "Врачи пока не загружены."))
    doctors = svc.doctors(s["specialty"])
    if not doctors:
        s.update(specialty=None, doctor_id=None, doctor_name=None)
        s["step"] = "specialty"
        return "К сожалению, в загруженном расписании такого специалиста нет. Назовите другого врача."
    if not s.get("doctor_id"):
        if len(doctors) > 1:
            s["step"] = "doctor"
            names = "; ".join(f"{i+1}. {d['name']}" for i, d in enumerate(doctors[:3]))
            return f"Можно выбрать врача: {names}. Назовите фамилию или номер."
        s["doctor_id"] = doctors[0]["id"]
        s["doctor_name"] = doctors[0]["name"]
    if not s.get("day"):
        s["step"] = "day"
        return "На какой день вас записать? Например, завтра, в пятницу или 16 октября. " + _next_days(svc, s["doctor_id"])
    try:
        day = date.fromisoformat(s["day"])
    except (ValueError, TypeError):
        s["day"] = None
        s["step"] = "day"
        return "Пожалуйста, назовите дату ещё раз."
    if day < date.today():
        s["day"] = None
        s["step"] = "day"
        return "Эта дата уже прошла. Выберите будущий день. " + _next_days(svc, s["doctor_id"])
    available = svc.free_slots(s["doctor_id"], s["day"], limit=100)
    if not available:
        s["step"] = "day"
        s["day"] = None
        s["time"] = None
        return "На этот день свободного времени нет. " + _next_days(svc, s["doctor_id"]) + " Какой день вам удобнее?"
    if not s.get("time") or f'{s["day"]}T{s["time"]}' not in available:
        s["time"] = None
        s["step"] = "time"
        relevant = [v for v in available if not s.get('after_noon') or v[-5:] >= '12:00']
        options = ", ".join(v[-5:] for v in relevant[:3])
        if not relevant:
            options = ", ".join(v[-5:] for v in available[:3])
        return (f"На {_friendly_date(s['day'])} у {s['doctor_name']} свободны: {options}. "
                "Выберите время голосом или из списка справа.")
    if not s.get("patient"):
        s["step"] = "patient"
        return "Отлично. Назовите, пожалуйста, фамилию и имя тестового пациента."
    if not s.get("birthdate"):
        s["step"] = "birthdate"
        return "Назовите дату рождения тестового пациента. Можно ввести её цифрами: 01.01.1990."
    s["step"] = "confirm"
    return (f"Проверим всё перед записью. Пациент: {s['patient']}, дата рождения: {s['birthdate']}. "
            f"Врач: {s['doctor_name']}. Дата: {_friendly_date(s['day'])}, время: {s['time']}. "
            "Подтверждаете? Ответьте «да» или «нет».")


def _initial_time(text: str) -> str | None:
    # Never mistake the day of month for a time in an initial combined request.
    t = text.lower()
    if re.search(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", t) or re.search(r"\b\d{1,2}\s*(час|ч\b)", t):
        return parse_time(text)
    return None


def reply(message: str, state: dict | None, svc: BookingService) -> tuple[str, dict]:
    if getattr(svc,'clinic_mode',False) is True:
        from .clinic_dialog import reply as clinic_reply
        return clinic_reply(message,state,svc)
    s = dict(state or new_state())
    t = re.sub(r"\s+", " ", (message or "").strip())
    if not t:
        return "Не расслышала. Повторите, пожалуйста, или напишите сообщение.", s
    if handoff(t):
        return HANDOFF_MESSAGE, new_state()
    norm = t.lower().replace("ё", "е").strip(".!, ")
    if norm in ("начать заново", "сброс", "заново", "новая запись", "сначала"):
        fresh = new_state()
        fresh['step'] = 'specialty'
        return "Начнём заново. К какому специалисту вас записать?", fresh
    if s.get('step') not in ('start', 'done') and is_booking_abort(t):
        return "Запись не создана. Можно начать заново.", new_state()
    if s.get("step") in ("start", "done"):
        if any(x in norm for x in ("отменить запись", "перенести", "статус записи")):
            return ("Сейчас проверена только новая запись. Перенос и отмена ещё в разработке. "
                    "Для помощи обратитесь к оператору."), s
        s = new_state()
        s["specialty"] = extract_specialty(t)
        s["day"] = extract_day(t)
        s['after_noon'] = 'после обеда' in norm
        s["time"] = _initial_time(t)
        return _ask_next(s, svc), s
    # Corrections precede confirmation and always require a fresh summary/yes.
    corrected_day = extract_day(t) if s.get('step') not in ('patient', 'birthdate') else None
    correction = bool(re.search(r'\b(?:нет|изменить|поменять|лучше|хотел\w*|друг\w*)\b', norm))
    specialty = extract_specialty(t)
    if specialty and specialty != s.get('specialty'):
        s.update(specialty=specialty, doctor_id=None, doctor_name=None, day=None, time=None)
        return _ask_next(s, svc), s
    if corrected_day and (s.get('step') == 'day' or correction):
        s.update(day=corrected_day, time=None, after_noon='после обеда' in norm)
        return _ask_next(s, svc), s
    if norm in ("другую дату", "другой день", "изменить дату", "другая дата"):
        s.update(day=None, time=None)
        s["step"] = "day"
        return _ask_next(s, svc), s
    if norm in ('другое время', 'изменить время', 'другие часы', 'нет, другое время'):
        s['time'] = None
        return _ask_next(s, svc), s
    if correction and s.get('doctor_id') and s.get('day') and re.search(r'\b(?:в|на)\s+\d{1,2}:\d{2}\b', norm):
        available = svc.free_slots(s['doctor_id'], s['day'], limit=100)
        s['time'] = parse_time(t, available)
        return _ask_next(s, svc), s
    if norm in ("другой врач", "другого врача", "изменить врача"):
        s.update(specialty=None, doctor_id=None, doctor_name=None, day=None, time=None)
        s["step"] = "specialty"
        return _ask_next(s, svc), s
    if s["step"] == "confirm":
        if norm in ("нет", "отмена", "не подтверждаю", "стоп", "не надо"):
            return "Хорошо, запись не создана. Можем начать заново.", new_state()
        if norm in ('да', 'верно', 'подтверждаю', 'согласен', 'согласна', 'да, подтверждаю', 'да подтверждаю', 'да, все верно', 'да все верно'):
            slot = f'{s["day"]}T{s["time"]}'
            result = svc.create(s["patient"], s["birthdate"], s["doctor_id"], slot)
            if result.kind == "ok":
                s["step"] = "done"
                return (f"Готово, тестовая запись создана. {s['doctor_name']}, "
                        f"{_friendly_date(s['day'])} в {s['time']}. "
                        f"Номер в локальной имитации МИС: {result.external_id}."), s
            if result.kind == "uncertain":
                s["step"] = "done"
                return "Не удалось проверить итог записи. Повторно её не создаём до сверки с системой.", s
            s["time"] = None
            return "Создать запись не удалось: " + result.message + ". " + _ask_next(s, svc), s
        return "Прежде чем создавать запись, мне нужно услышать чёткое «да» или «нет».", s
    if s["step"] == "specialty":
        s["specialty"] = extract_specialty(t)
        if not s["specialty"]:
            return _ask_next(s, svc), s
    elif s["step"] == "doctor":
        docs = svc.doctors(s["specialty"])
        selected = None
        if norm.isdigit() and 1 <= int(norm) <= len(docs):
            selected = docs[int(norm)-1]
        else:
            matches = [d for d in docs if d["name"].lower().startswith(norm) or norm in d["name"].lower()]
            if len(matches) == 1:
                selected = matches[0]
        if not selected:
            return "Не смогла определить врача. " + _ask_next(s, svc), s
        s["doctor_id"], s["doctor_name"] = selected["id"], selected["name"]
    elif s["step"] == "day":
        s["day"] = extract_day(t)
        if not s["day"]:
            return "Не удалось понять дату. Попробуйте «завтра», «в пятницу» или «16 октября».", s
        s["time"] = None
    elif s["step"] == "time":
        available = svc.free_slots(s["doctor_id"], s["day"], limit=100)
        s["time"] = parse_time(t, available)
        if not s["time"]:
            return ("Не удалось выбрать свободное время. Скажите «девять тридцать» "
                    "или выберите точное время из списка справа. " + _ask_next(s, svc)), s
    elif s["step"] == "patient":
        words = t.split()
        if not (2 <= len(words) <= 3) or len(t) > 90 or not all(re.fullmatch(r"[А-Яа-яЁё-]+", x) for x in words):
            return "Назовите, пожалуйста, вымышленные фамилию и имя: например, Иван Тестов.", s
        s["patient"] = t
    elif s["step"] == "birthdate":
        s["birthdate"] = extract_birthdate(t)
        if not s["birthdate"]:
            return "Дату рождения не разобрала. Лучше введите цифрами, например 01.01.1990.", s
    return _ask_next(s, svc), s
