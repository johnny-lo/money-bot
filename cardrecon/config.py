"""刷卡比對的常數。"""
from datetime import date

LIST_FROM = date(2026, 4, 21)   # 開始用載具記帳的那一天；更早的刷卡不列
LOOKBACK_DAYS = 60              # 每週回看幾天的信（中信月帳單最晚約 40 天後才到）
LIST_LAG_DAYS = 3               # 刷卡 3 天後才列，等發票補拓追上
PAGE_SIZE = 25                  # 一張卡幾筆（= Discord 下拉選單上限）

# source → (寄件者, 主旨關鍵字)。DAWHO（mma@sinopac.com）是繳卡費，刻意不列。
CARD_SOURCES = {
    "sinopac_daily": ("spendservice@sinopac.com", "消費通知"),
    "ctbc_statement": ("ebill@estats.ctbcbank.com", "信用卡電子帳單"),
}
# 收據來源：(寄件者, 主旨關鍵字, parse.RECEIPT_PARSERS 的鍵)。收據只用來替同金額的刷卡補店名。
RECEIPT_SOURCES = [
    ("cs@autopass.xyz", "停車訂單收據", "autopass"),
    ("CardAuthService@sinopac.com", "網路消費通知", "sinopac_online"),
]
OCR_BATCH = 25                  # 中信店名格一次讀幾行（codex 讀圖每張超過 25 行會漏行）
BRAND_BATCH = 40                # 店名換品牌一次問幾個
TIME_WINDOW_MIN = 10            # 刷卡時間與發票開立時間相差幾分鐘內算同一筆（永豐才有刷卡時間）
MAX_SPLIT = 4                   # 一筆刷卡最多由幾張發票合計（同一刻分開結帳）
KEY_SEP = "+"                   # 一筆刷卡配到多張發票時，card_charges.matched_key 用它串起來
LINE_SOURCE = "ctbc_line"       # 中信 LINE 即時通知寫進 card_charges 的來源
# 同一筆刷卡會從兩個來源各來一次：後到的那列存成 merged、指回先到的那列（見 repo.upsert_charges）
MERGE_PAIRS = {"ctbc_line": "ctbc_statement", "ctbc_statement": "ctbc_line"}
MERGE_SLACK_DAYS = 1            # 同日找不到時，刷卡日最多差幾天還算同一筆
