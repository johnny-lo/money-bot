"""純函式：替清單上的未配對刷卡分組、附「同卡同金額」線索，讓使用者分得出哪些真的忘記。
刷卡金額與發票金額不會有差，金額不同就是不同消費，所以不拿帳上金額或時間相近的紀錄當線索。"""
from .types import Charge

GROUPS = [
    ("subscription", "疑似訂閱或固定扣款"),
    ("overseas", "海外消費"),
    ("small", "小額（≤100 元）"),
    ("other", "其他"),
]
_ORDER = [k for k, _ in GROUPS]


def repeat_months(c: Charge, all_charges: list[Charge]) -> int:
    months = {(x.charge_date.year, x.charge_date.month) for x in all_charges
              if x.card_last4 == c.card_last4 and x.amount == c.amount}
    months.add((c.charge_date.year, c.charge_date.month))
    return len(months)


def classify(c: Charge, repeats: int) -> str:
    if repeats >= 3:
        return "subscription"
    if c.region and c.region != "TW":
        return "overseas"
    if c.amount <= 100:
        return "small"
    return "other"


def hint_text(c: Charge, repeats: int) -> str | None:
    if repeats >= 3:
        return f"同卡同金額 {repeats} 個月都有"
    return None


def arrange(items: list[tuple[int, Charge]], all_charges: list[Charge]
            ) -> list[tuple[str, list[tuple[int, Charge, str | None]]]]:
    buckets: dict[str, list] = {k: [] for k in _ORDER}
    for cid, c in items:
        reps = repeat_months(c, all_charges)
        buckets[classify(c, reps)].append((cid, c, hint_text(c, reps)))
    return [(k, sorted(buckets[k], key=lambda x: (x[1].charge_date, x[0]))) for k in _ORDER if buckets[k]]
