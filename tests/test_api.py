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
