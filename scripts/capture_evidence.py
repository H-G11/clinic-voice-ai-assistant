"""Reproducible synthetic acceptance evidence in an isolated copy of the case DB."""
import json
import sqlite3
import tempfile
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.store import Store
from core.service import BookingService
from core.dialog import reply
from core.voice import synthesize

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(dir=root/'data') as tmp:
    store=Store(Path(tmp)/'evidence.sqlite3')
    with closing(sqlite3.connect(f'file:{root/"data/clinic_demo.sqlite3"}?mode=ro',uri=True)) as src, closing(sqlite3.connect(store.path)) as dst:
        src.backup(dst)
    # Fixed acceptance clock is explicit and isolated, never the product's clock.
    service=BookingService(store,now=lambda:datetime(2026,10,15,9,0))
    patient,birth='Демонстрационный Пациент Иванович','01.01.1990'
    registration=service.register_synthetic(patient,birth,confirmed=True)
    assert registration.kind=='ok'
    doctor=next(d for d in service.doctors('хирург') if service.next_available_days(d['id']))
    day=service.next_available_days(doctor['id'])[0]
    slots=service.free_slots(doctor['id'],day,100)
    state=None;transcript=[]
    def say(text):
        global state
        answer,state=reply(text,state,service)
        transcript.append({'synthetic_input':text,'reply':answer,'step':state['step']})
        assert len(answer.split())<=20,answer
        return answer
    for text in ('запишите к хирургу',patient,birth,doctor['id'],day,slots[0][-5:]): say(text)
    assert state['step']=='confirm' and not service.patient_bookings(patient,birth)
    say('да');created=service.patient_bookings(patient,birth)[0]
    duplicate=service.create(patient,birth,doctor['id'],slots[0])
    assert duplicate.kind=='rejected'
    for text in ('статус записи',patient,birth):say(text)
    for text in ('перенести запись',patient,birth,day,slots[1][-5:],'да'):say(text)
    moved=service.patient_bookings(patient,birth)[0]
    assert moved['start_at']==slots[1] and moved['external_id']==created['external_id']
    for text in ('отменить запись',patient,birth,'отменить','да'):say(text)
    assert not service.patient_bookings(patient,birth)
    say('оператор');say('давит в груди')
    audio=synthesize('Локальная запись отменена. Настоящая медицинская система не изменялась.')
    with store.connect() as con: source_slots=con.execute('SELECT COUNT(*) FROM slots').fetchone()[0]
    result={'mode':'MOCK_ONLY','clock':'2026-10-15 09:00 GMT+4 (isolated acceptance fixture)',
            'source_doctors':len(service.doctors()),'source_slots':source_slots,'synthetic_client_id':registration.external_id,
            'local_booking':created['id'],'simulated_visit_id':created['external_id'],
            'duplicate':duplicate.kind,'moved_using_same_visit_id':True,'cancelled':True,
            'live_api':'NOT RUN','browser_playback':'NOT RUN','tts':'PASS' if audio.path else 'FAIL',
            'wav':str(Path(audio.path).relative_to(root)) if audio.path else None,'transcript':transcript}
    (root/'docs/demo-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='transcript'},ensure_ascii=True))
