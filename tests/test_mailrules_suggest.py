import json

from mailrules import suggest

G = [{"sender": "news@shop.example", "name": "商店", "pattern": "本週 # 折", "subjects": ["本週 # 折"], "count": 30},
     {"sender": "noreply@bank.example", "name": "銀行", "pattern": "登入通知", "subjects": ["登入通知"], "count": 9}]


def test_解析與丟棄不合法(monkeypatch):
    seen = {}
    def fake(prompt, schema=None):
        seen["prompt"], seen["schema"] = prompt, schema
        return json.dumps({"items": [{"i": 0, "category": "promo", "why": "促銷"},
                                     {"i": 1, "category": "keep_inbox", "why": "x"},
                                     {"i": 9, "category": "login", "why": "x"}]})
    monkeypatch.setattr(suggest, "codex_text", fake)
    assert suggest.suggest(G) == {("news@shop.example", "本週 # 折"): "promo"}
    assert "不可信" in seen["prompt"] and "keep_inbox" not in seen["schema"]["properties"]["items"]["items"]["properties"]["category"]["enum"]


def test_分批_一批失敗不影響其他批(monkeypatch):
    calls = []
    def fake(prompt, schema=None):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("codex down")
        return json.dumps({"items": [{"i": 0, "category": "login", "why": "x"}]})
    monkeypatch.setattr(suggest, "codex_text", fake)
    groups = [dict(G[1], sender=f"s{i}@b.example") for i in range(41)]
    got = suggest.suggest(groups)
    assert len(calls) == 2 and got == {("s40@b.example", "登入通知"): "login"}


def test_items_不是_list_只略過那批(monkeypatch):
    replies = iter([json.dumps({"items": None}),
                    json.dumps({"items": 5}),
                    json.dumps({"items": [{"i": 0, "category": "login", "why": "x"}]})])
    monkeypatch.setattr(suggest, "codex_text", lambda prompt, schema=None: next(replies))
    groups = [dict(G[1], sender=f"s{i}@b.example") for i in range(81)]
    got = suggest.suggest(groups)
    assert got == {("s80@b.example", "登入通知"): "login"}
