"""Regression of the actual user journey: no pre-created patient or hidden setup form."""
import unittest
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from datetime import datetime
from unittest.mock import patch
from core.store import Store
from core.service import BookingService
from core.dialog import reply
from core.api_simulator import LocalAPI,LocalTransport
from core.mis import SwaggerMIS,Result

SOURCE=Path(__file__).resolve().parents[1]/'data/clinic_demo.sqlite3'


@unittest.skipUnless(SOURCE.exists(),'Case Excel required')
class TestNewPatientJourney(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'journey.sqlite3')
        with closing(sqlite3.connect(f'file:{SOURCE}?mode=ro',uri=True)) as src,closing(sqlite3.connect(self.store.path)) as dst: src.backup(dst)
        self.store.setup()
        self.service=BookingService(self.store,now=lambda:datetime(2026,10,15,9))
        with self.store.connect() as c:
            for table in ('bookings','mock_mis','api_visits','api_escalations','api_clients','synthetic_patients','client_registrations'):
                c.execute(f'DELETE FROM {table}')
        self.state=None

    def tearDown(self):
        self.service.flush_handoffs()
        self.tmp.cleanup()

    def say(self,text):
        answer,self.state=reply(text,self.state,self.service)
        return answer

    def registration_prompt(self):
        for text in ('запишите к хирургу','Новый Вымышленный Сергеевич','02.02.1992'):answer=self.say(text)
        self.assertEqual('register_confirm',self.state['step'],answer)
        self.assertEqual('хирург',self.state['specialty'])
        return answer

    def finish_booking(self):
        doctor=next(d for d in self.service.doctors('хирург') if self.service.next_available_days(d['id']))
        self.say(doctor['id'])
        day=self.service.next_available_days(doctor['id'])[0]
        self.say(day)
        slots=self.service.free_slots(doctor['id'],day,100)
        self.say(slots[0][-5:])
        self.assertEqual('confirm',self.state['step'])
        self.assertEqual([],self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992'))
        self.assertIn('создана',self.say('да'))
        return doctor,slots

    def test_inline_registration_to_cancelled_status(self):
        self.registration_prompt()
        self.assertIsNone(self.service.identify('Новый Вымышленный Сергеевич','02.02.1992'))
        self.say('да, но данные другие')
        self.assertEqual('register_confirm',self.state['step'])
        self.say('да')
        self.assertIsInstance(self.state['client_id'],int)
        doc,slots=self.finish_booking()
        b=self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992')[0]
        self.assertEqual('rejected',self.service.create('Новый Вымышленный Сергеевич','02.02.1992',doc['id'],slots[0]).kind)
        self.assertNotIn(slots[0],self.service.free_slots(doc['id'],slots[0][:10],100))
        for text in ('статус записи','Новый Вымышленный Сергеевич','02.02.1992'):answer=self.say(text)
        self.assertIn('Запланирована',answer)
        for text in ('перенести запись','Новый Вымышленный Сергеевич','02.02.1992',slots[1][:10],slots[1][-5:],'да'):answer=self.say(text)
        self.assertIn('перенесена',answer)
        moved=self.service.patient_bookings('Новый Вымышленный Сергеевич','02.02.1992')[0]
        self.assertEqual(b['external_id'],moved['external_id'])
        self.assertEqual(slots[1],moved['start_at'])
        for text in ('отменить запись','Новый Вымышленный Сергеевич','02.02.1992','отменить','да'):answer=self.say(text)
        self.assertIn('отменена',answer)
        for text in ('статус записи','Новый Вымышленный Сергеевич','02.02.1992'):answer=self.say(text)
        self.assertIn('Отменена',answer)

    def test_registration_refusal_and_real_mode_never_create(self):
        self.registration_prompt();self.say('нет')
        self.assertIsNone(self.service.identify('Новый Вымышленный Сергеевич','02.02.1992'))
        self.state=None;self.service.mode='live'
        with patch.object(self.service,'register_synthetic') as register:
            for text in ('к хирургу','Новый Вымышленный Сергеевич','02.02.1992'): self.say(text)
        self.assertNotEqual('register_confirm',self.state['step'])
        register.assert_not_called()

    def test_existing_api_card_without_cache_and_normalized_fields(self):
        self.assertEqual('ok',self.service.mis.register('Ёлкин Иван Сергеевич','01.01.1990').kind)
        self.assertIsNotNone(self.service.identify('  елКИН\u00a0ИВАН   Сергеевич ','1.1.1990'))
        with self.store.connect() as c: self.assertEqual(0,c.execute('SELECT COUNT(*) FROM synthetic_patients').fetchone()[0])
        s=None
        for text in ('к хирургу','ЕЛКИН, ИВАН, СЕРГЕЕВИЧ','01.01.1990'):
            answer,s=reply(text,s,self.service)
        self.assertEqual('doctor',s['step'],answer)

    def test_team_context_isolated(self):
        self.assertEqual('ok',self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True).kind)
        api=LocalAPI(self.store,{'other-fixture':'another-team'})
        other=BookingService(self.store,mis=SwaggerMIS(self.store,LocalTransport(api,'other-fixture'),self.service.mis.doctor_map))
        self.assertIsNone(other.identify('Новый Вымышленный Сергеевич','02.02.1992'))

    def test_registration_timeout_never_blindly_posts_again(self):
        with patch.object(self.service.mis,'register',side_effect=TimeoutError) as post:
            a=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
            b=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
        self.assertEqual(('uncertain','uncertain'),(a.kind,b.kind))
        post.assert_called_once()

    def test_malformed_registration_id_stays_uncertain_without_retry(self):
        with patch.object(self.service.mis,'register',return_value=Result('ok','invalid')) as post:
            first=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
            second=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
        self.assertEqual(('uncertain','uncertain'),(first.kind,second.kind))
        post.assert_called_once()

    def test_registration_final_persistence_failure_keeps_pending_guard(self):
        original=self.store.connect
        calls=0
        def connect():
            nonlocal calls
            calls+=1
            if calls==3:raise sqlite3.OperationalError('synthetic disk failure')
            return original()
        with patch.object(self.service.mis,'register',return_value=Result('ok','123')) as post:
            with patch.object(self.store,'connect',side_effect=connect):
                first=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
            second=self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
        self.assertEqual(('uncertain','uncertain'),(first.kind,second.kind))
        post.assert_called_once()
