"""Execute an isolated synthetic service demo, without Excel, models or sockets."""

from __future__ import annotations

import argparse
import json
import time
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.service import BookingService
from core.store import Store


def run_demo(*, measure: bool = False, trace=None) -> dict:
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

        def record(action, operation, expected):
            started = time.perf_counter()
            result = operation()
            elapsed = (time.perf_counter() - started) * 1000
            if result.kind != expected:
                raise RuntimeError(f'{action}: expected {expected}, got {result.kind}')
            event = {'action': action, 'result': result.kind}
            if measure:
                event['latency_ms'] = elapsed
            events.append(event)
            if trace is not None:
                trace(dict(event))

        record('registration_without_consent', lambda: svc.register_synthetic(patient, birthdate), 'rejected')
        record('explicit_synthetic_registration', lambda: svc.register_synthetic(patient, birthdate, confirmed=True), 'ok')
        record('create_after_reviewed_summary', lambda: svc.create(patient, birthdate, 'D001', '2026-10-16T10:00'), 'ok')
        booking = svc.patient_bookings(patient, birthdate)[0]
        record('duplicate_booking', lambda: svc.create(patient, birthdate, 'D001', '2026-10-16T10:00'), 'rejected')
        record('status', lambda: svc.booking_status(patient, birthdate, booking['id']), 'ok')
        record('move_without_consent', lambda: svc.reschedule(patient, birthdate, booking['id'], 'D001', '2026-10-16T11:00'), 'rejected')
        record('confirmed_move', lambda: svc.reschedule(patient, birthdate, booking['id'], 'D001', '2026-10-16T11:00', confirmed=True), 'ok')
        moved = svc.patient_bookings(patient, birthdate)[0]
        if booking['external_id'] != moved['external_id']:
            raise RuntimeError('Reschedule changed the external visit ID')
        record('cancel_without_consent', lambda: svc.cancel(patient, birthdate, moved['id']), 'rejected')
        record('confirmed_cancel', lambda: svc.cancel(patient, birthdate, moved['id'], confirmed=True), 'ok')
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', action='store_true', help='Print actual service execution, not a conversation')
    args = parser.parse_args()
    if args.trace:
        print('LOCAL SERVICE DEMO | synthetic fixture | fixed clock | no speech or real MIS', flush=True)
        def show(event):
            print(f"{event['action']:<33} {event['result']:<9} {event['latency_ms']:8.3f} ms", flush=True)
        report = run_demo(measure=True, trace=show)
        print('VERIFIED: same visit ID after move; cancellation checked; both slots free', flush=True)
    else:
        print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
