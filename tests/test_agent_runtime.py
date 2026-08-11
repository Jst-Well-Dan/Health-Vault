import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import agent_runtime


class _RunningProcess:
    def poll(self):
        return None


class _Headers:
    def get_content_type(self):
        return "application/json"


class _Upstream:
    status = 200
    headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b'{"ok": true}'


def _request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/agent-runtime/agent/settings",
            "query_string": b"provider=test",
            "headers": [],
        },
        receive,
    )


class AgentRuntimeProxyTest(unittest.TestCase):
    def setUp(self):
        self.old_process = agent_runtime._process
        self.old_port = agent_runtime._port
        self.old_secret = agent_runtime._secret
        agent_runtime._process = _RunningProcess()
        agent_runtime._port = 1
        agent_runtime._secret = "test-agent-secret"

    def tearDown(self):
        agent_runtime._process = self.old_process
        agent_runtime._port = self.old_port
        agent_runtime._secret = self.old_secret

    def test_proxy_runs_blocking_upstream_io_in_a_worker_thread(self):
        event_loop_thread = threading.get_ident()
        upstream_threads = []

        def urlopen(request, timeout):
            upstream_threads.append(threading.get_ident())
            self.assertEqual(request.full_url, "http://127.0.0.1:1/agent/settings?provider=test")
            self.assertEqual(timeout, 60)
            return _Upstream()

        with patch("agent_runtime.urllib.request.urlopen", side_effect=urlopen):
            response = asyncio.run(agent_runtime.proxy_agent_request("agent/settings", _request()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b'{"ok": true}')
        self.assertEqual(len(upstream_threads), 1)
        self.assertNotEqual(upstream_threads[0], event_loop_thread)

    def test_proxy_returns_gateway_timeout_when_upstream_times_out(self):
        with patch("agent_runtime.urllib.request.urlopen", side_effect=TimeoutError):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(agent_runtime.proxy_agent_request("agent/settings", _request()))

        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(raised.exception.detail, "健康助手服务响应超时")


if __name__ == "__main__":
    unittest.main()
