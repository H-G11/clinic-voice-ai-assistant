"""Case-data dialogue, separate from the preserved MVP v2 synthetic scenario."""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from .parse_ru import parse_day,parse_time,parse_patient_birthdate,normalized
from .regulation import route,faq
from .mis import patient_name
from .understanding import understand


def human_day(value):
    day=datetime.fromisoformat(value)
    weekdays=('понедельник','вторник','среда','четверг','пятница','суббота','воскресенье')
    return f'{day:%d.%m.%Y} ({weekdays[day.weekday()]})'

YES={'да','подтверждаю','да подтверждаю','да, подтверждаю','верно','да, все верно'}
NO={'нет','отмена','стоп','не подтверждаю','не надо'}


def fresh():
    return {'step':'start','intent':'book','errors':0,'patient':None,'birthdate':None,
            'doctor_id':None,'specialty':None,'day':None,'time':None,'period':None,'doctor_offset':0}


def _handoff(s,svc,reason,rule,priority='P3',kind='operator'):
    try:return svc.queue_handoff(s,reason=reason,rule=rule,priority=priority,kind=kind)
    except Exception:return {'rule':rule,'priority':priority,'status':'Требуется оператор','connected':False,'api_status':'unavailable'}


def intent(text):
    if re.search(r'отмен|не приду|снять запись|вычеркните',text): return 'cancel'
    if re.search(r'перенес|перенести|перезапис|сдвинуть',text): return 'move'
    if re.search(r'статус|когда я записан|когда.*записан|во сколько.*врачу|мои записи|проверить запись',text): return 'status'
    if re.search(r'график|когда принимает',text): return 'schedule'
    return 'book'


def period(text):
    if re.search(r'после обеда|днем',text): return 'day'
    if re.search(r'утром|с утра',text): return 'morning'
    if re.search(r'вечером|вечер',text): return 'evening'
    return None


def filtered_slots(s,svc):
    values=svc.free_slots(s['doctor_id'],s['day'],100)
    bounds={'morning':('07:30','12:00'),'day':('12:00','16:00'),'evening':('16:00','24:00')}
    if s.get('period') in bounds:
        lo,hi=bounds[s['period']]
        values=[v for v in values if lo<=v[-5:]<hi]
    if s.get('after'):values=[v for v in values if v[-5:]>s['after']]
    if s.get('late'): values.reverse()
    return values


def _summary(s,svc):
    info=svc.slot_info(s['doctor_id'],s['day']+'T'+s['time'])
    if not info:
        s.update(step='time',time=None)
        return 'Это время отсутствует. Выберите другой слот.'
    s['step']='confirm'
    s['room']=info['room']
    day_label=human_day(s['day'])
    return f"{s['patient']}, {s['birthdate']}. {info['name']}, {day_label}, {s['time']}, кабинет {info['room']}. Подтверждаете {'перенос' if s['intent']=='move' else 'запись'}?"


