import json
from database import SessionLocal
from models import Transaction
from gemini import gemini_text


def run_weekly_categorization():
    """撈出所有未分類的帳目，交給 AI 批次分類後寫回資料庫。回傳結果訊息字串。"""
    db = SessionLocal()
    try:
        uncategorized = db.query(Transaction).filter(
            Transaction.category.is_(None)
        ).all()

        if not uncategorized:
            print("📋 週分類：沒有未分類的帳目，跳過。")
            return "📋 目前沒有未分類的帳目，不需要分類。"

        # 組裝帳目清單給 AI
        items_list = "\n".join(
            [f"ID:{t.id} | {t.item} | {t.price}元" for t in uncategorized]
        )

        # 撈出已有的分類當作參考，讓 AI 保持一致性
        existing_categories = db.query(Transaction.category).filter(
            Transaction.category.isnot(None)
        ).distinct().all()
        cat_hint = ""
        if existing_categories:
            cats = ", ".join([c[0] for c in existing_categories])
            cat_hint = f"\n目前資料庫中已使用過的分類有：{cats}\n請盡量沿用這些分類名稱以保持一致性，除非某筆帳目確實不屬於任何現有分類才建立新的。"

        prompt = (
            f"你是一個記帳分類助手。請幫以下每一筆消費記錄分類。{cat_hint}\n\n"
            f"帳目清單：\n{items_list}\n\n"
            f"請嚴格只回傳 JSON 陣列格式，每個元素包含 id 和 category 兩個欄位。\n"
            f"分類請用簡短的中文（例如：飲食、交通、娛樂、日用品、醫療、服飾、3C、居住、教育、社交等）。\n"
            f"格式範例：\n"
            f'[{{"id": 1, "category": "飲食"}}, {{"id": 2, "category": "交通"}}]\n'
            f"不要包含任何其他文字或 Markdown 標籤。"
        )

        result_text = gemini_text(prompt).strip()

        # 清掉可能的 Markdown 標籤
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]

        categories_data = json.loads(result_text.strip())

        updated_count = 0
        for item in categories_data:
            record_id = item.get("id")
            category = item.get("category", "").strip()
            if record_id and category:
                record = db.query(Transaction).filter(Transaction.id == record_id).first()
                if record and record.category is None:
                    record.category = category
                    updated_count += 1

        db.commit()
        msg = f"✅ AI 分類完成：{updated_count}/{len(uncategorized)} 筆已分類"
        print(msg)
        return msg

    except Exception as e:
        db.rollback()
        msg = f"💥 分類失敗：{e}"
        print(msg)
        return msg
    finally:
        db.close()
