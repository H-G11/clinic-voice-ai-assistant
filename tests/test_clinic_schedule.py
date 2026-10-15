import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900
from core.schedule import excel_day, excel_time, import_clinic_excel
from core.store import Store
from core.service import BookingService


SOURCE_DB = Path(__file__).resolve().parents[1]/'data/clinic_demo.sqlite3'


@unittest.skipUnless(SOURCE_DB.exists(), 'Run scripts/import_clinic.py with supplied case workbook')
class TestClinicSchedule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'clinic.sqlite3')
        with closing(sqlite3.connect(f'file:{SOURCE_DB}?mode=ro',uri=True)) as src, closing(sqlite3.connect(self.store.path)) as dst:
            src.backup(dst)
        self.store.setup()
        self.svc = BookingService(self.store, now=lambda:datetime(2026,10,15,8,0))
        # Users may already have demo patients/bookings in the active DB. Only
        # retain schedule/reference rows in this disposable test copy.
        with self.store.connect() as c:
            for table in ('bookings','mock_mis','api_visits','api_escalations','api_clients','synthetic_patients','client_registrations','patient_permissions'):
                c.execute(f'DELETE FROM {table}')
        self.assertEqual('ok',self.svc.register_synthetic('Тестов Иван Сергеевич','01.01.1990',confirmed=True).kind)

    def tearDown(self):
        self.svc.flush_handoffs()
        self.tmp.cleanup()

    def test_exact_counts_and_boundary_source_rows(self):
        with self.store.connect() as c:
            self.assertEqual(85,c.execute('SELECT COUNT(*) FROM doctors').fetchone()[0])
            self.assertEqual(136973,c.execute('SELECT COUNT(*) FROM slots').fetchone()[0])
            self.assertEqual(7,c.execute('SELECT COUNT(*) FROM source_sheets').fetchone()[0])
            first = c.execute("SELECT * FROM slots WHERE source_id='S000001'").fetchone()
            self.assertEqual('2026-06-25T14:00',first['start_at'])
            self.assertEqual(20,first['duration'])
            last = c.execute('SELECT source_id,start_at FROM slots ORDER BY source_id DESC LIMIT 1').fetchone()
            self.assertEqual('S136973',last['source_id'])
            self.assertEqual('2026-12-30T19:20',last['start_at'])
            self.assertEqual('2026-12-30T19:40',c.execute('SELECT max(start_at) FROM slots').fetchone()[0])

    def test_future_status_calendar_and_unavailability(self):
        with self.store.connect() as c:
            rows = c.execute("SELECT s.* FROM slots s WHERE start_at BETWEEN '2026-10-15T08:30' AND '2026-10-28T23:59' LIMIT 10000").fetchall()
            found_free = found_busy = False
            for row in rows:
                free = self.svc.free_slots(row['doctor_id'],row['start_at'][:10],limit=100)
                if row['file_status'] != 'Свободен':
                    self.assertNotIn(row['start_at'],free)
                    found_busy = True
                elif row['start_at'] in free:
                    found_free = True
                if found_free and found_busy:
                    break
            self.assertTrue(found_free and found_busy)
            absence = c.execute("SELECT * FROM unavailability LIMIT 1").fetchone()
            self.assertEqual([],self.svc.free_slots(absence['doctor_id'],absence['start_day'],100))
            off = c.execute("SELECT * FROM calendar WHERE day>'2026-10-15' AND day<'2026-10-28' AND code='В' LIMIT 1").fetchone()
            self.assertEqual([],self.svc.free_slots(off['doctor_id'],off['day'],100))
        self.assertEqual([],self.svc.free_slots('nonexistent','2026-10-16'))

    def test_horizon_and_today_thirty_minutes(self):
        for doctor in self.svc.doctors():
            self.assertEqual([],self.svc.free_slots(doctor['id'],'2026-10-29'))
            for slot in self.svc.free_slots(doctor['id'],'2026-10-15',100):
                self.assertGreaterEqual(slot,'2026-10-15T08:30')

    def test_thirty_minutes_are_not_rounded_down(self):
        doctor=next(d for d in self.svc.doctors('хирург') if self.svc.next_available_days(d['id']))
        day=self.svc.next_available_days(doctor['id'])[0]
        slot=self.svc.free_slots(doctor['id'],day)[0]
        self.svc.now=lambda:datetime.fromisoformat(slot)-timedelta(minutes=30)+timedelta(seconds=1)
        self.assertNotIn(slot,self.svc.free_slots(doctor['id'],day,100))

    def test_unicode_doctor_search(self):
        self.assertEqual('D001',self.svc.doctors(query='верещагин')[0]['id'])

    def test_absence_and_calendar_override_conflicting_free_row(self):
        # Fault injection only in this disposable copy: stale source free status
        # must not override an absence or a non-working calendar code.
        with self.store.connect() as c:
            absence=c.execute("SELECT * FROM unavailability WHERE start_day<='2026-10-28' AND end_day>='2026-10-15' LIMIT 1").fetchone()
            self.assertIsNotNone(absence)
            day=max('2026-10-15',absence['start_day']);slot=day+'T12:01'
            c.execute("UPDATE calendar SET code='Р' WHERE doctor_id=? AND day=?",(absence['doctor_id'],day))
            c.execute("INSERT INTO slots(doctor_id,start_at,file_status) VALUES (?,?,'Свободен')",(absence['doctor_id'],slot))
            off=c.execute("""SELECT cal.* FROM calendar cal WHERE day BETWEEN '2026-10-15' AND '2026-10-28' AND code='В'
                AND NOT EXISTS(SELECT 1 FROM unavailability u WHERE u.doctor_id=cal.doctor_id AND cal.day BETWEEN u.start_day AND u.end_day) LIMIT 1""").fetchone()
            offslot=off['day']+'T12:01'
            c.execute("INSERT INTO slots(doctor_id,start_at,file_status) VALUES (?,?,'Свободен')",(off['doctor_id'],offslot))
        self.assertNotIn(slot,self.svc.free_slots(absence['doctor_id'],day,100))
        self.assertNotIn(offslot,self.svc.free_slots(off['doctor_id'],off['day'],100))

    def test_atomic_booking_and_patient_specialty_constraint(self):
        doctor = next(d for d in self.svc.doctors('хирург') if self.svc.next_available_days(d['id']))
        day = self.svc.next_available_days(doctor['id'])[0]
        slot = self.svc.free_slots(doctor['id'],day)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:self.svc.create('Тестов Иван Сергеевич','01.01.1990',doctor['id'],slot).kind,range(2)))
        self.assertCountEqual(['ok','rejected'],results)
        second = self.svc.free_slots(doctor['id'],day)[0]
        self.assertEqual('rejected',self.svc.create('Тестов Иван Сергеевич','01.01.1990',doctor['id'],second).kind)


class TestExcelSerialization(unittest.TestCase):
    def test_serial_dates_and_fractional_time(self):
        self.assertEqual('2026-10-15',excel_day(46310,CALENDAR_WINDOWS_1900))
        self.assertEqual('09:30',excel_time(9.5/24,CALENDAR_WINDOWS_1900))
        self.assertEqual('00:00',excel_time(0,CALENDAR_WINDOWS_1900))
