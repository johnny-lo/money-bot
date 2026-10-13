import asyncio
import json
from datetime import datetime, timedelta

import pytest

from discordbot import autofix_ui

NOW = datetime(2026, 10, 10, 21, 0)


@pytest.mark.parametrize("uid,owner,status,rep,expect", [
    (1, 1, "reported", NOW - timedelta(days=1), None),
    (2, 1, "reported", NOW, "只有"),                          # 女友按
    (1, None, "reported", NOW, "AUTOFIX_OWNER_USER_ID"),     # 沒設 owner
    (1, 1, "deploying", NOW, "deploying"),                   # 按第二次
    (1, 1, "abandoned", NOW, "abandoned"),
    (1, 1, None, NOW, "找不到"),
    (1, 1, "reported", NOW - timedelta(days=8), "過期"),     # 7 天後
])
def test_can_act(uid, owner, status, rep, expect):
    got = autofix_ui.can_act(uid, owner, status, rep, NOW)
    assert (got is None) if expect is None else (expect in got)


def test_write_approval(monkeypatch, tmp_path):
    (tmp_path / "approved").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    autofix_ui.write_approval(7, "deploy")
    assert (tmp_path / "approved" / "7.deploy").exists()


def test_custom_id_格式_重啟後還能解析():
    item = autofix_ui.AutofixButton("deploy", 42)
    assert item.custom_id == "autofix:deploy:42"
    m = autofix_ui.AutofixButton.__discord_ui_compiled_template__.fullmatch("autofix:abandon:7")
    assert m["action"] == "abandon" and m["id"] == "7"


class FakeChannel:
    def __init__(self):
        self.sent = []
    async def send(self, **kw):
        self.sent.append(kw)
        class M: id = 555
        return M()
    async def fetch_message(self, mid):
        ch = self
        class M:
            async def reply(self, **kw):
                ch.sent.append({"reply_to": mid, **kw})
        return M()


class FakeBot:
    def __init__(self, ch): self.ch = ch
    def get_channel(self, cid): return self.ch


def test_process_outbox_報告與部署結果(monkeypatch, tmp_path):
    (tmp_path / "outbox").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOFIX_CHANNEL_ID", "123")
    marks = []
    monkeypatch.setattr(autofix_ui.incidents, "mark", lambda i, s, **f: marks.append((i, s, f)))
    monkeypatch.setattr(autofix_ui.incidents, "get", lambda i: {"report_message_id": "555"})
    monkeypatch.setattr(autofix_ui.incidents, "now_tw", lambda: NOW)
    rep = {"type": "report", "incident_id": 7, "title": "t", "diff_file": None,
           "report": {"verdict": "fixed", "tests": {"passed": 1, "failed": 0}}}
    (tmp_path / "outbox" / "7-report.json").write_text(json.dumps(rep))
    dep = {"type": "deploy", "incident_id": 7, "status": "resolved", "stage": "verify",
           "message": "ok", "log_tail": ""}
    (tmp_path / "outbox" / "7-deploy.json").write_text(json.dumps(dep))
    ch = FakeChannel()
    n = asyncio.run(autofix_ui.process_outbox(FakeBot(ch)))
    assert n == 2 and list((tmp_path / "outbox").iterdir()) == []
    assert ch.sent[0]["view"] is not None                  # fixed → 有按鈕
    assert ch.sent[1]["reply_to"] == 555                   # 部署結果回在報告卡底下
    assert marks[0][:2] == (7, "reported") and marks[0][2]["report_message_id"] == "555"
    assert marks[1][:2] == (7, "resolved")


def test_process_outbox_壞檔不卡住整個佇列(monkeypatch, tmp_path, capsys):
    (tmp_path / "outbox").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOFIX_CHANNEL_ID", "123")
    (tmp_path / "outbox" / "1-report.json").write_text("{壞掉")
    asyncio.run(autofix_ui.process_outbox(FakeBot(FakeChannel())))
    assert (tmp_path / "outbox" / "1-report.json.bad").exists()


# ── 任何失敗都不能讓事件卡在 dispatched/deploying ──

def test_核可檔寫不出去_不改狀態_回錯誤(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))          # 沒有 approved/ 目錄
    marks = []
    monkeypatch.setattr(autofix_ui.incidents, "mark", lambda *a, **k: marks.append(a))
    err = autofix_ui.apply_action(7, "deploy")
    assert err and "核可檔" in err and marks == []


def test_核可成功_先寫檔再改狀態(monkeypatch, tmp_path):
    (tmp_path / "approved").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    monkeypatch.setattr(autofix_ui.incidents, "now_tw", lambda: NOW)
    marks = []
    monkeypatch.setattr(autofix_ui.incidents, "mark",
                        lambda i, s, **k: marks.append((i, s, (tmp_path / "approved" / "7.deploy").exists())))
    assert autofix_ui.apply_action(7, "deploy") is None
    assert marks == [(7, "deploying", True)]


class GoneChannel(FakeChannel):
    async def fetch_message(self, mid):
        raise RuntimeError("Unknown Message")


def test_報告卡被刪_部署結果改直接發_且仍更新狀態(monkeypatch, tmp_path):
    (tmp_path / "outbox").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOFIX_CHANNEL_ID", "123")
    marks = []
    monkeypatch.setattr(autofix_ui.incidents, "mark", lambda i, s, **f: marks.append((i, s)))
    monkeypatch.setattr(autofix_ui.incidents, "get", lambda i: {"report_message_id": "555"})
    monkeypatch.setattr(autofix_ui.incidents, "now_tw", lambda: NOW)
    dep = {"type": "deploy", "incident_id": 7, "status": "resolved", "stage": "verify",
           "message": "ok", "log_tail": ""}
    (tmp_path / "outbox" / "7-deploy.json").write_text(json.dumps(dep))
    ch = GoneChannel()
    assert asyncio.run(autofix_ui.process_outbox(FakeBot(ch))) == 1
    assert (7, "resolved") in marks and ch.sent and "embed" in ch.sent[0]


class DeadChannel(FakeChannel):
    async def send(self, **kw):
        raise RuntimeError("Missing Access")


def test_發卡失敗_事件結案_inconclusive_不讓感測器失聲(monkeypatch, tmp_path):
    (tmp_path / "outbox").mkdir()
    monkeypatch.setenv("AUTOFIX_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOFIX_CHANNEL_ID", "123")
    marks = []
    monkeypatch.setattr(autofix_ui.incidents, "mark", lambda i, s, **f: marks.append((i, s)))
    monkeypatch.setattr(autofix_ui.incidents, "now_tw", lambda: NOW)
    rep = {"type": "report", "incident_id": 8, "title": "t", "diff_file": None,
           "report": {"verdict": "fixed", "tests": {"passed": 1, "failed": 0}}}
    (tmp_path / "outbox" / "8-report.json").write_text(json.dumps(rep))
    asyncio.run(autofix_ui.process_outbox(FakeBot(DeadChannel())))
    assert marks == [(8, "inconclusive")]
    assert (tmp_path / "outbox" / "8-report.json.bad").exists()
