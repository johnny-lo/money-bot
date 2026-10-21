"""確認卡的寄件者資訊：顯示名稱＋最近一封主旨（repo.card_sender_info）、卡片內文、「這些不是」下拉、
手動指定卡，以及所有畫卡路徑都帶 info。全部合成值（*.example）。"""
import asyncio
import re
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import discord

from discordbot import mailrules_ui as ui
from mailrules import repo
from mailrules.types import Rule
from tests.test_mailrules_integration import RecSession, _ix, row

PAT = "本週 # 折"


def R(i, sender, pat=PAT, cat="promo", status="suggested", by="ai", card="s3"):
    return Rule(id=i, sender=sender, subject_pattern=pat, category=cat, status=status, suggested_by=by, card=card)


def I(name, subject):
    return {"name": name, "subject": subject}


# ── AC1：repo.card_sender_info ─────────────────────────────────────

def _card(monkeypatch, *pairs):
    rules = [SimpleNamespace(sender=s, subject_pattern=p) for s, p in pairs]
    monkeypatch.setattr(repo, "_card_rows", lambda db, card: rules)


def test_card_sender_info_取卡上樣式最新一封的名稱與主旨(monkeypatch):
    _card(monkeypatch, ("a@x.example", "週報 #"), ("a@x.example", "新品"), ("b@x.example", "通知"))
    msgs = [row("1", from_addr="a@x.example", subject_pattern="週報 #", subject="週報 3", from_name="甲商店",
                sent_date=date(2026, 10, 1)),
            row("2", from_addr="a@x.example", subject_pattern="新品", subject="新品上架", from_name="甲商店",
                sent_date=date(2026, 10, 5)),
            row("3", from_addr="a@x.example", subject_pattern="週報 #", subject="週報 4", from_name="甲商店",
                sent_date=date(2026, 10, 3)),
            row("4", from_addr="b@x.example", subject_pattern="通知", subject="系統通知", from_name=None,
                sent_date=date(2026, 9, 1))]
    got = repo.card_sender_info(RecSession(msgs), "s3")
    assert got == {"a@x.example": {"name": "甲商店", "subject": "新品上架"},
                   "b@x.example": {"name": None, "subject": "系統通知"}}


def test_card_sender_info_不在卡上的樣式與已不在信箱的信不算(monkeypatch):
    _card(monkeypatch, ("a@x.example", "週報 #"))
    msgs = [row("1", from_addr="a@x.example", subject_pattern="週報 #", subject="舊的", sent_date=date(2026, 10, 1)),
            row("2", from_addr="a@x.example", subject_pattern="別的樣式", subject="別的", sent_date=date(2026, 10, 9)),
            row("3", from_addr="a@x.example", subject_pattern="週報 #", subject="消失的", sent_date=date(2026, 10, 8),
                gone_at=datetime(2026, 10, 9)),
            row("4", from_addr="c@x.example", subject_pattern="週報 #", subject="別人的", sent_date=date(2026, 10, 9))]
    db = RecSession(msgs)
    assert repo.card_sender_info(db, "s3") == {"a@x.example": {"name": None, "subject": "舊的"}}
    assert any("gone_at IS NULL" in f for f in db.filters)


def test_card_sender_info_名稱去頭尾空白_空字串當_None(monkeypatch):
    _card(monkeypatch, ("a@x.example", "p"), ("b@x.example", "p"), ("c@x.example", "p"))
    msgs = [row("1", from_addr="a@x.example", subject_pattern="p", subject="s", from_name="  甲商店 \n"),
            row("2", from_addr="b@x.example", subject_pattern="p", subject="s", from_name="   "),
            row("3", from_addr="c@x.example", subject_pattern="p", subject="s", from_name="")]
    got = repo.card_sender_info(RecSession(msgs), "s3")
    assert [got[s]["name"] for s in ("a@x.example", "b@x.example", "c@x.example")] == ["甲商店", None, None]


