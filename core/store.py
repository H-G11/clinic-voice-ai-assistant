"""Локальное хранилище расписания, броней и имитатора МИС."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.setup()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def setup(self) -> None:
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS doctors (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS slots (
                doctor_id TEXT NOT NULL REFERENCES doctors(id),
                start_at TEXT NOT NULL,
                PRIMARY KEY (doctor_id, start_at)
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id TEXT NOT NULL, start_at TEXT NOT NULL,
                patient_name TEXT NOT NULL, birthdate TEXT NOT NULL,
                status TEXT NOT NULL, external_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_blocked_slot
                ON bookings(doctor_id, start_at)
                WHERE status IN ('pending','confirmed','uncertain');
            CREATE TABLE IF NOT EXISTS mock_mis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL UNIQUE,
                doctor_id TEXT NOT NULL, start_at TEXT NOT NULL,
                patient_name TEXT NOT NULL, birthdate TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_mock_mis_slot
                ON mock_mis(doctor_id, start_at)
                WHERE status='active';
            """)
            # Additive migration: legacy database and synthetic tests remain usable.
            additions = {
                'doctors': {'department': "TEXT NOT NULL DEFAULT ''", 'room': "TEXT NOT NULL DEFAULT ''", 'duration': 'INTEGER NOT NULL DEFAULT 30', 'patients': "TEXT NOT NULL DEFAULT ''"},
                'slots': {'source_id': 'TEXT', 'end_at': 'TEXT', 'duration': 'INTEGER NOT NULL DEFAULT 30', 'room': "TEXT NOT NULL DEFAULT ''", 'file_status': "TEXT NOT NULL DEFAULT 'Свободен'"},
                'bookings': {'patient_key': 'TEXT', 'specialty': 'TEXT', 'client_id': 'INTEGER', 'operation': "TEXT NOT NULL DEFAULT 'create'", 'related_id': 'INTEGER', 'mis_mode': "TEXT NOT NULL DEFAULT 'mock'"},
            }
            for table, columns in additions.items():
                existing = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
                for name, definition in columns.items():
                    if name not in existing:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            c.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calendar(doctor_id TEXT, day TEXT, code TEXT, PRIMARY KEY(doctor_id,day));
                CREATE TABLE IF NOT EXISTS unavailability(doctor_id TEXT, start_day TEXT, end_day TEXT, kind TEXT);
                CREATE INDEX IF NOT EXISTS ix_unavailability ON unavailability(doctor_id,start_day,end_day);
                CREATE INDEX IF NOT EXISTS ix_free_slots ON slots(doctor_id,file_status,start_at);
                CREATE TABLE IF NOT EXISTS source_sheets(name TEXT PRIMARY KEY, rows INTEGER, headers TEXT);
                CREATE TABLE IF NOT EXISTS source_reference(sheet TEXT,row_number INTEGER,values_json TEXT,PRIMARY KEY(sheet,row_number));
                CREATE TABLE IF NOT EXISTS synthetic_patients(id INTEGER PRIMARY KEY, full_name TEXT, birthdate TEXT,
                    UNIQUE(full_name,birthdate));
                CREATE TABLE IF NOT EXISTS patient_permissions(patient_id INTEGER, doctor_id TEXT, kind TEXT,
                    PRIMARY KEY(patient_id,doctor_id,kind));
                CREATE TABLE IF NOT EXISTS client_registrations(team TEXT,identity_key TEXT,status TEXT,external_id TEXT,
                    PRIMARY KEY(team,identity_key));
                CREATE TABLE IF NOT EXISTS operator_incidents(
                    id TEXT PRIMARY KEY,created_at TEXT,reason TEXT,rule TEXT,priority TEXT,snapshot TEXT,
                    status TEXT NOT NULL DEFAULT 'Требуется оператор',api_id TEXT,api_status TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_specialty ON bookings(patient_key,specialty)
                    WHERE patient_key IS NOT NULL AND status IN ('pending','confirmed','uncertain') AND operation='create';
            """)
