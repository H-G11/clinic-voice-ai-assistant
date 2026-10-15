import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from core.schedule import import_excel, write_demo_excel
from core.service import BookingService
from core.store import Store
from core.voice import SpeechResult,Transcription


class TestUI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        store=Store(root/'ui.sqlite3')
        write_demo_excel(root/'schedule.xlsx');import_excel(store,root/'schedule.xlsx')
        replacement=patch.object(app,'svc',BookingService(store))
        replacement.start();self.addCleanup(replacement.stop)

    def test_uncertain_and_empty_voice_never_changes_dialogue(self):
        state={'step':'confirm'}
        for result in (Transcription('',0,.1,'cpu'),Transcription('Да',0,.1,'cpu',needs_review=True)):
            with patch.object(app,'recognize_result',return_value=result),patch.object(app,'send_recognized') as send:
                output=list(app.voice_turn('test.wav',[],state,False,'Точнее: small'))[-1]
            send.assert_not_called();self.assertIs(state,output[1])
            self.assertIn('Проверьте',output[5])

    def test_voice_critical_yes_is_spoken_but_not_applied(self):
        state={'step':'confirm'}
        with patch.object(app,'recognize_result',return_value=Transcription('Да',0,.1,'cpu')),\
             patch.object(app,'synthesize',return_value=SpeechResult('reply.wav','ready')),\
             patch.object(app,'submit_message') as send:
            output=list(app.voice_turn('test.wav',[],state,True,'Точнее: small'))[-1]
        send.assert_not_called();self.assertEqual('reply.wav',output[3]);self.assertIs(state,output[1])

    def test_sequential_voice_requests_preserve_history(self):
        state=None;history=[]
        with patch.object(app,'recognize_result',side_effect=[Transcription('к хирургу',0,.1,'cpu'),Transcription('оператор',0,.1,'cpu')]):
            first=list(app.voice_turn('one.wav',history,state,False,'Точнее: small'))[-1]
            second=list(app.voice_turn('two.wav',[],first[1],False,'Точнее: small'))[-1]
        self.assertEqual(4,len(second[0]))
        self.assertEqual('оператор',second[0][-2]['content'])

    def test_recognized_yes_cannot_confirm_critical_action(self):
        for step in ('register_confirm','confirm','cancel_confirm'):
            state={'step':step}
            with patch.object(app,'submit_message') as submit:
                output=app.send_recognized('Да.',[],state,False)
            submit.assert_not_called()
            self.assertIs(state,output[1])
            self.assertIn('кнопкой',output[0][-1]['content'])

    def test_profile_uses_cached_small_and_respects_explicit_settings(self):
        import os
        with patch.dict(os.environ,{'ASR_MODEL':'configured-model','ASR_DEVICE':'cpu','ASR_BEAM_SIZE':'3','ASR_VAD':'1'}):
            options=app.asr_settings()
        self.assertEqual('configured-model',options['model_name'])
        self.assertEqual(3,options['beam_size']);self.assertTrue(options['vad_filter'])

    def test_manual_identity_correction_keeps_doctor_and_intent(self):
        state={'step':'register_confirm','intent':'book','doctor_id':'D010','patient':'ошибка','birthdate':'1990-01-01'}
        with patch.object(app,'submit_message',return_value=('result',)) as submit:
            app.submit_manual_identity('Тестов Иван Сергеевич','01.01.1990',[],state,False)
        changed=submit.call_args.args[2]
        self.assertEqual('D010',changed['doctor_id']);self.assertEqual('book',changed['intent'])
        self.assertIsNone(changed['patient']);self.assertEqual('patient',changed['step'])
    def test_callback_booking_and_voice_failure_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / 'test.sqlite')
            write_demo_excel(root / 'schedule.xlsx')
            import_excel(store, root / 'schedule.xlsx')
            svc = BookingService(store)
            day = svc.next_available_days('d1')[0]
            slot = svc.free_slots('d1', day)[0]
            history, state = [], None
            with patch.object(app, 'svc', svc), patch.object(app, 'synthesize', return_value=SpeechResult(None, 'Synthetic TTS error')), patch.object(app.gr, 'Warning') as warning:
                for message in ('к терапевту ' + day, slot[-5:], 'Иван Тестов', '01.01.1990'):
                    history, state, _, audio, _ = app.submit_message(message, history, state, True)
                    self.assertIsNone(audio)
                self.assertEqual('confirm', state['step'])
                self.assertEqual([], svc.mock_records())
                history, state, _, _, _ = app.submit_message('да', history, state, True)
                self.assertEqual('done', state['step'])
                self.assertEqual(1, len(svc.mock_records()))
                self.assertEqual(5, warning.call_count)

    def test_voice_diagnostic_reaches_player_and_status(self):
        with patch.object(app, 'voice_diagnostics', return_value={'voices': [], 'message': 'Local voices'}), patch.object(app, 'synthesize', return_value=SpeechResult('synthetic.wav', 'Ready')):
            path, message = app.check_voice()
        self.assertEqual('synthetic.wav', path)
        self.assertIn('Ready', message)

    def test_speech_error_not_exposed_as_exception(self):
        with patch.object(app, 'transcribe_detailed', side_effect=RuntimeError('private diagnostic')):
            transcript, info = app.recognize('synthetic.wav')
        self.assertEqual('', transcript)
        self.assertNotIn('private', info)

    def test_text_only_does_not_call_speech(self):
        with patch.object(app, 'synthesize') as speech:
            _, state, _, audio, _ = app.submit_message('оператор', [], None, False)
        speech.assert_not_called()
        self.assertIsNone(audio)
        self.assertEqual('start', state['step'])
