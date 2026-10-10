"""Places I/O 邊界的錯誤語意與 log。

背景：2026-09 專案免費試用到期被 Google 停用，Places 每一發都 403，
而**伺服器 log 一行都沒有**——只有 Discord 上的補件卡片寫著「查 Google 失敗」。
故障存在了好幾天沒人知道。這組測試釘住兩件事：
① 403 的原因要在 log 裡講人話（尤其「金鑰沒問題、是專案層級」這個最難猜的情況）；
② 「服務掛了」與「Google 真的查無此店」不能長得一樣。
"""
import io
import json
import urllib.error

import pytest

from food import places


@pytest.fixture(autouse=True)
def reset_counter():
    places.reset_failure_streak()
    yield
    places.reset_failure_streak()


def _http_error(code: int, body: str):
    return urllib.error.HTTPError(
        "https://places.googleapis.com/v1/places:searchText", code, "err", {},
        io.BytesIO(body.encode("utf-8")))


# ── describe_api_error：純函式，把 Google 的回應翻成人話 ──────────

def test_key_restriction_error_is_named():
    body = json.dumps({"error": {"code": 403, "message": "blocked", "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
         "reason": "API_KEY_SERVICE_BLOCKED",
         "metadata": {"consumer": "projects/979794256721"}}]}})
    reason, human = places.describe_api_error(403, body)
    assert reason == "API_KEY_SERVICE_BLOCKED"
    assert "API 限制" in human


def test_referrer_and_ip_restrictions_are_named():
    for reason_code, expect in [("API_KEY_HTTP_REFERRER_BLOCKED", "referer"),
                                ("API_KEY_IP_ADDRESS_BLOCKED", "IP")]:
        body = json.dumps({"error": {"details": [{"reason": reason_code}]}})
        reason, human = places.describe_api_error(403, body)
        assert reason == reason_code
        assert expect in human


def test_service_disabled_is_named():
    body = json.dumps({"error": {"details": [{"reason": "SERVICE_DISABLED"}]}})
    _, human = places.describe_api_error(403, body)
    assert "啟用" in human


def test_bare_403_points_at_project_not_the_key():
    """今天踩到的那個：金鑰通過全部檢查，Google 卻只回一句沒有 reason 的拒絕。

    這時最容易走錯的路是去翻金鑰設定（我們就走了一次）。log 要直接說「不是金鑰」。
    """
    body = json.dumps({"error": {"code": 403,
                                 "message": "The caller does not have permission",
                                 "status": "PERMISSION_DENIED"}})
    reason, human = places.describe_api_error(403, body)
    assert reason is None
    assert "帳單" in human and "金鑰" in human


def test_quota_exhausted_is_named():
    body = json.dumps({"error": {"details": [{"reason": "RATE_LIMIT_EXCEEDED"}]}})
    _, human = places.describe_api_error(429, body)
    assert "配額" in human


def test_unparsable_body_degrades_safely():
    reason, human = places.describe_api_error(500, "<html>nope</html>")
    assert reason is None
    assert human                      # 有話可說，不是空字串
    assert "500" in human


# ── search_text：例外要帶語意，而且一定留下 log ────────────────

def test_search_text_raises_places_unavailable_on_http_error(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")
    body = json.dumps({"error": {"code": 403, "message": "The caller does not have permission"}})
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, body)))
    with pytest.raises(places.PlacesUnavailable) as e:
        places.search_text("鼎泰豐")
    assert e.value.status == 403
    # 訊息短（會出現在 Discord 卡片上給兩個人看），診斷細節只進 log
    assert "帳單" not in str(e.value)
    assert "帳單" in e.value.detail

    out = capsys.readouterr().out
    assert "⚠️" in out and "Places" in out and "403" in out and "帳單" in out


def test_search_text_raises_on_network_error(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("no route")))
    with pytest.raises(places.PlacesUnavailable):
        places.search_text("鼎泰豐")
    assert "⚠️" in capsys.readouterr().out


def test_log_counts_consecutive_failures(monkeypatch, capsys):
    """連續第幾次要寫在 log 裡——這是「壞多久了」唯一的線索。"""
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, "{}")))
    for _ in range(3):
        with pytest.raises(places.PlacesUnavailable):
            places.search_text("x")
    assert "連續第 3 次" in capsys.readouterr().out


def test_success_resets_the_streak(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"places": []}).encode()

    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, "{}")))
    with pytest.raises(places.PlacesUnavailable):
        places.search_text("x")
    monkeypatch.setattr(places.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    assert places.search_text("x") is None          # 查無此店，不是錯誤
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, "{}")))
    with pytest.raises(places.PlacesUnavailable):
        places.search_text("x")
    assert "連續第 1 次" in capsys.readouterr().out.splitlines()[-1]


def test_missing_key_is_also_places_unavailable(monkeypatch):
    """沒設金鑰跟金鑰被拒一樣是「服務不可用」，呼叫端只要接一種例外。"""
    monkeypatch.delenv("GOOGLE_PLACES_SERVER_KEY", raising=False)
    with pytest.raises(places.PlacesUnavailable):
        places.search_text("鼎泰豐")


# ── best-effort 的兩支：行為不變（不炸），但要留 log ───────────

def test_fetch_reviews_still_returns_empty_but_logs(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, "{}")))
    assert places.fetch_reviews("pid") == []        # 事後加值失敗不影響入庫
    out = capsys.readouterr().out
    assert "⚠️" in out and "評論" in out


def test_fetch_place_photo_still_returns_none_but_logs(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_PLACES_SERVER_KEY", "k")
    monkeypatch.setattr(places.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403, "{}")))
    assert places.fetch_place_photo("pid") is None
    out = capsys.readouterr().out
    assert "⚠️" in out and "照片" in out
