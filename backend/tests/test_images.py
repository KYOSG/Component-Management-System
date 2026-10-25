from fastapi.testclient import TestClient

from app.services.images import image_dir
from tests.test_api import register


class _JpegResponse:
    content = b"\xff\xd8\xff\xd9"
    headers = {"content-type": "image/jpeg"}

    def raise_for_status(self):
        return None


class _Client:
    calls: list[str] = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, headers=None):
        _Client.calls.append(url)
        return _JpegResponse()


class _OfflineClient:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, headers=None):
        raise OSError("offline")


def test_item_image_is_stored_and_served_locally(client: TestClient, monkeypatch):
    _Client.calls = []
    monkeypatch.setattr("app.services.images.httpx.Client", _Client)
    register(client, "img@example.com")
    created = client.post(
        "/api/items",
        json={
            "lcsc_code": "C105580",
            "mpn": "RC0603FR-075K1L",
            "quantity": 1,
            "image_url": "https://assets.example/front.jpg",
        },
    )
    assert created.status_code == 200, created.text
    image_url = created.json()["image_url"]
    assert image_url.startswith("/api/media/lcsc-C105580.")
    assert _Client.calls == ["https://assets.example/front.jpg"]
    stored = image_dir() / image_url.rsplit("/", 1)[-1]
    assert stored.is_file()
    downloaded = client.get(image_url)
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"\xff\xd8\xff")
    updated = client.put(f"/api/items/{created.json()['id']}", json={**created.json(), "quantity": 2})
    assert updated.status_code == 200, updated.text
    assert updated.json()["image_url"] == image_url
    assert _Client.calls == ["https://assets.example/front.jpg"]
    listed = client.get("/api/map")
    assert listed.status_code == 200
    assert listed.json()["unboxed"][0]["image_url"] == image_url
    client.post("/api/auth/logout")
    assert client.get(image_url).status_code == 401
    logged = client.post("/api/auth/login", json={"email": "img@example.com", "password": "secret1"})
    assert logged.status_code == 200
    deleted = client.delete(f"/api/items/{created.json()['id']}")
    assert deleted.status_code == 200
    assert stored.is_file()


def test_failed_image_download_is_not_exposed(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.images.httpx.Client", _OfflineClient)
    register(client, "offline-img@example.com")
    created = client.post(
        "/api/items",
        json={"mpn": "NO-PHOTO", "quantity": 1, "image_url": "https://assets.example/missing.jpg"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["image_url"] == ""
    assert "assets.example" not in created.text
