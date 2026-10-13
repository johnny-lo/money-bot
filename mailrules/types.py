"""mailrules 各層之間的資料契約（無 I/O）。"""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class MailHeader:
    gm_msgid: str                 # Gmail X-GM-MSGID（跨資料夾不變）
    uid: int                      # 「所有郵件」資料夾內的 UID
    from_addr: str                # 小寫
    from_name: str
    subject: str
    sent_date: date | None
    labels: tuple[str, ...]       # 已解碼的 X-GM-LABELS
    unsub: bool                   # 有 List-Unsubscribe
    in_inbox: bool


@dataclass(frozen=True)
class Rule:
    id: int | None
    sender: str                   # 完整地址 'a@b.com' 或網域 '@b.com'
    subject_pattern: str          # '*' = 任何主旨
    category: str
    status: str                   # 'suggested' | 'confirmed' | 'rejected'
    suggested_by: str             # 'builtin' | 'ai' | 'user'
    card: str | None = None       # 出現在哪張確認卡（只增不減的卡號）


@dataclass(frozen=True)
class ValuedDomain:
    domain: str                   # 重視的公司網域（安全網第 2 條）
    pattern: str | None           # 當初學到它的主旨樣式
    status: str                   # 'pending' | 'confirmed' | 'rejected'；只有 confirmed 會保護信
    card: str | None = None       # 出現在哪張重視公司確認卡（'v<N>'，只增不減）


@dataclass(frozen=True)
class Verdict:
    category: str | None          # None = 未知
    reason: str
    protected: bool               # 安全網命中


@dataclass(frozen=True)
class Action:
    gm_msgid: str
    uid: int
    kind: str                     # 'label' | 'archive' | 'trash'
    label: str | None = None


@dataclass(frozen=True)
class MessageState:
    in_inbox: bool
    labels_applied: frozenset = frozenset()
    trashed: bool = False


@dataclass
class RunReport:
    counts: dict = field(default_factory=dict)        # {(category, kind): n}
    protected: list = field(default_factory=list)     # list[MailHeader]
    unknown_patterns: int = 0
    failed: int = 0
    gone: int = 0                                     # 所有郵件已找不到的信（封數，略過不算失敗）
    job_digest: list = field(default_factory=list)    # list[MailHeader]
    promo_digest: list = field(default_factory=list)  # list[MailHeader]
    applied: bool = False                             # 歷史未完成前每日只分類不寫入 → False
    new_cards: list = field(default_factory=list)     # 本次新開的確認卡號
    skipped: bool = False                             # 另一個信件整理正在跑，這次整個略過
