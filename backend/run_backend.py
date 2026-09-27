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
    """Tailscale-only：只允许本机 + Tailscale 100.x，其余拒绝（fail-closed）。"""
    if system_settings.is_allowed_bind_host(bind_host):
        return None
    return (
        f"拒绝启动：{bind_host} 不是本机也不是 Tailscale 地址。"
        "只允许 127.0.0.1 或 Tailscale 100.x；不要设为 0.0.0.0 或局域网 IP。"
    )


def _drop_unbindable_loopback_v6(hosts: list[str], port: int) -> list[str]:
    """Best-effort ::1: some machines have no IPv6 loopback; drop it instead of
    refusing to start (127.0.0.1 still covers local use)."""
    import socket

    if "::1" not in hosts:
        return hosts
    try:
        addr_infos = socket.getaddrinfo("::1", port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        addr_infos = []
    for family, socktype, proto, _, sockaddr in addr_infos:
        probe = socket.socket(family, socktype, proto)
        try:
            probe.bind(sockaddr)
            return hosts
        except OSError:
            continue
        finally:
            probe.close()
    print("本机 IPv6 回环不可用，仅监听 127.0.0.1（不影响使用）。", flush=True)
    return [h for h in hosts if h != "::1"]


def port_conflict_error(bind_host: str, port: int) -> str | None:
    """启动前预检端口：被占用时给可执行的下一步，而不是 uvicorn 的原始报错。"""
    import socket

    try:
        addr_infos = socket.getaddrinfo(bind_host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return f"无法解析监听地址 {bind_host}（{exc}）"
    for family, socktype, proto, _, sockaddr in addr_infos:
        probe = socket.socket(family, socktype, proto)
        try:
            probe.bind(sockaddr)
        except OSError:
            continue
        finally:
            probe.close()
        return None
    return (
        f"端口被占用：{bind_host}:{port} 已有进程在监听，可能是网页“立即重启”留下的子进程。"
        "先结束旧进程再启动：新开 PowerShell 跑 "
        "Get-NetTCPConnection -LocalPort 8000 | Format-Table LocalAddress,OwningProcess,State -AutoSize"
        "，记下 OwningProcess 列的数字，再跑 taskkill /F /PID <数字>，然后重新 npm start。"
    )


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    bind_hosts, warning = system_settings.resolve_bind_hosts_with_heal()
    port = int(os.getenv("HEALTH_PORT", "8000"))
    bind_hosts = _drop_unbindable_loopback_v6(bind_hosts, port)
    os.environ["HEALTH_BOUND_HOSTS"] = ",".join(bind_hosts)  # records the hosts actually bound this run, for /api/settings/system
    os.environ.pop("HEALTH_BOUND_HOST", None)  # legacy single-host key, superseded by HEALTH_BOUND_HOSTS
    if warning:
        os.environ["HEALTH_BOUND_WARNING"] = warning
    else:
        os.environ.pop("HEALTH_BOUND_WARNING", None)
    for bind_host in bind_hosts:
        guard = bind_guard_error(bind_host)
        if guard:
            print(guard, file=sys.stderr, flush=True)
            sys.exit(1)
    for bind_host in bind_hosts:
        conflict = port_conflict_error(bind_host, port)
        if conflict:
            print(conflict, file=sys.stderr, flush=True)
            sys.exit(1)
    if os.getenv("HEALTH_RESTART_CHILD") == "1":
        lifecycle.mark_restart_child()
    configs = [
        uvicorn.Config(
            "main:app",
            host=bind_host,
            port=port,
            log_level="warning",
        )
        for bind_host in bind_hosts
    ]
    lifecycle.run_servers(configs)
