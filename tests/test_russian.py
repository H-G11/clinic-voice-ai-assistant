import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

from core.parse_ru import parse_day, parse_time, parse_birthdate
from core.store import Store
from core.schedule import write_demo_excel, import_excel
from core.dialog import reply
from core.service import BookingService


class TestRussianParsing(unittest.TestCase):
    def test_date_relative_and_weekday(self):
        now = date(2026, 10, 15)  # Thursday
        self.assertEqual(parse_day('в пятницу', now), '2026-10-16')
        self.assertEqual(parse_day('на следующей неделе в понедельник', now), '2026-10-19')
        self.assertEqual(parse_day('послезавтра', now), '2026-10-17')

    def test_date_written_and_spoken(self):
        now = date(2026, 10, 15)
        self.assertEqual(parse_day('15 октября', now), '2026-10-15')
        self.assertEqual(parse_day('пятнадцатого октября', now), '2026-10-15')
        self.assertEqual(parse_day('двадцать первого октября', now), '2026-10-21')
        self.assertEqual(parse_day('2026-10-16', now), '2026-10-16')
        self.assertEqual(parse_day('31 февраля', now), None)

    def test_russian_time_matched_to_open_slots(self):
        available = ['2026-10-16T09:30', '2026-10-16T10:00', '2026-10-16T14:00', '2026-10-16T15:30']
        self.assertEqual(parse_time('девять тридцать', available), '09:30')
        self.assertEqual(parse_time('в два часа дня', available), '14:00')
        self.assertEqual(parse_time('в десять', available), '10:00')
        self.assertEqual(parse_time('пятнадцать тридцать', available), '15:30')
        self.assertIsNone(parse_time('одиннадцать', available))

    def test_birthdate_conservative(self):
        self.assertEqual(parse_birthdate('первого января 1990'), None)
        self.assertEqual(parse_birthdate('1 января 1990'), '01.01.1990')
        self.assertIsNone(parse_birthdate('31.02.1990'))


class TestDialogSchedule(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Store(root / 'test.sqlite')
        excel = root / 'test.xlsx'
        write_demo_excel(excel)
        import_excel(self.db, excel)
        self.svc = BookingService(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_spoken_time_and_confirmation(self):
        slots = []
        day = ''
        for i in range(1, 22):
            cand = (date.today() + timedelta(days=i)).isoformat()
            slots = self.svc.free_slots('d1', cand)
            if slots:
                day = cand
                break
        text = f'запиши к терапевту {date.fromisoformat(day).strftime("%d.%m.%Y")}'
        ans, state = reply(text, None, self.svc)
        self.assertEqual(state['step'], 'time')
        ans, state = reply('в девять тридцать', state, self.svc)
        self.assertEqual(state['time'], '09:30')
        self.assertEqual(state['step'], 'patient')
        self.assertEqual(len(self.svc.mock_records()), 0)
        ans, state = reply('Иван Тестов', state, self.svc)
        ans, state = reply('01.01.1990', state, self.svc)
        self.assertEqual(state['step'], 'confirm')
        ans, state = reply('да, подтверждаю', state, self.svc)
        self.assertEqual(state['step'], 'done')
        self.assertEqual(len(self.svc.mock_records()), 1)

    def test_initial_date_not_mistaken_for_time(self):
        day = None
        for i in range(1, 22):
            d = (date.today() + timedelta(days=i)).isoformat()
            if self.svc.free_slots('d1', d):
                day = d
                break
        ans, state = reply('Запишите к терапевту ' + date.fromisoformat(day).strftime('%d.%m.%Y'), None, self.svc)
        self.assertEqual(state['step'], 'time')
        self.assertIsNone(state['time'])

    def test_day_with_no_slots_offers_real_days(self):
        ans, state = reply('запиши к терапевту', None, self.svc)
        self.assertIn('Ближайшие варианты', ans)
        self.assertEqual(state['step'], 'day')

if __name__ == '__main__':
    unittest.main()