def test_card_sender_info_同日多封結果穩定_與列的順序無關(monkeypatch):
    _card(monkeypatch, ("a@x.example", "p"))
    msgs = [row(g, from_addr="a@x.example", subject_pattern="p", subject=f"主旨 {g}", sent_date=date(2026, 10, 1))
            for g in ("m1", "m3", "m2")]
    first = repo.card_sender_info(RecSession(msgs), "s3")
    second = repo.card_sender_info(RecSession(list(reversed(msgs))), "s3")
    assert first == second


def test_card_sender_info_沒有日期的信最舊(monkeypatch):
    _card(monkeypatch, ("a@x.example", "p"))
    msgs = [row("1", from_addr="a@x.example", subject_pattern="p", subject="沒日期", sent_date=None),
            row("2", from_addr="a@x.example", subject_pattern="p", subject="有日期", sent_date=date(2020, 1, 1))]
    assert repo.card_sender_info(RecSession(msgs), "s3")["a@x.example"]["subject"] == "有日期"
    assert repo.card_sender_info(RecSession(msgs[:1]), "s3")["a@x.example"]["subject"] == "沒日期"


def test_card_sender_info_沒有任何信的寄件者不出現(monkeypatch):
    _card(monkeypatch, ("a@x.example", "p"), ("z@x.example", "p"))
    msgs = [row("1", from_addr="a@x.example", subject_pattern="p", subject="s")]
    assert list(repo.card_sender_info(RecSession(msgs), "s3")) == ["a@x.example"]


def test_card_sender_info_分批查詢結果相同(monkeypatch):
    senders = [f"s{i}@x.example" for i in range(5)]
    _card(monkeypatch, *[(s, "p") for s in senders])
    msgs = [row(f"g{i}", from_addr=s, subject_pattern="p", subject=f"主旨{i}", from_name=f"名{i}")
            for i, s in enumerate(senders)]
    whole = repo.card_sender_info(RecSession(msgs), "s3")
    monkeypatch.setattr(repo, "_IN_CHUNK", 2)
    chunked = RecSession(msgs)
    assert repo.card_sender_info(chunked, "s3") == whole and len(whole) == 5
    assert sum("IN" in f for f in chunked.filters) == 3          # 5 個寄件者、每批 2 個 → 3 次查詢


# ── AC2：卡片內文 ──────────────────────────────────────────────────

def test_embed_省略_info_與空_info_輸出相同():
    rules = [R(1, "a@shop.example", "週報 #"), R(2, "b@news.example", status="rejected")]
    counts = {("a@shop.example", "週報 #"): 3}
    base = ui.suggest_embed("s3", rules, counts)
    for info in (None, {}):
        e = ui.suggest_embed("s3", rules, counts, info)
        assert (e.title, e.description, e.footer.text) == (base.title, base.description, base.footer.text)
    assert base.description.split("\n") == ["`a@shop.example`｜1 種主旨｜3 封", "~~`b@news.example`｜1 種主旨｜0 封~~ 已拒絕"]


def test_embed_有_info_名稱粗體_地址_樣式數_封數_下一行主旨():
    rules = [R(1, "a@shop.example"), R(2, "b@news.example")]
    counts = {("a@shop.example", PAT): 3, ("b@news.example", PAT): 9}
    info = {"a@shop.example": I("甲商店", "週報 第12期"), "b@news.example": I("乙電子報", "新品上架")}
    e = ui.suggest_embed("s3", rules, counts, info)
    assert e.description.split("\n") == [
        "**乙電子報** `b@news.example`｜1 種主旨｜9 封", "　└ 新品上架",
        "**甲商店** `a@shop.example`｜1 種主旨｜3 封", "　└ 週報 第12期"]


def test_embed_沒有顯示名稱只顯示地址_有主旨仍顯示主旨():
    e = ui.suggest_embed("s3", [R(1, "a@shop.example")], {}, {"a@shop.example": I(None, "週報")})
    assert e.description.split("\n") == ["`a@shop.example`｜1 種主旨", "　└ 週報"]


