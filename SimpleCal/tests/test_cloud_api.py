"""Verify the ASGI app using simulated quota storage and model responses."""

import json
import os
import unittest
from importlib.util import find_spec
from io import BytesIO
from unittest.mock import Mock, patch

HAS_CLOUD_TEST_DEPS = find_spec("fastapi") is not None and find_spec("httpx") is not None
if HAS_CLOUD_TEST_DEPS:
    from httpx import Response

    from simple_calculate.ai_server import ExplanationError
    from simple_calculate.cloud_api import RedisQuota, create_app


@unittest.skipUnless(HAS_CLOUD_TEST_DEPS, "云端测试需要 FastAPI 和 httpx")
class TestCloudApi(unittest.TestCase):
    origin = "https://atri-realm.github.io"

    def setUp(self):
        env = patch.dict(os.environ, {
            "SIMPLECAL_ALLOWED_ORIGINS": self.origin,
            "SIMPLECAL_API_BASE": "https://provider.example/v1",
            "SIMPLECAL_API_KEY": "example-key",
            "RENDER": "true",
        })
        env.start()
        self.addCleanup(env.stop)
        self.evaluate = Mock(return_value=0)
        self.quota = RedisQuota(self.evaluate, per_ip=4, per_day=60)
        self.app = create_app(quota=self.quota)

        async def run_inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        threadpool = patch("simple_calculate.cloud_api.run_in_threadpool", run_inline)
        threadpool.start()
        self.addCleanup(threadpool.stop)

        def model_response(request, timeout):
            content = json.dumps({"steps": ["先求出两部分合起来有多少。"]}, ensure_ascii=False)
            body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
            return BytesIO(json.dumps(body).encode())

        opener = patch("simple_calculate.ai_server.build_opener")
        self.upstream = opener.start().return_value.open
        self.upstream.side_effect = model_response
        self.addCleanup(opener.stop)

    def request(self, method, path, *, headers, payload=None):
        headers = {**headers}
        body = b""
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        scope = {
            "type": "http", "http_version": "1.1", "asgi": {"version": "3.0"},
            "method": method, "scheme": "https", "path": path, "raw_path": path.encode(), "query_string": b"",
            "root_path": "", "client": ("127.0.0.1", 12345), "server": ("api.example", 443),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        }
        outgoing = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            outgoing.append(message)

        # These ASGI messages and the test model complete in memory without opening sockets.
        request = self.app(scope, receive, send)
        try:
            with self.assertRaises(StopIteration):
                request.send(None)
        finally:
            request.close()
        status = outgoing[0]
        content = b"".join(message.get("body", b"") for message in outgoing[1:])
        return Response(status["status"], headers=status["headers"], content=content)

    def post(self, expression="2 + 3", *, origin=None):
        return self.request("POST", "/api/explain", payload={"expression": expression}, headers={
            "Origin": self.origin if origin is None else origin, "CF-Connecting-IP": "192.0.2.99",
        })

    def test_origin_preflight_and_explanation(self):
        preflight = self.request("OPTIONS", "/api/explain", headers={
            "Origin": self.origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], self.origin)
        health = self.request("GET", "/healthz", headers={"Origin": self.origin})
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(health.headers["access-control-allow-origin"], self.origin)
        self.evaluate.assert_not_called()

        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["access-control-allow-origin"], self.origin)
        self.assertEqual(response.json()["steps"][0]["equation"], "2 + 3 = 5")
        self.upstream.assert_called_once()
        _, count, minute, day, per_ip, per_day, _, _ = self.evaluate.call_args.args
        self.assertEqual((count, per_ip, per_day), (2, 4, 60))
        self.assertTrue(minute.startswith("simplecal:ai:minute:"))
        self.assertNotIn("192.0.2.99", minute)
        self.assertTrue(day.startswith("simplecal:ai:day:"))

    def test_forbidden_origin_and_invalid_input_do_not_use_quota(self):
        denied = self.post(origin="https://unapproved.example")
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("access-control-allow-origin", denied.headers)
        invalid = self.post("3 ÷ 0")
        self.assertEqual(invalid.status_code, 400)
        extra = self.request("POST", "/api/explain", payload={"expression": "2 + 3", "student": "demo"}, headers={"Origin": self.origin})
        self.assertEqual(extra.status_code, 400)
        oversized = self.post("0" * 1500)
        self.assertEqual(oversized.status_code, 413)
        self.evaluate.assert_not_called()
        self.upstream.assert_not_called()

    def test_quota_and_store_failure_prevent_model_requests(self):
        for result, expected in [(1, "频繁"), (2, "今天")]:
            with self.subTest(result=result):
                self.evaluate.return_value = result
                response = self.post()
                self.assertEqual(response.status_code, 429)
                self.assertIn(expected, response.json()["error"])
                self.assertGreater(int(response.headers["retry-after"]), 0)
                self.assertEqual(response.headers["access-control-allow-origin"], self.origin)
        self.evaluate.side_effect = ExplanationError(503, "暂时无法核对剩余次数")
        self.assertEqual(self.post().status_code, 503)
        self.upstream.assert_not_called()

    def test_beijing_daily_window_and_shared_daily_key(self):
        with patch("simple_calculate.cloud_api.time", return_value=57599):
            self.quota.reserve("192.0.2.1")
            self.quota.reserve("192.0.2.2")
        with patch("simple_calculate.cloud_api.time", return_value=57600):
            self.quota.reserve("192.0.2.1")
        first, second, tomorrow = [call.args for call in self.evaluate.call_args_list]
        self.assertNotEqual(first[2], second[2])
        self.assertEqual(first[3], second[3])
        self.assertEqual(first[-1], 1)
        self.assertNotEqual(first[3], tomorrow[3])
        self.assertEqual(tomorrow[-1], 86400)
