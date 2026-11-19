"""The metrics guard: what it refuses, what it lets through, and that it stays out of the way."""

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY = "test-metrics-key"


def load(key=KEY):
    """Build the middleware around a recording app, with the given key in the environment."""
    environment = {} if key is None else {"METRICS_API_KEY": key}
    with mock.patch.dict(os.environ, environment, clear=True):
        module = importlib.import_module("maple_metrics_auth")
        calls = []

        async def app(scope, receive, send):
            calls.append((scope, receive, send))

        return module.MetricsAuthMiddleware(app), calls


def request(path, authorization=None, kind="http", root_path="", extra_headers=()):
    headers = list(extra_headers)
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    return {"type": kind, "path": path, "root_path": root_path, "headers": headers, "method": "GET"}


def run(middleware, scope):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent, receive, send


class Refusals(unittest.TestCase):
    def assert_refused(self, scope, middleware=None):
        middleware, calls = (middleware, None) if middleware else load()
        sent, _, _ = run(middleware, scope)
        self.assertEqual([m["type"] for m in sent], ["http.response.start", "http.response.body"])
        self.assertEqual(sent[0]["status"], 401)
        self.assertIn((b"www-authenticate", b"Bearer"), sent[0]["headers"])
        self.assertEqual(sent[1]["body"], b'{"error":"Unauthorized"}')
        if calls is not None:
            self.assertEqual(calls, [])

    def test_no_key_sent(self):
        self.assert_refused(request("/metrics"))

    def test_wrong_key(self):
        self.assert_refused(request("/metrics", "Bearer not-the-key"))

    def test_key_with_extra_characters(self):
        for value in (f"Bearer {KEY}x", f"Bearer x{KEY}", f"Bearer {KEY} ", f"Bearer  {KEY}"):
            with self.subTest(value=value):
                self.assert_refused(request("/metrics", value))

    def test_other_schemes_and_empty_tokens(self):
        for value in (f"Basic {KEY}", KEY, "Bearer", "Bearer ", ""):
            with self.subTest(value=value):
                self.assert_refused(request("/metrics", value))

    def test_two_authorization_headers(self):
        scope = request(
            "/metrics",
            f"Bearer {KEY}",
            extra_headers=[(b"authorization", b"Bearer something-else")],
        )
        self.assert_refused(scope)

    def test_every_spelling_under_metrics(self):
        # vLLM routes with the pattern ^/metrics(.*)$, so all of these reach Prometheus.
        for path in ("/metrics/", "/metrics/anything", "/metricsfoo", "//metrics", "/METRICS", "/Metrics/x", "metrics"):
            with self.subTest(path=path):
                self.assert_refused(request(path))

    def test_root_path_prefix(self):
        self.assert_refused(request("/proxy/metrics", root_path="/proxy"))

    def test_every_method(self):
        for method in ("GET", "HEAD", "POST", "OPTIONS"):
            with self.subTest(method=method):
                scope = request("/metrics")
                scope["method"] = method
                self.assert_refused(scope)

    def test_no_key_configured_refuses_everything(self):
        for key in (None, ""):
            for authorization in (None, "Bearer ", "Bearer anything"):
                with self.subTest(key=key, authorization=authorization):
                    middleware, calls = load(key)
                    self.assert_refused(request("/metrics", authorization), middleware)
                    self.assertEqual(calls, [])

    def test_websocket_is_closed(self):
        middleware, calls = load()
        sent, _, _ = run(middleware, request("/metrics", kind="websocket"))
        self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])
        self.assertEqual(calls, [])


class PassThrough(unittest.TestCase):
    def assert_passed_untouched(self, scope, key=KEY):
        middleware, calls = load(key)
        sent, receive, send = run(middleware, scope)
        self.assertEqual(sent, [])
        self.assertEqual(len(calls), 1)
        # The very same objects: nothing is wrapped, so streaming and
        # disconnect handling behave exactly as they do without the guard.
        self.assertIs(calls[0][0], scope)
        self.assertIs(calls[0][1], receive)
        self.assertIs(calls[0][2], send)

    def test_metrics_with_the_key(self):
        for value in (f"Bearer {KEY}", f"bearer {KEY}", f"BEARER {KEY}"):
            with self.subTest(value=value):
                self.assert_passed_untouched(request("/metrics", value))

    def test_header_name_case(self):
        scope = request("/metrics", extra_headers=[(b"Authorization", f"Bearer {KEY}".encode())])
        self.assert_passed_untouched(scope)

    def test_inference_paths_need_nothing_from_this_guard(self):
        for path in ("/v1/chat/completions", "/v1/models", "/v1/responses", "/health", "/", "/v1/metrics"):
            with self.subTest(path=path):
                self.assert_passed_untouched(request(path))

    def test_inference_paths_pass_without_a_configured_key(self):
        self.assert_passed_untouched(request("/v1/chat/completions"), key=None)

    def test_lifespan_and_other_scopes(self):
        self.assert_passed_untouched({"type": "lifespan"})


class Module(unittest.TestCase):
    def test_standard_library_only(self):
        source = (Path(__file__).resolve().parent.parent / "maple_metrics_auth.py").read_text()
        imports = sorted(line.split()[1] for line in source.splitlines() if line.startswith("import "))
        self.assertEqual(imports, ["hashlib", "hmac", "os"])
        self.assertNotIn("\nfrom ", source)

    def test_key_is_never_kept_in_the_clear(self):
        middleware, _ = load()
        self.assertNotIn(KEY, repr(vars(middleware)))


if __name__ == "__main__":
    unittest.main()
