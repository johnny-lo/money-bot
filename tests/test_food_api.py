"""美食寫操作 API 的 route 層測試：repo/photos 全 monkeypatch，不碰真 DB/檔案。"""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.food_map as food_map
from auth import require_token


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(food_map.router)
    app.dependency_overrides[require_token] = lambda: None   # 測 route 邏輯，不測認證
    return TestClient(app)


# ── 標去過 ──────────────────────────────────────────────────

def test_visited_ok(client, monkeypatch):
    calls = {}
    monkeypatch.setattr(food_map, "set_visited",
                        lambda fid, rating=None, note=None: calls.update(
                            fid=fid, rating=rating, note=note) or {"id": fid, "status": "去過"})
    r = client.post("/api/food/places/7/visited", json={"rating": 4, "note": "好吃"})
    assert r.status_code == 200
    assert r.json()["place"]["status"] == "去過"
    assert calls == {"fid": 7, "rating": 4, "note": "好吃"}


def test_visited_404(client, monkeypatch):
    monkeypatch.setattr(food_map, "set_visited", lambda fid, rating=None, note=None: None)
    assert client.post("/api/food/places/999/visited", json={}).status_code == 404


def test_visited_out_of_range_rating_dropped(client, monkeypatch):
    calls = {}
    monkeypatch.setattr(food_map, "set_visited",
                        lambda fid, rating=None, note=None: calls.update(rating=rating) or {"id": fid})
    r = client.post("/api/food/places/7/visited", json={"rating": 9})
    assert r.status_code == 200
    assert calls["rating"] is None    # 超範圍 → 當沒給（與 /去過 slash 行為一致）


# ── 照片上傳 ─────────────────────────────────────────────────

def _upload(client, data: bytes, ctype="image/jpeg"):
    return client.post("/api/food/places/7/photos",
                       files={"file": ("x.jpg", io.BytesIO(data), ctype)})


def test_upload_photo_ok(client, monkeypatch):
    monkeypatch.setattr(food_map, "list_photos", lambda fid: [])
    saved = {}
    monkeypatch.setattr(food_map, "add_photo",
                        lambda fid, data, ext, source: saved.update(
                            fid=fid, n=len(data), ext=ext, source=source
                        ) or {"id": 1, "url": "/media/food/7/a.jpg", "source": source})
    r = _upload(client, b"\xff\xd8fakejpeg")
    assert r.status_code == 200
    assert r.json()["photo"]["source"] == "app"
    assert saved["ext"] == "jpg" and saved["source"] == "app" and saved["fid"] == 7


def test_upload_photo_too_large(client, monkeypatch):
    monkeypatch.setattr(food_map, "list_photos", lambda fid: [])
    r = _upload(client, b"x" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 413


def test_upload_photo_cap_reached(client, monkeypatch):
    monkeypatch.setattr(food_map, "list_photos", lambda fid: [{"id": i} for i in range(10)])
    r = _upload(client, b"x")
    assert r.status_code == 409


def test_upload_photo_rejects_non_image(client, monkeypatch):
    monkeypatch.setattr(food_map, "list_photos", lambda fid: [])
    r = client.post("/api/food/places/7/photos",
                    files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 415


# ── 照片刪除 ─────────────────────────────────────────────────

def test_delete_photo_ok(client, monkeypatch):
    monkeypatch.setattr(food_map, "delete_photo", lambda pid: True)
    assert client.delete("/api/food/photos/3").status_code == 200


def test_delete_photo_404(client, monkeypatch):
    monkeypatch.setattr(food_map, "delete_photo", lambda pid: False)
    assert client.delete("/api/food/photos/999").status_code == 404