def _ask(s,svc):
    s['errors']=0
    if not s.get('patient'):
        s['step']='patient'; return 'Назовите фамилию, имя и отчество.'
    if not s.get('birthdate'):
        s['step']='birthdate'; return 'Назовите дату рождения: день, месяц и год.'
    if not svc.identify(s['patient'],s['birthdate']):
        if svc.mode=='mock':
            s['step']='register_confirm'
            return f"Тестовой карточки нет. {s['patient']}, {s['birthdate']}. Создать карточку вымышленного пациента? Ответьте «да» или «нет»."
        s['identity_misses']=s.get('identity_misses',0)+1
        if s['identity_misses']>=2:
            s['step']='done';s['handoff']={'rule':'R-07','status':'demo','connected':False}
            return 'Пациент повторно не найден. Карточка передачи оператору сформирована (демо); сведения о записях не сообщаю.'
        s['step']='patient'; s['patient']=None; s['birthdate']=None
        return 'Пациент не найден. Проверьте данные или попросите оператора. Новую карточку автоматически не создаём.'
    s['client_id']=svc.identify(s['patient'],s['birthdate'])
    if s['intent'] in ('cancel','move','status') and not s.get('booking_id'):
        records=svc.patient_bookings(s['patient'],s['birthdate'],include_history=s['intent']=='status')
        if not records:
            s['step']='done'; return 'Будущих локальных записей не найдено. Можно начать новую запись.'
        s['records']=[r['id'] for r in records]
        if s['intent']=='status':
            s['step']='status_page'
            return _status_page(s,svc)
        if len(records)>1:
            s['step']='booking'
            return 'Выберите запись: '+ '; '.join(f"{i+1}: {r['doctor'].split()[0]}, {r['start_at'].replace('T',' ')}" for i,r in enumerate(records[:3]))+'.'
        return _select_booking(s,svc,records[0])
    if not s.get('specialty'):
        s['step']='specialty'; return 'К какому специалисту записать? Выберите специальность из списка или назовите её.'
    docs=svc.doctors(s['specialty'])
    if not docs:
        s.update(specialty=None,doctor_id=None,step='specialty'); return 'Такого специалиста нет в расписании. Выберите доступную специальность из списка.'
    if not s.get('doctor_id'):
        if len(docs)>1:
            s['step']='doctor'
            offset=s.get('doctor_offset',0)
            s['offered_doctors']=[d['id'] for d in docs[offset:offset+3]]
            return 'Выберите врача: '+ '; '.join(f"{i+offset+1}: {d['name']}" for i,d in enumerate(docs[offset:offset+3]))+'. Можно сказать «ещё».'
        s['doctor_id']=docs[0]['id']
    error=svc.eligibility(s['patient'],s['birthdate'],s['doctor_id'])
    if error:
        s['step']='done';s['handoff']=_handoff(s,svc,error,'R-07')
        return error+' Передача сотруднику: демо.'
    if s['intent']=='schedule':
        days=svc.next_available_days(s['doctor_id'])
        s['step']='done'
        return 'Свободные даты из Excel: '+(', '.join(days) if days else 'в пределах 14 дней нет')+'.'
    if not s.get('day'):
        s['step']='day'
        days=[d for d in svc.next_available_days(s['doctor_id'],14) if datetime.fromisoformat(d).weekday() not in s.get('excluded_weekdays',[])][:3]
        s['offered_days']=days
        return 'На какую дату? Свободны: '+(', '.join(human_day(d) for d in days) if days else 'в пределах 14 дней отсутствуют')+'.'
    days=[d for d in svc.next_available_days(s['doctor_id'],limit=14) if datetime.fromisoformat(d).weekday() not in s.get('excluded_weekdays',[])]
    if s['day'] not in days:
        s.update(day=None,time=None,step='day')
        s['offered_days']=days[:3]
        return 'Эта дата недоступна. Выберите: '+(', '.join(human_day(d) for d in days[:3]) if days else 'попросите оператора')+'.'
    available=filtered_slots(s,svc)
    if not s.get('time') or s['day']+'T'+s['time'] not in available:
        s.update(time=None,step='time')
        s['slot_offset']=s.get('slot_offset',0)
        shown=available[s['slot_offset']:s['slot_offset']+3]
        s['offered_times']=shown
        preference=(' после '+s['after']) if s.get('after') else ''
        return 'На '+human_day(s['day'])+preference+' есть '+(', '.join(v[-5:] for v in shown) if shown else 'нет подходящих слотов')+'. Какое время удобно?' if shown else 'Подходящего времени нет. Попробуем другую дату или другой период?'
    return _summary(s,svc)


def _select_booking(s,svc,r):
    if r['status']!='confirmed':
        s['step']='done'; return 'Результат этой записи требует сверки сотрудником. Повторных операций не выполняем.'
    s.update(booking_id=r['id'],doctor_id=r['doctor_id'],specialty=r['specialty'])
    if s['intent']=='cancel':
        s['step']='cancel_offer'
        return f"{r['doctor'].split()[0]}, {r['start_at'].replace('T',' ')}. Можно перенести вместо отмены. Перенести или отменить?"
    s.update(day=None,time=None)
    return _ask(s,svc)


def _status_page(s,svc):
    records=svc.patient_bookings(s['patient'],s['birthdate'],include_history=True)
    offset=s.get('status_offset',0)
    shown=records[offset:offset+3]
    parts=[]
    for r in shown:
        checked=svc.booking_status(s['patient'],s['birthdate'],r['id'])
        status=checked.message if checked.kind=='ok' else 'требует сверки'
        parts.append(f"{r['doctor'].split()[0]}: {human_day(r['start_at'][:10])}, {r['start_at'][-5:]}, кабинет {r['room']}, {status}")
    return '; '.join(parts)+'.'


