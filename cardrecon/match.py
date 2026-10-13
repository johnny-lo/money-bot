"""純函式：刷卡 × 帳目群組的一對一配對，與收據補店名。"""
from datetime import datetime, time
from itertools import combinations

from . import config
from .types import Charge, Receipt, TxGroup

OFFSETS = (0, 1, -1, 2, 3)          # tx_date − charge_date，依序嘗試
_RECEIPT_OFFSETS = (0, -1, 1)       # paid_date − charge_date


def charge_at(c: Charge) -> datetime | None:
    """刷卡日期＋時間（永豐才有 HH:MM）；沒有或格式不對回 None。"""
    if not c.charge_time:
        return None
    try:
        hh, mm = (int(x) for x in c.charge_time.split(":"))
        return datetime.combine(c.charge_date, time(hh, mm))
    except ValueError:
        return None


def minutes_apart(at: datetime, grp) -> float | None:
    """刷卡時刻與群組（TxGroup／TxHint）開立時刻差幾分鐘（含跨午夜）；群組沒時間回 None。"""
    if grp.tx_time is None:
        return None
    return abs((datetime.combine(grp.tx_date, grp.tx_time) - at).total_seconds()) / 60


def _in_window(at: datetime, grps) -> list[tuple[float, str, TxGroup]]:
    """時間窗內的群組，依 (分鐘差, key) 排好。"""
    out = []
    for grp in grps:
        gap = minutes_apart(at, grp)
        if gap is not None and gap <= config.TIME_WINDOW_MIN:
            out.append((gap, grp.key, grp))
    return sorted(out, key=lambda x: x[:2])


def _split(amount: int, at: datetime, grps: list[TxGroup]) -> list[str] | None:
    """時間窗內 2～MAX_SPLIT 張發票合計剛好等於刷卡金額（同一刻分開結帳）。張數少的優先。"""
    near = [grp for _, _, grp in _in_window(at, grps) if grp.amount > 0]
    for k in range(2, config.MAX_SPLIT + 1):
        for combo in combinations(near, k):
            if sum(grp.amount for grp in combo) == amount:
                return sorted(grp.key for grp in combo)
    return None


def match(charges: list[tuple[int, Charge]], groups: list[TxGroup]) -> dict[int, str]:
    """有刷卡時間的先用時間對發票（單張同金額 → 多張合計），全部對完才輪到日期差；
    沒時間的刷卡（中信）、沒時間的群組（手記帳、舊發票）只走日期差，跟原本一樣。"""
    by_amount: dict[int, list[TxGroup]] = {}
    for grp in groups:
        by_amount.setdefault(grp.amount, []).append(grp)
    used, out = set(), {}
    ordered = sorted(charges, key=lambda x: (x[1].charge_date, x[0]))
    timed = [(cid, c, at) for cid, c in ordered if (at := charge_at(c)) is not None]
    for cid, c, at in timed:
        near = _in_window(at, [grp for grp in by_amount.get(c.amount, ()) if grp.key not in used])
        if near:
            out[cid] = near[0][1]
            used.add(near[0][1])
    for cid, c, at in timed:
        if cid in out:
            continue
        keys = _split(c.amount, at, [grp for grp in groups if grp.key not in used])
        if keys:
            out[cid] = config.KEY_SEP.join(keys)
            used.update(keys)
    for cid, c in ordered:
        if cid in out:
            continue
        cands = [grp for grp in by_amount.get(c.amount, ()) if grp.key not in used]
        for off in OFFSETS:
            hit = next((grp for grp in cands if (grp.tx_date - c.charge_date).days == off), None)
            if hit:
                out[cid] = hit.key
                used.add(hit.key)
                break
    return out


def _same_card(r: Receipt, c: Charge) -> bool:
    """收據與刷卡都有卡號且不同才算別張卡；任一邊沒卡號（Autopass）就不擋。"""
    return not (r.card_last4 and c.card_last4 and r.card_last4 != c.card_last4)


def enrich(charges: list[tuple[int, Charge]], receipts: list[Receipt]) -> dict[int, str]:
    used, out = set(), {}
    for cid, c in sorted(charges, key=lambda x: (x[1].charge_date, x[0])):
        if c.merchant:
            continue
        for off in _RECEIPT_OFFSETS:
            idx = next((i for i, r in enumerate(receipts)
                        if i not in used and r.amount == c.amount and (r.paid_date - c.charge_date).days == off
                        and _same_card(r, c)), None)
            if idx is not None:
                out[cid] = receipts[idx].merchant
                used.add(idx)
                break
    return out


def group_transactions(rows: list[tuple[int, str | None, datetime, int]]) -> list[TxGroup]:
    """同一張發票的品項加總成一組（含折扣負數行），手記帳一筆一組（key＝id<id>）。
    發票的 created_at 不是 00:00 才算有開立時間；手記帳的 created_at 是記帳時間，一律不帶。"""
    acc: dict[str, list] = {}
    for tid, inv, created, price in rows:
        key = inv or f"id{tid}"
        d = created.date()
        if key not in acc:
            acc[key] = [d, 0, None]
        acc[key][0] = min(acc[key][0], d)
        acc[key][1] += price or 0
        if inv and acc[key][2] is None and created.time() != time():
            acc[key][2] = created.time()
    return [TxGroup(key=k, tx_date=v[0], amount=v[1], tx_time=v[2]) for k, v in acc.items()]
