# QuantScreen Docker + Pipeline Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Docker deployment files, a FastAPI pipeline trigger API, and an n8n workflow JSON so QuantScreen runs self-hosted on TrueNAS SCALE with automated daily data refreshes.

**Architecture:** A single `Dockerfile` builds one image used by both compose services. The `app` service runs Streamlit on port 8501; the `pipeline` service runs FastAPI on port 8502 and spawns `run_pipeline.py` as a non-blocking subprocess when triggered. Both share a named Docker volume (`quantscreen-data`) mounted at `/app/data`. n8n (same host, port 5678) uses an Execute Command node to rebuild the app and an HTTP POST to the pipeline API, with Telegram notifications on success/failure.

**Tech Stack:** Python 3.12-slim, FastAPI ≥ 0.111, Uvicorn ≥ 0.29, Docker Compose v2, pytest ≥ 8, httpx ≥ 0.27, n8n 1.x

## Global Constraints

- `python:3.12-slim` base image — no deviation
- `run_pipeline.py`, `app/main.py`, `config.py` are NOT modified
- `DATA_DIR` in `config.py` resolves to `/app/data` inside containers — no path changes needed
- Named volume `quantscreen-data` is the single data store; never use bind mounts for data
- Port 8501 → Streamlit UI; port 8502 → FastAPI trigger (both exposed to host)
- Both containers use the same built image; the `pipeline` service overrides `command:` in compose
- All timestamps: UTC, ISO 8601 string (e.g. `2026-06-23T07:00:00+00:00`)
- Pipeline is always triggered with `--index "NSE All"` — no other index is supported via the API

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `api.py` | CREATE | FastAPI app: `/health`, `/pipeline/trigger`, `/pipeline/status` |
| `tests/test_api.py` | CREATE | Full pytest suite for all three endpoints |
| `requirements.txt` | UPDATE | Append `fastapi>=0.111.0` and `uvicorn[standard]>=0.29.0` |
| `requirements-dev.txt` | CREATE | Test-only deps: `pytest>=8.0.0`, `httpx>=0.27.0` |
| `.dockerignore` | CREATE | Exclude `venv/`, `data/`, `__pycache__/`, `.git/` from build context |
| `Dockerfile` | CREATE | `python:3.12-slim`, installs deps, defaults to `streamlit run` |
| `docker-compose.yml` | CREATE | `app` + `pipeline` services sharing `quantscreen-data` volume |
| `n8n_workflow.json` | CREATE | Importable n8n 1.x workflow (schedule → exec → trigger → Telegram) |

---

### Task 1: FastAPI trigger service

**Files:**
- Create: `api.py`
- Create: `tests/test_api.py`
- Modify: `requirements.txt` (append 2 lines at end)
- Create: `requirements-dev.txt`

**Interfaces — Produces:**
- `GET /health` → `200 {"status": "ok"}`
- `POST /pipeline/trigger` → `202 {"status": "started", "started_at": "<iso>"}` or `409 {"status": "already_running", "started_at": "<iso>"}`
- `GET /pipeline/status` → `200 {"status": "idle|running|failed", "started_at": str|null, "last_completed": str|null, "last_error": str|null}`

---

- [ ] **Step 1: Update requirements and install dev deps**

Append to the end of `requirements.txt`:
```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
```

Create `requirements-dev.txt`:
```
pytest>=8.0.0
httpx>=0.27.0
```

Install everything:
```
pip install fastapi "uvicorn[standard]" pytest httpx
```

---

- [ ] **Step 2: Create tests directory and write the failing tests**

