"""Validated speech meaning; never chooses a slot or executes a mutation."""
from __future__ import annotations
import json,os,re,time
from datetime import date,datetime
from typing import Literal
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from pydantic import BaseModel,ConfigDict,Field
from .parse_ru import normalized,parse_day,parse_time,DIGITS,_words_number


class Meaning(BaseModel):
    model_config=ConfigDict(extra='forbid')
    intent:Literal['book','move','cancel','status']|None=None
    day:date|None=None
    period:Literal['morning','day','evening']|None=None
    after:str|None=Field(default=None,pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    time:str|None=Field(default=None,pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    choice:int|None=Field(default=None,ge=1,le=3)
    abort:bool=False
    room:bool=False


def deterministic(text,today,anchor_day=None):
    s=normalized(text).strip(' .!?')
    positive=re.split(r'\bа не\b',s)[0]
    day=parse_day(positive,today)
    if day is None and re.search(r'сказал|имел[аи]? в виду|числ[ао]|лучше|на\s',positive):
        tail=re.search(r'(?:сказал[аи]?|в виду|числ[ао]|на)\s+([а-я]+(?:\s+[а-я]+)?|\d{1,2})\b',positive)
        if tail:
            token=tail.group(1).strip()
            number=int(token) if token.isdigit() else _words_number(token) or DIGITS.get(token.split()[0])
            if number and 1<=number<=31:
                anchor=date.fromisoformat(anchor_day) if anchor_day else today
                try:day=date(anchor.year,anchor.month,number).isoformat()
                except ValueError:pass
    period='morning' if re.search(r'утром|утра|с утра',s) else 'day' if re.search(r'после обеда|днем',s) else 'evening' if 'вечер' in s else None
    after=None
    match=re.search(r'после\s+(\d{1,2}(?::\d{2})?|[а-я]+)',s)
    if match:
        token=match.group(1)
        hour=int(token.split(':')[0]) if token[0].isdigit() else DIGITS.get(token)
        minute=int(token.split(':')[1]) if ':' in token else 0
        if hour is not None and 0<=hour<24 and 0<=minute<60:
            if 1<=hour<=7 and period!='morning':hour+=12
            after=f'{hour:02d}:'+ (token.split(':')[1] if ':' in token else '00')
    choice=None
    if re.search(r'вариант|первый|второй|третий',s):
        for pattern,value in [(r'перв\w*|\b1\b',1),(r'втор\w*|\b2\b',2),(r'трет\w*|\b3\b',3)]:
            if re.search(pattern,s):choice=value;break
    action='cancel' if re.search(r'отмен.*запис|снять запись',s) else 'move' if re.search(r'перенес|перенести|перезапис',s) else 'status' if re.search(r'статус|мои записи',s) else None
    clock=None
    if not after and not day:
        clock=parse_time(positive)
    elif not after:
        m=re.search(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\b|\bв\s+(?:[а-я]+|\d{1,2})\s+час\w*(?:\s+дня|\s+утра|\s+вечера)?',positive)
        if m:clock=parse_time(m.group())
    return Meaning(intent=action,day=day,period=period,after=after,time=clock,choice=choice,
                   abort=bool(re.fullmatch(r'(?:я )?передумал[аи]?|не хочу записываться|не надо записывать|не записывайте|стоп',s)),
                   room=bool(re.search(r'какой кабинет|каком кабинете|номер кабинета',s)))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def ollama_parse(text,today):
    """Opt-in loopback ONLY; no downloads, CPU only, bounded timeout/output."""
    payload={'model':os.environ['DIALOG_NLU_MODEL'],'stream':False,'think':False,'keep_alive':0,
             'format':Meaning.model_json_schema(),'options':{'temperature':0,'num_predict':160,'num_gpu':0},
             'prompt':f'Извлеки только явно названные параметры записи. Сегодня {today.isoformat()}. Не выполняй действий. Ответ JSON. Реплика: '+text[:1000]}
    request=Request('http://127.0.0.1:11434/api/generate',data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=.8) as response:
        raw=response.read(16385)
    if len(raw)>16384:raise ValueError('Oversized NLU output')
    return json.loads(raw)['response']


_circuit_open=False


def understand(text,today,anchor_day=None,provider=None):
    global _circuit_open
    baseline=deterministic(text,today,anchor_day)
    # No Ollama installed in the audited environment; deterministic is the shipped default.
    if provider is None:
        if not os.getenv('DIALOG_NLU_MODEL') or _circuit_open:return baseline
        provider=ollama_parse
    try:
        started=time.perf_counter()
        candidate=Meaning.model_validate_json(provider(text,today))
        if time.perf_counter()-started>.8:raise TimeoutError('Slow local NLU')
        values=baseline.model_dump()
        for key,value in candidate.model_dump().items():
            if values[key] is None and value is not None:values[key]=value
        return Meaning.model_validate(values)
    except Exception:
        _circuit_open=True
        return baseline
