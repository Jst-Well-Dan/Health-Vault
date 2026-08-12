import os
import sys

import uvicorn

from services import system_settings

import lifecycle


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
    if os.getenv("HEALTH_RESTART_CHILD") == "1":
        lifecycle.mark_restart_child()
    config = uvicorn.Config(
        "main:app",
        host=bind_host,
        port=int(os.getenv("HEALTH_PORT", "8000")),
        log_level="warning",
    )
    lifecycle.run_server(config)
