"""Exercise actual Gradio HTTP callbacks in a temporary case-DB copy."""
import json
import sqlite3
import tempfile
import sys
import wave
import hashlib
from contextlib import closing
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from gradio_client import Client,handle_file
from core.store import Store
from core.service import BookingService
from core.voice import Transcription
from core.asr_eval import MicrophoneBenchmark
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]


def source_signature():
    digest=hashlib.sha256()
    with closing(sqlite3.connect(f'file:{root/"data/clinic_demo.sqlite3"}?mode=ro',uri=True)) as con:
        for table in ('doctors','slots','bookings','api_clients','api_visits','api_escalations','synthetic_patients','operator_incidents'):
            for row in con.execute(f'SELECT * FROM {table} ORDER BY 1'):
                digest.update(repr(row).encode('utf-8'))
    return digest.digest()


before=source_signature()
with tempfile.TemporaryDirectory(dir=root/'data') as tmp:
    tmp=Path(tmp);store=Store(tmp/'ui.sqlite3')
    with closing(sqlite3.connect(f'file:{root/"data/clinic_demo.sqlite3"}?mode=ro',uri=True)) as src,closing(sqlite3.connect(store.path)) as dst:
        src.backup(dst)
    store.setup()
    with store.connect() as con:
        for table in ('bookings','mock_mis','api_visits','api_escalations','api_clients','synthetic_patients','client_registrations','operator_incidents'):
            con.execute(f'DELETE FROM {table}')
    original=app.svc
    app.svc=BookingService(store,now=lambda:datetime(2026,10,15,9))
    try:
        _,url,_=app.demo.launch(server_name='127.0.0.1',share=False,inbrowser=False,prevent_thread_lock=True,quiet=True)
        client=Client(url,verbose=False,download_files=tmp/'downloads',analytics_enabled=False)
        assert app.svc.store.path==app.svc.mis.store.path==app.svc.mis.transport.api.store.path
        doctor=next(d for d in app.svc.doctors('хирург') if app.svc.next_available_days(d['id']))
        day=app.svc.next_available_days(doctor['id'])[0]
        slot=app.svc.free_slots(doctor['id'],day)[0]
        history=[];transcript=[]
        def say(message,voice=False):
            global history
            output=client.predict(message,history,voice,api_name='/submit_message')
            history=output[0]
            content=history[-1]['content']
            answer=content if isinstance(content,str) else ' '.join(p.get('text','') for p in content)
            transcript.append({'synthetic_input':message,'reply':answer})
            return output,answer
        for message in ('запишите к хирургу','Тестов Иван Сергеевич','01.01.1990'): _,answer=say(message)
        assert 'Создать карточку' in answer,answer
        assert app.svc.identify('Тестов Иван Сергеевич','01.01.1990') is None
        say('да')  # separate client registration consent; no hidden setup form
        for message in (doctor['id'],day,slot[-5:]):say(message)
        assert not app.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990')
        output,answer=say('да',voice=True)
        assert output[2],'Booking reply audio missing'
        with wave.open(str(output[2]),'rb') as wav: assert wav.getnframes()>0
        assert len(app.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990'))==1
        created=app.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990')[0]
        assert slot not in app.svc.free_slots(doctor['id'],day,100)
        assert app.svc.create('Тестов Иван Сергеевич','01.01.1990',doctor['id'],slot).kind=='rejected'
        for message in ('статус записи','Тестов Иван Сергеевич','01.01.1990'):_,answer=say(message)
        assert 'Запланирована' in answer,answer
        newslot=app.svc.free_slots(doctor['id'],day,100)[0]
        for message in ('перенести запись','Тестов Иван Сергеевич','01.01.1990',day,newslot[-5:],'да'):_,answer=say(message)
        assert 'перенесена' in answer,answer
        moved=app.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990')[0]
        assert moved['external_id']==created['external_id'] and moved['start_at']==newslot
        for message in ('статус записи','Тестов Иван Сергеевич','01.01.1990'):_,answer=say(message)
        assert newslot[-5:] in answer,answer
        for message in ('отменить запись','Тестов Иван Сергеевич','01.01.1990','отменить','да'):_,answer=say(message)
        assert 'отменена' in answer,answer
        for message in ('статус записи','Тестов Иван Сергеевич','01.01.1990'):_,answer=say(message)
        assert 'Отменена' in answer,answer
        assert newslot in app.svc.free_slots(doctor['id'],day,100)
        say('оператор');say('давит в груди')
        app.svc.flush_handoffs()
        queue=client.predict(api_name='/operator_queue')
        assert 'Требуется оператор' in str(queue),queue
        assert 'P1' in str(queue) and 'P3' in str(queue),queue
        say('запишите к хирургу')
        manual=client.predict('Резервов Пётр Тестович','03.03.1991',history,False,api_name='/submit_manual_identity')
        assert 'Создать карточку' in str(manual[0]),manual
        assert app.svc.identify('Резервов Пётр Тестович','03.03.1991') is None
        asr_probe='NOT RUN (local corpus/model required)'
        if (root/'data/asr_eval/piper/01.wav').is_file() and (root/'data/asr_models/small/model.bin').is_file():
            words,diagnostic=client.predict(handle_file(str(root/'data/asr_eval/piper/01.wav')),'Точнее: small',api_name='/recognize')
            assert words and 'small' in diagnostic and '16000' in diagnostic,(words,diagnostic)
            asr_probe='PASS small / actual audio / diagnostics / HTTP'
        reset=client.predict(api_name='/reset_conversation');history=reset[0]
        natural='Мне бы к хирургу в пятницу после обеда'
        output,answer=say(natural)
        for message in ('Тестов Иван Сергеевич','01.01.1990',doctor['id']):say(message)
        say('А какой кабинет?');say('Можно сначала узнать, сколько это стоит?')
        say('Я передумал')
        reset=client.predict(api_name='/reset_conversation');history=reset[0]
        # Simulated ASR tests queue/state handling only, never claimed as real voice accuracy.
        clips={'01.wav':natural,'16.wav':'Тестов Иван Сергеевич','18.wav':'01.01.1990'}
        def simulated_asr(path,profile):return Transcription(clips[Path(path).name],0,.01,'cpu',model='synthetic-test-stub')
        with patch.object(app,'recognize_result',side_effect=simulated_asr):
            jobs=[client.submit(handle_file(str(root/'data/asr_eval/piper'/name)),history,False,'Точнее: small',api_name='/voice_turn') for name in clips]
            outputs=[job.result() for job in jobs]
        lengths=sorted(len(output[0]) for output in outputs)
        assert lengths==[len(history)+2,len(history)+4,len(history)+6],lengths
        latest=max(outputs,key=lambda output:len(output[0]))
        assert '01.01.1990' in str(latest[0]) and 'Иван' in str(latest[0]),latest[0]
        # Benchmark callbacks use one explicitly synthetic fixture in a disposable folder.
        with patch.object(app,'benchmark',MicrophoneBenchmark(tmp/'benchmark',source_kind='synthetic_test')):
            status,phrase=client.predict(handle_file(str(root/'data/asr_eval/piper/01.wav')),'01',api_name='/save_benchmark_audio')
            assert '1/20' in status and phrase=='02',(status,phrase)
            table,summary=client.predict(api_name='/run_benchmark')
            assert 'WER' in summary and 'CER' in summary and 'base/original' in summary,summary
            assert 'small/current' in str(table),table
        audio,message=client.predict(api_name='/check_voice')
        assert audio,message
        with wave.open(str(audio),'rb') as wav:
            assert wav.getnframes()>0
        assert before==source_signature(),'Main DB changed during the test; review external activity, do not restore automatically'
        result={'inline_registration':'PASS','no_setup_form_used':True,'same_database_and_team':True,
                'ui_http_booking':'PASS','status_before_and_after_cancel':'PASS','reschedule_same_id':'PASS','duplicate_blocked':'PASS',
                'booking_voice_delivery':'PASS','ui_http_wav_delivery':'PASS','voice_engine':'Piper local CPU',
                'operator_queue_http':'PASS','emergency_no_client':'PASS','manual_identity_http':'PASS','asr_http':asr_probe,
                'source_db':'isolated empty-patient copy','main_db_mutations':False,'main_db_signature_before_after':'MATCH',
                'browser_audibility':'user reported PASS','live_api':'NOT RUN',
                'natural_dialog_http':'PASS','rapid_voice_http':'PASS (simulated ASR, actual HTTP queue)',
                'microphone_benchmark_http':'PASS instrumentation on synthetic fixture only','human_asr_accuracy':'NOT MEASURED (no recordings supplied)',
                'synthetic_transcript':transcript}
        (root/'docs/ui-evidence.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='synthetic_transcript'}))
    finally:
        app.svc.flush_handoffs()
        app.demo.close();app.svc=original