Create `tests/` directory and `tests/test_api.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import api


@pytest.fixture(autouse=True)
def reset_state():
    """Reset pipeline state before every test."""
    api._state.update({
        "status": "idle",
        "started_at": None,
        "last_completed": None,
        "last_error": None,
        "process": None,
    })
    yield


@pytest.fixture
def client():
    return TestClient(api.app)


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trigger_returns_202_when_idle(client):
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("api.subprocess.Popen", return_value=mock_proc) as mock_popen:
        response = client.post("/pipeline/trigger")

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "started"
    assert data["started_at"] is not None
    args, _ = mock_popen.call_args
    assert args[0] == ["python", "run_pipeline.py", "--index", "NSE All"]


def test_trigger_returns_409_when_running(client):
    api._state["status"] = "running"
    api._state["started_at"] = "2026-06-23T07:00:00+00:00"

    response = client.post("/pipeline/trigger")

    assert response.status_code == 409
    data = response.json()
    assert data["status"] == "already_running"
    assert data["started_at"] == "2026-06-23T07:00:00+00:00"


def test_failed_run_is_retryable(client):
    """A previously failed run must not block the next trigger."""
    api._state["status"] = "failed"
    api._state["last_error"] = "exit code 1"

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("api.subprocess.Popen", return_value=mock_proc):
        response = client.post("/pipeline/trigger")

    assert response.status_code == 202


def test_status_returns_idle_by_default(client):
    response = client.get("/pipeline/status")
    assert response.status_code == 200
    assert response.json() == {
        "status": "idle",
        "started_at": None,
        "last_completed": None,
        "last_error": None,
    }


def test_status_reflects_running_state(client):
    api._state["status"] = "running"
    api._state["started_at"] = "2026-06-23T07:00:00+00:00"

    response = client.get("/pipeline/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["started_at"] == "2026-06-23T07:00:00+00:00"
```

---

- [ ] **Step 3: Run tests — expect ImportError**

```
python -m pytest tests/test_api.py -v
```
Expected: `ERROR tests/test_api.py - ModuleNotFoundError: No module named 'api'`

---

- [ ] **Step 4: Implement api.py**

Create `api.py` at the project root:
```python
import subprocess
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
            ["python", "run_pipeline.py", "--index", "NSE All"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
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
```

---

- [ ] **Step 5: Run tests — expect all pass**

```
python -m pytest tests/test_api.py -v
```
Expected:
```
PASSED tests/test_api.py::test_health_returns_ok
PASSED tests/test_api.py::test_trigger_returns_202_when_idle
PASSED tests/test_api.py::test_trigger_returns_409_when_running
PASSED tests/test_api.py::test_failed_run_is_retryable
PASSED tests/test_api.py::test_status_returns_idle_by_default
PASSED tests/test_api.py::test_status_reflects_running_state
6 passed in <1s
```

---

- [ ] **Step 6: Commit**

```
git add api.py tests/test_api.py requirements.txt requirements-dev.txt
git commit -m "feat: add FastAPI pipeline trigger service with tests"
```

---

### Task 2: Docker build files

**Files:**
- Create: `.dockerignore`
- Create: `Dockerfile`

**Interfaces:**
- Consumes: `requirements.txt` (updated in Task 1)
- Produces: Docker image `quantscreen` that runs Streamlit by default; command can be overridden to run Uvicorn

---

- [ ] **Step 1: Create .dockerignore**

Create `.dockerignore` at project root:
```
venv/
.venv/
data/
__pycache__/
*.pyc
*.pyo
.git/
.pytest_cache/
*.egg-info/
dist/
build/
docs/
.vscode/
.idea/
```

---

- [ ] **Step 2: Create Dockerfile**

