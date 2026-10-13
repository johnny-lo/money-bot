"""每日／歷史流程編排：同步信頭 → 分類 → 建議 → 規劃 → 執行。歷史整理完成前每日只分類不寫入。

同一時間只跑一個（_LOCK）：每日排程搶不到就整個略過，歷史準備／計畫／執行搶不到就拋 Busy（RuntimeError）。
"""
import threading
from contextlib import contextmanager
from datetime import date, timedelta

from . import classify as C
from . import config, gmail_rw, repo, suggest
from .patterns import subject_pattern
from .plan import plan_actions
from .repo import card_no, rules_fingerprint
from .types import MailHeader, MessageState, RunReport

_AI_BY = "ai"
_BUSY = "另一個信件整理正在跑，請稍後再試"
_EXPIRED = "計畫已過期，請用 /信件計畫 重發"
_LOCK = threading.Lock()


class Busy(RuntimeError):
    """另一個信件整理正在跑（搶不到 _LOCK）。"""


@contextmanager
def _exclusive():
    if not _LOCK.acquire(blocking=False):
        raise Busy(_BUSY)
    try:
        yield
    finally:
        _LOCK.release()


@contextmanager
def _session(db):
    if db is not None:
        yield db
        return
    from database import session_scope
    with session_scope() as s:
        yield s


def _sync(db, full: bool = False) -> list[MailHeader]:
    """增量（uidvalidity 變了、或 full=True 就全量）抓信頭寫進 DB，回傳本次抓到的信頭。"""
    state = repo.get_state(db)
    uidv, hs = gmail_rw.read_headers(None if full or state is None else state[1])
    if full or (state is not None and uidv != state[0]):
        if not full:
            uidv, hs = gmail_rw.read_headers(None)
        last = max((h.uid for h in hs), default=0)
    else:
        last = max([h.uid for h in hs] + [state[1] if state else 0])
    repo.upsert_headers(db, hs, config.owner_name())
    repo.set_state(db, uidv, last)
    return hs


def _classify_all(db, today: date, fresh=(), rules=None) -> dict:
    """對每封未丟、還在信箱的信算樣式與判定並存檔。fresh（本次同步的信頭）蓋過 DB 讀回的版本。
    rules＝要用的已確認規則（None＝現在 DB 裡的）；歷史執行傳入已核對過指紋的那一份。"""
    over = {h.gm_msgid: h for h in fresh}
    hs = [over.get(h.gm_msgid, h) for h in repo.headers(db)]
    owner, selfs, comp = config.owner_name(), config.self_addresses(), config.company_domains()
    repo.add_valued(db, C.learn_valued_domains(hs, selfs, comp))
    valued = repo.valued_set(db)
    rules = repo.confirmed_rules(db) if rules is None else rules
    out = {}
    for h in hs:
        out[h.gm_msgid] = (h, C.classify(h, subject_pattern(h.subject, owner), rules, valued, selfs))
    repo.save_verdicts(db, {g: v for g, (_, v) in out.items()})
    return out


def _unknown_groups(db, verdicts: dict) -> dict:
    """{(from_addr, pattern): [header, ...]}：判定未知且還沒有任何規則（任何 status）的群組。"""
    owner, known = config.owner_name(), repo.known_keys(db)
    groups: dict = {}
    for h, v in verdicts.values():
        if v.category is not None:
            continue
        key = (h.from_addr, subject_pattern(h.subject, owner))
        if key not in known:
            groups.setdefault(key, []).append(h)
    return groups


def _suggest_unknown(db, verdicts: dict) -> list[str]:
    groups = _unknown_groups(db, verdicts)
    comp = config.company_domains()
    items, rest = [], []
    for (sender, pattern), hs in groups.items():
        cat = C.builtin_suggest(hs[0], pattern, comp)
        if cat:
            items.append((sender, pattern, cat, "builtin"))
        else:
            rest.append({"sender": sender, "name": hs[0].from_name, "pattern": pattern,
                         "subjects": [pattern][:5], "count": len(hs)})
    if rest:
        try:
            got = suggest.suggest(rest)
        except Exception as e:                       # AI 掛了不擋流程：只送內建建議，其餘留未知
            print(f"⚠️ mailrules suggest 失敗：{e}")
            got = {}
        for g in rest:
            cat = got.get((g["sender"], g["pattern"]))
            if cat in config.LABELS:
                items.append((g["sender"], g["pattern"], cat, _AI_BY))
    return repo.add_suggestions(db, items)


def _plan_all(db, verdicts: dict, today: date, mode: str) -> list:
    sts = repo.states(db)
    actions = []
    for gid, (h, v) in verdicts.items():
        st = sts.get(gid) or MessageState(in_inbox=h.in_inbox)
        actions += plan_actions(h, v, st, today, mode)
    return actions


def _execute(db, actions: list, cats: dict, report: RunReport, batch: int | None = None) -> None:
    """逐批 apply；每批做完的立刻記進 DB（後面的批次出事也不丟）。已不在信箱的信記 gone、不算失敗。"""
    step = batch or max(len(actions), 1)
    gone_ids: set[str] = set()
    for i in range(0, len(actions), step):
        done, failed, gone = gmail_rw.apply(actions[i:i + step])
        repo.record_actions(db, done)
        if gone:
            repo.mark_gone(db, sorted({a.gm_msgid for a in gone} - gone_ids))
            gone_ids |= {a.gm_msgid for a in gone}
        report.failed += len(failed)
        report.gone = len(gone_ids)
        for a in done:
            key = (cats.get(a.gm_msgid), a.kind)
            report.counts[key] = report.counts.get(key, 0) + 1


