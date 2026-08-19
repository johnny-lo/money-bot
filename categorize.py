import json
from database import SessionLocal
from models import Transaction
from codex_cli import codex_text


# 15 細類（封閉清單，AI 必須從這裡選一個）
CATEGORIES = [
    "居住水電",
    "分期保險",
    "交通",
    "三餐",
    "聚餐",
    "飲料零食",
    "食材",
    "超商",
    "日用品",
    "家電3C",
    "醫療",
    "服飾",
    "娛樂",
    "投資",
    "其他",
]

# 細類 → 大組
CATEGORY_GROUPS: dict[str, str] = {
    "居住水電": "固定",
    "分期保險": "固定",
    "交通":     "交通",
    "三餐":     "飲食",
    "聚餐":     "飲食",
    "飲料零食": "飲食",
    "食材":     "飲食",
    "超商":     "飲食",
    "日用品":   "生活",
    "家電3C":   "生活",
    "醫療":     "生活",
    "服飾":     "生活",
    "娛樂":     "娛樂",
    "投資":     "投資",
    "其他":     "其他",
}

# 大組顯示順序
GROUP_ORDER = ["固定", "交通", "飲食", "生活", "娛樂", "投資", "其他"]


CATEGORIZE_RULES = """請依下列規則分類，每筆從這 15 類選一個：
- 居住水電 = 房租、管理費、電費、水費、瓦斯
- 分期保險 = 車貸、手機分期、其他貸款攤提、車險、人壽險、意外險（健保自付歸醫療）
- 交通     = 加油、油費、停車費、車輛保養、洗車、ETC、捷運/客運/高鐵
- 三餐     = 正餐外食（午晚餐、便當、麵店、一般餐廳；單筆通常 1500 元以下）
- 聚餐     = 家人/朋友聚餐、請客、宴客、大額餐廳消費（單筆通常超過 1500 元）
- 飲料零食 = 咖啡、手搖、罐裝飲料、茶、豆漿、果汁、餅乾、甜點、糖果、零嘴
- 食材     = 自煮材料（生鮮、蔬菜、肉品、蛋、奶、麵條、起司、調味料、即食麵）
- 超商     = 萊爾富、7-11、全家、OK 等超商只有店名看不出品項的發票
- 日用品   = 消耗品：收納、清潔、燈泡、紙巾、擴香、洗衣服務、隱形眼鏡、衛生用品、保養品
- 家電3C   = 耐久財：電視、冰箱、洗衣機、冷氣、手機、電腦、平板、耳機、相機、鍵盤滑鼠
            （跟日用品的差別是「用好幾年」而不是「用完就沒了」，金額通常也大得多）
- 醫療     = 看醫生、藥局處方、健保自付
- 服飾     = 衣服、鞋、配件、包包
- 娛樂     = 健身、按摩、休閒運動、訂閱服務、遊戲、影音
- 投資     = 股票、ETF、基金、定期定額、證券扣款、複委託、債券（保險與儲蓄險歸分期保險，那是義務不是投資）
- 其他     = 確實兜不到任何一類"""


def _categorize_batch(items: list[Transaction]) -> dict[int, str]:
    """送一批帳目給 AI，回傳 {id: category}。category 不在封閉清單者剔除。"""
    items_list = "\n".join(f"ID:{t.id} | {t.item} | {t.price}元" for t in items)
    prompt = (
        f"你是一個記帳分類助手。請幫以下每一筆消費記錄分類。\n\n"
        f"帳目清單：\n{items_list}\n\n"
        f"{CATEGORIZE_RULES}\n\n"
        f"請嚴格只回傳 JSON 陣列格式，每個元素包含 id 和 category 兩個欄位。\n"
        f'範例：[{{"id": 1, "category": "三餐"}}, {{"id": 2, "category": "飲料零食"}}]\n'
        f"不要包含任何其他文字或 Markdown 標籤。"
    )
    result_text = codex_text(prompt).strip()
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
    data = json.loads(result_text.strip())
    out: dict[int, str] = {}
    for item in data:
        rid = item.get("id")
        cat = (item.get("category") or "").strip()
        if rid and cat in CATEGORIES:
            out[int(rid)] = cat
    return out


def _run_categorization(targets: list[Transaction], db) -> str:
    """對一組 Transaction 分批跑 AI 分類並寫回 DB。"""
    if not targets:
        return "📋 沒有要分類的帳目，跳過。"
    BATCH = 50
    updated = 0
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i + BATCH]
        try:
            mapping = _categorize_batch(batch)
        except Exception as e:
            print(f"💥 第 {i // BATCH + 1} 批分類失敗：{e}")
            continue
        for record in batch:
            cat = mapping.get(record.id)
            if cat:
                record.category = cat
                updated += 1
    db.commit()
    return f"✅ AI 分類完成：{updated}/{len(targets)} 筆已分類"


def run_weekly_categorization() -> str:
    """撈出所有未分類（category IS NULL）的帳目並分類。每週日排程呼叫。"""
    db = SessionLocal()
    try:
        uncategorized = db.query(Transaction).filter(
            Transaction.category.is_(None)
        ).all()
        if not uncategorized:
            print("📋 週分類：沒有未分類的帳目，跳過。")
            return "📋 目前沒有未分類的帳目，不需要分類。"
        msg = _run_categorization(uncategorized, db)
        print(msg)
        return msg
    except Exception as e:
        db.rollback()
        msg = f"💥 分類失敗：{e}"
        print(msg)
        return msg
    finally:
        db.close()


def run_full_recategorization() -> str:
    """清掉所有 category 後重新分類所有歷史帳目。改規則時手動觸發。"""
    db = SessionLocal()
    try:
        all_records = db.query(Transaction).all()
        for r in all_records:
            r.category = None
        db.commit()
        msg = _run_categorization(all_records, db)
        print(f"🔁 全量重跑：{msg}")
        return msg
    except Exception as e:
        db.rollback()
        msg = f"💥 全量分類失敗：{e}"
        print(msg)
        return msg
    finally:
        db.close()


def category_group(category: str | None) -> str:
    """細類 → 大組。未知或 None → 其他。"""
    return CATEGORY_GROUPS.get(category or "", "其他")
