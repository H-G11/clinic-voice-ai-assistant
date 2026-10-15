import csv
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from core.dialog import reply, handoff, new_state
from core.parse_ru import parse_day, parse_time


class TestSafetyDialog(unittest.TestCase):
    def test_handoff_corpus(self):
        with Path(__file__).with_name('handoff_phrases.csv').open(encoding='utf-8', newline='') as file:
            rows = list(csv.DictReader(file))
        self.assertGreaterEqual(len(rows), 40)
        for row in rows:
            with self.subTest(text=row['text']):
                self.assertEqual(row['handoff'] == '1', handoff(row['text']))

    def test_global_exits_on_every_step(self):
        svc = Mock()
        for step in ('start', 'specialty', 'doctor', 'day', 'time', 'patient', 'birthdate', 'confirm', 'done'):
            for text in ('оператор', 'начать заново'):
                with self.subTest(step=step, text=text):
                    _, state = reply(text, dict(new_state(), step=step), svc)
                    self.assertIn(state['step'], ('start', 'specialty'))
        svc.create.assert_not_called()

    def test_ambiguous_confirmation_never_calls_service(self):
        svc = Mock()
        for text in ('да, но время другое', 'да нет', 'да, не подтверждаю', 'ага', 'да, в пятницу', 'давайте'):
            with self.subTest(text=text):
                _, state = reply(text, dict(new_state(), step='confirm'), svc)
                self.assertNotEqual('done', state['step'])
        svc.create.assert_not_called()

    def test_date_and_time_corrections(self):
        svc = Mock()
        svc.doctors.return_value = [{'id': 'd1', 'name': 'Тестов', 'specialty': 'терапевт'}]
        svc.free_slots.return_value = ['2099-01-02T09:30', '2099-01-02T14:00']
        svc.next_available_days.return_value = ['2099-01-02']
        original = dict(new_state(), step='confirm', specialty='терапевт', doctor_id='d1', doctor_name='Тестов', day='2099-01-02', time='09:30', patient='Иван Тестов', birthdate='01.01.1990')
        _, state = reply('другое время', original, svc)
        self.assertEqual('time', state['step'])
        self.assertIsNone(state['time'])
        _, state = reply('нет, в 14:00', original, svc)
        self.assertEqual('14:00', state['time'])
        self.assertEqual('confirm', state['step'])
        _, state = reply('нет, 02.01.2099', original, svc)
        self.assertEqual('2099-01-02', state['day'])
        self.assertEqual('time', state['step'])
        svc.create.assert_not_called()

    def test_time_ambiguity_and_invalid_input(self):
        for text in ('25:00', '09:99', '09:00 или 14:00', 'девять или десять', 'без десяти десять', 'около девяти', '9 99'):
            self.assertIsNone(parse_time(text, ['2099-01-02T09:00', '2099-01-02T14:00']))
        self.assertIsNone(parse_time('в половине десятого', ['2099-01-02T09:30', '2099-01-02T21:30']))
        self.assertEqual('09:30', parse_time('в половине десятого утра', ['2099-01-02T09:30', '2099-01-02T21:30']))

    def test_relative_date_corrections(self):
        now = date(2026, 10, 15)
        self.assertEqual('2026-10-19', parse_day('в понедельник после обеда', now))
        self.assertEqual('2026-10-16', parse_day('нет, в пятницу', now))
        self.assertIsNone(parse_day('31 февраля', now))
        self.assertEqual('2020-01-01', parse_day('01.01.2020', now))
        self.assertEqual('2026-10-15', parse_day('запишите к терапевту пятнадцатого октября', now))
        self.assertEqual('2026-10-21', parse_day('на двадцать первого октября', now))

    def test_change_specialty_resets_previous_doctor_slot(self):
        svc = Mock()
        svc.doctors.return_value = [{'id':'d2', 'name':'Пробная', 'specialty':'невролог'}]
        svc.next_available_days.return_value = ['2099-01-02']
        state = dict(new_state(), step='confirm', specialty='терапевт', doctor_id='d1', doctor_name='Тестов', day='2099-01-02', time='09:30')
        _, changed = reply('нет, к неврологу', state, svc)
        self.assertEqual('d2', changed['doctor_id'])
        self.assertEqual('невролог', changed['specialty'])
        self.assertIsNone(changed['day'])
        self.assertIsNone(changed['time'])
        svc.create.assert_not_called()

    def test_past_day_not_used_by_dialogue(self):
        svc = Mock()
        svc.doctors.return_value = [{'id':'d1', 'name':'Тестов', 'specialty':'терапевт'}]
        svc.next_available_days.return_value = ['2099-01-02']
        _, changed = reply('к терапевту 01.01.2020', None, svc)
        self.assertEqual('day', changed['step'])
        self.assertIsNone(changed['day'])
        svc.create.assert_not_called()
