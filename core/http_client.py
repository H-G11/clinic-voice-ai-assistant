"""Contract-neutral transport. No real routes, authentication scheme or MIS mapping.

One process only: all default clients share the same rolling-window limiter.
No automatic retries or redirects (including GET). Payloads/tokens never logged.
"""
from __future__ import annotations

import json
import threading
import time
import math
from http.client import HTTPException
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class RateLimiter:
    def __init__(self, limit=8, window=60.0, clock=time.monotonic):
        if type(limit) is not int or not 1 <= limit <= 10 or not math.isfinite(window) or window < 60:
            raise ValueError('Limit must be 1..10 calls per >=60 seconds')
        self.limit, self.window, self.clock = limit, window, clock
        self.calls = deque()
        self.blocked_until = 0.0
        self.lock = threading.Lock()

    def acquire(self) -> float:
        """0 grants one network attempt; positive value is required wait in seconds."""
        with self.lock:
            now = self.clock()
            while self.calls and self.calls[0] <= now - self.window:
                self.calls.popleft()
            wait = max(0.0, self.blocked_until - now)
            if len(self.calls) >= self.limit:
                wait = max(wait, self.calls[0] + self.window - now)
            if wait > 0:
                return wait
            self.calls.append(now)
            return 0.0

    def defer(self, seconds):
        with self.lock:
            self.blocked_until = max(self.blocked_until, self.clock() + seconds)


SHARED_LIMITER = RateLimiter()


@dataclass
class HTTPResult:
    kind: str  # response / rate_limited / uncertain / error
    status: int | None = None
    data: object = None
    retry_after: float = 0.0
    # A successful HTTP response is NOT proof of a confirmed appointment.


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def retry_after_seconds(value: str | None) -> float:
    try:
        seconds = float(value)
        return max(1.0, seconds) if math.isfinite(seconds) else 60.0
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(value)
            return max(1.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 60.0


class HTTPClient:
    def __init__(self, base_url: str, *, headers=None, limiter=None, timeout=8.0):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Invalid API base URL; credentials in URLs are prohibited')
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('Only local fixtures may use HTTP')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Timeout must be positive')
        self.base_url = base_url.rstrip('/')
        self.headers = dict(headers or {})  # actual auth format supplied only after OpenAPI
        self.limiter = limiter or SHARED_LIMITER
        self.timeout = timeout
        self.opener = build_opener(_NoRedirect())
        self.cache = {}
        self.cache_lock = threading.Lock()

    def request(self, method, path, payload=None, *, mutation_authorized=False, params=None) -> HTTPResult:
        method = method.upper()
        if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            raise ValueError('Unsupported method')
        if method != 'GET' and not mutation_authorized:
            raise PermissionError('Mutation requires explicit authorization through the booking service')
        parsed = urlsplit(path)
        if not path.startswith('/') or path.startswith('//') or parsed.scheme or parsed.netloc or parsed.fragment or parsed.query or '\\' in path or '..' in parsed.path.split('/'):
            raise ValueError('Only explicit relative API paths without query secrets are accepted')
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        headers = dict(self.headers)
        headers['Accept'] = 'application/json'
        if body is not None:
            headers['Content-Type'] = 'application/json'
        # Documented query filters are encoded separately; credentials never belong here.
        allowed_params = {'specialty','limit','offset','last_name','first_name','birth_date','client_id','doctor_id','status','date_from','date_to'}
        if params and set(params)-allowed_params:
            raise ValueError('Unknown API query parameter')
        query = '?'+urlencode(params) if params else ''
        request = Request(self.base_url + path + query, data=body, headers=headers, method=method)
        wait = self.limiter.acquire()
        if wait:
            return HTTPResult('rate_limited', retry_after=wait)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.status
                try:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ValueError('Oversized response')
                    data = json.loads(raw) if raw else None
                except (ValueError, UnicodeError):
                    return HTTPResult('uncertain' if method != 'GET' else 'error', status)
                return HTTPResult('response', status, data)
        except HTTPError as exc:
            status = exc.code
            delay = retry_after_seconds(exc.headers.get('Retry-After')) if status == 429 else 0.0
            exc.close()
            if status == 429:
                self.limiter.defer(delay)
                return HTTPResult('rate_limited', status, retry_after=delay)
            # POST may have committed before a server/proxy error. Never retry.
            return HTTPResult('uncertain' if method != 'GET' and (status >= 500 or status in (408, 301, 302, 303, 307, 308)) else 'response', status)
        except (URLError, TimeoutError, OSError, HTTPException):
            return HTTPResult('uncertain' if method != 'GET' else 'error')

    def cached_get(self, path, ttl=60.0) -> HTTPResult:
        """Only for verified reference dictionaries, never appointment availability."""
        with self.cache_lock:
            cached = self.cache.get(path)
            if cached and cached[0] > time.monotonic():
                import copy
                return copy.deepcopy(cached[1])
            result = self.request('GET', path)
            if result.kind == 'response' and result.status == 200:
                import copy
                self.cache[path] = (time.monotonic() + ttl, copy.deepcopy(result))
            return result
