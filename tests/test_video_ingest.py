import video.ingest as ing


def test_from_url_happy_path(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "唐朝的經濟\n某史頻道")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "唐朝", "tags": ["經濟", "戰爭"]})
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        ({"id": 7, "title": title, "topic": topic, "tags": []}, True))
    added = []
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: added.append((vid, tag)) or True)

    rec, reason = ing.from_url("https://youtu.be/x")
    assert reason == ""
    assert rec["id"] == 7 and rec["topic"] == "唐朝"
    assert rec["_created"] is True
    assert rec["tags"] == ["經濟", "戰爭"]      # 回傳前把建議標籤帶上，省一次查詢
    assert added == [(7, "經濟"), (7, "戰爭")]   # 標籤逐一入庫


def test_from_url_extract_fail_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "youtube")
    def boom(u, p):
        raise RuntimeError("yt-dlp 掛了")
    monkeypatch.setattr(ing, "_extract_from_url", boom)
    rec, reason = ing.from_url("https://youtu.be/x")
    assert rec is None and "yt-dlp 掛了" in reason


def test_from_url_no_title_falls_back_to_blob_first_line(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "other")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "  某個影片標題  \n第二行")
    monkeypatch.setattr(ing, "meta_from_text", lambda t: {"topic": "", "tags": []})
    captured = {}
    monkeypatch.setattr(ing.repo, "add_video",
                        lambda title, url, topic=None, channel=None, platform=None:
                        (captured.update(title=title, topic=topic) or {"id": 1, "tags": []}, True))
    monkeypatch.setattr(ing.repo, "add_tag", lambda vid, tag: True)
    rec, reason = ing.from_url("https://example.com/x")
    assert reason == ""
    assert captured["title"] == "某個影片標題"   # blob 第一行當標題
    assert captured["topic"] is None             # 空 topic 不寫空字串，存 None


def test_from_url_blank_blob_returns_reason(monkeypatch):
    monkeypatch.setattr(ing, "classify_platform", lambda u: "other")
    monkeypatch.setattr(ing, "_extract_from_url", lambda u, p: "")
    rec, reason = ing.from_url("https://example.com/x")
    assert rec is None and reason == ing._NO_TITLE_REASON
