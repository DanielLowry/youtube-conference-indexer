import pytest

pytestmark = pytest.mark.skip(reason="DB mode toggle no longer exists in stateless migration.")

from fastapi.testclient import TestClient


def test_no_db_mode_toggle_banner(client: TestClient, app_ctx):
    client.post("/db/use-memory")
    home = client.get("/")
    assert "NO-DB" in home.text
    assert "in-memory" in home.text.lower()

    client.post("/db/reconnect")
    home = client.get("/")
    if "NO-DB" in home.text:
        assert "in-memory" in home.text.lower()
    else:
        assert "NO-DB" not in home.text
