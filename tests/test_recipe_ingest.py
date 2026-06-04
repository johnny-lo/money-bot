import recipe.ingest as ing


def _no_add(*a, **k):
    raise AssertionError("不該呼叫 add_recipe")


def test_gmaps_is_skipped(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "gmaps")
    monkeypatch.setattr(ing, "_extract_from_url",
                        lambda url, platform: (_ for _ in ()).throw(AssertionError("不該抽取 gmaps")))
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://maps.app.goo.gl/abc")
    assert rec is None
    assert "地點" in reason


def test_none_blob_with_no_caption_returns_missing(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "instagram")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: None)
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://www.instagram.com/p/X/")
    assert rec is None
    assert "抽不到菜名" in reason


def test_name_from_text_used_when_blob_present(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: "一大段影片描述")
    monkeypatch.setattr(ing, "name_from_text", lambda text: "蒜香奶油蝦")
    captured = {}
    def fake_add(name, url, platform):
        captured.update(name=name, url=url, platform=platform)
        return {"id": 1, "name": name, "url": url, "platform": platform}, True
    monkeypatch.setattr(ing.repo, "add_recipe", fake_add)
    rec, reason = ing.from_url("https://youtu.be/abc")
    assert reason == ""
    assert rec["name"] == "蒜香奶油蝦"
    assert rec["_created"] is True
    assert captured["platform"] == "youtube"


def test_caption_prepended_to_blob(monkeypatch):
    seen = {}
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: "影片描述")
    def fake_name(text):
        seen["text"] = text
        return "x"
    monkeypatch.setattr(ing, "name_from_text", fake_name)
    monkeypatch.setattr(ing.repo, "add_recipe",
                        lambda name, url, platform: ({"id": 1, "name": name, "url": url}, True))
    ing.from_url("https://youtu.be/abc", caption="我的註解")
    assert "我的註解" in seen["text"]
    assert "影片描述" in seen["text"]


def test_falls_back_to_blob_first_line_when_name_empty(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url",
                        lambda url, platform: "宮保雞丁超下飯\n第二行廢話")
    monkeypatch.setattr(ing, "name_from_text", lambda text: "")
    monkeypatch.setattr(ing.repo, "add_recipe",
                        lambda name, url, platform: ({"id": 1, "name": name, "url": url}, True))
    rec, reason = ing.from_url("https://youtu.be/abc")
    assert reason == ""
    assert rec["name"] == "宮保雞丁超下飯"


def test_all_empty_returns_missing(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: None)
    monkeypatch.setattr(ing, "name_from_text", lambda text: "")
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://youtu.be/abc", caption="")
    assert rec is None
    assert "抽不到菜名" in reason


def test_whitespace_only_blob_does_not_crash(monkeypatch):
    # blob 全是空白(yt-dlp 可能回空白標題)：truthy 但 splitlines() 為空 → 不可 IndexError
    monkeypatch.setattr(ing, "classify_platform", lambda url: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda url, platform: "   \n  ")
    monkeypatch.setattr(ing, "name_from_text", lambda text: "")
    monkeypatch.setattr(ing.repo, "add_recipe", _no_add)
    rec, reason = ing.from_url("https://youtu.be/abc")
    assert rec is None
    assert "抽不到菜名" in reason