def test_embed_沒有主旨或沒有這個寄件者的資訊_不多一行():
    rules = [R(1, "a@shop.example"), R(2, "b@shop.example")]
    e = ui.suggest_embed("s3", rules, {}, {"a@shop.example": I("甲商店", "")})
    assert e.description.split("\n") == ["**甲商店** `a@shop.example`｜1 種主旨", "`b@shop.example`｜1 種主旨"]


def test_embed_已拒絕與已指定_整段劃掉_保留尾註():
    rules = [R(1, "a@shop.example", status="rejected"),
             R(2, "b@shop.example", cat="receipt", status="confirmed", by="user"),
             R(3, "c@shop.example")]
    info = {s: I(n, "主旨" + n) for s, n in (("a@shop.example", "甲"), ("b@shop.example", "乙"), ("c@shop.example", "丙"))}
    lines = ui.suggest_embed("s3", rules, {}, info).description.split("\n")
    assert lines == ["~~**甲** `a@shop.example`｜1 種主旨", "　└ 主旨甲~~ 已拒絕",
                     "~~**乙** `b@shop.example`｜1 種主旨", "　└ 主旨乙~~ → 收據／訂單／出貨",
                     "**丙** `c@shop.example`｜1 種主旨", "　└ 主旨丙"]


def test_embed_名稱與主旨的_markdown_符號跳脫():
    info = {"a@shop.example": I("A*B*", "5折 ~~限時~~ ||秘密|| `x`")}
    desc = ui.suggest_embed("s3", [R(1, "a@shop.example")], {}, info).description
    assert desc.startswith("**A\\*B\\*** `a@shop.example`")
    assert "　└ 5折 \\~\\~限時\\~\\~ \\|\\|秘密\\|\\| \\`x\\`" in desc


def test_embed_名稱主旨地址各自截短():
    rules = [R(1, "x" * 100 + "@shop.example")]
    info = {rules[0].sender: I("名" * 100, "題" * 100)}
    name_line, subject_line = ui.suggest_embed("s3", rules, {}, info).description.split("\n")
    assert name_line.startswith("**" + "名" * 29 + "…** `" + "x" * 39 + "…`｜")
    assert subject_line == "　└ " + "題" * 49 + "…"


# ── AC3：長度安全 ──────────────────────────────────────────────────

def _full_card(n, **kw):
    """n 個寄件者，名稱、主旨、地址都是上限長度；封數遞減讓排序穩定。"""
    senders = [f"{'s%02d' % i}{'x' * 100}@shop.example" for i in range(n)]
    rules = [R(i, s, **kw) for i, s in enumerate(senders)]
    counts = {(s, PAT): 99999 - i for i, s in enumerate(senders)}
    info = {s: I("名" * 30, "題" * 50) for s in senders}
    return senders, rules, counts, info


def test_embed_25個寄件者都是上限長度_不超過4096_25個都在():
    senders, rules, counts, info = _full_card(25)
    e = ui.suggest_embed("s3", rules, counts, info)
    assert len(e.description) <= 4096
    assert e.description.count("　└ ") == 25 and e.description.count("**" + "名" * 30 + "**") == 25
    assert all(f"`{s[:39]}…`" in e.description for s in senders)


def test_embed_超過25個寄件者_上限長度_仍列25個加尾行():
    senders, rules, counts, info = _full_card(40)
    e = ui.suggest_embed("s3", rules, counts, info)
    lines = e.description.split("\n")
    assert len(e.description) <= 4096 and "…還有 15 個寄件者" in lines[-1]
    assert sum(f"`{s[:39]}…`" in e.description for s in senders) == 25
    assert e.description.count("　└ ") == 25


def test_embed_最壞情況_已指定_大封數_多樣式_25個寄件者一個都不少():
    senders = [f"s{i:02d}{'x' * 100}@shop.example" for i in range(26)]
    rules = [R(i * 1000 + j, s, f"樣式 {j}", cat="receipt", status="confirmed", by="user")
             for i, s in enumerate(senders) for j in range(120)]
    counts = {(r.sender, r.subject_pattern): 99999 for r in rules}
    info = {s: I("名" * 30, "題" * 50) for s in senders}
    e = ui.suggest_embed("s3", rules, counts, info)
    assert len(e.description) <= 4096
    assert sum(f"`{s[:39]}…`" in e.description or f"`{s[:59]}…`" in e.description for s in senders) == 25


