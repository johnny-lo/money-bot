"""自動修復的決策核心——純函式，不碰 DB、不碰檔案。

狀態機：counting →(到門檻)→ dispatched → reported → deploying → resolved/failed
                                           └→ needs_human / inconclusive / abandoned（結案）
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

BUSY = {"dispatched", "reported", "deploying"}
CLOSED = {"resolved", "failed", "abandoned", "needs_human", "inconclusive"}
RECUR_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Policy:
    threshold: int                 # 需要幾個不同的去重鍵
    window: timedelta | None       # 命中只算最近這段時間；None＝不限（連續性靠感測器 clear 歸零）


POLICIES = {
    "einvoice_login": Policy(3, None),              # 3 個不同台北日曆日
    "scheduler_job": Policy(3, None),               # 連 3 次（成功一次就 clear）
    "link_extract": Policy(3, timedelta(days=7)),   # 7 天內 3 條不同網址
    "drill": Policy(1, None),                       # 演習：一觸即發
}


@dataclass(frozen=True)
class Snapshot:
    status: str
    hit_keys: list
    closed_at: datetime | None


@dataclass(frozen=True)
class Decision:
    action: str      # noop / new / count / dispatch / escalate
    hit_keys: list


def _prune(hit_keys: list, now: datetime, window: timedelta | None) -> list:
    if window is None:
        return list(hit_keys)
    keep = []
    for key, ts in hit_keys:
        try:
            if now - datetime.fromisoformat(ts) <= window:
                keep.append([key, ts])
        except (TypeError, ValueError):
            continue
    return keep


def decide(latest: Snapshot | None, key: str, now: datetime, policy: Policy) -> Decision:
    """latest＝這個 (sensor, signature) 最新一筆事件。"""
    fresh = [[key, now.isoformat()]]
    if latest is not None:
        if latest.status in BUSY:
            return Decision("noop", latest.hit_keys)
        if latest.status == "counting":
            keys = _prune(latest.hit_keys, now, policy.window)
            if key not in [k for k, _ in keys]:
                keys.append([key, now.isoformat()])
            return Decision("dispatch" if len(keys) >= policy.threshold else "count", keys)
        if latest.closed_at is not None and now - latest.closed_at < RECUR_WINDOW:
            # 修好才 7 天又壞＝上次修正無效 → 升級人工（只升一次：新事件本身就是 needs_human，之後走冷卻）
            if latest.status == "resolved":
                return Decision("escalate", fresh)
            return Decision("noop", latest.hit_keys)
    return Decision("dispatch" if policy.threshold <= 1 else "new", fresh)


def merge_context(old: dict, new: dict, cap: int = 10) -> dict:
    """清單取聯集（保序、只留最後 cap 個），其他鍵新值覆蓋。"""
    out = dict(old or {})
    for k, v in (new or {}).items():
        if isinstance(v, list) and isinstance(out.get(k), list):
            merged = list(out[k])
            for item in v:
                if item not in merged:
                    merged.append(item)
            out[k] = merged[-cap:]
        else:
            out[k] = v
    return out
