import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.http_client import HTTPClient, RateLimiter, retry_after_seconds
from core.mis import Result
import test_mvp


class FixtureHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        type(self).calls.append((self.command, self.path))
        if self.path == '/timeout':
            time.sleep(.15)
        status = int(self.path.strip('/')) if self.path.strip('/').isdigit() else 200
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if status == 429:
            self.send_header('Retry-After', '2')
        if status == 302:
            self.send_header('Location', '/200')
        self.end_headers()
        try:
            self.wfile.write(b'{"synthetic_id":"FIXTURE-1"}' if self.path != '/invalid' else b'not json')
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        FixtureHandler.calls = []

    def client(self, **kwargs):
        return HTTPClient(self.url, limiter=RateLimiter(), **kwargs)

    def test_success_is_transport_response_only(self):
        result = self.client().request('POST', '/200', {'synthetic': True}, mutation_authorized=True)
        self.assertEqual(('response', 200), (result.kind, result.status))
        self.assertEqual('FIXTURE-1', result.data['synthetic_id'])
        self.assertEqual(1, len(FixtureHandler.calls))

    def test_client_errors_no_retry(self):
        for status in (400, 401, 403, 404, 409):
            with self.subTest(status=status):
                result = self.client().request('POST', f'/{status}', {}, mutation_authorized=True)
                self.assertEqual(('response', status), (result.kind, result.status))
        self.assertEqual(5, len(FixtureHandler.calls))

    def test_timeout_post_is_uncertain_and_never_retried(self):
        result = self.client(timeout=.03).request('POST', '/timeout', {}, mutation_authorized=True)
        self.assertEqual('uncertain', result.kind)
        self.assertEqual(1, len(FixtureHandler.calls))

    def test_server_error_and_invalid_success_are_uncertain(self):
        for path in ('/500', '/503', '/invalid'):
            self.assertEqual('uncertain', self.client().request('POST', path, {}, mutation_authorized=True).kind)
        self.assertEqual(3, len(FixtureHandler.calls))

    def test_429_defers_all_clients_sharing_limiter(self):
        limiter = RateLimiter()
        a = HTTPClient(self.url, limiter=limiter)
        b = HTTPClient(self.url, limiter=limiter)
        result = a.request('GET', '/429')
        self.assertEqual(2, result.retry_after)
        self.assertEqual('rate_limited', b.request('GET', '/200').kind)
        self.assertEqual(1, len(FixtureHandler.calls))

    def test_reference_cache_reduces_network_calls(self):
        client = self.client()
        a = client.cached_get('/200')
        a.data['synthetic_id'] = 'modified locally'
        self.assertEqual('FIXTURE-1', client.cached_get('/200').data['synthetic_id'])
        self.assertEqual(1, len(FixtureHandler.calls))

    def test_no_redirect_or_unapproved_mutation(self):
        client = self.client()
        with self.assertRaises(PermissionError):
            client.request('POST', '/200', {})
        result = client.request('POST', '/302', {}, mutation_authorized=True)
        self.assertEqual('uncertain', result.kind)
        self.assertEqual(1, len(FixtureHandler.calls))

    def test_reject_credential_urls_and_external_paths(self):
        with self.assertRaises(ValueError):
            HTTPClient('https://user:secret@example.invalid')
        for path in ('//example.invalid', '/200?token=secret', '/../../200', '/\\example.invalid'):
            with self.assertRaises(ValueError):
                self.client().request('GET', path)
        self.assertFalse(FixtureHandler.calls)

    def test_default_limiter_shared(self):
        self.assertIs(HTTPClient(self.url).limiter, HTTPClient(self.url).limiter)


class TestLimiter(unittest.TestCase):
    def test_rolling_window_shared_reads_and_writes(self):
        now = [0.0]
        limiter = RateLimiter(clock=lambda: now[0])
        self.assertEqual([0.0] * 8, [limiter.acquire() for _ in range(8)])
        self.assertEqual(60.0, limiter.acquire())
        now[0] = 59.0
        self.assertEqual(1.0, limiter.acquire())
        now[0] = 60.0
        self.assertEqual(0.0, limiter.acquire())

    def test_parallel_attempts_cannot_exceed_budget(self):
        limiter = RateLimiter()
        with ThreadPoolExecutor(max_workers=16) as pool:
            waits = list(pool.map(lambda _: limiter.acquire(), range(30)))
        self.assertEqual(8, waits.count(0.0))

    def test_retry_after_formats(self):
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime
        self.assertEqual(60, retry_after_seconds('invalid'))
        self.assertEqual(60, retry_after_seconds('NaN'))
        self.assertEqual(3, retry_after_seconds('3'))
        value = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
        self.assertGreater(retry_after_seconds(value), 28)


class TestServiceFailureResults(unittest.TestCase):
    setUp = test_mvp.TestMVP.setUp
    tearDown = test_mvp.TestMVP.tearDown

    def test_final_persistence_failure_keeps_pending_reservation(self):
        from contextlib import contextmanager
        from unittest.mock import patch, Mock
        from core.service import BookingService
        connect = self.store.connect
        count = [0]
        @contextmanager
        def failing_connect():
            count[0] += 1
            if count[0] == 2:
                raise OSError('Synthetic persistence failure')
            with connect() as con:
                yield con
        adapter = Mock()
        adapter.create.return_value = Result('ok', 'FIXTURE-1')
        service = BookingService(self.store, adapter)
        with patch.object(self.store, 'connect', failing_connect):
            result = service.create('Иван Тестов', '01.01.1990', 'd1', self.slot)
        self.assertEqual('uncertain', result.kind)
        self.assertNotIn(self.slot, service.free_slots('d1', self.day, limit=100))
        with self.store.connect() as con:
            self.assertEqual('pending', con.execute('SELECT status FROM bookings').fetchone()[0])

    def test_invalid_identity_never_calls_adapter(self):
        from unittest.mock import Mock
        from core.service import BookingService
        adapter = Mock()
        service = BookingService(self.store, adapter)
        for name, dob in (('', '01.01.1990'), ('Иван Тестов', '31.02.1990'), ('Иван Тестов', '01.01.2999')):
            self.assertEqual('rejected', service.create(name, dob, 'd1', self.slot).kind)
        adapter.create.assert_not_called()

    def test_invalid_adapter_response_blocks_slot(self):
        for response in (Result('ok'), Result('unexpected'), None):
            with self.subTest(response=response):
                from core.service import BookingService
                class Adapter:
                    def create(self, *args):
                        return response
                slot = self.svc.free_slots('d1', self.day, limit=100)[0]
                service = BookingService(self.store, Adapter())
                self.assertEqual('uncertain', service.create('Иван Тестов', '01.01.1990', 'd1', slot).kind)
                self.assertNotIn(slot, service.free_slots('d1', self.day, limit=100))
