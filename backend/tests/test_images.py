import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import images
from app.services.images import UnsafeUrl, check_public_url, fetch_image_bytes, image_dir
from tests.test_api import register

JPEG = b"\xff\xd8\xff\xd9"
PUBLIC = {"assets.example": ["93.184.216.34"], "cdn.example": ["93.184.216.35"]}


class _Response:
    def __init__(self, url, status=200, headers=None, body=JPEG):
        self.url = httpx.URL(url)
        self.status_code = status
        self.headers = headers or {"content-type": "image/jpeg"}
        self.body = body

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "location" in self.headers

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)

    def iter_bytes(self):
        for start in range(0, len(self.body), 1024 * 1024):
            yield self.body[start : start + 1024 * 1024]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Client:
    calls: list[str] = []
    routes: dict[str, _Response] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, method, url):
        _Client.calls.append(url)
        if url in _Client.routes:
            return _Client.routes[url]
        return _Response(url)


class _OfflineClient(_Client):
    def stream(self, method, url):
        raise OSError("offline")


def _fake_resolve(host):
    if host in PUBLIC:
        return PUBLIC[host]
    if host == "intranet.example":
        return ["192.168.1.10"]
    if host == "mapped.example":
        return ["::ffff:127.0.0.1"]
    try:
        import ipaddress

        return [str(ipaddress.ip_address(host))]
    except ValueError as exc:
        raise OSError("unknown host") from exc


@pytest.fixture
def fake_net(monkeypatch):
    _Client.calls = []
    _Client.routes = {}
    monkeypatch.setattr(images, "_client", _Client)
    monkeypatch.setattr(images, "resolve_host", _fake_resolve)
    return _Client


def test_item_image_is_stored_and_served_locally(client: TestClient, fake_net):
    register(client, "img@example.com")
    my_id = client.get("/api/auth/me").json()["id"]
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
    assert fake_net.calls == ["https://assets.example/front.jpg"]
    stored = image_dir(my_id) / image_url.rsplit("/", 1)[-1]
    assert stored.is_file()
    downloaded = client.get(image_url)
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"\xff\xd8\xff")
    updated = client.put(f"/api/items/{created.json()['id']}", json={**created.json(), "quantity": 2})
    assert updated.status_code == 200, updated.text
    assert updated.json()["image_url"] == image_url
    assert fake_net.calls == ["https://assets.example/front.jpg"]
    listed = client.get("/api/map")
    assert listed.status_code == 200
    assert listed.json()["unboxed"][0]["image_url"] == image_url

    with TestClient(client.app) as other:
        register(other, "img-other@example.com")
        assert other.get(image_url).status_code == 404

    client.post("/api/auth/logout")
    assert client.get(image_url).status_code == 401
    logged = client.post("/api/auth/login", json={"email": "img@example.com", "password": "secret1"})
    assert logged.status_code == 200
    deleted = client.delete(f"/api/items/{created.json()['id']}")
    assert deleted.status_code == 200
    assert stored.is_file()


def test_failed_image_download_is_not_exposed(client: TestClient, monkeypatch):
    monkeypatch.setattr(images, "_client", _OfflineClient)
    monkeypatch.setattr(images, "resolve_host", _fake_resolve)
    register(client, "offline-img@example.com")
    created = client.post(
        "/api/items",
        json={"mpn": "NO-PHOTO", "quantity": 1, "image_url": "https://assets.example/missing.jpg"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["image_url"] == ""
    assert "assets.example" not in created.text


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://assets.example/a.jpg",
        "http://127.0.0.1/a.jpg",
        "http://localhost.example/a.jpg",
        "http://10.0.0.5/a.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://intranet.example/a.jpg",
        "http://mapped.example/a.jpg",
        "http://[::1]/a.jpg",
    ],
)
def test_private_or_bad_urls_are_rejected(url, fake_net):
    with pytest.raises(UnsafeUrl):
        check_public_url(url)


def test_redirect_to_private_host_is_rejected(fake_net):
    fake_net.routes["https://assets.example/jump.jpg"] = _Response(
        "https://assets.example/jump.jpg", status=302, headers={"location": "http://192.168.1.10/a.jpg"}
    )
    with pytest.raises(UnsafeUrl):
        fetch_image_bytes("https://assets.example/jump.jpg")
    assert fake_net.calls == ["https://assets.example/jump.jpg"]


def test_public_redirect_is_followed(fake_net):
    fake_net.routes["https://assets.example/jump.jpg"] = _Response(
        "https://assets.example/jump.jpg", status=302, headers={"location": "https://cdn.example/real.jpg"}
    )
    content, kind = fetch_image_bytes("https://assets.example/jump.jpg")
    assert content == JPEG and kind == "image/jpeg"
    assert fake_net.calls == ["https://assets.example/jump.jpg", "https://cdn.example/real.jpg"]


def test_oversized_image_is_rejected(fake_net):
    big = JPEG + b"0" * (images.MAX_BYTES + 1)
    fake_net.routes["https://assets.example/big.jpg"] = _Response("https://assets.example/big.jpg", body=big)
    with pytest.raises(UnsafeUrl):
        fetch_image_bytes("https://assets.example/big.jpg")


def test_private_image_url_is_dropped_on_save(client: TestClient, fake_net):
    register(client, "ssrf@example.com")
    created = client.post(
        "/api/items",
        json={"mpn": "SSRF-1", "quantity": 1, "image_url": "http://169.254.169.254/latest/meta-data"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["image_url"] == ""
    assert fake_net.calls == []
