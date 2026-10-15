import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from core.store import Store
from core.schedule import write_demo_excel, import_excel
from core.service import BookingService
from core.dialog import reply, handoff, extract_day


class TestMVP(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        schedule = root / "test.xlsx"
        write_demo_excel(schedule)
        self.store = Store(root / "db.sqlite")
        import_excel(self.store, schedule)
        self.svc = BookingService(self.store)
        self.day = None
        for d in range(1, 20):
            day = (date.today()+timedelta(days=d)).isoformat()
            if self.svc.free_slots("d1", day):
                self.day = day
                break
        self.assertIsNotNone(self.day)
        self.slot = self.svc.free_slots("d1", self.day)[0]

    def tearDown(self):
        self.td.cleanup()

    def test_create_and_no_duplicates(self):
        a = self.svc.create("Иван Тестов", "01.01.1990", "d1", self.slot)
        b = self.svc.create("Анна Проба", "02.02.1992", "d1", self.slot)
        self.assertEqual("ok", a.kind)
        self.assertEqual("rejected", b.kind)
        self.assertEqual(1, len(self.svc.mock_records()))
        self.assertNotIn(self.slot, self.svc.free_slots("d1", self.day))

    def test_concurrent_booking(self):
        def go(_):
            return self.svc.create("Иван Тестов", "01.01.1990", "d1", self.slot).kind
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(go, range(2)))
        self.assertCountEqual(results, ["ok", "rejected"])
        self.assertEqual(1, len(self.svc.mock_records()))

    def test_missing_slot(self):
        result = self.svc.create("Иван Тестов", "01.01.1990", "d1", "2030-01-01T04:15")
        self.assertEqual("rejected", result.kind)

    def test_dialog_requires_confirmation(self):
        day_human = date.fromisoformat(self.day).strftime("%d.%m.%Y")
        ans, s = reply("запиши к терапевту " + day_human, None, self.svc)
        self.assertEqual("time", s["step"])
        ans, s = reply(self.slot[-5:], s, self.svc)
        self.assertEqual("patient", s["step"])
        ans, s = reply("Иван Тестов", s, self.svc)
        self.assertEqual("birthdate", s["step"])
        ans, s = reply("01.01.1990", s, self.svc)
        self.assertEqual("confirm", s["step"])
        self.assertEqual(0, len(self.svc.mock_records()))
        ans, s = reply("да", s, self.svc)
        self.assertEqual("done", s["step"])
        self.assertIn("создана", ans)
        self.assertEqual(1, len(self.svc.mock_records()))

    def test_cancel_confirmation(self):
        ans, s = reply("запись", None, self.svc)
        self.assertEqual("specialty", s["step"])
        s = {"step":"confirm", "specialty":"терапевт", "day":self.day,
             "time":self.slot[-5:], "doctor_id":"d1", "doctor_name":"Иванов Иван Иванович",
             "patient":"Иван Тестов", "birthdate":"01.01.1990"}
        ans, s = reply("нет", s, self.svc)
        self.assertEqual(0, len(self.svc.mock_records()))

    def test_handoff(self):
        self.assertTrue(handoff("Соедините с оператором"))
        self.assertTrue(handoff("У меня острая боль"))
        ans, s = reply("У меня сильная боль", None, self.svc)
        self.assertIn("сотрудника", ans)
        self.assertEqual(0, len(self.svc.mock_records()))

    def test_unknown_mis_result_blocks_slot(self):
        class TimeoutMIS:
            def create(self, *args):
                raise TimeoutError("no response")
        svc = BookingService(self.store, mis=TimeoutMIS())
        result = svc.create("Иван Тестов", "01.01.1990", "d1", self.slot)
        self.assertEqual("uncertain", result.kind)
        self.assertNotIn(self.slot, self.svc.free_slots("d1", self.day))
        self.assertEqual("rejected", self.svc.create("Анна Проба", "02.02.1990", "d1", self.slot).kind)


if __name__ == "__main__":
    unittest.main()
