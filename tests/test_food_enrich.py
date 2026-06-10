import pytest

import food.enrich as enrich
import food.places as places


@pytest.fixture(autouse=True)
def no_db_writes(monkeypatch):
    """enrich 的 DB 寫入點全部換成記錄器，不碰真 DB。"""
    calls = {"update_recommended": [], "add_photo": []}
    monkeypatch.setattr(enrich.repo, "update_recommended",
                        lambda fid, text: calls["update_recommended"].append((fid, text)))
    monkeypatch.setattr(enrich, "add_photo",
                        lambda fid, data, ext, source: calls["add_photo"].append(fid))
    return calls


def test_enrich_skips_when_already_has_recommended(monkeypatch, no_db_writes):
    monkeypatch.setattr(enrich, "recommended_for_place_id",
                        lambda pid: pytest.fail("已有推薦菜不該再打 API"))
    monkeypatch.setattr(enrich, "_has_google_photo", lambda fid: True)
    out = enrich.enrich_place(1, "pid-1", cur_recommended="滷肉飯")
    assert out == {"recommended": "", "photo": False}


def test_enrich_skips_photo_when_google_photo_exists(monkeypatch, no_db_writes):
    monkeypatch.setattr(enrich, "recommended_for_place_id", lambda pid: "牛肉麵")
    monkeypatch.setattr(enrich, "_has_google_photo", lambda fid: True)
    monkeypatch.setattr(enrich, "fetch_place_photo",
                        lambda pid: pytest.fail("已有 google 照片不該再抓"))
    out = enrich.enrich_place(1, "pid-1", cur_recommended=None)
    assert out["recommended"] == "牛肉麵"
    assert out["photo"] is False
    assert no_db_writes["update_recommended"] == [(1, "牛肉麵")]


def test_backfill_stops_at_budget(monkeypatch, no_db_writes, capsys):
    rows = [(i, f"pid-{i}", f"店{i}", None) for i in range(1, 6)]  # 5 家
    monkeypatch.setattr(enrich, "_all_rows_with_place_id", lambda: rows)

    def fake_enrich(fid, pid, cur):
        places._count(3)  # 每家假裝吃 3 個 API call
        return {"recommended": "x", "photo": True}

    monkeypatch.setattr(enrich, "enrich_place", fake_enrich)
    enrich.backfill_all(max_api_calls=7)
    out = capsys.readouterr().out
    # 預算 7、每家 3 → 第 3 家開跑前已用 6 (<7) 可跑、第 4 家前已用 9 (>=7) 停
    assert "[3/5]" in out
    assert "[4/5]" not in out
    assert "剩 2 家未跑" in out


def test_backfill_no_budget_runs_all(monkeypatch, no_db_writes, capsys):
    rows = [(i, f"pid-{i}", f"店{i}", None) for i in range(1, 4)]
    monkeypatch.setattr(enrich, "_all_rows_with_place_id", lambda: rows)
    monkeypatch.setattr(enrich, "enrich_place",
                        lambda fid, pid, cur: {"recommended": "", "photo": False})
    enrich.backfill_all(max_api_calls=10_000)
    out = capsys.readouterr().out
    assert "[3/3]" in out and "done." in out