def run_daily(today: date, db=None) -> RunReport:
    """另一個信件整理正在跑 → 回傳 skipped 的報告（不同步、不寫入、不拋例外）。"""
    if not _LOCK.acquire(blocking=False):
        return RunReport(skipped=True)
    try:
        return _run_daily(today, db)
    finally:
        _LOCK.release()


def _run_daily(today: date, db=None) -> RunReport:
    with _session(db) as db:
        fresh = _sync(db)
        verdicts = _classify_all(db, today, fresh)
        new_cards = _suggest_unknown(db, verdicts)
        fresh_ids = {h.gm_msgid for h in fresh}
        report = RunReport(unknown_patterns=len(_unknown_groups(db, verdicts)), new_cards=list(new_cards),
                           protected=[h for g, (h, v) in verdicts.items() if v.protected and g in fresh_ids])
        state = repo.get_state(db)
        if state is None or state[2] is None:
            return report
        actions = _plan_all(db, verdicts, today, "daily")
        _execute(db, actions, {g: v.category for g, (_, v) in verdicts.items()}, report)
        report.applied = True
        report.job_digest = [h for g, (h, v) in verdicts.items() if g in fresh_ids and v.category == "jobs"]
        if today.weekday() == config.PROMO_DIGEST_DOW:
            since = today - timedelta(days=7)
            report.promo_digest = [h for h, v in verdicts.values()
                                   if v.category == "promo" and h.sent_date and h.sent_date >= since]
        return report


def prepare_history(today: date, db=None) -> int:
    with _exclusive(), _session(db) as db:
        fresh = _sync(db, full=True)          # 舊信的 unsub / 顯示名稱只有信頭有
        verdicts = _classify_all(db, today, fresh)
        _suggest_unknown(db, verdicts)
        return len(repo.pending_cards(db))


def history_plan(today: date, db=None) -> dict:
    """歷史計畫：各（類別, 動作）封數、每類 3 個不重複的範例主旨、待確認卡數、未知樣式數，
    upto_card（算計畫當下的最大確認卡號；執行鈕只被不大於它的卡擋），
    以及 fingerprint（算計畫用的已確認規則集合指紋；執行時規則集合變了就拒絕）。會寫 DB（判定）→ 也走鎖。"""
    with _exclusive(), _session(db) as db:
        rules = repo.confirmed_rules(db)
        verdicts = _classify_all(db, today, rules=rules)
        cats = {g: v.category for g, (_, v) in verdicts.items()}
        subjects = {g: h.subject for g, (h, _) in verdicts.items()}
        counts, samples, sampled = {}, {}, set()
        for a in _plan_all(db, verdicts, today, "history"):
            cat = cats.get(a.gm_msgid)
            counts[(cat, a.kind)] = counts.get((cat, a.kind), 0) + 1
            subs = samples.setdefault(cat, [])
            if a.gm_msgid in sampled or len(subs) >= 3:
                continue
            sampled.add(a.gm_msgid)
            if subjects[a.gm_msgid] not in subs:
                subs.append(subjects[a.gm_msgid])
        return {"counts": counts, "samples": samples, "pending_cards": len(repo.pending_cards(db)),
                "unknown": len(_unknown_groups(db, verdicts)), "upto_card": repo.max_card(db),
                "fingerprint": rules_fingerprint(rules)}


def execute_history(today: date, db=None, upto_card: str | None = None,
                    fingerprint: str | None = None) -> RunReport:
    """upto_card＝計畫卡發出當下的最大卡號（'none'＝當時沒有卡）：只有卡號不大於它的卡還沒處理才拒絕，
    之後才長出的卡不擋（它們的信是未知，本來就不會動）。None＝任何待確認卡都擋（原本行為）。
    fingerprint＝計畫卡上的已確認規則指紋：現在的規則集合不同（之後又確認卡、手動指定）→ 計畫已過期，
    零寫入拒絕。None＝不比對（程式內部呼叫）。"""
    with _exclusive(), _session(db) as db:
        state = repo.get_state(db)
        if state is not None and state[2] is not None:
            raise RuntimeError("歷史整理已完成，不能再用 history 模式重跑")
        pending = repo.pending_cards(db)
        if upto_card is not None:
            pending = [c for c in pending if card_no(c) <= card_no(upto_card)]
        if pending:
            raise RuntimeError(f"還有 {len(pending)} 張確認卡沒處理")
        if fingerprint is not None and rules_fingerprint(repo.confirmed_rules(db)) != fingerprint:
            raise RuntimeError(_EXPIRED)
        fresh = _sync(db, full=True)          # 寫入用的 UID 要是現在的；舊信的 unsub／顯示名稱也一併刷新
        rules = repo.confirmed_rules(db)      # 同步期間（不在鎖內的）確認鈕可能又改了規則 → 用的這一份要再核對一次
        if fingerprint is not None and rules_fingerprint(rules) != fingerprint:
            raise RuntimeError(_EXPIRED)
        verdicts = _classify_all(db, today, fresh, rules=rules)
        report = RunReport(unknown_patterns=len(_unknown_groups(db, verdicts)),
                           protected=[h for h, v in verdicts.values() if v.protected])
        actions = _plan_all(db, verdicts, today, "history")
        _execute(db, actions, {g: v.category for g, (_, v) in verdicts.items()}, report, config.BATCH_SIZE)
        repo.mark_history_done(db)
        report.applied = True
        return report
