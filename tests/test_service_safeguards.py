"""Service regressions using synthetic SQLite fixtures; no Excel or network."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core.http_client import HTTPClient, HTTPResult, RateLimiter
from core.mis import Result, SwaggerMIS
from core.service import BookingService
from core.store import Store


class ServiceSafeguards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'test.sqlite3')
        self.day = '2026-10-16'
        self.first, self.second = self.day + 'T10:00', self.day + 'T11:00'
        with self.store.connect() as db:
            db.execute("INSERT INTO metadata VALUES ('dataset','clinic_excel')")
            db.execute("INSERT INTO doctors(id,name,specialty) VALUES ('D001','Вымышленный Врач Сергеевич','хирург')")
            db.execute("INSERT INTO calendar VALUES ('D001',?,'Р')", (self.day,))
            db.executemany("INSERT INTO slots(doctor_id,start_at) VALUES ('D001',?)", [(self.first,), (self.second,)])
        self.svc = BookingService(self.store, now=lambda: datetime(2026, 10, 15, 9))
        self.name, self.dob = 'Тестов Иван Сергеевич', '01.01.1990'
        self.assertEqual('ok', self.svc.register_synthetic(self.name, self.dob, confirmed=True).kind)

    def book(self):
        self.assertEqual('ok', self.svc.create(self.name, self.dob, 'D001', self.first).kind)
        return self.svc.patient_bookings(self.name, self.dob)[0]['id']

    def test_create_status_move_cancel_actual_local_api(self):
        booking = self.book()
        before = self.svc.booking_status(self.name, self.dob, booking)
        self.assertEqual(('ok', 'Запланирована'), (before.kind, before.message))
        moved = self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True)
        self.assertEqual('ok', moved.kind)
        after = self.svc.patient_bookings(self.name, self.dob)[0]
        self.assertEqual(before.external_id, after['external_id'])
        self.assertIn(self.first, self.svc.free_slots('D001', self.day))
        self.assertEqual('ok', self.svc.cancel(self.name, self.dob, after['id'], confirmed=True).kind)
        self.assertEqual('Отменена', self.svc.booking_status(self.name, self.dob, after['id']).message)
        self.assertIn(self.second, self.svc.free_slots('D001', self.day))

    def test_parallel_booking_has_one_external_mutation(self):
        with patch.object(self.svc.mis, 'create', wraps=self.svc.mis.create) as post:
            with ThreadPoolExecutor(max_workers=2) as pool:
                kinds = list(pool.map(lambda _: self.svc.create(self.name, self.dob, 'D001', self.first).kind, range(2)))
        self.assertCountEqual(['ok', 'rejected'], kinds)
        post.assert_called_once()

    def test_move_timeout_blocks_both_and_does_not_retry(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'reschedule', side_effect=TimeoutError) as request:
            result = self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True)
            again = self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True)
        self.assertEqual(('uncertain', 'rejected'), (result.kind, again.kind))
        request.assert_called_once()
        self.assertEqual([], self.svc.free_slots('D001', self.day))

    def test_rejected_move_keeps_original_and_releases_target(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'reschedule', return_value=Result('rejected')):
            self.assertEqual('rejected', self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True).kind)
        self.assertEqual([self.second], self.svc.free_slots('D001', self.day))

    def test_cancellation_requires_confirmation_and_correct_identity(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'cancel') as request:
            self.assertEqual('rejected', self.svc.cancel(self.name, self.dob, booking).kind)
            self.assertEqual('rejected', self.svc.cancel('Другой Тестовый Пациент', self.dob, booking, confirmed=True).kind)
        request.assert_not_called()

    def test_cancellation_timeout_retains_lock(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'cancel', side_effect=TimeoutError) as request:
            self.assertEqual('uncertain', self.svc.cancel(self.name, self.dob, booking, confirmed=True).kind)
            self.assertEqual('rejected', self.svc.cancel(self.name, self.dob, booking, confirmed=True).kind)
        request.assert_called_once()
        self.assertNotIn(self.first, self.svc.free_slots('D001', self.day))

    def test_status_malformed_doctor_is_uncertain_without_unlock(self):
        booking = self.book()
        original = self.svc.mis.status
        for invalid in (None, [], 'invalid'):
            response = original('1')
            response.data['doctor'] = invalid
            with patch.object(self.svc.mis, 'status', return_value=response):
                self.assertEqual('uncertain', self.svc.booking_status(self.name, self.dob, booking).kind)
        with patch.object(self.svc.mis, 'status', return_value=None):
            self.assertEqual('uncertain', self.svc.booking_status(self.name, self.dob, booking).kind)
        self.assertNotIn(self.first, self.svc.free_slots('D001', self.day))

    def test_malformed_move_response_blocks_both_slots(self):
        booking = self.book()
        response = HTTPResult('response', 200, {'id': 1, 'scheduled_at': '16.10.2026 11:00', 'status': 'Запланирована', 'doctor': None})
        with patch.object(self.svc.mis, '_send', return_value=response):
            self.assertEqual('uncertain', self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True).kind)
        self.assertEqual([], self.svc.free_slots('D001', self.day))

    def test_registration_conflict_retains_reconciliation_guard(self):
        # Simulator idempotency ignores patronymic: never claim a mismatched card.
        other = 'Тестов Иван Другович'
        with patch.object(self.svc.mis, 'register', wraps=self.svc.mis.register) as post:
            self.assertEqual('uncertain', self.svc.register_synthetic(other, self.dob, confirmed=True).kind)
            self.assertEqual('uncertain', self.svc.register_synthetic(other, self.dob, confirmed=True).kind)
        post.assert_called_once()
        self.assertIsNone(self.svc.identify(other, self.dob))

    def test_malformed_transport_is_never_confirmed(self):
        for response in (None, HTTPResult('unexpected', 201, {'id': 1}), HTTPResult('response', None)):
            with self.subTest(response=response):
                self.assertEqual('uncertain', self.svc.mis._result(response, (201,)).kind)

    def test_mock_records_cannot_be_cancelled_in_live_mode(self):
        booking = self.book()
        self.svc.mode = 'live'
        with patch.object(self.svc.mis, 'cancel') as request:
            self.assertEqual('rejected', self.svc.cancel(self.name, self.dob, booking, confirmed=True).kind)
        request.assert_not_called()


class ConfigurationValidation(unittest.TestCase):
    def test_invalid_timeouts_rejected_without_network(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HTTPClient('http://localhost', timeout=value)

    def test_invalid_limiter_budget_and_window_rejected(self):
        for options in ({'limit': True}, {'limit': 1.5}, {'window': float('nan')}, {'window': float('inf')}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                RateLimiter(**options)


class MutationIDGuards(unittest.TestCase):
    setUp = ServiceSafeguards.setUp
    book = ServiceSafeguards.book
    def test_cancel_wrong_external_id_does_not_release_slot(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'cancel', return_value=Result('ok', 'unexpected-visit')):
            self.assertEqual('uncertain', self.svc.cancel(self.name, self.dob, booking, confirmed=True).kind)
        self.assertNotIn(self.first, self.svc.free_slots('D001', self.day))

    def test_move_wrong_external_id_blocks_original_and_target(self):
        booking = self.book()
        with patch.object(self.svc.mis, 'reschedule', return_value=Result('ok', 'unexpected-visit')):
            self.assertEqual('uncertain', self.svc.reschedule(self.name, self.dob, booking, 'D001', self.second, confirmed=True).kind)
        self.assertEqual([], self.svc.free_slots('D001', self.day))
