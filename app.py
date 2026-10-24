"""Local MVP: synthetic MIS only; audio is editable before applying to dialogue."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from core.presentation import schedule_presentation
from core.store import Store
from core.schedule import write_demo_excel, import_excel, import_clinic_excel
from core.service import BookingService
from core.dialog import reply, new_state
from core.voice import transcribe_detailed, synthesize, voice_diagnostics
from core.parse_ru import normalized,parse_patient_birthdate
from core.asr_eval import MicrophoneBenchmark,corpus as benchmark_corpus

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
os.environ.setdefault('GRADIO_TEMP_DIR',str(DATA/'audio_cache'))
os.environ.setdefault('ASR_LOCAL_ONLY','1')
if os.getenv("MIS_MODE", "mock") != "mock":
    raise RuntimeError("Реальный стенд не проверен. Сейчас доступен только локальный MOCK.")
clinic_sources = sorted((DATA/'source').glob('*.xlsx'))
if len(clinic_sources) > 1:
    raise RuntimeError('В data/source должен быть ровно один разрешённый Excel; неоднозначный выбор расписания запрещён.')
store = Store(DATA / ('clinic_demo.sqlite3' if clinic_sources else 'demo.sqlite3'))
if clinic_sources:
    import_clinic_excel(store, clinic_sources[0])
with store.connect() as con:
    ready = con.execute("SELECT 1 FROM doctors LIMIT 1").fetchone()
if not ready:
    sample = DATA / "synthetic_schedule.xlsx"
    if not sample.exists():
        write_demo_excel(sample)
    print(f"Загружено синтетических слотов: {import_excel(store, sample)}")
svc = BookingService(store)

import gradio as gr

UI_COPY = schedule_presentation(store, svc.clinic_mode)
GREETING = UI_COPY['greeting']
DIALOGUE_QUEUE=dict(concurrency_id='dialogue',concurrency_limit=1)


def available_options(state):
    if not state or state.get("step") != "time":
        return gr.update(choices=[], value=None, interactive=False)
    if not state.get("doctor_id") or not state.get("day"):
        return gr.update(choices=[], value=None, interactive=False)
    if svc.clinic_mode:
        from core.clinic_dialog import filtered_slots
        options=[v[-5:] for v in filtered_slots(state,svc)]
    else:
        options = [v[-5:] for v in svc.free_slots(state["doctor_id"], state["day"], limit=100)]
    return gr.update(choices=options, value=None, interactive=bool(options))


def submit_message(message, history, state, voice_enabled):
    history = list(history or [])
    if state and len(state.get('_history',[]))>len(history):history=list(state['_history'])
    if not str(message or "").strip():
        return history, state or new_state(), "", None, available_options(state)
    answer, state = reply(str(message), state, svc)
    state.pop('_voice_before',None);state.pop('_voice_text',None)
    import re
    answer=re.sub(r'\. ID симулятора: [^.]+\. Настоящая МИС не изменялась\.', ' в демо.',answer).replace('Локальная запись','Запись')
    history.extend([{"role": "user", "content": str(message)}, {"role": "assistant", "content": answer}])
    state['_history']=list(history)
    speech = synthesize(answer) if voice_enabled else None
    audio = speech.path if speech else None
    if speech:
        if not audio:gr.Warning('Не удалось озвучить ответ. Он доступен в диалоге.')
    return history, state, "", audio, available_options(state)


def send_recognized(words, history, state, voice_enabled):
    from core.clinic_dialog import YES
    if state and len(state.get('_history',[]))>len(history or []):history=list(state['_history'])
    if state and state.get('step') in ('confirm','cancel_confirm','register_confirm') and normalized(words or '').strip('.!, ') in YES:
        answer='Проверьте сводку и подтвердите кнопкой или введите «да» вручную. Распознанное согласие само по себе ничего не изменяет.'
        history=list(history or [])+[{'role':'user','content':str(words)},{'role':'assistant','content':answer}]
        state['_history']=list(history)
        speech=synthesize(answer) if voice_enabled else None
        return history,state,'',speech.path if speech else None,available_options(state)
    history, state, _, audio, options = submit_message(words, history, state, voice_enabled)
    return history, state, "", audio, options


def send_slot(slot, history, state, voice_enabled):
    if not state or state.get("step") != "time":
        return history, state, None, available_options(state)
    history, state, _, audio, options = submit_message(slot, history, state, voice_enabled)
    return history, state, audio, options


def send_corrected(words,history,state,voice_enabled):
    if state and state.get('_voice_before') is not None:
        if normalized(words or '')==normalized(state.get('_voice_text','')):
            return history,state,words,None,available_options(state)
        before=dict(state['_voice_before'])
        before['_history']=list(state.get('_history',history or []))
        return send_recognized(words,history,before,voice_enabled)
    return send_recognized(words,history,state,voice_enabled)


def asr_settings(profile='Точнее: small'):
    small=DATA/'asr_models/small'
    model=str(small) if profile=='Точнее: small' and (small/'model.bin').is_file() else 'base'
    return dict(model_name=os.getenv('ASR_MODEL') or model,device=os.getenv('ASR_DEVICE','cpu'),
                beam_size=int(os.getenv('ASR_BEAM_SIZE','5')),vad_filter=os.getenv('ASR_VAD','0')=='1')


def recognize_result(audio_path,profile):
    try:return transcribe_detailed(audio_path,**asr_settings(profile))
    finally:
        candidate=Path(audio_path).resolve()
        if candidate.is_relative_to((DATA/'audio_cache').resolve()) and candidate.is_file():candidate.unlink(missing_ok=True)


def recognize(audio_path,profile='Точнее: small'):
    if not audio_path:
        return "", "Сначала запишите аудио в поле микрофона."
    start = time.perf_counter()
    try:
        result = recognize_result(audio_path,profile)
        text = result.text
        duration = time.perf_counter() - start
        if not text:
            return "", f"Речь не распознана за {duration:.1f} с. Повторите короткой фразой."
        source=result.audio
        audio_info=(f"Вход: {source.get('source_rate')} Гц, {source.get('source_channels')} кан.; "
                    f"обработка: 16000 Гц, моно; длина {source.get('duration_seconds',0):.1f} с. "
                    f"Доля предельной амплитуды: {source.get('clipped_fraction',0):.3f}. ") if source else ''
        return text, (f'{Path(result.model).name}, {result.device}, beam={result.beam_size}, VAD={result.vad_filter}. '
                      f'ASR: {result.asr_seconds:.1f} с; загрузка: {result.load_seconds:.1f} с; '
                      f'декодирование: {result.decode_seconds:.1f} с. {audio_info}'
                      f'{result.warning} Проверьте текст перед отправкой.')
    except Exception:
        return '', 'Распознавание недоступно. Проверьте установку ASR и настройки модели. Можно продолжить текстом.'


def _voice_turn(audio_path,history,state,voice_enabled,profile):
    """One normal voice turn; uncertain text and critical consent require review."""
    history=list(history or []);state=state or new_state()
    if len(state.get('_history',[]))>len(history):history=list(state['_history'])
    state.pop('_voice_before',None);state.pop('_voice_text',None)
    yield history,state,'',None,available_options(state),'Распознаю речь…',''
    if not audio_path:
        yield history,state,'',None,available_options(state),'Запишите фразу или напишите сообщение.','empty_audio'
        return
    try:
        result=recognize_result(audio_path,profile)
    except Exception:
        speech=synthesize('Не удалось разобрать запись. Повторите фразу или напишите сообщение.') if voice_enabled else None
        yield history,state,'',speech.path if speech else None,available_options(state),'Не удалось разобрать запись. Повторите или напишите текст.','ASR error (details hidden)'
        return
    diagnostic=f'{Path(result.model).name} / {result.device}; beam={result.beam_size}; VAD={result.vad_filter}; load={result.load_seconds:.2f}s; decode={result.decode_seconds:.2f}s; ASR={result.asr_seconds:.2f}s; audio={result.audio}; confidence={result.confidence}; {result.warning}'
    if result.needs_review or not result.text.strip():
        speech=synthesize('Я не уверен, что верно расслышал. Повторите фразу или исправьте текст.') if voice_enabled else None
        yield history,state,result.text,speech.path if speech else None,available_options(state),'Не уверен в распознавании. Проверьте текст ниже и отправьте исправленный вариант.',diagnostic
        return
    yield history,state,result.text,None,available_options(state),'Готовлю ответ…',diagnostic
    before={key:value for key,value in state.items() if key!='_history'}
    updated,new,_,audio,options=send_recognized(result.text,history,state,voice_enabled)
    new['_voice_before']=before;new['_voice_text']=result.text
    review=new.get('step') in ('register_confirm','confirm','cancel_confirm')
    yield updated,new,result.text,audio,options,('Проверьте данные и подтвердите кнопкой.' if review else 'Ответ готов. Можно говорить дальше.'),diagnostic


def voice_turn(audio_path,history,state,voice_enabled,profile):
    for output in _voice_turn(audio_path,history,state,voice_enabled,profile):
        busy=output[5] in ('Распознаю речь…','Готовлю ответ…')
        yield (*output,gr.update(interactive=not busy),gr.update(interactive=not busy))


benchmark=MicrophoneBenchmark()


def benchmark_reference(phrase_id):
    item=next(r for r in benchmark_corpus() if r['id']==phrase_id)
    return 'Прочитайте: **'+item['text']+'**'


def save_benchmark_audio(audio_path,phrase_id,session):
    session=session or uuid.uuid4().hex
    if not audio_path:return session,'Сначала запишите фразу.',phrase_id
    try:
        count=benchmark.save(audio_path,phrase_id,session)
        next_id=f'{min(20,int(phrase_id)+1):02d}'
        return session,f'Сохранено {count}/20 фраз локально. Можно записать следующую.',next_id
    except (OSError,ValueError,StopIteration):return session,'Не удалось сохранить запись. Повторите.',phrase_id


def run_benchmark(session,progress=gr.Progress()):
    if not session:return [],'Сначала запишите эталонные фразы.'
    small=DATA/'asr_models/small'
    if not (small/'model.bin').is_file():return [],'Для сравнения нужна локальная small. Модели автоматически не скачиваются.'
    try:
        report,_=benchmark.run(session,{
            'base/original':dict(model_name='base',device='cpu',beam_size=1,vad_filter=True,legacy_decode=True),
            'small/current':dict(model_name=str(small),device='cpu',beam_size=5,vad_filter=False)},progress=progress)
        rows=[[r['phrase_id'],r['profile'],r['reference'],r['transcript'],round(r['word_errors']/max(1,r['word_count']),3),
               round(r['char_errors']/max(1,r['char_count']),3),r['field_correct'],round(r['asr_seconds'],2),round(r['total_seconds'],2)] for r in report['results']]
        summary=f"Записано {report['recordings']}/20 фраз. "+('Полный корпус.' if report['complete'] else 'Неполный корпус: вывод предварительный.')
        for model,result in report['summary'].items():
            summary+=f"\n\n**{model}**: WER {result['wer']:.1%}, CER {result['cer']:.1%}; поля {result['field_correct']}/{result['samples']}; медиана ASR {result['median_asr_seconds']:.2f} с, p95 {result['p95_asr_seconds']:.2f} с. По полям: {result['by_field']}."
        return rows,summary+'\n\nАудио, эталоны, транскрипты и полный JSON сохранены в data/asr_benchmark/ локально.'
    except Exception:return [],'Сравнение не завершилось. Записи сохранены; проверьте локальные модели в диагностике.'


def records():
    return [[r["id"], r["patient_name"], r["start_at"], r["doctor"], r["status"],r.get('external_id') or f"MOCK-{r['id']}"]
            for r in svc.mock_records()]


def reset_conversation():
    return ([{"role": "assistant", "content": GREETING}], new_state(), "", "", None,
            gr.update(choices=[], value=None, interactive=False))


def check_voice():
    diagnostic = voice_diagnostics()
    speech = synthesize('Здравствуйте! Это проверка голоса тестовой регистратуры.')
    return speech.path, diagnostic['message'] + '\n\n' + speech.message


def register_demo_patient(name,birthdate,confirmed):
    if not svc.clinic_mode:
        return 'Доступно только в отдельной базе кейса.'
    result=svc.register_synthetic(name,birthdate,confirmed=bool(confirmed))
    return ('Создана/найдена СИНТЕТИЧЕСКАЯ карточка в локальном симуляторе, ID '+str(result.external_id)) if result.kind=='ok' else result.message


def submit_manual_identity(name,birthdate,history,state,voice_enabled):
    if not state or state.get('step') in ('start','done'):
        gr.Warning('Поля ФИО и даты рождения используются на шаге идентификации.')
        return history,state,'',None,available_options(state)
    name=name or state.get('patient')
    birthdate=birthdate or state.get('birthdate')
    if not name or not birthdate or not parse_patient_birthdate(birthdate):
        gr.Warning('Введите вымышленные ФИО и корректную дату рождения.')
        return history,state,'',None,available_options(state)
    state=dict(state);state.update(step='patient',patient=None,birthdate=None,client_id=None)
    return submit_message(name+', '+birthdate,history,state,voice_enabled)


def submit_manual_day(day,history,state,voice_enabled):
    if not state or state.get('step') not in ('day','time','confirm'):
        gr.Warning('Сначала выберите врача.')
        return history,state,'',None,available_options(state)
    return submit_message(day,history,state,voice_enabled)


def operator_queue():
    return [[r['id'],r['priority'],r['status'],r['rule'],r['reason'],
             '; '.join(f'{k}: {v}' for k,v in r['snapshot'].items()),r['api_id'] or 'нет',r['api_status']]
            for r in svc.handoff_queue()]


with gr.Blocks(title="Голосовая регистратура — демо / имитация МИС") as demo:
    gr.Markdown("# Голосовая регистратура — локальное демо")
    gr.Markdown('**ДЕМО — только вымышленные пациенты.** Настоящая МИС и телефонное соединение не подключены.')
    gr.Markdown('Скажите или напишите: **«Мне бы к хирургу в пятницу после обеда»**. Можно исправить любое поле перед подтверждением.')
    gr.Markdown(UI_COPY['policy'])
    with gr.Accordion('Подготовка синтетического пациента — отдельное действие',open=False):
        synthetic_name=gr.Textbox(label='Только вымышленное ФИО (фамилия имя отчество)',value='Тестов Иван Сергеевич')
        synthetic_birth=gr.Textbox(label='Вымышленная дата рождения',value='01.01.1990')
        synthetic_confirm=gr.Checkbox(label='Подтверждаю создание только синтетической карточки в локальном MOCK',value=False)
        synthetic_create=gr.Button('Создать синтетическую карточку')
        synthetic_status=gr.Markdown('Эта форма — альтернатива регистрации в разговоре. Обе используют одну активную базу и команду демо.')
    with gr.Row():
        with gr.Column(scale=2):
            chat = gr.Chatbot(value=[{"role": "assistant", "content": GREETING}], height=400, label="Диалог")
            state = gr.State(new_state())
            flow_status=gr.Markdown('Можно говорить или написать сообщение.')
            msg = gr.Textbox(label="Сообщение", placeholder="Запишите к хирургу", lines=1)
            with gr.Row():
                send = gr.Button("Отправить", variant="primary")
                reset = gr.Button("Начать заново")
            with gr.Row():
                register_yes=gr.Button('Да, создать вымышленную карточку',interactive=False)
                register_no=gr.Button('Не создавать карточку',interactive=False)
                confirm_action=gr.Button('Подтвердить показанную запись / отмену',interactive=False)
            with gr.Accordion('Если голос ошибается: ввести данные вручную',open=False):
                manual_name=gr.Textbox(label='Вымышленные фамилия имя отчество')
                manual_birth=gr.Textbox(label='Дата рождения — ДД.ММ.ГГГГ',placeholder='01.01.1990')
                manual_identity=gr.Button('Использовать эти ФИО и дату рождения')
                manual_day=gr.Textbox(label='Дата приёма — ДД.ММ.ГГГГ')
                manual_day_send=gr.Button('Выбрать дату приёма')
            tts_on = gr.Checkbox(label="Озвучивать ответы", value=True)
            test_voice = gr.Button('Проверить голос')
            gr.Markdown('Если ответ не зазвучал автоматически, нажмите ▶ в плеере.')
            gr.Markdown('### Скажите — помощник ответит\nОстановите запись, чтобы получить ответ. Перед важным действием проверьте данные.')
            mic = gr.Audio(sources=["microphone", "upload"], type="filepath", format='wav',label="Ваше сообщение")
            voice_status=gr.Markdown('Готов к записи.')
            voice_send=gr.Button('Получить ответ на аудиозапись')
            transcript = gr.Textbox(label="Я услышал — можно исправить", lines=2, interactive=True)
            send_asr = gr.Button("Отправить исправленный текст")
            outgoing = gr.Audio(label="Озвученный ответ", interactive=False, autoplay=True)
        with gr.Column(scale=1):
            specialty_search = gr.Dropdown(label='Специальность из Excel', choices=sorted({d['specialty'] for d in svc.doctors()}), interactive=True)
            doctor_search = gr.Dropdown(label='Поиск врача: ФИО / кабинет', choices=[(f"{d['name']} · {d['specialty']} · каб. {d['room']}",d['id']) for d in svc.doctors()], interactive=True)
            select_specialty=gr.Button('Передать специальность в диалог')
            select_doctor=gr.Button('Передать врача в диалог')
            doctor_page = gr.Number(label='Страница врачей (по 10)', value=1, minimum=1, precision=0)
            show_doctors = gr.Button('Показать врачей')
            doctor_table = gr.Dataframe(headers=['ID','Врач','Специальность','Кабинет','Минут'], interactive=False)
            if not any(svc.next_available_days(d['id'], limit=1) for d in svc.doctors()):
                gr.Markdown('⚠ В загруженном расписании нет будущих свободных дат. Нужен актуальный синтетический Excel и сверка; существующие брони автоматически не удаляются.')
            gr.Markdown("### Свободное время")
            quick_times=gr.Radio(choices=[],label='Ближайшие варианты',interactive=True)
            free_time = gr.Dropdown(label="Доступные часы для выбранного врача и дня", choices=[], interactive=False)
            choose_time = gr.Button("Выбрать это время")
            gr.Markdown("Часы появляются после выбора врача и даты. Выбор производится только среди реально свободных слотов локального расписания.")
            with gr.Accordion('Демонстрационные записи',open=False):
                refresh = gr.Button("Обновить таблицу")
                grid = gr.Dataframe(value=records(), headers=["Локальный ID", "Синтетический пациент", "Дата и время", "Врач", "Статус",'ID симулятора'], interactive=False)
            gr.Markdown("**Примеры:** «к терапевту в пятницу», «девять тридцать», «в два часа дня», «15 октября». Для даты рождения лучше ввести цифры.")
    with gr.Accordion('ASR Benchmark — записать и сравнить свой голос',open=False):
        gr.Markdown('Прочитайте 20 подготовленных фраз. Здесь аудио **сохраняется локально**; используйте только указанные вымышленные данные. Для «завтра» эталон — 15.10.2026, только в измерении.')
        bench_session=gr.State(None)
        bench_phrase=gr.Dropdown(choices=[(r['id']+' · '+r['kind'],r['id']) for r in benchmark_corpus()],value='01',label='Фраза')
        bench_reference=gr.Markdown(benchmark_reference('01'))
        bench_mic=gr.Audio(sources=['microphone','upload'],type='filepath',format='wav',label='Прочитайте эталон без добавлений')
        bench_save=gr.Button('Сохранить фразу и перейти к следующей')
        bench_status=gr.Markdown('Пока записей нет. Результат вашего голоса ещё не измерен.')
        bench_run=gr.Button('Сравнить base и small на собранных записях')
        bench_table=gr.Dataframe(headers=['№','Модель','Эталон','Распознано','WER','CER','Поле верно','ASR, с','Всего, с'],interactive=False)
        bench_summary=gr.Markdown('')
    with gr.Accordion('Разработчику — диагностика голоса',open=False):
        asr_profile=gr.Radio(['Точнее: small','Быстрее: base'],value='Точнее: small',label='Локальное распознавание')
        btn_asr=gr.Button('Только распознать, без отправки')
        asr_info=gr.Markdown('Диагностика последней записи появится здесь.')
        tts_info=gr.Markdown('Диагностика синтеза доступна по кнопке «Проверить голос».')
        gr.Markdown(UI_COPY['schedule'] + ' Речевые модели подготовьте заранее; LLM выключена по умолчанию.')
    with gr.Accordion('Административный раздел — очередь оператору (демо)',open=False):
        gr.Markdown('Статус «Требуется оператор» означает заявку, а не телефонное соединение. Только вымышленные данные.')
        incident_refresh=gr.Button('Обновить очередь оператору')
        incident_grid=gr.Dataframe(headers=['ID','Приоритет','Статус','Правило','Причина','Собранные сведения','ID заявки API-симулятора','Сохранение'],interactive=False)
    send.click(submit_message, [msg, chat, state, tts_on], [chat, state, msg, outgoing, free_time],**DIALOGUE_QUEUE)
    msg.submit(submit_message, [msg, chat, state, tts_on], [chat, state, msg, outgoing, free_time],**DIALOGUE_QUEUE)
    btn_asr.click(recognize, [mic,asr_profile], [transcript, asr_info])
    voice_inputs=[mic,chat,state,tts_on,asr_profile]
    voice_outputs=[chat,state,transcript,outgoing,free_time,voice_status,asr_info,mic,voice_send]
    mic.start_recording(lambda:'Записываю…',outputs=voice_status,api_visibility='private')
    mic.stop_recording(voice_turn,voice_inputs,voice_outputs,concurrency_id='dialogue',concurrency_limit=1,trigger_mode='multiple')
    voice_send.click(voice_turn,voice_inputs,voice_outputs,concurrency_id='dialogue',concurrency_limit=1)
    send_asr.click(send_corrected, [transcript, chat, state, tts_on], [chat, state, transcript, outgoing, free_time],**DIALOGUE_QUEUE)
    transcript.submit(send_corrected, [transcript, chat, state, tts_on], [chat, state, transcript, outgoing, free_time],**DIALOGUE_QUEUE)
    choose_time.click(send_slot, [free_time, chat, state, tts_on], [chat, state, outgoing, free_time],**DIALOGUE_QUEUE)
    reset.click(reset_conversation, outputs=[chat, state, msg, transcript, outgoing, free_time],**DIALOGUE_QUEUE)
    refresh.click(records, outputs=grid)
    test_voice.click(check_voice, outputs=[outgoing, tts_info])
    show_doctors.click(lambda spec,page: [[d['id'],d['name'],d['specialty'],d['room'],d['duration']] for d in svc.doctors(spec or '',limit=10,offset=(max(1,int(page or 1))-1)*10)], [specialty_search,doctor_page], doctor_table)
    specialty_search.change(lambda spec: gr.update(choices=[(f"{d['name']} · каб. {d['room']}",d['id']) for d in svc.doctors(spec or '')],value=None), [specialty_search], doctor_search)
    select_specialty.click(submit_message,[specialty_search,chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    select_doctor.click(submit_message,[doctor_search,chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    synthetic_create.click(register_demo_patient,[synthetic_name,synthetic_birth,synthetic_confirm],synthetic_status)
    register_yes.click(lambda history,s,voice: submit_message('да',history,s,voice),[chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    register_no.click(lambda history,s,voice: submit_message('нет',history,s,voice),[chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    confirm_action.click(lambda history,s,voice: submit_message('да',history,s,voice),[chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    manual_identity.click(submit_manual_identity,[manual_name,manual_birth,chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    manual_day_send.click(submit_manual_day,[manual_day,chat,state,tts_on],[chat,state,msg,outgoing,free_time],**DIALOGUE_QUEUE)
    incident_refresh.click(operator_queue,outputs=incident_grid)
    bench_phrase.change(lambda phrase:(benchmark_reference(phrase),None),bench_phrase,[bench_reference,bench_mic])
    bench_save.click(save_benchmark_audio,[bench_mic,bench_phrase,bench_session],[bench_session,bench_status,bench_phrase],concurrency_id='benchmark',concurrency_limit=1)
    bench_run.click(run_benchmark,bench_session,[bench_table,bench_summary],concurrency_id='benchmark',concurrency_limit=1)
    state.change(lambda s:gr.update(choices=[v[-5:] for v in (s or {}).get('offered_times',[])][:3],value=None),state,quick_times)
    state.change(lambda s:((s or {}).get('patient') or '',(s or {}).get('birthdate') or ''),state,[manual_name,manual_birth])
    quick_times.change(send_slot,[quick_times,chat,state,tts_on],[chat,state,outgoing,free_time],concurrency_id='dialogue',concurrency_limit=1)
    state.change(lambda s: gr.update(interactive=bool(s and s.get('step') in ('confirm','cancel_confirm'))),state,confirm_action)
    state.change(lambda s: [gr.update(interactive=bool(s and s.get('step')=='register_confirm'))]*2,state,[register_yes,register_no])
    state.change(lambda s: 'Сценарий: '+{'start':'ожидаем запрос','patient':'нужно ФИО','birthdate':'нужна дата рождения','register_confirm':'подтверждение создания вымышленной карточки','specialty':'выбор специальности','doctor':'выбор врача','day':'выбор даты','time':'выбор времени','confirm':'ожидаем подтверждение','cancel_offer':'перенести или отменить','cancel_confirm':'подтверждение отмены','status_page':'проверка статуса','done':'завершён'}.get((s or {}).get('step'),'уточнение'),state,flow_status)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=True, show_error=True)
