from datetime import date

from models import MailMessage, MailRule, MailState, MailValuedDomain
from mailrules import config
from mailrules.types import Action, MailHeader, Rule, Verdict


def test_tables():
    assert set(MailRule.__table__.columns.keys()) == {
        "id", "sender", "subject_pattern", "category", "status", "suggested_by", "card", "created_at", "confirmed_at",
        "posted_at"}
    assert set(MailMessage.__table__.columns.keys()) == {
        "id", "gm_msgid", "uid", "from_addr", "subject_pattern", "subject", "sent_date", "category", "reason",
        "protected", "in_inbox", "labels_applied", "trashed_at", "updated_at", "gone_at", "unsub", "from_name"}
    assert set(MailValuedDomain.__table__.columns.keys()) == {"domain", "first_seen", "source_subject_pattern"}
    assert set(MailState.__table__.columns.keys()) == {"id", "uidvalidity", "last_uid", "history_done_at", "plan_posted_card"}
    assert MailMessage.__table__.columns["gm_msgid"].unique


def test_每個類別都有保留規則_且標籤都在整理底下():
    keys = [k for k, _ in config.CATEGORIES]
    assert set(keys) == set(config.RETENTION)
    assert keys[0] == "keep_inbox"
    for k, r in config.RETENTION.items():
        assert r.label is None or r.label.startswith(config.LABEL_ROOT + "/"), k


def test_保留期限():
    R = config.RETENTION
    assert (R["login"].trash_after_days, R["social"].trash_after_days) == (0, 0)
    assert (R["company"].trash_after_days, R["jobs"].trash_after_days, R["promo"].trash_after_days) == (30, 14, 14)
    assert R["card"].trash_after_days == R["receipt"].trash_after_days == R["bill"].trash_after_days == config.FINANCE_KEEP_DAYS
    assert R["travel"].trash_after_days == 180
    assert R["security"].archive_after_days == 7 and R["security"].trash_after_days is None
    for k in ("keep_inbox",):
        assert R[k].label is None and R[k].archive_after_days is None and R[k].trash_after_days is None
    for k in ("self", "tax", "school"):
        assert R[k].trash_after_days is None and R[k].archive_after_days == 0
    assert R["jobs"].digest == "daily" and R["promo"].digest == "weekly"


def test_env_設定讀取(monkeypatch):
    monkeypatch.setenv("MAIL_OWNER_NAME", " 王小明 ")
    monkeypatch.setenv("MAIL_SELF_ADDRESSES", "A@x.com, b@y.com")
    monkeypatch.setenv("MAIL_COMPANY_DOMAINS", "corp.example")
    monkeypatch.setenv("MAIL_CHANNEL_ID", "123")
    assert config.owner_name() == "王小明"
    assert config.self_addresses() == {"a@x.com", "b@y.com"}
    assert config.company_domains() == {"corp.example"}
    assert config.mail_channel_id() == 123
    monkeypatch.delenv("MAIL_CHANNEL_ID")
    assert config.mail_channel_id() is None


def test_types():
    h = MailHeader(gm_msgid="1", uid=5, from_addr="a@b.com", from_name="A", subject="s",
                   sent_date=date(2026, 1, 1), labels=("\\Inbox",), unsub=False, in_inbox=True)
    assert Verdict(category=None, reason="未知", protected=False).category is None
    assert Action(gm_msgid="1", uid=5, kind="trash").label is None
    assert Rule(id=None, sender="@b.com", subject_pattern="*", category="promo",
                status="suggested", suggested_by="ai").card is None
    assert h.in_inbox
