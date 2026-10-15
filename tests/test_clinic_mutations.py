import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from core.mis import Result
import test_clinic_schedule


@unittest.skipUnless(test_clinic_schedule.SOURCE_DB.exists(),'Case import required')
class TestClinicMutations(unittest.TestCase):
    setUp=test_clinic_schedule.TestClinicSchedule.setUp
    tearDown=test_clinic_schedule.TestClinicSchedule.tearDown

    def book(self):
        doctor=next(d for d in self.svc.doctors('хирург') if self.svc.next_available_days(d['id']))
        day=self.svc.next_available_days(doctor['id'])[0]
        slots=self.svc.free_slots(doctor['id'],day,100)
        self.assertEqual('ok',self.svc.create('Тестов Иван Сергеевич','01.01.1990',doctor['id'],slots[0]).kind)
        booking=self.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990')[0]
        return doctor,slots,booking

    def test_move_timeout_blocks_both_slots_no_retry(self):
        doctor,slots,b=self.book()
        with patch.object(self.svc.mis,'reschedule',side_effect=TimeoutError) as request:
            result=self.svc.reschedule('Тестов Иван Сергеевич','01.01.1990',b['id'],doctor['id'],slots[1],confirmed=True)
        self.assertEqual('uncertain',result.kind)
        request.assert_called_once()
        available=self.svc.free_slots(doctor['id'],slots[0][:10],100)
        self.assertNotIn(slots[0],available);self.assertNotIn(slots[1],available)

    def test_move_rejection_preserves_old_and_releases_new(self):
        doctor,slots,b=self.book()
        with patch.object(self.svc.mis,'reschedule',return_value=Result('rejected')):
            result=self.svc.reschedule('Тестов Иван Сергеевич','01.01.1990',b['id'],doctor['id'],slots[1],confirmed=True)
        self.assertEqual('rejected',result.kind)
        available=self.svc.free_slots(doctor['id'],slots[0][:10],100)
        self.assertNotIn(slots[0],available);self.assertIn(slots[1],available)

    def test_parallel_move_is_one_patch(self):
        doctor,slots,b=self.book()
        original=self.svc.mis.reschedule
        with patch.object(self.svc.mis,'reschedule',wraps=original) as request:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:self.svc.reschedule('Тестов Иван Сергеевич','01.01.1990',b['id'],doctor['id'],slots[1],confirmed=True).kind,range(2)))
        self.assertCountEqual(['ok','rejected'],results)
        request.assert_called_once()

    def test_identity_confirmation_and_mode_isolation(self):
        doctor,slots,b=self.book()
        self.assertEqual('rejected',self.svc.cancel('Тестов Иван Сергеевич','01.01.1990',b['id']).kind)
        self.assertEqual('rejected',self.svc.cancel('Другой Тестовый Пациент','01.01.1990',b['id'],confirmed=True).kind)
        self.svc.mode='live'
        self.assertEqual([],self.svc.patient_bookings('Тестов Иван Сергеевич','01.01.1990'))
        self.assertEqual('rejected',self.svc.cancel('Тестов Иван Сергеевич','01.01.1990',b['id'],confirmed=True).kind)

    def test_registration_is_separate_confirmed_operation(self):
        before=self.svc.identify('Новый Синтетический Пациент','02.02.1992')
        self.assertIsNone(before)
        self.assertEqual('rejected',self.svc.register_synthetic('Новый Синтетический Пациент','02.02.1992').kind)
        self.assertIsNone(self.svc.identify('Новый Синтетический Пациент','02.02.1992'))
