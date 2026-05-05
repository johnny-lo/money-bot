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

        prompt = (
            f"你是一個記帳分類助手。請幫以下每一筆消費記錄分類。\n\n"
            f"帳目清單：\n{items_list}\n\n"
            f"請嚴格只回傳 JSON 陣列格式，每個元素包含 id 和 category 兩個欄位。\n"
            f"分類請從以下選一個：三餐、飲料、零食、食材、油費、停車、居家用品、個人保養、醫療、服飾、娛樂、其他。\n"
            f"判斷原則：\n"
            f"- 三餐 = 正餐外食（午晚餐、便當、餐廳、麵店）\n"
            f"- 飲料 = 咖啡、手搖、罐裝飲料、茶、豆漿、果汁\n"
            f"- 零食 = 餅乾、甜點、糖果、零嘴\n"
            f"- 食材 = 自煮的菜、肉、蛋、奶、麵、起司、即食麵\n"
            f"- 油費 = 加油、加油站\n"
            f"- 停車 = 停車費\n"
            f"- 居家用品 = 收納、清潔、家電、燈泡、紙巾、擴香、洗衣服務\n"
            f"- 個人保養 = 隱形眼鏡、衛生用品、保養品\n"
            f"- 醫療 = 看醫生、藥局處方\n"
            f"- 服飾 = 衣服、鞋、配件\n"
            f"- 娛樂 = 健身、按摩、休閒運動\n"
            f"- 其他 = 確實無法歸類\n"
            f"格式範例：\n"
            f'[{{"id": 1, "category": "三餐"}}, {{"id": 2, "category": "飲料"}}]\n'
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
