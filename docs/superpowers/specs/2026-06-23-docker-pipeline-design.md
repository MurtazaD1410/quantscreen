# QuantScreen — Docker + Pipeline Trigger Design

**Date:** 2026-06-23  
**Status:** Approved

---

## Goal

Deploy QuantScreen on TrueNAS SCALE as a self-hosted Docker app, with an automated data pipeline that n8n can trigger on a schedule and on demand.

---

## Architecture

Two Docker containers built from a single image, sharing a named volume for data.

```
TrueNAS SCALE Host
├── /mnt/tank/quantscreen/          ← git repo clone location (placeholder path)
│
├── Container: quantscreen-app      (port 8501)
│   └── streamlit run app/main.py
│       └── reads /app/data  ─────────────────────┐
│                                                   │ named volume: quantscreen-data
├── Container: quantscreen-pipeline (port 8502)    │
│   └── uvicorn api:app                             │
│       └── writes /app/data ───────────────────────┘
│
└── n8n (port 5678, same host)
    └── Workflow: 7AM + 1PM
        ├── Execute Command: git pull + docker compose up --build -d
        ├── HTTP POST: http://localhost:8502/pipeline/trigger
        └── Telegram: success / failure notification
```

---

## Files Added / Changed

| File | Action | Notes |
|------|--------|-------|
| `Dockerfile` | NEW | Single image for both services |
| `.dockerignore` | NEW | Excludes `venv/`, `data/`, `__pycache__/` from build context |
| `docker-compose.yml` | NEW | Two services + named volume |
| `api.py` | NEW | FastAPI pipeline trigger service |
| `n8n_workflow.json` | NEW | Importable n8n workflow export |
| `requirements.txt` | UPDATED | Add `fastapi`, `uvicorn[standard]` |
| `run_pipeline.py` | UNCHANGED | Pipeline container calls this as subprocess |
| `app/main.py` | UNCHANGED | Reads from `/app/data` as before |
| `config.py` | UNCHANGED | `DATA_DIR` already resolves to `data/` |

---

## Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

- Single stage, no multi-stage needed (no compiled assets)
- `CMD` is overridden by `docker-compose.yml` for the pipeline service
- `.dockerignore` excludes `venv/`, `data/`, `__pycache__/`

---

## docker-compose.yml

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

- Both services share `quantscreen-data` volume → data survives rebuilds
- App starts independently of pipeline (shows stale data until first pipeline run)
- Port 8502 exposed to host so n8n (not in compose network) can reach it via `localhost`

---

## api.py — FastAPI Trigger Service

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` |
| `POST` | `/pipeline/trigger` | Start pipeline; 202 if started, 409 if already running |
| `GET` | `/pipeline/status` | Returns state: `running \| idle \| failed` + timestamps |

### Behaviour

- `POST /pipeline/trigger` spawns `python run_pipeline.py --index "NSE All"` as a non-blocking subprocess
- Returns 202 immediately — n8n does not wait for the 3-hour run to complete
- In-memory state tracks: `status`, `started_at`, `last_completed`, `last_error`
- State resets on container restart (acceptable — an interrupted run leaves data partially updated, same as before)
- 409 response includes `started_at` so the caller knows when the current run began

### State machine

```
idle ──→ running (POST /trigger received)
           ├── subprocess exits 0 ──→ idle  (last_completed updated)
           └── subprocess exits ≠0 ──→ failed (last_error set)
failed ──→ running (next POST /trigger — failed runs are retryable)
```

---

## requirements.txt additions

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
```

---

## n8n Workflow

### Nodes

1. **Schedule Trigger** — cron `0 7 * * *` and `0 13 * * *` (7:00 AM, 1:00 PM daily)
2. **Execute Command** — shell command:
   ```bash
   cd /mnt/tank/quantscreen && git pull && docker compose up --build -d
   ```
   Placeholder path `/mnt/tank/quantscreen` — update to actual clone location.
3. **HTTP Request** — `POST http://localhost:8502/pipeline/trigger`
4. **IF** — condition: `{{ $json.statusCode }} === 202`
   - `true` branch → Telegram success node
   - `false` branch → Telegram failure node
5. **Telegram (success)** — message: `✅ QuantScreen pipeline triggered — NSE All refresh started at {{ $now }}`
6. **Telegram (failure)** — message: `❌ QuantScreen trigger failed — {{ $json.body }}`
7. **Error Trigger** (separate workflow entry) — catches any node error (e.g. git pull fails, HTTP unreachable) → Telegram alert: `🚨 QuantScreen workflow error — {{ $json.message }}`

### Placeholders to fill in after setup

| Placeholder | Where | Value |
|-------------|-------|-------|
| `/mnt/tank/quantscreen` | Execute Command node | Actual path where repo is cloned on TrueNAS |
| `TELEGRAM_BOT_TOKEN` | n8n Telegram credentials | From @BotFather |
| `TELEGRAM_CHAT_ID` | n8n Telegram node | Your personal or group chat ID |

---

## Deployment — First Deploy on TrueNAS

```bash
# 1. Clone the repo (adjust path to your TrueNAS pool/dataset)
git clone https://github.com/<your-username>/quantscreen.git /mnt/tank/quantscreen
cd /mnt/tank/quantscreen

# 2. Build and start both containers
docker compose up --build -d

# 3. Verify containers are running
docker compose ps

# 4. Seed initial data (runs NSE All — takes ~3 hours first time)
#    Option A: trigger via API
curl -X POST http://localhost:8502/pipeline/trigger

#    Option B: run directly in the pipeline container
docker compose exec pipeline python run_pipeline.py --index "NSE All"

# 5. Open the app
# http://<truenas-ip>:8501
```

---

## Deployment — Update (git pull + rebuild)

```bash
cd /mnt/tank/quantscreen
git pull
docker compose up --build -d
# Both containers restart with new code; named volume data is preserved
```

This is also exactly what the n8n Execute Command node runs on each scheduled trigger.

---

## Data Volume Notes

- `quantscreen-data` is a Docker named volume managed by Docker, not a host-path bind mount
- Data persists across `docker compose up --build`, `docker compose restart`, and even `docker compose down` (only `docker compose down -v` deletes it)
- If you want to inspect or back up data: `docker volume inspect quantscreen-data` shows the host path (typically under `/var/lib/docker/volumes/`)
- TrueNAS SCALE stores Docker volumes under the app's dataset — they survive pool scrubs and reboots

---

## Out of Scope

- HTTPS / reverse proxy (TrueNAS SCALE Nginx can front-proxy if needed separately)
- Authentication on the Streamlit app or the trigger API
- Pipeline cancellation endpoint
- Multiple simultaneous pipeline indexes
