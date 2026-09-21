import os
import sys

try:
    import uvicorn
except ModuleNotFoundError as exc:  # 没有装依赖时给出可执行的下一步，而不是一长串 traceback
    sys.stderr.write(
        f"缺少后端依赖（{exc.name}）。请用项目虚拟环境安装后重试：\n"
        "  python -m venv .venv\n"
        + (
            "  .\\.venv\\Scripts\\python -m pip install -r backend\\requirements.txt\n"
            if os.name == "nt"
            else "  .venv/bin/python -m pip install -r backend/requirements.txt\n"
        )
        + "也可用 HEALTH_PYTHON 指向已装好依赖的解释器。\n"
    )
    raise SystemExit(1) from exc

from services import system_settings

import lifecycle


def bind_guard_error(bind_host: str) -> str | None:
    """本应用没有登录凭据，因此只允许监听本机地址（fail-closed）。"""
    if system_settings.is_loopback_host(bind_host):
        return None
    return (
        f"拒绝启动：绑定到非本机地址（{bind_host}）会让局域网内任何人直接读写健康档案。"
        "本版本没有登录鉴权，因此只允许 127.0.0.1；请把监听地址改回本机。"
    )


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    bind_host, warning = system_settings.resolve_bind_host_with_heal()
    os.environ["HEALTH_BOUND_HOST"] = bind_host  # records the host actually bound this run, for /api/settings/system
    if warning:
        os.environ["HEALTH_BOUND_WARNING"] = warning
    else:
        os.environ.pop("HEALTH_BOUND_WARNING", None)
    guard = bind_guard_error(bind_host)
    if guard:
        print(guard, file=sys.stderr, flush=True)
        sys.exit(1)
    if os.getenv("HEALTH_RESTART_CHILD") == "1":
        lifecycle.mark_restart_child()
    config = uvicorn.Config(
        "main:app",
        host=bind_host,
        port=int(os.getenv("HEALTH_PORT", "8000")),
        log_level="warning",
    )
    lifecycle.run_server(config)
