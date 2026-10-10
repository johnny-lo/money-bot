"""自動修復事件的 DB 外殼：計次、派發（寫 inbox）、狀態轉換。決策邏輯在 policy.py。

鐵則：感測器是「順便看一眼」，絕不能讓業務流程失敗 → 對外函式全部吞例外、只印 log。
交接目錄由主機建立（autofix/install.sh）；這裡遇到目錄不存在只印 log、不建立
（容器是 root，建出來的目錄主機刪不掉）。
"""
import json
import os
import zlib
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from database import SessionLocal
from models import AutofixIncident
from autofix.policy import POLICIES, Snapshot, decide, merge_context

TZ = ZoneInfo("Asia/Taipei")


def enabled() -> bool:
    return os.getenv("AUTOFIX_ENABLED", "") == "1"


def now_tw() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def _dir(name: str) -> str:
    return os.path.join(os.getenv("AUTOFIX_DIR", "/app/autofix"), name)


def inbox_payload(inc: AutofixIncident) -> dict:
    return {"id": inc.id, "sensor": inc.sensor, "signature": inc.signature,
            "title": inc.title, "context": inc.context or {}, "hit_keys": inc.hit_keys or [],
            "escalated": inc.status == "needs_human"}


def _write_inbox(inc: AutofixIncident) -> bool:
    """寫成功回 True。失敗只印 log——呼叫端據此決定要不要標 dispatched。"""
    d = _dir("inbox")
    if not os.path.isdir(d):
        print(f"⚠️ autofix：{d} 不存在（主機沒跑 autofix/install.sh？），事件 #{inc.id} 先不派發", flush=True)
        return False
    try:
        tmp = os.path.join(d, f".{inc.id}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(inbox_payload(inc), f, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(d, f"{inc.id}.json"))   # 原子：path unit 不會看到寫一半的檔
        return True
    except OSError as ex:
        print(f"⚠️ autofix：事件 #{inc.id} 寫 inbox 失敗，先不派發：{ex}", flush=True)
        return False


def _lock_key(sensor: str, signature: str) -> int:
    """(sensor, signature) → 穩定的 signed 64-bit，給 pg_advisory_xact_lock。"""
    raw = f"{sensor}|{signature}".encode("utf-8")
    return (zlib.crc32(raw) << 32 | zlib.adler32(raw)) - 2**63


def _latest(db, sensor: str, signature: str):
    return (db.query(AutofixIncident)
            .filter(AutofixIncident.sensor == sensor, AutofixIncident.signature == signature)
            .order_by(AutofixIncident.id.desc())
            .with_for_update()       # 開機補拓與 21:00 排程可能同時打進來 → 鎖列，只派發一次
            .first())


def _raise(sensor, signature, title, context, dedupe_key) -> None:
    policy = POLICIES[sensor]
    now = now_tw()
    db = SessionLocal()
    try:
        # 交易級鎖：連「還沒有任何資料列」的情況也序列化（with_for_update 只鎖得到已存在的列）
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(sensor, signature)})
        latest = _latest(db, sensor, signature)
        snap = None if latest is None else Snapshot(latest.status, latest.hit_keys or [], latest.closed_at)
        d = decide(snap, dedupe_key, now, policy)
        if d.action == "noop":
            return
        if d.action in ("count", "dispatch") and latest is not None and latest.status == "counting":
            inc = latest
            inc.context = merge_context(inc.context or {}, context)
        else:
            inc = AutofixIncident(sensor=sensor, signature=signature, title=title[:200],
                                  context=dict(context), first_seen=now)
            db.add(inc)
        inc.hit_keys = d.hit_keys
        inc.last_seen = now
        if d.action == "escalate":
            inc.status, inc.closed_at = "needs_human", now
            inc.title = f"[上次修正無效] {title}"[:200]
        elif d.action == "dispatch":
            inc.status = "dispatched"
        else:
            inc.status = "counting"
        db.flush()   # 先拿到 id
        # 先寫 inbox、成功才算派發：沒有 inbox 檔卻標 dispatched，這個簽名的感測器就永遠失聲
        if d.action in ("dispatch", "escalate") and not _write_inbox(inc) and d.action == "dispatch":
            inc.status = "counting"   # 門檻已到，下次命中會再試派發
        db.commit()
        print(f"🛠 autofix 事件 #{inc.id} {sensor}/{signature}：{d.action} → {inc.status}"
              f"（{len(d.hit_keys)}/{policy.threshold}）", flush=True)
    finally:
        db.close()


def raise_incident(sensor: str, signature: str, title: str, context: dict, dedupe_key: str) -> None:
    if not enabled():
        return
    try:
        _raise(sensor, signature, title, context, dedupe_key)
    except Exception as ex:
        print(f"⚠️ autofix 記錄事件失敗（不影響主流程）：{type(ex).__name__}: {ex}", flush=True)


def clear(sensor: str, signature: str, *, prefix: bool = False) -> None:
    """恢復正常 → 刪掉還在計數的事件（已派發的不動，交給流水線結案）。"""
    if not enabled():
        return
    try:
        db = SessionLocal()
        try:
            rows = (db.query(AutofixIncident)
                    .filter(AutofixIncident.sensor == sensor, AutofixIncident.status == "counting")
                    .all())
            for r in rows:
                if r.status != "counting":
                    continue
                if (r.signature.startswith(signature) if prefix else r.signature == signature):
                    db.delete(r)
            db.commit()
        finally:
            db.close()
    except Exception as ex:
        print(f"⚠️ autofix clear 失敗（不影響主流程）：{type(ex).__name__}: {ex}", flush=True)


def get(incident_id: int) -> dict | None:
    db = SessionLocal()
    try:
        r = db.query(AutofixIncident).filter(AutofixIncident.id == incident_id).first()
        if r is None:
            return None
        return {c: getattr(r, c) for c in AutofixIncident.__table__.columns.keys()}
    finally:
        db.close()


def mark(incident_id: int, status: str, **fields) -> None:
    db = SessionLocal()
    try:
        r = db.query(AutofixIncident).filter(AutofixIncident.id == incident_id).first()
        if r is None:
            return
        r.status = status
        for k, v in fields.items():
            setattr(r, k, v)
        db.commit()
    finally:
        db.close()
