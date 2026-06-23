import subprocess
import sys
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

_lock = threading.Lock()
_state = {
    "status": "idle",
    "started_at": None,
    "last_completed": None,
    "last_error": None,
    "process": None,
}


def _monitor(proc):
    proc.wait()
    with _lock:
        if proc.returncode == 0:
            _state["status"] = "idle"
            _state["last_completed"] = datetime.now(timezone.utc).isoformat()
            _state["last_error"] = None
        else:
            _state["status"] = "failed"
            _state["last_error"] = f"exit code {proc.returncode}"
        _state["process"] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/pipeline/trigger")
def trigger():
    with _lock:
        if _state["status"] == "running":
            return JSONResponse(
                status_code=409,
                content={
                    "status": "already_running",
                    "started_at": _state["started_at"],
                },
            )
        proc = subprocess.Popen(
            [sys.executable, "run_pipeline.py", "--index", "NSE All"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        now = datetime.now(timezone.utc).isoformat()
        _state["status"] = "running"
        _state["started_at"] = now
        _state["process"] = proc

    threading.Thread(target=_monitor, args=(proc,), daemon=True).start()
    return JSONResponse(
        status_code=202,
        content={"status": "started", "started_at": now},
    )


@app.get("/pipeline/status")
def pipeline_status():
    with _lock:
        return {
            "status": _state["status"],
            "started_at": _state["started_at"],
            "last_completed": _state["last_completed"],
            "last_error": _state["last_error"],
        }
