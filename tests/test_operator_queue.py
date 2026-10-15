import unittest,time,threading
from unittest.mock import patch
from core.dialog import reply
import test_user_journey


@unittest.skipUnless(test_user_journey.SOURCE.exists(),'Case Excel required')
class TestOperatorQueue(unittest.TestCase):
    setUp=test_user_journey.TestNewPatientJourney.setUp
    tearDown=test_user_journey.TestNewPatientJourney.tearDown

    def test_unidentified_incident_never_invents_api_client(self):
        answer,state=reply('оператор',None,self.service)
        self.assertIn('соединение не выполняется',answer)
        self.service.flush_handoffs()
        card=self.service.handoff_queue()[0]
        self.assertEqual(('P3','Требуется оператор',None),(card['priority'],card['status'],card['api_id']))
        self.assertFalse(card['connected'])
        with self.store.connect() as c:
            self.assertEqual(0,c.execute('SELECT COUNT(*) FROM api_escalations').fetchone()[0])

    def test_identified_case_uses_api_escalation_and_context(self):
        self.service.register_synthetic('Новый Вымышленный Сергеевич','02.02.1992',confirmed=True)
        state={'step':'doctor','intent':'book','patient':'Новый Вымышленный Сергеевич','birthdate':'02.02.1992','specialty':'хирург'}
        _,state=reply('хочу пожаловаться',state,self.service)
        self.service.flush_handoffs()
        card=self.service.handoff_queue()[0]
        self.assertEqual('P2',card['priority'])
        self.assertTrue(card['api_id'])
        self.assertEqual('хирург',card['snapshot']['specialty'])
        with self.store.connect() as c:
            row=c.execute('SELECT client_id FROM api_escalations').fetchone()
            self.assertEqual(self.service.identify('Новый Вымышленный Сергеевич','02.02.1992'),row[0])

    def test_emergency_response_does_not_wait_for_database(self):
        entered=threading.Event();release=threading.Event()
        connect=self.store.connect
        def blocked():
            entered.set();release.wait(2)
            return connect()
        with patch.object(self.store,'connect',side_effect=blocked):
            started=time.perf_counter()
            answer,state=reply('давит в груди',None,self.service)
            elapsed=time.perf_counter()-started
            self.assertIn('103',answer)
            self.assertLess(elapsed,.5)
            self.assertEqual('P1',state['handoff']['priority'])
            entered.wait(1);release.set();self.service.flush_handoffs()

    def test_failed_patient_lookup_still_leaves_local_queue(self):
        state={'step':'birthdate','intent':'book','patient':'Неизвестный Тестовый Пациент','birthdate':'01.01.1990'}
        _,state=reply('оператор',state,self.service)
        self.service.flush_handoffs()
        queue=self.service.handoff_queue()
        self.assertEqual(1,len(queue));self.assertIsNone(queue[0]['api_id'])