def test_embed_全是_markdown_符號的名稱主旨_也不超過上限():
    senders, rules, counts, _ = _full_card(25)
    info = {s: I("*" * 100, "~" * 100) for s in senders}
    e = ui.suggest_embed("s3", rules, counts, info)
    assert len(e.description) <= 4096
    assert all(len(line) <= 160 for line in e.description.split("\n"))
    assert sum(f"`{s[:39]}…`" in e.description for s in senders) == 25


# ── AC4：「勾選不是這類的寄件者」下拉 ───────────────────────────────

def _reject_select(view):
    return next(c for c in view.children if c.custom_id.startswith("mailrules:rejsender:")).item


def test_view_有_info_label_是名稱_description_是地址加主旨_value_不變():
    rules = [R(1, "c@x.example"), R(2, "a@x.example"), R(3, "b@x.example")]
    counts = {("b@x.example", PAT): 9, ("c@x.example", PAT): 5, ("a@x.example", PAT): 1}
    info = {"a@x.example": I("甲", "週報"), "b@x.example": I(None, "新品"), "c@x.example": I("丙公司", "")}

    async def go():
        opts = _reject_select(ui.suggest_view("s3", rules, counts, info)).options
        assert [(o.label, o.description, o.value) for o in opts] == [
            ("b@x.example", "b@x.example｜新品", "1"),
            ("丙公司", "c@x.example", "2"),
            ("甲", "a@x.example｜週報", "0")]
    asyncio.run(go())


def test_view_省略_info_label是地址_description是樣式數與封數():
    rules = [R(1, "a@x.example"), R(2, "b@x.example")]

    async def go():
        for info in (None, {}):
            opts = _reject_select(ui.suggest_view("s3", rules, {("b@x.example", PAT): 4}, info)).options
            assert [(o.label, o.description, o.value) for o in opts] == [
                ("b@x.example", "1 種主旨｜4 封", "1"), ("a@x.example", "1 種主旨｜0 封", "0")]
    asyncio.run(go())


def test_view_長名稱主旨_label與description_不超過100():
    senders = [f"s{i:02d}{'x' * 200}@shop.example" for i in range(30)]
    rules = [R(i, s) for i, s in enumerate(senders)]
    info = {s: I("名" * 300, "題" * 300) for s in senders}

    async def go():
        opts = _reject_select(ui.suggest_view("s3", rules, {}, info)).options
        assert len(opts) == 25
        assert all(0 < len(o.label) <= 100 and len(o.description) <= 100 for o in opts)
    asyncio.run(go())


def test_from_custom_id_重建_option_保留_description():
    async def go():
        item = ui.SenderRejectSelect("s3", [discord.SelectOption(label="甲", value="0", description="a@x.example｜週報")])
        m = ui.SenderRejectSelect.__discord_ui_compiled_template__.fullmatch("mailrules:rejsender:s3")
        new = await ui.SenderRejectSelect.from_custom_id(None, item.item, m)
        assert [(o.label, o.value, o.description) for o in new.item.options] == [("甲", "0", "a@x.example｜週報")]
    asyncio.run(go())


# ── AC5：被拒絕後的手動指定卡 ───────────────────────────────────────

def test_assign_view_placeholder_有名稱寫名稱加地址_custom_id不變():
    async def go():
        v = ui.assign_view("s3", [(0, "a@x.example"), (1, "b@x.example")], {"a@x.example": I("甲商店", "週報")})
        assert [c.custom_id for c in v.children] == ["mailrules:assignsender:s3:0", "mailrules:assignsender:s3:1"]
        assert [c.item.placeholder for c in v.children] == ["甲商店 a@x.example → 選類別", "b@x.example → 選類別"]
    asyncio.run(go())


