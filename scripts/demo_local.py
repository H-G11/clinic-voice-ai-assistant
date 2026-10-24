"""Execute an isolated synthetic service demo, without Excel, models or sockets."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.service import BookingService
from core.store import Store


def run_demo() -> dict:
    events = []
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'demo.sqlite3')
        with store.connect() as db:
            # Enable the case-policy branch on a generated fixture, NOT an imported workbook.
            db.execute("INSERT INTO metadata VALUES ('dataset','clinic_excel')")
            db.execute("INSERT INTO doctors(id,name,specialty) VALUES ('D001','Вымышленный Врач Сергеевич','хирург')")
            db.execute("INSERT INTO calendar VALUES ('D001','2026-10-16','Р')")
            db.executemany("INSERT INTO slots(doctor_id,start_at) VALUES ('D001',?)",
                           [('2026-10-16T10:00',), ('2026-10-16T11:00',)])
        svc = BookingService(store, now=lambda: datetime(2026, 10, 15, 9))
        patient, birthdate = 'Тестов Иван Сергеевич', '01.01.1990'

        def record(action, result, expected):
            if result.kind != expected:
                raise RuntimeError(f'{action}: expected {expected}, got {result.kind}')
            events.append({'action': action, 'result': result.kind})

        record('registration_without_consent', svc.register_synthetic(patient, birthdate), 'rejected')
        record('explicit_synthetic_registration', svc.register_synthetic(patient, birthdate, confirmed=True), 'ok')
        record('create_after_reviewed_summary', svc.create(patient, birthdate, 'D001', '2026-10-16T10:00'), 'ok')
        booking = svc.patient_bookings(patient, birthdate)[0]
        record('duplicate_booking', svc.create(patient, birthdate, 'D001', '2026-10-16T10:00'), 'rejected')
        record('status', svc.booking_status(patient, birthdate, booking['id']), 'ok')
        record('move_without_consent', svc.reschedule(patient, birthdate, booking['id'], 'D001', '2026-10-16T11:00'), 'rejected')
        record('confirmed_move', svc.reschedule(patient, birthdate, booking['id'], 'D001', '2026-10-16T11:00', confirmed=True), 'ok')
        moved = svc.patient_bookings(patient, birthdate)[0]
        if booking['external_id'] != moved['external_id']:
            raise RuntimeError('Reschedule changed the external visit ID')
        record('cancel_without_consent', svc.cancel(patient, birthdate, moved['id']), 'rejected')
        record('confirmed_cancel', svc.cancel(patient, birthdate, moved['id'], confirmed=True), 'ok')
        cancelled = svc.booking_status(patient, birthdate, moved['id'])
        if cancelled.kind != 'ok' or cancelled.message != 'Отменена':
            raise RuntimeError('Cancellation was not verified by the mock API')
        if len(svc.free_slots('D001', '2026-10-16')) != 2:
            raise RuntimeError('Slots not released after confirmed cancellation')
        return {'source_kind': 'synthetic_generated_fixture', 'clock': '2026-10-15T09:00:00 GMT+4',
                'scope': 'Actual service and in-process mock API; no dialogue, speech, real MIS or telephony',
                'database': 'temporary; removed after demo', 'events': events,
                'same_external_id_after_move': True, 'cancellation_verified': True, 'free_slots_after_cancel': 2}


if __name__ == '__main__':
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
