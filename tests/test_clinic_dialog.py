import unittest
from core.dialog import reply
from core.regulation import route,faq,FAQ
from datetime import datetime
import test_clinic_schedule


@unittest.skipUnless(test_clinic_schedule.SOURCE_DB.exists(),'Case import required')
class TestCaseFlows(unittest.TestCase):
    setUp=test_clinic_schedule.TestClinicSchedule.setUp
    tearDown=test_clinic_schedule.TestClinicSchedule.tearDown

    def flow_to_confirm(self):
        s=None
        for text in ('запишите к хирургу','Тестов Иван Сергеевич','01.01.1990'):
            answer,s=reply(text,s,self.svc)
            self.assertLessEqual(len(answer.split()),20,answer)
        doc=next(d for d in self.svc.doctors('хирург') if self.svc.next_available_days(d['id']))
        _,s=reply(doc['id'],s,self.svc)
        day=self.svc.next_available_days(doc['id'])[0]
        _,s=reply(day,s,self.svc)
        slot=self.svc.free_slots(doc['id'],day)[0]
        answer,s=reply(slot[-5:],s,self.svc)
        self.assertEqual('confirm',s['step'],answer)
        self.assertIn('кабинет',answer)
        self.assertLessEqual(len(answer.split()),20)
        return s,doc,slot

    def test_booking_status_move_cancel_end_to_end(self):
        s,doc,slot=self.flow_to_confirm()
        self.assertEqual([],self.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990'))
        _,s=reply('да, но время другое',s,self.svc)
        self.assertEqual([],self.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990'))
        answer,s=reply('да',s,self.svc)
        self.assertIn('создана',answer)
        self.assertNotIn(slot,self.svc.free_slots(doc['id'],slot[:10],100))
        for text in ('статус записи','Тестов Иван Сергеевич','01.01.1990'):
            answer,s=reply(text,s,self.svc)
        self.assertIn('кабинет',answer)
        for text in ('начать заново','перенести запись','Тестов Иван Сергеевич','01.01.1990'):
            answer,s=reply(text,s,self.svc)
        # Start/reset followed by an intent must be recognized before name collection.
        self.assertEqual('day',s['step'],answer)
        _,s=reply(slot[:10],s,self.svc)
        newslot=self.svc.free_slots(doc['id'],slot[:10],100)[0]
        _,s=reply(newslot[-5:],s,self.svc)
        answer,s=reply('да',s,self.svc)
        self.assertIn('перенесена',answer)
        self.assertIn(slot,self.svc.free_slots(doc['id'],slot[:10],100))
        for text in ('отменить запись','Тестов Иван Сергеевич','01.01.1990','отменить','да'):
            answer,s=reply(text,s,self.svc)
        self.assertIn('отменена',answer)
        self.assertIn(newslot,self.svc.free_slots(doc['id'],slot[:10],100))

    def test_unknown_identity_and_missing_referral(self):
        s=None
        for text in ('к неврологу','Тестов Иван Сергеевич','01.01.1990'):
            answer,s=reply(text,s,self.svc)
        doctor=self.svc.doctors('невролог')[0]
        answer,s=reply(doctor['id'],s,self.svc)
        self.assertIn('Направление',answer)
        self.assertEqual('done',s['step'])
        self.assertFalse(self.svc.identify('Незнакомый Тестовый Пациент','01.01.1990'))

    def test_operator_emergency_and_three_failures(self):
        s=None
        for text in ('к хирургу','???','???','???'):
            answer,s=reply(text,s,self.svc)
        self.assertIn('R-05',s['handoff']['rule'])
        answer,s=reply('давит в груди',s,self.svc)
        self.assertIn('103',answer)
        self.assertEqual('R-01',s['handoff']['rule'])

    def test_cancel_correction_never_creates_a_new_booking(self):
        s,doc,slot=self.flow_to_confirm()
        _,s=reply('да',s,self.svc)
        for text in ('отменить запись','Тестов Иван Сергеевич','01.01.1990'):
            _,s=reply(text,s,self.svc)
        answer,s=reply('другой врач',s,self.svc)
        self.assertEqual('cancel_offer',s['step'])
        self.assertEqual(1,len(self.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990')))
        self.assertIn('не выполнена',answer)


class TestRegulation(unittest.TestCase):
    def test_extended_birthdate_is_conservative(self):
        from core.parse_ru import parse_patient_birthdate
        today=datetime(2026,10,15).date()
        self.assertEqual('01.01.1990',parse_patient_birthdate('первого января 1990',today))
        self.assertEqual('01.01.1990',parse_patient_birthdate('первого января тысяча девятьсот девяностого',today))
        self.assertEqual('12.03.1978',parse_patient_birthdate('12.03.78',today))
        self.assertIsNone(parse_patient_birthdate('12.03.20',today))
        self.assertIsNone(parse_patient_birthdate('31.02.78',today))
    def test_regulation_corpus(self):
        import csv
        from pathlib import Path
        with Path(__file__).with_name('regulation_phrases.csv').open(encoding='utf-8',newline='') as f:
            values=list(csv.DictReader(f))
        self.assertGreaterEqual(len(values),40)
        for row in values:
            with self.subTest(text=row['text']):
                decision=route(row['text'],datetime(2026,10,15,10))
                self.assertEqual(row['kind'],decision.kind if decision else 'none')
    def test_category_a_and_b(self):
        for text in ('давит в груди','ребенок посинел','не может дышать','отошли воды','перекосило лицо','наглотался таблеток'):
            self.assertEqual('emergency',route(text,datetime(2026,10,15,10)).kind,text)
        self.assertEqual('urgent',route('температура сорок',datetime(2026,10,15,10)).kind)
        self.assertIn('103',route('температура сорок',datetime(2026,10,15,22)).message)

    def test_history_and_hospital_not_emergency(self):
        self.assertIsNone(route('запишите в больницу',datetime(2026,10,15,10)))
        self.assertNotEqual('emergency',getattr(route('инфаркт в прошлом году',datetime(2026,10,15,10)),'kind',None))
        self.assertNotEqual('emergency',getattr(route('нет боли в груди',datetime(2026,10,15,10)),'kind',None))
        self.assertEqual('emergency',route('раньше был инсульт, но сейчас не может дышать',datetime(2026,10,15,10)).kind)

    def test_faq_words(self):
        for pattern,answer in FAQ:
            self.assertLessEqual(len(answer.split()),20,answer)
        self.assertIn('регламенту',faq('как вы работаете'))
