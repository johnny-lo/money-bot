from autofix.verify import check


def _inc(sensor, **ctx):
    return {"id": 7, "sensor": sensor, "signature": "載具1", "context": ctx}


def test_einvoice_登入成功才算通過():
    ok, msg = check(_inc("einvoice_login"), scrape=lambda n: 5, extract_one=None, run_tests=None)
    assert ok and "5" in msg
    def boom(n): raise RuntimeError("LoginFailed")
    ok, _ = check(_inc("einvoice_login"), scrape=boom, extract_one=None, run_tests=None)
    assert not ok


def test_extract_過半成功算通過():
    inc = _inc("link_extract", urls=["a", "b", "c"])
    res = {"a": True, "b": True, "c": False}
    ok, _ = check(inc, scrape=None, extract_one=lambda u: res[u], run_tests=None)
    assert ok
    res = {"a": True, "b": False, "c": False}
    ok, _ = check(inc, scrape=None, extract_one=lambda u: res[u], run_tests=None)
    assert not ok


def test_scheduler_標記待下次排程確認():
    ok, msg = check(_inc("scheduler_job"), scrape=None, extract_one=None, run_tests=None)
    assert ok and "下次排程" in msg


def test_drill_跑登入落地測試():
    ok, _ = check(_inc("drill"), scrape=None, extract_one=None,
                  run_tests=lambda path: path.endswith("test_einvoice_login_landing.py"))
    assert ok
