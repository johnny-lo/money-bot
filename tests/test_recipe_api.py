"""食譜 JSON API 的 route 層測試：repo 全 monkeypatch，不碰真 DB。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.recipes as recipes_route
from auth import require_token


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(recipes_route.router)
    app.dependency_overrides[require_token] = lambda: None
    return TestClient(app)


def test_list_recipes(client, monkeypatch):
    monkeypatch.setattr(recipes_route, "list_recipes",
                        lambda: [{"id": 1, "name": "滷肉飯", "url": "https://x", "platform": "youtube"}])
    r = client.get("/api/recipes")
    assert r.status_code == 200
    assert r.json()["recipes"][0]["name"] == "滷肉飯"


def test_rename_ok(client, monkeypatch):
    calls = {}
    monkeypatch.setattr(recipes_route, "rename",
                        lambda rid, name: calls.update(rid=rid, name=name) or {"id": rid, "name": name})
    r = client.put("/api/recipes/3", json={"name": "  紅燒牛肉麵  "})
    assert r.status_code == 200
    assert calls == {"rid": 3, "name": "紅燒牛肉麵"}   # route 先 strip 再進 repo


def test_rename_empty_name_rejected(client, monkeypatch):
    monkeypatch.setattr(recipes_route, "rename",
                        lambda rid, name: pytest.fail("空名不該進 repo"))
    assert client.put("/api/recipes/3", json={"name": "   "}).status_code == 422


def test_rename_404(client, monkeypatch):
    monkeypatch.setattr(recipes_route, "rename", lambda rid, name: None)
    assert client.put("/api/recipes/999", json={"name": "x"}).status_code == 404


def test_delete_ok(client, monkeypatch):
    monkeypatch.setattr(recipes_route, "delete_recipe", lambda rid: True)
    assert client.delete("/api/recipes/3").status_code == 200


def test_delete_404(client, monkeypatch):
    monkeypatch.setattr(recipes_route, "delete_recipe", lambda rid: False)
    assert client.delete("/api/recipes/999").status_code == 404
