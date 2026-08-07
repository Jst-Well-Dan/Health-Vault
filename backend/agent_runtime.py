"""Launch and proxy the loopback-only Node health-agent runtime."""

import atexit
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse

_process: subprocess.Popen | None = None
_port: int | None = None
_secret: str | None = None


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _data_home() -> Path:
    return Path(os.getenv("HEALTH_VAULT_HOME", _root())).resolve()


def _secret_path() -> Path:
    return _data_home() / "data" / "agent-runtime-secret.bin"


def _load_secret() -> str:
    global _secret
    if _secret:
        return _secret
    path = _secret_path()
    try:
        _secret = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        _secret = ""
    if not _secret:
        path.parent.mkdir(parents=True, exist_ok=True)
        _secret = secrets.token_urlsafe(32)
        path.write_text(_secret, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return _secret


def is_agent_request(request: Request) -> bool:
    return secrets.compare_digest(request.headers.get("X-Health-Agent-Secret", ""), _load_secret())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_agent_runtime(port: int) -> None:
    global _process, _port
    if _process and _process.poll() is None:
        return
    node = shutil.which("node")
    script = _root() / "dist-server" / "server.js"
    if not node:
        raise RuntimeError("未找到 Node.js；纯 Web 版健康助手需要 Node.js 22.19+。")
    if not script.is_file():
        raise RuntimeError("Agent runtime 尚未编译；请先运行 npm run compile。")
    _port = _free_port()
    env = {
        **os.environ,
        "HEALTH_AGENT_PORT": str(_port),
        "HEALTH_API_URL": f"http://127.0.0.1:{port}",
        "HEALTH_AGENT_SECRET": _load_secret(),
        "HEALTH_VAULT_HOME": str(_data_home()),
        "HEALTH_AGENT_DATA_HOME": str(_data_home() / "data"),
    }
    _process = subprocess.Popen([node, str(script)], cwd=_root(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            with urllib.request.urlopen(_url("/health"), timeout=0.25) as response:
                payload = response.read().decode("utf-8")
                expected = hmac.new(_load_secret().encode("utf-8"), b"health", hashlib.sha256).hexdigest()
                if response.status == 200 and hmac.compare_digest(json.loads(payload).get("proof", ""), expected):
                    return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.1)
    stop_agent_runtime()
    raise RuntimeError("Health Agent runtime 启动超时")


def stop_agent_runtime() -> None:
    global _process, _port
    process, _process = _process, None
    _port = None
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _url(path: str) -> str:
    if not _port:
        raise RuntimeError("Health Agent runtime 尚未启动")
    return f"http://127.0.0.1:{_port}{path}"


def _request(path: str, method: str, body: bytes = b"", content_type: str | None = None) -> urllib.request.Request:
    headers = {"X-Health-Agent-Secret": _load_secret()}
    if content_type:
        headers["Content-Type"] = content_type
    return urllib.request.Request(_url(path), data=body if method != "GET" else None, headers=headers, method=method)


async def proxy_agent_request(path: str, request: Request) -> Response:
    if not _process or _process.poll() is not None:
        raise HTTPException(status_code=503, detail="健康助手服务不可用")
    body = await request.body()
    query = f"?{request.url.query}" if request.url.query else ""
    try:
        with urllib.request.urlopen(_request(f"/{path}{query}", request.method, body, request.headers.get("content-type")), timeout=60) as upstream:
            return Response(content=upstream.read(), status_code=upstream.status, media_type=upstream.headers.get_content_type())
    except urllib.error.HTTPError as error:
        return Response(content=error.read(), status_code=error.code, media_type=error.headers.get_content_type())
    except (urllib.error.URLError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail=f"健康助手服务不可用：{error}") from error


def proxy_agent_stream(request: Request) -> StreamingResponse:
    if not _process or _process.poll() is not None:
        raise HTTPException(status_code=503, detail="健康助手服务不可用")

    def stream() -> Iterator[bytes]:
        try:
            with urllib.request.urlopen(_request("/agent/stream", "GET"), timeout=3600) as upstream:
                while True:
                    chunk = upstream.readline()
                    if not chunk:
                        break
                    yield chunk
        except (urllib.error.URLError, RuntimeError):
            return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


atexit.register(stop_agent_runtime)
