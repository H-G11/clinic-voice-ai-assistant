import unittest
from datetime import date
from unittest.mock import patch
import test_user_journey
from core.understanding import understand,Meaning


@unittest.skipUnless(test_user_journey.SOURCE.exists(),'Case Excel required')
class TestNaturalDialog(unittest.TestCase):
    setUp=test_user_journey.TestNewPatientJourney.setUp
    tearDown=test_user_journey.TestNewPatientJourney.tearDown
    say=test_user_journey.TestNewPatientJourney.say

    def identity(self,first='запишите к хирургу'):
        for text in (first,'Новый Вымышленный Сергеевич','02.02.1992','да'):answer=self.say(text)
        return answer

    def draft(self):
        self.identity()
        doctor=next(d for d in self.service.doctors('хирург') if self.service.next_available_days(d['id']))
        self.say(doctor['id']);day=self.service.next_available_days(doctor['id'])[0];self.say(day)
        slots=self.service.free_slots(doctor['id'],day,100)
        self.say(slots[0][-5:])
        self.assertEqual('confirm',self.state['step'])
        return doctor,slots

    def test_multiple_parameters_and_after_three(self):
        self.identity('Мне бы к хирургу в пятницу после обеда')
        self.assertEqual(('хирург','2026-10-16','day'),(self.state['specialty'],self.state['day'],self.state['period']))
        doctor=next(d for d in self.service.doctors('хирург') if any(v[-5:]>'15:00' for v in self.service.free_slots(d['id'],'2026-10-16',100)))
        self.say(doctor['id']);answer=self.say('Лучше после трёх')
        self.assertEqual('15:00',self.state['after'])
        self.assertEqual('2026-10-16',self.state['day'])
        self.assertIn('15:00',answer)
        self.assertTrue(all(v[-5:]>'15:00' for v in self.state['offered_times']))

    def test_date_correction_keeps_identity_and_doctor(self):
        doctor,_=self.draft();identity=self.state['client_id']
        self.say('17 октября')
        self.say('Нет, я сказал шестнадцатого, а не семнадцатого')
        self.assertEqual(doctor['id'],self.state['doctor_id'])
        self.assertEqual(identity,self.state['client_id'])
        self.assertEqual('2026-10-16',self.state['day'])
        self.assertIsNone(self.state['time'])

    def test_clock_correction_and_repeat_confirmation_no_duplicate(self):
        _,slots=self.draft()
        self.say('Лучше в '+slots[1][-5:])
        self.assertEqual(slots[1][-5:],self.state['time'])
        self.assertEqual('confirm',self.state['step'])
        self.assertEqual([],self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992'))
        self.say('да');self.say('да')
        self.assertEqual(1,len(self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992')))

    def test_unavailable_clock_invalidates_old_summary(self):
        self.draft();answer=self.say('Лучше в 23:59')
        self.assertIn('недоступно',answer)
        self.assertIsNone(self.state['time'])
        self.assertNotEqual('confirm',self.state['step'])
        self.say('да')
        self.assertEqual([],self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992'))

    def test_second_offered_time(self):
        self.draft();self.say('Другое время')
        selected=self.state['offered_times'][1]
        self.say('Тогда второй вариант')
        self.assertEqual(selected[-5:],self.state['time'])
        self.assertEqual('confirm',self.state['step'])

    def test_room_and_price_interrupt_without_reset(self):
        doctor,_=self.draft();before=dict(self.state)
        self.assertIn(str(doctor['room']),self.say('А какой кабинет?'))
        self.assertEqual(before,self.state)
        self.assertIn('стоимость',self.say('Можно сначала узнать, сколько это стоит?'))
        self.assertEqual(before,{k:self.state[k] for k in before})

    def test_abort_draft(self):
        self.draft();self.say('Я передумал')
        self.assertEqual('done',self.state['step'])
        self.assertEqual([],self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992'))

    def test_move_draft_to_monday_and_morning(self):
        doctor,_=self.draft();identity=self.state['client_id']
        self.say('Хотя нет, перенесите на понедельник')
        self.assertEqual('book',self.state['intent'])
        self.assertEqual(identity,self.state['client_id'])
        self.assertEqual(doctor['id'],self.state['doctor_id'])
        self.say('А утром что-нибудь есть?')
        self.assertEqual('morning',self.state['period'])
        self.assertEqual(identity,self.state['client_id'])

    def test_medical_and_operator_interrupt_draft(self):
        self.draft();answer=self.say('Не могу дышать')
        self.assertIn('103',answer);self.assertEqual('P1',self.state['handoff']['priority'])
        self.say('оператор');self.assertEqual('P3',self.state['handoff']['priority'])
        self.assertEqual([],self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992'))

    def test_editing_recognized_name_replaces_that_turn_not_next_question(self):
        import app
        from core.voice import Transcription
        self.say('к хирургу')
        with patch.object(app,'svc',self.service),patch.object(app,'recognize_result',return_value=Transcription('Ошибков Иван Сергеевич',0,.1,'cpu')):
            output=list(app.voice_turn('fixture.wav',[],self.state,False,'Точнее: small'))[-1]
            self.assertEqual('birthdate',output[1]['step'])
            corrected=app.send_corrected('Вернов Иван Сергеевич',output[0],output[1],False)
        self.assertEqual('Вернов Иван Сергеевич',corrected[1]['patient'])
        self.assertEqual('birthdate',corrected[1]['step'])
        self.assertEqual('хирург',corrected[1]['specialty'])


class TestValidatedUnderstanding(unittest.TestCase):
    def test_llm_timeout_and_invalid_json_fall_back(self):
        for response in (TimeoutError(),'{bad json','{"time":"99:90"}','{"execute_booking":true}'):
            def provider(*args):
                if isinstance(response,Exception):raise response
                return response
            value=understand('в пятницу после обеда',date(2026,10,15),provider=provider)
            self.assertEqual(date(2026,10,16),value.day)
            self.assertEqual('day',value.period)

    def test_nlu_cannot_override_known_date(self):
        value=understand('в пятницу',date(2026,10,15),provider=lambda *args:'{"day":"2026-10-20"}')
        self.assertEqual(date(2026,10,16),value.day)

    def test_spoken_ordinal_date_correction(self):
        value=understand('Нет, я сказал шестнадцатого, а не семнадцатого',date(2026,10,15),'2026-10-17')
        self.assertEqual(date(2026,10,16),value.day)

    def test_invalid_time_preference_is_not_an_exception(self):
        value=understand('после 3:99',date(2026,10,15))
        self.assertIsNone(value.after)
