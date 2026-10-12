"""純函式：刷卡 × 帳目群組的一對一配對，與收據補店名。"""
from datetime import datetime

from .types import Charge, Receipt, TxGroup

OFFSETS = (0, 1, -1, 2, 3)          # tx_date − charge_date，依序嘗試
_RECEIPT_OFFSETS = (0, -1, 1)       # paid_date − charge_date


def match(charges: list[tuple[int, Charge]], groups: list[TxGroup]) -> dict[int, str]:
    by_amount: dict[int, list[TxGroup]] = {}
    for grp in groups:
        by_amount.setdefault(grp.amount, []).append(grp)
    used, out = set(), {}
    for cid, c in sorted(charges, key=lambda x: (x[1].charge_date, x[0])):
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
    """同一張發票的品項加總成一組（含折扣負數行），手記帳一筆一組（key＝id<id>）。"""
    acc: dict[str, list] = {}
    for tid, inv, created, price in rows:
        key = inv or f"id{tid}"
        d = created.date()
        if key not in acc:
            acc[key] = [d, 0]
        acc[key][0] = min(acc[key][0], d)
        acc[key][1] += price or 0
    return [TxGroup(key=k, tx_date=v[0], amount=v[1]) for k, v in acc.items()]
