import os
import sys

import uvicorn


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("HEALTH_PORT", "8000")), log_level="warning")
