import subprocess
import sys
from fastapi.testclient import TestClient


def test_server_imports() -> None:
    result = subprocess.run([sys.executable, "-c", "import server.main"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_health_is_public() -> None:
    from server.main import app
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