Create `Dockerfile` at project root:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["streamlit", "run", "app/main.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

---

- [ ] **Step 3: Build the image (requires Docker)**

```
docker build -t quantscreen:test .
```
Expected: `Successfully built <image-id>` with no errors. First build: 3–7 min (pip install). Subsequent rebuilds with unchanged `requirements.txt`: ~30 s (cached `pip install` layer).

---

- [ ] **Step 4: Verify Streamlit starts from the built image**

```
docker run --rm -p 8501:8501 quantscreen:test
```
Expected: Streamlit starts and prints the URL. Visit `http://localhost:8501` — app loads (may show empty data with no volume mounted; that's expected). Stop with Ctrl+C.

---

- [ ] **Step 5: Verify Uvicorn starts when the command is overridden**

```
docker run --rm -p 8502:8502 quantscreen:test uvicorn api:app --host 0.0.0.0 --port 8502
```
In a second terminal:
```
curl http://localhost:8502/health
```
Expected: `{"status":"ok"}`. Stop with Ctrl+C.

---

- [ ] **Step 6: Commit**

```
git add Dockerfile .dockerignore
git commit -m "feat: add Dockerfile and .dockerignore"
```

---

### Task 3: Compose orchestration

**Files:**
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `Dockerfile` (Task 2)
- Produces: two running services (`quantscreen-app` on 8501, `quantscreen-pipeline` on 8502) sharing named volume `quantscreen-data` at `/app/data`

---

- [ ] **Step 1: Create docker-compose.yml**

Create `docker-compose.yml` at project root:
```yaml
services:
  app:
    build: .
    container_name: quantscreen-app
    ports:
      - "8501:8501"
    volumes:
      - quantscreen-data:/app/data
    restart: unless-stopped

  pipeline:
    build: .
    container_name: quantscreen-pipeline
    command: uvicorn api:app --host 0.0.0.0 --port 8502
    ports:
      - "8502:8502"
    volumes:
      - quantscreen-data:/app/data
    restart: unless-stopped

volumes:
  quantscreen-data:
```

---

- [ ] **Step 2: Validate compose syntax**

```
docker compose config
```
Expected: Full resolved config prints with no errors. Confirm `quantscreen-data` appears under `volumes:` in the output.

---

- [ ] **Step 3: Build and start both services**

```
docker compose up --build -d
docker compose ps
```
Expected:
```
NAME                      STATUS
quantscreen-app           running
quantscreen-pipeline      running
```

---

- [ ] **Step 4: Smoke-test both endpoints**

```
curl http://localhost:8502/health
curl http://localhost:8501/_stcore/health
```
Expected: both return `{"status":"ok"}`.

---

- [ ] **Step 5: Verify volume persists across rebuild**

```
docker compose down
docker volume ls | findstr quantscreen-data
docker compose up --build -d
```
Expected: `docker volume ls` shows `quantscreen-data` after `down` (volumes are only deleted with `down -v`). Both services start again after rebuild.

---

- [ ] **Step 6: Commit**

```
git add docker-compose.yml
git commit -m "feat: add docker-compose with two services and shared data volume"
```

---

### Task 4: n8n workflow export

**Files:**
- Create: `n8n_workflow.json`

**Interfaces:**
- Consumes: `POST http://localhost:8502/pipeline/trigger` (Task 1 — must be running)
- Produces: importable n8n 1.x workflow JSON; three values to replace after import: repo path, Telegram credential ID, Telegram chat ID

---

- [ ] **Step 1: Create n8n_workflow.json**

Create `n8n_workflow.json` at project root:
```json
{
  "name": "QuantScreen Pipeline Refresh",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "0 7,13 * * *"
            }
          ]
        }
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000001",
      "name": "Schedule (7AM + 1PM)",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1.1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "command": "cd /mnt/tank/quantscreen && git pull && docker compose up --build -d"
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000002",
      "name": "Git Pull & Rebuild",
      "type": "n8n-nodes-base.executeCommand",
      "typeVersion": 1,
      "position": [460, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://localhost:8502/pipeline/trigger",
        "options": {
          "response": {
            "response": {
              "neverError": true
            }
          }
        }
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000003",
      "name": "Trigger Pipeline",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.1,
      "position": [680, 300]
    },
    {
      "parameters": {
        "conditions": {
          "string": [
            {
              "value1": "={{ $json.status }}",
              "operation": "equal",
              "value2": "started"
            }
          ]
        }
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000004",
      "name": "Triggered OK?",
      "type": "n8n-nodes-base.if",
      "typeVersion": 1,
      "position": [900, 300]
    },
    {
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "✅ QuantScreen pipeline triggered — NSE All refresh started at {{ $now.toISO() }}",
        "additionalFields": {}
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000005",
      "name": "Telegram Success",
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1.1,
      "position": [1120, 180],
      "credentials": {
        "telegramApi": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "Telegram Bot"
        }
      }
    },
    {
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "⏳ QuantScreen pipeline already running since {{ $json.started_at }} — skipping trigger",
        "additionalFields": {}
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000006",
      "name": "Telegram Already Running",
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1.1,
      "position": [1120, 420],
      "credentials": {
        "telegramApi": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "Telegram Bot"
        }
      }
    },
    {
      "parameters": {},
      "id": "a1b2c3d4-0000-0000-0000-000000000007",
      "name": "On Workflow Error",
      "type": "n8n-nodes-base.errorTrigger",
      "typeVersion": 1,
      "position": [240, 560]
    },
    {
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "🚨 QuantScreen workflow error — {{ $json.execution.error.message }}",
        "additionalFields": {}
      },
      "id": "a1b2c3d4-0000-0000-0000-000000000008",
      "name": "Telegram Error",
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1.1,
      "position": [460, 560],
      "credentials": {
        "telegramApi": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "Telegram Bot"
        }
      }
    }
  ],
  "connections": {
    "Schedule (7AM + 1PM)": {
      "main": [
        [{"node": "Git Pull & Rebuild", "type": "main", "index": 0}]
      ]
    },
    "Git Pull & Rebuild": {
      "main": [
        [{"node": "Trigger Pipeline", "type": "main", "index": 0}]
      ]
    },
    "Trigger Pipeline": {
      "main": [
        [{"node": "Triggered OK?", "type": "main", "index": 0}]
      ]
    },
    "Triggered OK?": {
      "main": [
        [{"node": "Telegram Success", "type": "main", "index": 0}],
        [{"node": "Telegram Already Running", "type": "main", "index": 0}]
      ]
    },
    "On Workflow Error": {
      "main": [
        [{"node": "Telegram Error", "type": "main", "index": 0}]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1"
  },
  "id": "quantscreen-pipeline-refresh",
  "meta": {
    "instanceId": "quantscreen"
  }
}
```

---

- [ ] **Step 2: Import into n8n and configure**

1. n8n → **Workflows → Import from File** → select `n8n_workflow.json`
2. Open **Git Pull & Rebuild** node → change `/mnt/tank/quantscreen` to the actual clone path on TrueNAS
3. Create Telegram credential: **Credentials → Add → Telegram API** → paste Bot Token from @BotFather → Save
4. Open each of the three Telegram nodes → select your saved credential → set `chatId` to your Telegram chat ID
5. Workflow **Settings → Error Workflow** → select this same workflow (enables the `On Workflow Error` trigger to catch node failures like a failed git pull)
6. Toggle workflow **Active**

---

- [ ] **Step 3: Manual test run**

In n8n click **Execute Workflow**. Verify in the execution log:
- **Git Pull & Rebuild**: stdout shows git output and docker compose output, exit code 0
- **Trigger Pipeline**: response body shows `{"status":"started",...}` or `{"status":"already_running",...}`
- The appropriate Telegram node fires
- Check Telegram for the notification message

---

- [ ] **Step 4: Commit**

```
git add n8n_workflow.json
git commit -m "feat: add n8n workflow for scheduled pipeline refresh with Telegram alerts"
```

---

## Deployment Reference

First-deploy and update commands for TrueNAS are documented in the approved spec:
`docs/superpowers/specs/2026-06-23-docker-pipeline-design.md` — sections "Deployment — First Deploy on TrueNAS" and "Deployment — Update".

**TrueNAS note:** n8n's Execute Command node runs as the n8n process user. That user must be in the `docker` group on TrueNAS to run `docker compose`. Verify with: `groups <n8n-user>`. If not, add it via TrueNAS shell: `usermod -aG docker <n8n-user>` then restart n8n.
