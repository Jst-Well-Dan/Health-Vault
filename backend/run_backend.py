import os
import sys

import uvicorn

from services import system_settings


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    bind_host = system_settings.resolved_host()
    os.environ["HEALTH_BOUND_HOST"] = bind_host  # records the host actually bound this run, for /api/settings/system
    uvicorn.run(
        "main:app",
        host=bind_host,
        port=int(os.getenv("HEALTH_PORT", "8000")),
        log_level="warning",
    )
