import tempfile
import unittest
from pathlib import Path

from core.presentation import schedule_presentation
from core.store import Store


class PresentationTests(unittest.TestCase):
    def test_counts_and_capabilities_follow_loaded_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'synthetic.sqlite3')
            with store.connect() as database:
                database.execute("INSERT INTO doctors(id,name,specialty) VALUES ('test','Synthetic','surgeon')")
                database.execute("INSERT INTO slots(doctor_id,start_at) VALUES ('test','2030-01-01T10:00')")
            legacy = schedule_presentation(store, False)
            self.assertIn('врачи — 1; слоты — 1', legacy['schedule'])
            self.assertNotIn('85', legacy['schedule'])
            self.assertNotIn('GMT+4', legacy['policy'])
            self.assertNotIn('отменить', legacy['greeting'])
            case = schedule_presentation(store, True)
            self.assertIn('GMT+4', case['policy'])
            self.assertIn('отменить', case['greeting'])
            self.assertIn('врачи — 1; слоты — 1', case['schedule'])
