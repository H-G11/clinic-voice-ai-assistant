import unittest
from unittest.mock import Mock

from core.dialog import reply
from core.parse_ru import is_booking_abort


class BookingRefusal(unittest.TestCase):
    def test_booking_refusal_is_distinct_from_recording(self):
        for phrase in ('Не записывайте меня!', 'не записывайте меня к врачу', 'не записывайте на приём', 'стоп'):
            self.assertTrue(is_booking_abort(phrase), phrase)
        for phrase in ('не записывайте разговор', 'да', 'запишите меня'):
            self.assertFalse(is_booking_abort(phrase), phrase)

    def test_legacy_refusal_invalidates_confirmation_without_mutation(self):
        svc = Mock(clinic_mode=False)
        state = {'step': 'confirm', 'patient': 'Иван Тестов', 'birthdate': '01.01.1990',
                 'doctor_id': 'd1', 'day': '2026-10-16', 'time': '10:00'}
        answer, updated = reply('не записывайте меня', state, svc)
        self.assertEqual('start', updated['step'])
        self.assertIn('не создана', answer)
        svc.create.assert_not_called()