def test_assign_view_省略_info_placeholder只有地址():
    async def go():
        v = ui.assign_view("s3", [(0, "a@x.example")])
        assert v.children[0].item.placeholder == "a@x.example → 選類別"
    asyncio.run(go())


def test_手動指定卡文字_名稱地址與主旨(monkeypatch):
    rules = [R(1, "a@x.example", status="rejected"), R(2, "a@x.example", "新品", status="rejected"),
             R(3, "b@x.example", status="rejected")]
    info = {"a@x.example": I("甲商店", "週報 第12期"), "b@x.example": I(None, "")}
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", rules, info))
    text = it.followup.send.await_args.args[0]
    assert "**甲商店** `a@x.example`｜2 種主旨\n　└ 週報 第12期" in text
    assert "\n`b@x.example`｜1 種主旨" in text and text.count("└") == 1
    view = it.followup.send.await_args.kwargs["view"]
    assert [c.item.placeholder for c in view.children] == ["甲商店 a@x.example → 選類別", "b@x.example → 選類別"]
    assert [c.custom_id for c in view.children] == ["mailrules:assignsender:s3:0", "mailrules:assignsender:s3:1"]


def test_手動指定卡文字_省略_info_只列地址與樣式數():
    rules = [R(1, "a@x.example", status="rejected")]
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", rules))
    assert it.followup.send.await_args.args[0].endswith("：\n`a@x.example`｜1 種主旨")


def test_手動指定卡文字_長名稱主旨_不超過2000():
    senders = [f"s{i}{'x' * 200}@x.example" for i in range(4)]
    rules = [R(i, s, status="rejected") for i, s in enumerate(senders)]
    info = {s: I("名" * 300, "題" * 300) for s in senders}
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", rules, info))
    text = it.followup.send.await_args.args[0]
    assert len(text) <= 2000 and text.count("└") == 4


# ── AC6：所有畫卡路徑都帶 info ─────────────────────────────────────

class InfoRepo:
    def __init__(self, rules, counts=None, info=None, boom=False):
        self.rules, self.counts, self.info, self.boom = list(rules), dict(counts or {}), dict(info or {}), boom
        self.marked = []
    def card_rules(self, db, card): return [r for r in self.rules if r.card == card]
    def card_counts(self, db, card): return dict(self.counts)
    def card_sender_info(self, db, card):
        if self.boom:
            raise RuntimeError("DB 斷線")
        return dict(self.info)
    def reject_senders(self, db, card, senders):
        self.rules = [replace(r, status="rejected") if r.sender in senders and r.status == "suggested" else r
                      for r in self.rules]
        return len(senders)
    def reject(self, db, card, ids):
        self.rules = [replace(r, status="rejected") if r.id in ids and r.status == "suggested" else r
                      for r in self.rules]
        return len(ids)
    def confirm_card(self, db, card, ids):
        self.rules = [replace(r, status="confirmed") if r.status == "suggested" else r for r in self.rules]
        return 0, 0
    def mark_cards_posted(self, db, cards): self.marked += list(cards)


RULES = [R(1, "a@x.example"), R(2, "b@x.example")]
COUNTS = {("a@x.example", PAT): 3, ("b@x.example", PAT): 5}
INFO = {"a@x.example": I("甲商店", "週報 第12期"), "b@x.example": I("乙電子報", "新品上架")}


