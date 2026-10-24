"""Conservative Russian date/time parsing for demo clinic scheduling.

Only resolves unambiguous values; appointment time is finally validated against
available slots. Intended for locally processed test audio, not medical advice.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
    "июня": 6, "июля": 7, "августа": 8, "сентября": 9,
    "октября": 10, "ноября": 11, "декабря": 12,
}
WEEKDAYS = {
    "понедельник": 0, "понедельника": 0,
    "вторник": 1, "вторника": 1,
    "среду": 2, "среда": 2, "среды": 2,
    "четверг": 3, "четверга": 3,
    "пятницу": 4, "пятница": 4, "пятницы": 4,
    "субботу": 5, "суббота": 5, "субботы": 5,
    "воскресенье": 6, "воскресенья": 6,
}
DIGITS = {
    "ноль": 0, "один": 1, "одна": 1, "одного": 1, "первое": 1, "первого": 1,
    "два": 2, "две": 2, "двух": 2, "второе": 2, "второго": 2,
    "три": 3, "трех": 3, "трёх": 3, "третье": 3, "третьего": 3,
    "четыре": 4, "четвертое": 4, "четвертого": 4,
    "пять": 5, "пятое": 5, "пятого": 5,
    "шесть": 6, "шестое": 6, "шестого": 6,
    "семь": 7, "седьмое": 7, "седьмого": 7,
    "восемь": 8, "восьмое": 8, "восьмого": 8,
    "девять": 9, "девятое": 9, "девятого": 9,
    "десять": 10, "десятое": 10, "десятого": 10,
    "одиннадцать": 11, "одиннадцатое": 11, "одиннадцатого": 11,
    "двенадцать": 12, "двенадцатое": 12, "двенадцатого": 12,
    "тринадцать": 13, "тринадцатое": 13, "тринадцатого": 13,
    "четырнадцать": 14, "четырнадцатое": 14, "четырнадцатого": 14,
    "пятнадцать": 15, "пятнадцатое": 15, "пятнадцатого": 15,
    "шестнадцать": 16, "шестнадцатое": 16, "шестнадцатого": 16,
    "семнадцать": 17, "семнадцатое": 17, "семнадцатого": 17,
    "восемнадцать": 18, "восемнадцатое": 18, "восемнадцатого": 18,
    "девятнадцать": 19, "девятнадцатое": 19, "девятнадцатого": 19,
    "двадцать": 20, "двадцатое": 20, "двадцатого": 20,
    "тридцать": 30, "тридцатое": 30, "тридцатого": 30,
    "сорок": 40, "пятьдесят": 50,
}


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е").strip())


def is_booking_abort(text: str) -> bool:
    """Recognize explicit draft refusal without confusing it with call recording."""
    value = normalized(text).strip(' .!?')
    return bool(re.fullmatch(
        r'(?:я )?передумал[аи]?|не хочу записываться|не надо записывать'
        r'|не записывайте(?: меня)?(?: к врачу| на прием)?|стоп', value,
    ))


def _words_number(value: str) -> int | None:
    words = value.split()
    if len(words) == 1:
        return DIGITS.get(words[0])
    if len(words) == 2 and DIGITS.get(words[0]) in (20, 30, 40, 50):
        units = DIGITS.get(words[1])
        if units is not None and 1 <= units <= 9:
            return DIGITS[words[0]] + units
    return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_day(text: str, today: date | None = None) -> str | None:
    today = today or date.today()
    s = normalized(text)
    if re.search(r'\bне\s+(?:в|на)\s+',s) or re.search(r'\b(?:или|либо)\b',s):
        return None
    if re.search(r"\bпослезавтра\b", s):
        return (today + timedelta(days=2)).isoformat()
    if re.search(r"\bзавтра\b", s):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\bсегодня\b", s):
        return today.isoformat()
    if re.search(r"\bчерез\s+два\s+дня\b", s):
        return (today + timedelta(days=2)).isoformat()
    # ISO date must be checked before dd-mm patterns.
    match = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", s)
    if match:
        candidate = _safe_date(*(int(x) for x in match.groups()))
        return candidate.isoformat() if candidate else None
    # dd.mm.yyyy / dd/mm/yyyy / dd-mm-yyyy
    match = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)", s)
    if match:
        d, m, y = match.groups()
        y = int(y) if y else today.year
        if y < 100:
            y += 2000
        candidate = _safe_date(y, int(m), int(d))
        if candidate and candidate < today and not match.group(3):
            candidate = _safe_date(y + 1, int(m), int(d))
        return candidate.isoformat() if candidate else None
    month_pattern = "|".join(MONTHS)
    match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})(?:\s+(\d{{4}}))?\b", s)
    if match:
        d, name, year = match.groups()
        y = int(year) if year else today.year
        candidate = _safe_date(y, MONTHS[name], int(d))
        if candidate and candidate < today and not year:
            candidate = _safe_date(y + 1, MONTHS[name], int(d))
        return candidate.isoformat() if candidate else None
    # "пятнадцатого октября", "двадцать первого октября"
    match = re.search(rf"\b([а-я]+(?:\s+[а-я]+)?)\s+({month_pattern})(?:\s+(\d{{4}}))?\b", s)
    if match:
        d = _words_number(match.group(1))
        if d is None:
            d = _words_number(match.group(1).split()[-1])
        y = int(match.group(3)) if match.group(3) else today.year
        candidate = _safe_date(y, MONTHS[match.group(2)], d) if d else None
        if candidate and candidate < today and not match.group(3):
            candidate = _safe_date(y + 1, MONTHS[match.group(2)], d)
        return candidate.isoformat() if candidate else None
    for word, weekday in WEEKDAYS.items():
        if re.search(rf"\b{word}\b", s):
            delta = (weekday - today.weekday()) % 7
            if "следующей неделе" in s or "следующую неделю" in s:
                delta = 7 - today.weekday() + weekday
            elif delta == 0:
                delta = 7
            return (today + timedelta(days=delta)).isoformat()
    return None


def _time_candidates(text: str) -> list[str]:
    s = normalized(text)
    explicit = re.search(r"(?<!\d)([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)(?!\d)", s)
    if explicit:
        return [f"{int(explicit.group(1)):02d}:{int(explicit.group(2)):02d}"]
    if re.search(r"\bв час дня\b", s):
        return ["13:00"]
    if re.search(r"\bв час ночи\b", s):
        return ["01:00"]
    # "в 14 часов 30 минут", "в 14 ч", "14 30"
    match = re.search(r"\b([01]?\d|2[0-3])\s*(?:час(?:а|ов)?|ч)\s*(?:([0-5]?\d)\s*(?:минут[уы]?|мин)?)?\b", s)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if ('дня' in s or 'вечера' in s) and hour < 12:
            hour += 12
        return [f"{hour:02d}:{minute:02d}"]
    match = re.search(r"\b(\d{1,2})\s+(\d{2})\b", s)
    if match and 0 <= int(match.group(1)) < 24 and 0 <= int(match.group(2)) < 60:
        return [f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"]
    if "половине" in s or "пол " in s:
        for word, number in DIGITS.items():
            if number and number <= 12 and re.search(rf"\b{word}\b", s):
                hour = (number - 1) % 12
                if 'дня' in s or 'вечера' in s:
                    return [f'{hour+12:02d}:30']
                if 'утра' in s or 'ночи' in s:
                    return [f'{hour:02d}:30']
                return [f'{hour:02d}:30', f'{hour+12:02d}:30']
    # E.g. "в десять тридцать", "в два часа дня".
    match = re.search(r"\b(\d{1,2})\b", s)
    numeric_hour = int(match.group(1)) if match else None
    token_words = re.findall(r"[а-я]+", s)
    # longest first, using adjacent words for "двадцать один"
    number_parts: list[int] = []
    i = 0
    while i < len(token_words):
        candidate = None
        consumed = 1
        if i + 1 < len(token_words):
            candidate = _words_number(" ".join(token_words[i:i+2]))
            if candidate is not None:
                consumed = 2
        if candidate is None:
            candidate = _words_number(token_words[i])
        if candidate is not None:
            number_parts.append(candidate)
        i += consumed if candidate is not None else 1
    hour = numeric_hour if numeric_hour is not None else (number_parts[0] if number_parts else None)
    if hour is None or hour > 23:
        return []
    minute = 0
    if numeric_hour is None and len(number_parts) >= 2 and number_parts[1] < 60:
        minute = number_parts[1]
    if "половина" in s or "половиной" in s:
        minute = 30
    if "четверть" in s:
        minute = 15
    if "дня" in s or "вечера" in s:
        if hour < 12:
            hour += 12
        return [f"{hour:02d}:{minute:02d}"]
    if "утра" in s or "ночи" in s or hour >= 13:
        return [f"{hour:02d}:{minute:02d}"]
    return [f"{hour:02d}:{minute:02d}", f"{hour+12:02d}:{minute:02d}"] if hour <= 11 else [f"{hour:02d}:{minute:02d}"]


def parse_time(text: str, available_slots: list[str] | None = None) -> str | None:
    """Resolve ambiguous AM/PM against real available slots; never invent time."""
    value = normalized(text)
    # Never salvage a valid fragment from an invalid numeric time or alternatives.
    if re.search(r'\b(?:или|либо)\b', value):
        return None
    if re.search(r'\b(?:без|около|примерно)\b', value):
        return None
    numeric = re.findall(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)', value)
    if len(numeric) > 1 or any(int(h) > 23 or int(m) > 59 for h, m in numeric):
        return None
    spaced = re.fullmatch(r'(?:в\s+)?(\d{1,2})\s+(\d{2})', value)
    if spaced and (int(spaced.group(1)) > 23 or int(spaced.group(2)) > 59):
        return None
    times = _time_candidates(text)
    if available_slots is None:
        return times[0] if times else None
    available = {str(s)[-5:] for s in available_slots}
    choices = [t for t in times if t in available]
    return choices[0] if len(choices) == 1 else None


def parse_birthdate(text: str) -> str | None:
    s = normalized(text)
    m = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)", s)
    if m:
        d, mo, y = map(int, m.groups())
        result = _safe_date(y, mo, d)
    else:
        mo_pattern = "|".join(MONTHS)
        m = re.search(rf"\b(\d{{1,2}})\s+({mo_pattern})\s+(\d{{4}})\b", s)
        result = _safe_date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))) if m else None
    if result and date(1900,1,1) <= result <= date.today():
        return result.strftime("%d.%m.%Y")
    return None


def parse_patient_birthdate(text: str, today: date | None = None) -> str | None:
    """Case dialogue extension; ambiguous two-digit birth years are never guessed."""
    today=today or date.today()
    exact=parse_birthdate(text)
    if exact:
        value=datetime.strptime(exact,'%d.%m.%Y').date()
        age=today.year-value.year-((today.month,today.day)<(value.month,value.day))
        return exact if value<=today and age<=110 else None
    s=normalized(text)
    candidate=None
    short=re.search(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2})(?!\d)',s)
    if short:
        day,month,yy=map(int,short.groups())
        choices=[]
        for century in (1900,2000):
            value=_safe_date(century+yy,month,day)
            if value and value<=today and today.year-value.year-((today.month,today.day)<(value.month,value.day))<=110:
                choices.append(value)
        candidate=choices[0] if len(choices)==1 else None
    else:
        month_pattern='|'.join(MONTHS)
        m=re.search(rf'\b([а-я]+(?:\s+[а-я]+)?)\s+({month_pattern})\s+(.+)$',s)
        if m:
            day=_words_number(m.group(1)) or _words_number(m.group(1).split()[-1])
            year_text=m.group(3).strip(' .,')
            year=int(year_text) if re.fullmatch(r'\d{4}',year_text) else None
            if year is None and year_text.startswith('тысяча девятьсот '):
                tail=year_text.removeprefix('тысяча девятьсот ')
                decades={'шестьдесят':60,'шестидесятого':60,'семьдесят':70,'семидесятого':70,
                         'восемьдесят':80,'восьмидесятого':80,'девяносто':90,'девяностого':90}
                number=_words_number(tail) or decades.get(tail)
                parts=tail.split()
                if number is None and len(parts)==2 and parts[0] in decades and DIGITS.get(parts[1]) in range(1,10):
                    number=decades[parts[0]]+DIGITS[parts[1]]
                if number: year=1900+number
            if day and year: candidate=_safe_date(year,MONTHS[m.group(2)],day)
    if candidate and candidate<=today and today.year-candidate.year-((today.month,today.day)<(candidate.month,candidate.day))<=110:
        return candidate.strftime('%d.%m.%Y')
    return None
