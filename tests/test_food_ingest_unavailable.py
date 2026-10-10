"""「Google 掛了」與「Google 查無此店」必須分得出來。

分不出來的代價：2026-09 專案被停用那次，批次匯入把 403 吞成 place=None，
畫面上顯示「❌ 找不到 N 家（加上地區再重貼）」——照著做一百次也不會成功。
"""
import asyncio

from food import ingest
from food.places import PlacesUnavailable
from discordbot import embeds


def _boom(*a, **k):
    raise PlacesUnavailable("Google 服務暫時不可用（403）", status=403, reason=None)


# ── 單則解析 ─────────────────────────────────────────────────

def test_single_ingest_says_service_not_missing_store(monkeypatch):
    # log 是 places.py 那層 I/O 邊界的責任（見 test_places_errors.py），
    # orchestrator 只負責把例外翻成使用者看得懂的話，不重複印一次。
    monkeypatch.setattr(ingest, "search_text", _boom)
    place, reason = ingest._from_fields({"name": "鼎泰豐", "area": "台北"}, source_url=None)
    assert place is None
    assert "不可用" in reason
    assert "找不到" not in reason       # 別叫使用者去改關鍵字，改了也沒用


def test_single_ingest_keeps_saying_not_found_when_google_answers(monkeypatch):
    """對照組：Google 正常回應但查無此店 → 訊息維持原樣，這時「加地區重試」才是對的建議。"""
    monkeypatch.setattr(ingest, "search_text", lambda q: None)
    place, reason = ingest._from_fields({"name": "不存在的店", "area": ""}, source_url=None)
    assert place is None
    assert "找不到" in reason


# ── 批次匯入 ─────────────────────────────────────────────────

def test_resolve_one_marks_unavailable(monkeypatch):
    monkeypatch.setattr(ingest, "search_text", _boom)
    r = ingest._resolve_one({"name": "鼎泰豐", "area": "台北"}, "想去", "鼎泰豐")
    assert r["bucket"] == "fail"
    assert r["unavailable"] is True


def test_resolve_one_not_unavailable_when_simply_absent(monkeypatch):
    monkeypatch.setattr(ingest, "search_text", lambda q: None)
    r = ingest._resolve_one({"name": "不存在", "area": ""}, "想去", "不存在")
    assert r["bucket"] == "fail"
    assert r["unavailable"] is False


def test_batch_counts_unavailable(monkeypatch):
    monkeypatch.setattr(ingest.extract, "parse_place_list",
                        lambda lines: [{"name": n, "area": ""} for n in lines])
    monkeypatch.setattr(ingest, "search_text", _boom)
    out = asyncio.run(ingest.batch_from_text("鼎泰豐\n春水堂"))
    assert out["unavailable"] == 2
    assert len(out["fail"]) == 2


def test_batch_unavailable_defaults_to_zero(monkeypatch):
    """沒踩到服務問題時這個欄位要存在且為 0（embed 才不用到處 .get 防禦）。"""
    monkeypatch.setattr(ingest.extract, "parse_place_list",
                        lambda lines: [{"name": n, "area": ""} for n in lines])
    monkeypatch.setattr(ingest, "search_text", lambda q: None)
    out = asyncio.run(ingest.batch_from_text("不存在的店"))
    assert out["unavailable"] == 0


# ── 使用者看到的字 ───────────────────────────────────────────

def test_batch_embed_warns_about_outage_instead_of_blaming_the_input():
    e = embeds.food_batch_summary_embed({
        "total_lines": 2, "dropped": 0, "wishlist": 2, "visited": 0,
        "ok": 0, "review": [], "fail": ["鼎泰豐", "春水堂"],
        "unavailable": 2, "error": None,
    })
    assert "不可用" in e.description
    assert "加上地區再重貼" not in e.description    # 這時候這句是錯的建議


def test_batch_embed_keeps_normal_advice_when_not_an_outage():
    e = embeds.food_batch_summary_embed({
        "total_lines": 1, "dropped": 0, "wishlist": 1, "visited": 0,
        "ok": 0, "review": [], "fail": ["不存在的店"],
        "unavailable": 0, "error": None,
    })
    assert "加上地區再重貼" in e.description
