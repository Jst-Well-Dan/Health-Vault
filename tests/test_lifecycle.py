import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import lifecycle


class FakePopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 4242


class RequestRestartTest(unittest.TestCase):
    def tearDown(self):
        lifecycle.set_server(None)

    def test_spawns_replacement_with_restart_env_and_no_stale_bound_host(self):
        with patch.dict(os.environ, {"HEALTH_BOUND_HOSTS": "127.0.0.1,100.64.0.1", "HEALTH_BOUND_HOST": "100.64.0.1", "HEALTH_BOUND_WARNING": "stale"}), \
             patch("subprocess.Popen", side_effect=FakePopen) as popen:
            pid = lifecycle.request_restart()
        self.assertEqual(pid, 4242)
        call = popen.call_args
        self.assertEqual(call.args[0][0], sys.executable)
        self.assertTrue(str(call.args[0][1]).endswith(str(Path("backend") / "run_backend.py")))
        child_env = call.kwargs["env"]
        self.assertEqual(child_env["HEALTH_RESTART_CHILD"], "1")
        self.assertNotIn("HEALTH_BOUND_HOSTS", child_env)
        self.assertNotIn("HEALTH_BOUND_HOST", child_env)
        self.assertNotIn("HEALTH_BOUND_WARNING", child_env)
        self.assertEqual(call.kwargs["cwd"], str(ROOT))
        if os.name == "nt":
            self.assertIs(call.kwargs.get("close_fds"), True)
        else:
            self.assertIs(call.kwargs.get("start_new_session"), True)

    def test_schedules_graceful_shutdown_of_running_server(self):
        server = MagicMock()
        server.should_exit = False
        lifecycle.set_server(server)
        with patch("subprocess.Popen", side_effect=FakePopen):
            lifecycle.request_restart(delay=0)
        time.sleep(0.25)
        self.assertIs(server.should_exit, True)

    def test_does_not_touch_server_when_none_registered(self):
        lifecycle.set_server(None)
        with patch("subprocess.Popen", side_effect=FakePopen):
            lifecycle.request_restart(delay=0)  # must not raise
        time.sleep(0.05)


class FakeServer:
    """uvicorn.Server stand-in: fail N binds then start successfully."""

    def __init__(self, config, fails):
        self.config = config
        self.fails = fails
        self.started = False
        self.run_calls = 0

    def run(self):
        self.run_calls += 1
        if self.fails > 0:
            self.fails -= 1
            raise SystemExit(3)
        self.started = True


class RunServerTest(unittest.TestCase):
    def tearDown(self):
        lifecycle.set_server(None)
        lifecycle._restart_child = False

    def test_retries_bind_for_restart_child(self):
        config = object()
        made = []
        fail_counts = [1, 0]

        def factory(cfg):
            server = FakeServer(cfg, fails=fail_counts.pop(0))
            made.append(server)
            return server

        fake_uvicorn = MagicMock()
        fake_uvicorn.Server = factory
        with patch.object(lifecycle, "uvicorn", fake_uvicorn), \
             patch.object(lifecycle.time, "sleep", lambda _: None):
            lifecycle.mark_restart_child()
            lifecycle.run_server(config)
        self.assertEqual(len(made), 2)
        self.assertTrue(made[-1].started)
        self.assertEqual(made[0].run_calls, 1)
        self.assertEqual(made[1].run_calls, 1)
        # the running server is registered for lifecycle control
        self.assertIs(lifecycle._server, made[-1])

    def test_gives_up_after_retry_window(self):
        config = object()
        fail_counts = [1] * 10  # every bind attempt fails

        def factory(cfg):
            return FakeServer(cfg, fails=fail_counts.pop(0))

        fake_uvicorn = MagicMock()
        fake_uvicorn.Server = factory
        with patch.object(lifecycle, "uvicorn", fake_uvicorn), \
             patch.object(lifecycle.time, "sleep", lambda _: None), \
             patch.object(lifecycle.time, "time", side_effect=[0, 0, 0, 0, 100, 100]):
            lifecycle.mark_restart_child()
            with self.assertRaises(RuntimeError):
                lifecycle.run_server(config)

    def test_runs_once_when_not_restart_child(self):
        config = object()
        made = []

        def factory(cfg):
            server = FakeServer(cfg, fails=0)
            made.append(server)
            return server

        fake_uvicorn = MagicMock()
        fake_uvicorn.Server = factory
        with patch.object(lifecycle, "uvicorn", fake_uvicorn):
            lifecycle.run_server(config)
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].started)


if __name__ == "__main__":
    unittest.main()
