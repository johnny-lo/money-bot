"""類別、保留期限、安全網字眼與本人設定（本人相關值只從環境變數讀，不進 repo）。"""
import os
import re
from dataclasses import dataclass

LABEL_ROOT = "整理"
FINANCE_KEEP_DAYS = 730          # 刷卡扣款、收據訂單、帳單：滾動保留天數（2 年）
BATCH_SIZE = 500                 # 歷史執行每批封數
DAILY_RUN = (23, 30)             # 每日執行時間（台北；在發票同步 21:00 之後）
PROMO_DIGEST_DOW = 6             # 週日（date.weekday()）

CATEGORIES = [
    ("keep_inbox", "重要（真人／求職）"),
    ("security", "安全警示"),
    ("self", "寄給自己"),
    ("tax", "稅務／保單／薪資"),
    ("school", "學校"),
    ("card", "刷卡／扣款／轉帳通知"),
    ("receipt", "收據／訂單／出貨"),
    ("bill", "帳單／對帳單"),
    ("travel", "旅遊／交通"),
    ("company", "公司系統通知"),
    ("jobs", "職缺推薦"),
    ("social", "LinkedIn 社群通知"),
    ("login", "登入／驗證碼"),
    ("promo", "推銷／電子報"),
]
LABELS = dict(CATEGORIES)


@dataclass(frozen=True)
class Retention:
    label: str | None = None               # 要加的標籤（school 由 plan 依網域加子層）
    archive_after_days: int | None = None  # 信件日期起幾天後移出收件匣
    trash_after_days: int | None = None    # 幾天後丟垃圾桶（優先於 archive）
    digest: str | None = None              # 'daily' | 'weekly'


RETENTION = {
    "keep_inbox": Retention(),
    "security": Retention(label=f"{LABEL_ROOT}/安全警示", archive_after_days=7),
    "self": Retention(label=f"{LABEL_ROOT}/寄給自己", archive_after_days=0),
    "tax": Retention(label=f"{LABEL_ROOT}/稅務保單", archive_after_days=0),
    "school": Retention(label=f"{LABEL_ROOT}/學校", archive_after_days=0),
    "card": Retention(label=f"{LABEL_ROOT}/刷卡扣款", archive_after_days=0, trash_after_days=FINANCE_KEEP_DAYS),
    "receipt": Retention(label=f"{LABEL_ROOT}/收據", archive_after_days=0, trash_after_days=FINANCE_KEEP_DAYS),
    "bill": Retention(label=f"{LABEL_ROOT}/帳單", archive_after_days=0, trash_after_days=FINANCE_KEEP_DAYS),
    "travel": Retention(label=f"{LABEL_ROOT}/旅遊", archive_after_days=0, trash_after_days=180),
    "company": Retention(archive_after_days=0, trash_after_days=30),
    "jobs": Retention(archive_after_days=0, trash_after_days=14, digest="daily"),
    "social": Retention(trash_after_days=0),
    "login": Retention(trash_after_days=0),
    "promo": Retention(archive_after_days=0, trash_after_days=14, digest="weekly"),
}

JOB_KEYWORDS = re.compile(
    r"面試|面談|應徵|邀請|邀約|錄取|聘任|聘書|到職|報到|二面|複試|評量|測驗|個人資料填寫|"
    r"offer|interview|application status|recruit", re.I)
# 安全網第 2 條只從「強」字眼學網域（弱字眼只保護那一封，見上面的 JOB_KEYWORDS）：
# 「邀請／報到／測驗」也常見於行銷信（生日邀請函、邀請朋友、報到通知），拿來學網域會把整個網域留下
STRONG_JOB_KEYWORDS = re.compile(
    r"面試|面談|錄取|錄用|複試|二面|到職|聘書|聘任|interview|job offer|offer letter|application status", re.I)
SCHOOL_SUFFIXES = (".edu", ".edu.tw")
SYSTEM_LOCALPART = re.compile(
    r"no[-_.]?reply|do[-_.]?not[-_.]?reply|service|news|info|notif|edm|mailer|system|support|alert|"
    r"marketing|promo|update|account|security|billing|bill|invoice|order|receipt|bounce|admin|team|hello|"
    r"contact|member|customer|cs$|^cs\b|ebill|statement", re.I)
JOB_BOARD_DOMAINS = ("linkedin.com", "104.com.tw", "1111.com.tw", "cakeresume.com", "yourator.co")
FREEMAIL_DOMAINS = ("gmail.com", "yahoo.com", "yahoo.com.tw", "hotmail.com", "outlook.com",
                    "icloud.com", "msn.com", "live.com")


def _csv_env(name: str) -> set[str]:
    return {x.strip().lower() for x in (os.getenv(name) or "").split(",") if x.strip()}


def owner_name() -> str:
    return (os.getenv("MAIL_OWNER_NAME") or "").strip()


def self_addresses() -> set[str]:
    return _csv_env("MAIL_SELF_ADDRESSES")


def company_domains() -> set[str]:
    return _csv_env("MAIL_COMPANY_DOMAINS")


def mail_channel_id() -> int | None:
    v = (os.getenv("MAIL_CHANNEL_ID") or "").strip()
    return int(v) if v.isdigit() else None
