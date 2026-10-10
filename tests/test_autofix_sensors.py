"""三個感測器：簽名、去重鍵、接線。"""
from autofix import sensors
import einvoice


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(sensors.incidents, "raise_incident",
                        lambda *a, **k: calls.append(("raise", a, k)))
    monkeypatch.setattr(sensors.incidents, "clear",
                        lambda *a, **k: calls.append(("clear", a, k)))
    return calls


def _inner_failure():
    raise ValueError("壞掉")


def test_job_signature_取最內層_repo_frame_的檔案與函式_不含行號():
    try:
        _inner_failure()
    except ValueError as e:
        sig = sensors.job_signature("weekly_pipeline", e)
    assert sig == "weekly_pipeline|ValueError|tests/test_autofix_sensors.py:_inner_failure"


def test_job_signature_沒有_repo_frame_時退回例外類別():
    e = ValueError("x")
    assert sensors.job_signature("j", e) == "j|ValueError|?"


def test_登入失敗_以台北日期去重(monkeypatch):
    calls = _capture(monkeypatch)
    sensors.login_failed(1, "0912***78", einvoice.LoginFailed(["第1次：未知狀態 URL=u"]))
    kind, a, k = calls[0]
    assert a[0] == "einvoice_login" and a[1] == "載具1"
    assert k["dedupe_key"] == sensors.incidents.now_tw().date().isoformat()
    assert a[3]["attempts"] == ["第1次：未知狀態 URL=u"] and a[3]["masked"] == "0912***78"


def test_抽取失敗_以網址去重_簽名是模組加平台(monkeypatch):
    calls = _capture(monkeypatch)
    sensors.extract_failed("food", "instagram", "https://ig/p/1", RuntimeError("403"))
    _, a, k = calls[0]
    assert a[:2] == ("link_extract", "food:instagram")
    assert a[3]["urls"] == ["https://ig/p/1"] and k["dedupe_key"] == "https://ig/p/1"


def test_成功時_clear(monkeypatch):
    calls = _capture(monkeypatch)
    sensors.login_ok(2)
    sensors.extract_ok("recipe", "youtube")
    sensors.job_ok("daily_invoice_sync")
    assert calls == [
        ("clear", ("einvoice_login", "載具2"), {}),
        ("clear", ("link_extract", "recipe:youtube"), {}),
        ("clear", ("scheduler_job", "daily_invoice_sync|"), {"prefix": True}),
    ]


def test_food_ingest_抽取失敗會通知感測器(monkeypatch):
    from food import ingest
    calls = _capture(monkeypatch)
    monkeypatch.setattr(ingest.extract, "from_url",
                        lambda url, platform: (_ for _ in ()).throw(RuntimeError("403")))
    place, reason = ingest.from_url("https://www.instagram.com/p/abc/")
    assert place is None and "連結抽取失敗" in reason
    assert calls[0][1][:2] == ("link_extract", "food:instagram")
