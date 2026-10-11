"""純函式：替清單上的未配對刷卡找帳上的近似紀錄、分組，讓使用者分得出哪些真的忘記。"""
from .types import Charge, TxHint

GROUPS = [
    ("near", "可能記過（帳上有近似紀錄）"),
    ("subscription", "疑似訂閱或固定扣款"),
    ("overseas", "海外消費"),
    ("small", "小額（≤100 元）"),
    ("other", "其他"),
]
_ORDER = [k for k, _ in GROUPS]


def near_miss(c: Charge, txs: list[TxHint]) -> TxHint | None:
    tol = max(10, round(0.1 * c.amount))
    cands = [t for t in txs
             if abs((t.tx_date - c.charge_date).days) <= 1 and t.amount > 0
             and t.amount != c.amount and abs(t.amount - c.amount) <= tol]
    return min(cands, key=lambda t: (abs(t.amount - c.amount), abs((t.tx_date - c.charge_date).days), t.key),
               default=None)


def repeat_months(c: Charge, all_charges: list[Charge]) -> int:
    months = {(x.charge_date.year, x.charge_date.month) for x in all_charges
              if x.card_last4 == c.card_last4 and x.amount == c.amount}
    months.add((c.charge_date.year, c.charge_date.month))
    return len(months)


def classify(c: Charge, near: TxHint | None, repeats: int) -> str:
    if near is not None:
        return "near"
    if repeats >= 3:
        return "subscription"
    if c.region and c.region != "TW":
        return "overseas"
    if c.amount <= 100:
        return "small"
    return "other"


def hint_text(c: Charge, near: TxHint | None, repeats: int) -> str | None:
    if near is not None:
        return (f"≈ 帳上 {near.tx_date:%m/%d} {near.label or '（無品名）'} ${near.amount:,}"
                f"（差 ${abs(near.amount - c.amount):,}）")
    if repeats >= 3:
        return f"同卡同金額 {repeats} 個月都有"
    return None


def arrange(items: list[tuple[int, Charge]], txs: list[TxHint],
            all_charges: list[Charge]) -> list[tuple[str, list[tuple[int, Charge, str | None]]]]:
    buckets: dict[str, list] = {k: [] for k in _ORDER}
    for cid, c in items:
        near = near_miss(c, txs)
        reps = repeat_months(c, all_charges)
        buckets[classify(c, near, reps)].append((cid, c, hint_text(c, near, reps)))
    return [(k, sorted(buckets[k], key=lambda x: (x[1].charge_date, x[0]))) for k in _ORDER if buckets[k]]