def _specialty(text,svc):
    specs={d['specialty'] for d in svc.doctors()}
    aliases={'невропатолог':'невролог','окулист':'офтальмолог','гинеколог':'акушер-гинеколог','лор':'лор (отоларинголог)','зубной':'стоматолог-терапевт'}
    for alias,canonical in aliases.items():
        if re.search(r'\b'+alias+r'\w*\b',text) and canonical in specs: return canonical
    for spec in sorted(specs,key=len,reverse=True):
        # Complete inflected profession; longer child/multiword names first.
        stem=spec[:-1] if spec.endswith(('г','т','р')) else spec
        if re.search(r'(?<![а-я])'+re.escape(stem)+r'(?:г|т|р)?(?:у|а)?(?![а-я])',text): return spec
    return None


def reply(message,state,svc):
    s=dict(state or fresh())
    if s.get('step') not in ('start','done') and 'intent' not in s: s=fresh()
    text=normalized(message or '').strip(' .!?')
    decision=route(text,svc.now())
    if decision:
        priority='P1' if decision.kind in ('emergency','urgent') else 'P2' if decision.kind=='complaint' else 'P3'
        card=_handoff(s,svc,message,decision.rule,priority,decision.kind)
        new=fresh(); new['handoff']=card
        return decision.message,new
    if s.get('patient') and re.search(r'дат\w* рождения|я родил',text):
        dob=parse_patient_birthdate(text,svc.now().date())
        if dob:
            s.update(birthdate=dob,client_id=None)
            return _ask(s,svc),s
    meaning=understand(text,svc.now().date(),s.get('day'))
    if meaning.abort and s.get('step') not in ('start','done'):
        return 'Хорошо, остановимся. Новых изменений нет; прежняя запись, если была, сохранена.',dict(s,step='done')
    if meaning.room:
        doctor=next((d for d in svc.doctors() if d['id']==s.get('doctor_id')),None)
        return (f"Кабинет {doctor['room']}." if doctor else 'Сначала выберем врача, затем я назову кабинет.'),s
    if text in ('начать заново','заново','сброс','новая запись','сначала'):
        return 'Начнём заново. Назовите фамилию, имя и отчество синтетического пациента.',dict(fresh(),step='patient')
    if re.search(r'не записыва|против записи(?: разговор)?|без записи разговор',text):
        s['recording_consent']=False
        return 'Запись разговора отключена. Продолжим обслуживание.',s
    if s.get('step')=='register_confirm':
        if text in NO:
            s['step']='done'
            return 'Тестовую карточку не создаём. Можно начать заново, исправить данные или попросить оператора.',s
        if text in YES:
            if svc.mode!='mock':
                s['step']='done';return 'Регистрация в REAL не разрешена. Нужна проверка сотрудника.',s
            result=svc.register_synthetic(s['patient'],s['birthdate'],confirmed=True)
            if result.kind=='ok':
                s['client_id']=int(result.external_id)
                return _ask(s,svc),s
            if result.kind=='uncertain':
                s['step']='done';return 'Результат регистрации неизвестен. Повторно не отправляем; нужна сверка сотрудником.',s
            return result.message,s
        return 'Создать только вымышленную карточку в демо? Ответьте «да» или «нет»; это ещё не запись к врачу.',s
    answer=faq(text)
    if answer:
        s['source']='РГ-ТЕЛ-01; условные сведения'
        return answer,s
    detected=intent(text)
    draft_move=(detected=='move' and meaning.day and s.get('intent')=='book' and s.get('step') in ('doctor','day','time','confirm'))
    if s.get('step') not in ('start','done','cancel_offer') and detected!='book' and detected!=s.get('intent') and not draft_move:
        s=fresh();s['intent']=detected
        s.update(day=meaning.day.isoformat() if meaning.day else None,period=meaning.period,after=meaning.after,time=meaning.time)
        return _ask(s,svc),s
    if s.get('step') in ('start','done'):
        s=fresh(); s['intent']=intent(text)
        s['specialty']=_specialty(text,svc)
        s['day']=meaning.day.isoformat() if meaning.day else None
        s['period']=meaning.period
        s['after']=meaning.after
        s['time']=meaning.time
        return _ask(s,svc),s
    previous=dict(s)
    if meaning.choice and s['step'] in ('doctor','day','time'):
        key={'doctor':'offered_doctors','day':'offered_days','time':'offered_times'}[s['step']]
        choices=s.get(key,[])
        if meaning.choice<=len(choices):
            selected=choices[meaning.choice-1]
            if s['step']=='doctor':s.update(doctor_id=selected)
            elif s['step']=='day':s.update(day=selected,time=None)
            else:s['time']=selected[-5:]
            return _ask(s,svc),s
        return 'В этом списке нет такого варианта. Выберите один из показанных.',s
    if s['step'] not in ('patient','birthdate','register_confirm','cancel_confirm','cancel_offer'):
        changed=False
        if meaning.day:s.update(day=meaning.day.isoformat(),time=None,slot_offset=0);changed=True
        if meaning.period:s.update(period=meaning.period,after=None,time=None,slot_offset=0);changed=True
        if meaning.after:s.update(after=meaning.after,period=meaning.period,time=None,slot_offset=0);changed=True
        if meaning.time and (s['step'] in ('time','confirm') or ':' in text):
            options=filtered_slots(s,svc) if s.get('doctor_id') and s.get('day') else []
            value=parse_time(text,options)
            if value:s['time']=value;changed=True
            elif s['step'] in ('time','confirm'):
                s.update(time=None,step='time')
                return 'Это время недоступно. '+_ask(s,svc),s
        if changed:return _ask(s,svc),s
    if s.get('intent')=='cancel' and s.get('booking_id') and (text in ('другой врач','другое время','другая дата','другой день') or parse_day(text,svc.now().date())):
        s['step']='cancel_offer'
        return 'Для изменения даты или врача выберите «перенести». Отмена пока не выполнена.',s
    if re.search(r'\bне\s+в\s+пятниц',text) and s.get('doctor_id'):
        s.update(excluded_weekdays=[4],day=None,time=None,period=period(text) or s.get('period'))
        return _ask(s,svc),s
    if text in ('другой врач','другого врача','изменить врача'):
        s.update(doctor_id=None,day=None,time=None,doctor_offset=0)
        return _ask(s,svc),s
    new_spec=_specialty(text,svc) if s['step'] not in ('patient','birthdate') else None
    if new_spec and new_spec!=s.get('specialty'):
        if s['intent']=='move': return 'Перенос возможен только внутри прежней специальности.',s
        s.update(specialty=new_spec,doctor_id=None,day=None,time=None,doctor_offset=0)
        return _ask(s,svc),s
    if text in ('другое время','изменить время'):
        s.update(time=None,slot_offset=0)
        return _ask(s,svc),s
    if text in ('другая дата','другую дату','другой день','изменить дату'):
        s.update(day=None,time=None)
        return _ask(s,svc),s
    if s['step'] not in ('patient','birthdate','cancel_confirm','cancel_offer'):
        day=parse_day(text,svc.now().date())
        if day:
            s.update(day=day,time=None,period=period(text) or s.get('period'),slot_offset=0)
            return _ask(s,svc),s
        p=period(text)
        if p:
            s.update(period=p,time=None,slot_offset=0)
            return _ask(s,svc),s
    if text in ('ближайшее','ближайший','пораньше','попозже') and s.get('doctor_id'):
        days=svc.next_available_days(s['doctor_id'])
        s.update(day=days[0] if days else None,time=None,late=text=='попозже')
        return _ask(s,svc),s
    if s['step']=='confirm' and re.search(r'\b(?:нет|лучше|изменить)\b',text):
        value=parse_time(text,filtered_slots(s,svc))
        if value:
            s['time']=value
            return _summary(s,svc),s
    if s['step']=='patient':
        text=normalized(patient_name(text))
        combined=re.match(r'^([а-я-]+ [а-я-]+ [а-я-]+)[, ]+(.+)$',text)
        if combined:
            dob=parse_patient_birthdate(combined.group(2),svc.now().date())
            if dob:
                s.update(patient=' '.join(w.capitalize() for w in combined.group(1).split()),birthdate=dob)
                return _ask(s,svc),s
        if re.fullmatch(r'[а-я-]+(?: [а-я-]+){2}',text):
            s.update(patient=' '.join(w.capitalize() for w in text.split()),step='birthdate')
            return 'Назовите дату рождения: день, месяц и год.',s
    elif s['step']=='birthdate':
        dob=parse_patient_birthdate(text,svc.now().date())
        if dob:
            s['birthdate']=dob
            return _ask(s,svc),s
    elif s['step']=='specialty':
        spec=_specialty(text,svc)
        if spec: s['specialty']=spec; return _ask(s,svc),s
    elif s['step']=='doctor':
        docs=svc.doctors(s['specialty'])
        if text in ('ещё','еще','другие'):
            s['doctor_offset']=(s.get('doctor_offset',0)+3)%max(1,len(docs))
            return _ask(s,svc),s
        matches=[d for d in docs if d['id'].casefold()==text or text in d['name'].casefold().replace('ё','е')]
        if text.isdigit() and 1<=int(text)<=len(docs): matches=[docs[int(text)-1]]
        if len(matches)==1: s['doctor_id']=matches[0]['id']; return _ask(s,svc),s
    elif s['step']=='time':
        if text in ('ещё','еще','другие'):
            s['slot_offset']=(s.get('slot_offset',0)+3)%max(1,len(filtered_slots(s,svc)))
            return _ask(s,svc),s
        value=parse_time(text,filtered_slots(s,svc))
        if value: s['time']=value; return _ask(s,svc),s
    elif s['step']=='booking':
        records=svc.patient_bookings(s['patient'],s['birthdate'])
        if text.isdigit() and 1<=int(text)<=min(3,len(records)):
            return _select_booking(s,svc,records[int(text)-1]),s
    elif s['step']=='status_page':
        if text in ('ещё','еще'):
            s['status_offset']=s.get('status_offset',0)+3
            return _status_page(s,svc),s
    elif s['step']=='cancel_offer':
        if 'перен' in text:
            s.update(intent='move',day=None,time=None); return _ask(s,svc),s
        if 'отмен' in text or text in NO:
            s['step']='cancel_confirm'
            return 'Подтверждаете отмену выбранной локальной записи? Ответьте «да» или «нет».',s
    elif s['step'] in ('confirm','cancel_confirm'):
        if text in NO:
            return 'Операция не выполнена. Исходная запись сохранена.',dict(fresh(),step='done')
        if text in YES:
            if s['step']=='confirm' and s['intent'] not in ('book','move'):
                return 'Уточните действие: запись, перенос или отмена. Изменения не выполнены.',s
            if s['step']=='cancel_confirm':
                result=svc.cancel(s['patient'],s['birthdate'],s['booking_id'],confirmed=True)
                action='отменена'
            elif s['intent']=='move':
                result=svc.reschedule(s['patient'],s['birthdate'],s['booking_id'],s['doctor_id'],s['day']+'T'+s['time'],confirmed=True)
                action='перенесена'
            else:
                result=svc.create(s['patient'],s['birthdate'],s['doctor_id'],s['day']+'T'+s['time'])
                action='создана'
            if result.kind=='ok':
                s['step']='done'; return f'Локальная запись {action}. ID симулятора: {result.external_id}. Настоящая МИС не изменялась.',s
            if result.kind=='uncertain':
                s['step']='done'; return 'Итог неизвестен. Слоты заблокированы до сверки сотрудником; повторно запрос не отправляем.',s
            s['step']='done'; return result.message,s
    # Failed comprehension is counted; meaningful state changes reset the counter.
    s['errors']=previous.get('errors',0)+1
    if s['errors']>=3:
        new=fresh(); new['handoff']=_handoff(s,svc,'Три неудачных уточнения','R-05')
        return 'Не удалось уточнить запрос. Карточка передачи оператору сформирована (демо); соединение не выполняется.',new
    if s['errors']==2: return 'Не удалось понять второй раз. Можно попросить оператора или повторить ответ текстом.',s
    return 'Уточните, пожалуйста, ответ. Можно выбрать значение из списка или написать текстом.',s