def _wire(monkeypatch, fake):
    monkeypatch.setenv("AUTOFIX_OWNER_USER_ID", "1")
    monkeypatch.setattr(ui, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(ui, "repo", fake)
    monkeypatch.setattr(ui.config, "mail_channel_id", lambda: 123)
    got = []
    monkeypatch.setattr(ui, "post_sync_wait",
                        lambda ch, embeds, make_view=None, timeout=30: got.append((embeds[0], make_view)) or True)
    return got


def test_notify_cards_新卡帶_info(monkeypatch):
    fake = InfoRepo(RULES, COUNTS, INFO)
    got = _wire(monkeypatch, fake)
    assert ui.notify_cards(["s3"]) == ["s3"] and fake.marked == ["s3"]
    embed, make_view = got[0]
    assert "**甲商店** `a@x.example`" in embed.description and "　└ 新品上架" in embed.description

    async def go():
        opts = _reject_select(make_view()).options
        assert sorted((o.label, o.description) for o in opts) == [("乙電子報", "b@x.example｜新品上架"),
                                                                  ("甲商店", "a@x.example｜週報 第12期")]
    asyncio.run(go())


def test_notify_cards_info_查詢失敗_照發卡_只印警告(monkeypatch, capsys):
    fake = InfoRepo(RULES, COUNTS, INFO, boom=True)
    got = _wire(monkeypatch, fake)
    assert ui.notify_cards(["s3"]) == ["s3"] and fake.marked == ["s3"]
    assert got[0][0].description == ui.suggest_embed("s3", RULES, COUNTS).description
    assert "⚠️" in capsys.readouterr().out


def test_勾拒絕後重畫_帶_info(monkeypatch):
    fake = InfoRepo(RULES, COUNTS, INFO)
    _wire(monkeypatch, fake)
    it = _ix()
    it.data = {"values": ["0"]}
    asyncio.run(ui.SenderRejectSelect("s3", []).callback(it))
    kw = it.response.edit_message.await_args.kwargs
    assert "~~**甲商店** `a@x.example`｜1 種主旨｜3 封\n　└ 週報 第12期~~ 已拒絕" in kw["embed"].description
    assert "**乙電子報** `b@x.example`" in kw["embed"].description

    async def go():
        assert [(o.label, o.description) for o in _reject_select(kw["view"]).options] == [
            ("乙電子報", "b@x.example｜新品上架")]
    asyncio.run(go())


def test_全部拒絕後重畫_手動指定卡也帶_info(monkeypatch):
    fake = InfoRepo(RULES, COUNTS, INFO)
    _wire(monkeypatch, fake)
    it = _ix()
    it.data = {"values": ["0", "1"]}
    asyncio.run(ui.SenderRejectSelect("s3", []).callback(it))
    text = it.followup.send.await_args.args[0]
    assert "**甲商店** `a@x.example`" in text and "　└ 週報 第12期" in text and "　└ 新品上架" in text
    view = it.followup.send.await_args.kwargs["view"]
    assert [c.item.placeholder for c in view.children] == ["甲商店 a@x.example → 選類別", "乙電子報 b@x.example → 選類別"]


def test_舊的逐條拒絕下拉重畫_也帶_info(monkeypatch):
    fake = InfoRepo(RULES, COUNTS, INFO)
    _wire(monkeypatch, fake)
    it = _ix()
    it.data = {"values": ["1"]}
    asyncio.run(ui.RejectSelect("s3", [discord.SelectOption(label="a", value="1")]).callback(it))
    assert "~~**甲商店**" in it.response.edit_message.await_args.kwargs["embed"].description


def test_整類確認後重畫_與手動指定卡_帶_info(monkeypatch):
    rules = [R(1, "a@x.example"), R(2, "b@x.example", status="rejected")]
    fake = InfoRepo(rules, COUNTS, INFO)
    _wire(monkeypatch, fake)
    it = _ix()
    asyncio.run(ui.ConfirmButton("s3").callback(it))
    kw = it.response.edit_message.await_args.kwargs
    assert kw["view"] is None
    assert "**甲商店** `a@x.example`" in kw["embed"].description
    assert "~~**乙電子報** `b@x.example`｜1 種主旨｜5 封\n　└ 新品上架~~ 已拒絕" in kw["embed"].description
    text = it.followup.send.await_args.args[0]
    assert "**乙電子報** `b@x.example`" in text and "　└ 新品上架" in text
    view = it.followup.send.await_args.kwargs["view"]
    assert [c.item.placeholder for c in view.children] == ["乙電子報 b@x.example → 選類別"]


def test_info_查詢失敗_按鈕照常重畫(monkeypatch, capsys):
    rules = [R(1, "a@x.example"), R(2, "b@x.example", status="rejected")]
    fake = InfoRepo(rules, COUNTS, INFO, boom=True)
    _wire(monkeypatch, fake)
    it = _ix()
    asyncio.run(ui.ConfirmButton("s3").callback(it))
    assert it.response.edit_message.await_args.kwargs["embed"].description == ui.suggest_embed(
        "s3", [replace(rules[0], status="confirmed"), rules[1]], COUNTS).description
    assert it.followup.send.await_args.args[0].endswith("：\n`b@x.example`｜1 種主旨")
    it2 = _ix()
    it2.data = {"values": ["0"]}
    asyncio.run(ui.SenderRejectSelect("s3", []).callback(it2))
    it2.response.edit_message.assert_awaited_once()
    assert capsys.readouterr().out.count("⚠️") == 2


# ── 外來文字：不能變成遮罩連結、不能 tag 人 ─────────────────────────────

# Discord（simple-markdown）的連結語法：先吃掉反斜線跳脫過的字元，剩下的 [..](..) 才會變成可點的連結
_MASKED_LINK = re.compile(r"""\[((?:\[[^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*)\]\(\s*<?((?:\([^)]*\)|[^\s\\]|\\.)*?)>?"""
                          r"""(?:\s+['"]([\s\S]*?)['"])?\s*\)""")
_ESCAPED = re.compile(r"\\[^0-9A-Za-z\s]")


def has_masked_link(text):
    i = 0
    while i < len(text):
        if _ESCAPED.match(text, i):
            i += 2
        elif text[i] == "[" and _MASKED_LINK.match(text, i):
            return True
        else:
            i += 1
    return False


def renders_mention(text):
    """貼進 Discord 內文會不會 tag 到人：@everyone／@here／@id 字樣（escape_mentions 還會改動它），
    或沒被反斜線跳脫的 <（<@…> <@&…> <#…> <:…:…> <t:…> 都從它起頭）。"""
    return discord.utils.escape_mentions(text) != text or "<" in _ESCAPED.sub("", text)


LINKS = ["[Bank](https://x.test)",
         "[a.test](https://e.test)",                # 顯示文字像網域、實際連到別處
         "\\[Bank](https://x.test)",                    # 自己帶的反斜線：只跳脫 [ 會變成 \\[ ，[ 反而恢復成連結
         "\\\\[Bank](https://x.test)",
         "[[Bank]](https://x.test)",
         "[Bank](<https://x.test>)",
         '[B](https://x.test "登入")']
PINGS = ["@everyone", "@here", "<@&123456789012345678>", "<@123456789012345678>", "<@!123456789012345678>"]


def test_外來文字_判斷用的連結規則本身可靠():
    assert has_masked_link("[Bank](https://x.test)") and has_masked_link("看 [a.test](https://e.test) 吧")
    assert has_masked_link("\\\\[Bank](https://x.test)")           # 反斜線自己被跳脫了，[ 沒有
    assert not has_masked_link("\\[Bank\\]\\(https://x.test\\)")
    assert not has_masked_link("\\[Bank](https://x.test)")
    assert not has_masked_link("[Bank] (https://x.test)")
    assert renders_mention("@everyone") and renders_mention("<@&123456789012345678>") and renders_mention("@@here")
    assert not renders_mention("@\u200beveryone \\<@\u200b&123456789012345678>")


def test_外來文字_名稱與主旨是遮罩連結_卡片內文不含連結():
    for evil in LINKS:
        info = {"a@shop.example": I(evil, evil)}
        desc = ui.suggest_embed("s3", [R(1, "a@shop.example")], {}, info).description
        assert not has_masked_link(desc), (evil, desc)
        assert "…" not in desc                      # 沒被截斷：是跳脫擋住的，不是截斷剛好切掉


def test_外來文字_遮罩連結逐字跳脫_括號與方括號都有反斜線():
    info = {"a@shop.example": I(LINKS[0], LINKS[0])}
    assert ui.suggest_embed("s3", [R(1, "a@shop.example")], {}, info).description.split("\n") == [
        "**\\[Bank\\]\\(https://x.test\\)** `a@shop.example`｜1 種主旨",
        "　└ \\[Bank\\]\\(https://x.test\\)"]


def test_外來文字_已拒絕劃掉的行也不含連結():
    info = {"a@shop.example": I(LINKS[1], LINKS[1])}
    desc = ui.suggest_embed("s3", [R(1, "a@shop.example", status="rejected")], {}, info).description
    assert desc.startswith("~~**") and desc.endswith("~~ 已拒絕") and not has_masked_link(desc)


def test_外來文字_括號方括號在截斷處不留孤立反斜線():
    info = {"a@shop.example": I("[" * 40, "(" * 80)}
    name_line, subject_line = ui.suggest_embed("s3", [R(1, "a@shop.example")], {}, info).description.split("\n")
    name = name_line[len("**"):name_line.index("** ")]
    subject = subject_line[len("　└ "):]
    for text, limit in ((name, 30), (subject, 50)):
        assert len(text) <= limit and text.endswith("…")
        assert _ESCAPED.sub("", text[:-1]) == ""                 # 每個字元都在一組「\\X」裡，沒有孤立的反斜線


def test_外來文字_名稱與主旨是提及_卡片內文不會tag人():
    rules = [R(i, f"{i}@shop.example") for i in range(len(PINGS))]
    info = {r.sender: I(p, p) for r, p in zip(rules, PINGS)}
    desc = ui.suggest_embed("s3", rules, {}, info).description
    assert not renders_mention(desc), desc
    assert desc.count("@\u200beveryone") == 2 and desc.count("@\u200bhere") == 2


def test_外來文字_md_提及與連結符號():
    assert ui._md("@everyone @here", 40) == "@\u200beveryone @\u200bhere"
    assert ui._md("<@&123456789012345678>", 40) == "\\<@\u200b&123456789012345678>"
    assert ui._md("[a](b)", 40) == "\\[a\\]\\(b\\)"
    assert ui._md("@" + "x" * 50, 10) == "@xxxxxxxx…"


def test_外來文字_手動指定卡_不tag人_訊息帶_allowed_mentions_none():
    rules = [R(i, f"{i}@shop.example", status="rejected") for i in range(len(PINGS))]
    info = {r.sender: I(p, p) for r, p in zip(rules, PINGS)}
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", rules, info))
    calls = it.followup.send.await_args_list
    assert len(calls) == 2
    for c in calls:
        assert not renders_mention(c.args[0]), c.args[0]
        am = c.kwargs["allowed_mentions"]
        assert (am.everyone, am.users, am.roles, am.replied_user) == (False, False, False, False)


def test_外來文字_沒有_info_的手動指定卡_也帶_allowed_mentions_none():
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", [R(1, "a@x.example", status="rejected")]))
    am = it.followup.send.await_args.kwargs["allowed_mentions"]
    assert (am.everyone, am.users, am.roles) == (False, False, False)


def test_外來文字_手動指定卡_遮罩連結不會變成連結():
    rules = [R(i, f"{i}@shop.example", status="rejected") for i in range(len(LINKS))]
    info = {r.sender: I(v, v) for r, v in zip(rules, LINKS)}
    it = _ix()
    asyncio.run(ui._send_assign_cards(it, "s3", rules, info))
    calls = it.followup.send.await_args_list
    assert len(calls) == 2
    assert not any(has_masked_link(c.args[0]) for c in calls)


def test_外來文字_下拉選項與_placeholder_是純文字_不跳脫():
    rules = [R(1, "a@x.example")]
    info = {"a@x.example": I("A*B* [x](y)", "5折 ~~限時~~ <@&123456789012345678>")}

    async def go():
        opt = _reject_select(ui.suggest_view("s3", rules, {}, info)).options[0]
        assert (opt.label, opt.description) == ("A*B* [x](y)", "a@x.example｜5折 ~~限時~~ <@&123456789012345678>")
        v = ui.assign_view("s3", [(0, "a@x.example")], info)
        assert v.children[0].item.placeholder == "A*B* [x](y) a@x.example → 選類別"
    asyncio.run(go())
