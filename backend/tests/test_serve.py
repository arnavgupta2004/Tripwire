"""The deployable app: API under /api, frontend at /, liveness at /healthz."""

from fastapi.testclient import TestClient

from api import serve


def test_public_build_mounts_api_frontend_and_health(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Tripwire</title>")
    monkeypatch.setattr(serve, "FRONTEND_DIST", dist)
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    client = TestClient(serve.build())

    assert client.get("/healthz").json() == {"ok": True, "public_demo": True}
    health = client.get("/api/health").json()
    assert health["public_demo"] is True and "budget" in health
    assert client.get("/api/memory").status_code == 400  # no visitor id
    assert client.get("/api/memory", headers={"X-Tripwire-Visitor": "visitor-aaaaaaaa"}).json()["facts"] == []
    assert "Tripwire" in client.get("/").text
