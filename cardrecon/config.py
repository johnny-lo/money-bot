"""刷卡比對的常數。"""
from datetime import date

LIST_FROM = date(2026, 2, 22)   # 帳目最早一天；更早的刷卡沒有帳可比，不列
LOOKBACK_DAYS = 60              # 每週回看幾天的信（中信月帳單最晚約 40 天後才到）
LIST_LAG_DAYS = 3               # 刷卡 3 天後才列，等發票補拓追上
PAGE_SIZE = 25                  # 一張卡幾筆（= Discord 下拉選單上限）

# source → (寄件者, 主旨關鍵字)。DAWHO（mma@sinopac.com）是繳卡費，刻意不列。
CARD_SOURCES = {
    "sinopac_daily": ("spendservice@sinopac.com", "消費通知"),
    "ctbc_statement": ("ebill@estats.ctbcbank.com", "信用卡電子帳單"),
}
RECEIPT_SOURCES = [("cs@autopass.xyz", "停車訂單收據")]
