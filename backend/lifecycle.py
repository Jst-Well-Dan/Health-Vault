"""Process lifecycle: expose the running uvicorn server and support a
browser-triggered self-restart that re-binds the listen address.

Why: the listen socket's bind address is fixed when the process starts, so
changing the Tailscale host (or recovering from a stale IP) requires a
restart. A plain "exit and tell the user to restart" is fragile — nothing
supervises the process (npm start and the autostart scripts start it once).
Instead we spawn a replacement process that re-reads settings and re-binds,
then gracefully stop the current server. On Windows the child shares the
parent's console so Ctrl+C keeps working; on POSIX it is detached into its
own session so it survives terminal closure.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

_BIND_RETRY_SECONDS = 90
_RESTART_DELAY_SECONDS = 1.2
_RESTART_CHILD_ENV = "HEALTH_RESTART_CHILD"

_server = None
_restart_child = False


def set_server(server) -> None:
    """Record the running uvicorn.Server so request_restart() can stop it."""
    global _server
    _server = server


def mark_restart_child() -> None:
    """Flag this process as the replacement spawned by request_restart()."""
    global _restart_child
    _restart_child = True


def is_restart_child() -> bool:
    return _restart_child


def request_restart(delay: float = _RESTART_DELAY_SECONDS) -> int:
    """Spawn a replacement process, then stop this server.

    The replacement re-reads settings (HEALTH_BOUND_HOST is removed from its
    environment) and retries the bind until the old process releases the
    port. Returns the child PID. Safe when no server is running (tests):
    only the spawn happens.
    """
    root = Path(__file__).resolve().parents[1]
    script = root / "backend" / "run_backend.py"
    env = {**os.environ}
    env.pop("HEALTH_BOUND_HOST", None)
    env.pop("HEALTH_BOUND_WARNING", None)
    env[_RESTART_CHILD_ENV] = "1"
    kwargs: dict = {}
    if os.name == "nt":
        # Inherit the console (and its standard handles) so the child keeps
        # the same terminal and Ctrl+C still stops it after the parent exits.
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(root),
        env=env,
        **kwargs,
    )

    def _stop_later() -> None:
        time.sleep(max(0.0, delay))
        if _server is not None:
            _server.should_exit = True

    threading.Thread(target=_stop_later, daemon=True).start()
    return proc.pid


def run_server(config) -> None:
    """Run uvicorn, retrying the bind while this process is a restart child
    (the old process may still hold the port briefly after a web restart)."""
    global _server
    server = uvicorn.Server(config)
    set_server(server)
    if not _restart_child:
        server.run()
        return
    deadline = time.time() + _BIND_RETRY_SECONDS
    while True:
        try:
            server.run()
        except SystemExit:
            pass
        if server.started:
            return
        if time.time() >= deadline:
            raise RuntimeError(f"重启后 {_BIND_RETRY_SECONDS} 秒内无法绑定监听地址，请检查端口占用与 Tailscale 状态后手动启动")
        time.sleep(1)
        server = uvicorn.Server(config)
        set_server(server)
