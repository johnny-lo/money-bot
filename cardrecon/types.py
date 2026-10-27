"""cardrecon 各層之間的資料契約（無 I/O）。"""
from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class Charge:
    source: str                      # "sinopac_daily" | "ctbc_statement" | "ctbc_line"
    card_last4: str
    charge_date: date
    amount: int                      # 台幣整數，> 0
    line_no: int                     # 該封信內的序號（0 起）；與 message_id 合為唯一鍵
    charge_time: str | None = None   # "23:12"（永豐才有）
    post_date: date | None = None    # 入帳日（中信才有）
    region: str | None = None
    merchant: str | None = None
    pay_method: str | None = None    # 中信帳單的行動支付代碼（"A" 等）；中信 LINE 通知的「交易類型」
    merchant_type: str | None = None # 中信 LINE 通知的「商店類型」（網路消費沒有店名時才有）


@dataclass(frozen=True)
class Receipt:
    paid_date: date
    amount: int
    merchant: str
    card_last4: str | None = None    # 收據寫了卡號才有（永豐網路消費通知）；Autopass 沒有


@dataclass(frozen=True)
class TxGroup:
    key: str                         # invoice_no，或手記帳 "id<transaction.id>"
    tx_date: date
    amount: int
    # 發票開立時間：只有載具發票、且 created_at 不是 00:00 才有；手記帳是記帳時間不是消費時間，一律 None。
    # 群組身分由 key／日期／金額決定，時間只是比對線索，不參與相等比較。
    tx_time: time | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Bitmap:
    """1-bit 圖片（中信帳單的店名格）。每列補齊到整數位元組，PDF 與 PBM 同款。"""
    width: int
    height: int
    data: bytes
    one_is_black: bool


@dataclass(frozen=True)
class RawMail:
    message_id: str
    sender: str
    subject: str
    received: date | None
    pdf: bytes | None
    text: str


@dataclass
class WeeklyResult:
    pages: list = field(default_factory=list)   # list[tuple[str, str, list[tuple[int, Charge, str | None]]]]（batch, 組別 key, 該頁項目 (id, Charge, 線索)）
    total: int = 0
    failed_mails: int = 0                       # 解密失敗
    unparsed_mails: int = 0                     # 沒附件或解析 0 筆


@dataclass(frozen=True)
class RecordResult:
    recorded: int        # 這次補記幾筆
    total: int           # 補記金額合計
    matched: int         # 補記前重比、發現已有帳而改成 matched 的筆數
