import re
import json
from datetime import datetime
from sqlalchemy import func
from database import SessionLocal
from models import Transaction, Income, RecurringRecord
from gemini import gemini_image, generate_persona_comment
from categorize import run_weekly_categorization
from auth import generate_report_token

# 擷取指令的正規表達式
PATTERN = re.compile(r"^(.+)\s+(\d+)$")
PATTERN_DELETE = re.compile(r"^刪除\s+(\d+)$")
PATTERN_UPDATE = re.compile(r"^修改\s+(\d+)\s+(.+)\s+(\d+)$")
PATTERN_INCOME = re.compile(r"^收入\s+(.+)\s+(\d+)$")
PATTERN_INCOME_DELETE = re.compile(r"^刪除收入\s+(\d+)$")
PATTERN_INCOME_UPDATE = re.compile(r"^修改收入\s+(\d+)\s+(.+)\s+(\d+)$")
PATTERN_RECURRING = re.compile(r"^固定\s+(支出|收入)\s+(.+)\s+(\d+)\s+(\d+)$")
PATTERN_RECURRING_DELETE = re.compile(r"^取消固定\s+(\d+)$")
PATTERN_FETCH_INVOICE = re.compile(r"^抓發票(?:\s+(\d+))?$")

HELP_TEXT = (
    "📖 【指令說明】\n"
    "\n"
    "💸 記支出：\n"
    "　午餐 150\n"
    "　（多筆可換行輸入）\n"
    "\n"
    "💰 記收入：\n"
    "　收入 薪水 50000\n"
    "\n"
    "🔍 查詢：\n"
    "　查詢 → 本月收支總覽\n"
    "　最近 → 最近 5 筆紀錄\n"
    "　報表 → 互動式圖表報表\n"
    "\n"
    "✏️ 修改：\n"
    "　修改 ID 新品名 新金額\n"
    "　修改收入 ID 新品名 新金額\n"
    "\n"
    "🗑️ 刪除：\n"
    "　刪除 ID\n"
    "　刪除收入 ID\n"
    "\n"
    "🏷️ 分類：\n"
    "　分類 → 手動觸發 AI 分類\n"
    "\n"
    "🧾 發票：\n"
    "　抓發票 → 抓今天的發票\n"
    "　抓發票 7 → 抓近 7 天\n"
    "\n"
    "🔄 固定收支：\n"
    "　固定 支出 房租 15000 1\n"
    "　固定 收入 薪水 50000 5\n"
    "　（最後數字＝每月幾號）\n"
    "　固定清單 → 查看所有固定項目\n"
    "　取消固定 ID\n"
    "\n"
    "📸 拍照記帳：\n"
    "　直接傳發票/明細照片\n"
)


def handle_help() -> str:
    return HELP_TEXT


def handle_categorize() -> str:
    try:
        return run_weekly_categorization()
    except Exception as e:
        return f"💥 手動分類失敗：{e}"


def handle_fetch_invoices(days: int = 1) -> str:
    try:
        from einvoice import sync_invoices
        return sync_invoices(days=days)["summary"]
    except Exception as e:
        return f"💥 抓發票失敗：{type(e).__name__}: {e}"


def fetch_invoices_data(days: int = 1) -> dict:
    """Discord 用：回傳 {"summary": str, "new_items": list[dict]}。"""
    try:
        from einvoice import sync_invoices
        return sync_invoices(days=days)
    except Exception as e:
        return {"summary": f"💥 抓發票失敗：{type(e).__name__}: {e}", "new_items": []}


def handle_report(user_id: str, base_url: str) -> str:
    token = generate_report_token(user_id)
    report_url = f"{base_url}/report?token={token}"
    return f"📊 點擊下方連結查看互動式報表（30 分鐘內有效）：\n{report_url}"


def handle_add_recurring(type_str: str, item: str, amount: int, day: int) -> str:
    r_type = "income" if type_str == "收入" else "expense"
    if day < 1 or day > 28:
        return "⚠️ 日期請設 1~28（避免大小月問題）"
    db = SessionLocal()
    try:
        rec = RecurringRecord(type=r_type, item=item, amount=amount, day_of_month=day)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        type_label = "收入" if r_type == "income" else "支出"
        return (
            f"🔄 固定{type_label}已建立！(ID: {rec.id})\n"
            f"項目：{item}\n"
            f"金額：{amount} 元\n"
            f"每月 {day} 號自動記入"
        )
    except Exception as e:
        db.rollback()
        return f"💥 建立失敗：{e}"
    finally:
        db.close()


def handle_list_recurring() -> str:
    db = SessionLocal()
    try:
        records = db.query(RecurringRecord).filter(RecurringRecord.active == 1).order_by(RecurringRecord.day_of_month).all()
        if not records:
            return "目前沒有任何固定收支項目。"
        lines = ["🔄 【固定收支清單】"]
        for r in records:
            icon = "💰" if r.type == "income" else "💸"
            lines.append(f"ID:{r.id} | {icon} {r.item} {r.amount}元 / 每月{r.day_of_month}號")
        return "\n".join(lines)
    except Exception as e:
        return f"💥 查詢失敗：{e}"
    finally:
        db.close()


def handle_delete_recurring(target_id: int) -> str:
    db = SessionLocal()
    try:
        rec = db.query(RecurringRecord).filter(RecurringRecord.id == target_id, RecurringRecord.active == 1).first()
        if rec:
            rec.active = 0
            db.commit()
            return f"🗑️ 已取消固定項目 ID:{target_id}（{rec.item} {rec.amount}元）"
        else:
            return f"⚠️ 找不到啟用中的固定項目 ID: {target_id}"
    except Exception as e:
        db.rollback()
        return f"💥 取消失敗：{e}"
    finally:
        db.close()


def handle_query_monthly() -> str:
    db = SessionLocal()
    try:
        now = datetime.now()
        total_expense = db.query(func.sum(Transaction.price)).filter(
            func.extract('year', Transaction.created_at) == now.year,
            func.extract('month', Transaction.created_at) == now.month
        ).scalar() or 0
        total_income = db.query(func.sum(Income.amount)).filter(
            func.extract('year', Income.created_at) == now.year,
            func.extract('month', Income.created_at) == now.month
        ).scalar() or 0
        net = total_expense - total_income
        return (
            f"📊 【本月結算】\n"
            f"💸 總支出：{total_expense} 元\n"
            f"💰 總收入：{total_income} 元\n"
            f"📋 淨支出：{net} 元"
        )
    except Exception as e:
        return f"💥 查詢失敗：{str(e)}"
    finally:
        db.close()


def handle_query_recent() -> str:
    db = SessionLocal()
    try:
        expenses = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(5).all()
        incomes = db.query(Income).order_by(Income.created_at.desc()).limit(5).all()

        combined = []
        for r in expenses:
            combined.append((r.created_at, f"ID:{r.id} | 💸 {r.item} ({r.price}元/支出) [{r.created_at.strftime('%m/%d %H:%M')}]"))
        for r in incomes:
            combined.append((r.created_at, f"ID:{r.id} | 💰 {r.item} ({r.amount}元/收入) [{r.created_at.strftime('%m/%d %H:%M')}]"))

        combined.sort(key=lambda x: x[0], reverse=True)
        combined = combined[:5]

        if combined:
            lines = ["🔍 【最近 5 筆紀錄】"]
            for _, line_text in combined:
                lines.append(line_text)
            return "\n".join(lines)
        else:
            return "目前還沒有任何記帳紀錄喔！"
    except Exception as e:
        return f"💥 查詢失敗：{str(e)}"
    finally:
        db.close()


def handle_delete_income(target_id: int) -> str:
    db = SessionLocal()
    try:
        record = db.query(Income).filter(Income.id == target_id).first()
        if record:
            db.delete(record)
            db.commit()
            return f"🗑️ 成功刪除收入 ID: {target_id}！"
        else:
            return f"⚠️ 找不到收入 ID: {target_id}，請確認 ID 是否正確。"
    except Exception as e:
        db.rollback()
        return f"💥 刪除失敗：{str(e)}"
    finally:
        db.close()


def handle_delete_expense(target_id: int) -> str:
    db = SessionLocal()
    try:
        record = db.query(Transaction).filter(Transaction.id == target_id).first()
        if record:
            db.delete(record)
            db.commit()
            return f"🗑️ 成功刪除支出 ID: {target_id}！"
        else:
            return f"⚠️ 找不到支出 ID: {target_id}，請確認 ID 是否正確。"
    except Exception as e:
        db.rollback()
        return f"💥 刪除失敗：{str(e)}"
    finally:
        db.close()


def handle_update_income(target_id: int, new_item: str, new_amount: int) -> str:
    db = SessionLocal()
    try:
        record = db.query(Income).filter(Income.id == target_id).first()
        if record:
            old_item = record.item
            old_amount = record.amount
            record.item = new_item
            record.amount = new_amount
            db.commit()
            return (
                f"✏️ 收入修改成功！(ID: {target_id})\n"
                f"原本：{old_item} ({old_amount} 元)\n"
                f"更新：{new_item} ({new_amount} 元)"
            )
        else:
            return f"⚠️ 找不到收入 ID: {target_id}。"
    except Exception as e:
        db.rollback()
        return f"💥 修改失敗：{str(e)}"
    finally:
        db.close()


def handle_update_expense(target_id: int, new_item: str, new_price: int) -> str:
    db = SessionLocal()
    try:
        record = db.query(Transaction).filter(Transaction.id == target_id).first()
        if record:
            old_item = record.item
            old_price = record.price
            record.item = new_item
            record.price = new_price
            db.commit()
            return (
                f"✏️ 支出修改成功！(ID: {target_id})\n"
                f"原本：{old_item} ({old_price} 元)\n"
                f"更新：{new_item} ({new_price} 元)"
            )
        else:
            return f"⚠️ 找不到支出 ID: {target_id}。"
    except Exception as e:
        db.rollback()
        return f"💥 修改失敗：{str(e)}"
    finally:
        db.close()


def handle_record_text(msg: str) -> list[str] | None:
    """處理一般記帳文字（支援多行）。回傳 [記帳結果, AI回應] 或 None（非記帳訊息）。"""
    lines = msg.split('\n')
    success_records = []

    db = SessionLocal()
    try:
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match_inc = PATTERN_INCOME.match(line)
            if match_inc:
                item_name = match_inc.group(1).strip()
                amount_val = int(match_inc.group(2))
                new_income = Income(item=item_name, amount=amount_val)
                db.add(new_income)
                db.flush()
                success_records.append(f"💰 收入 ID:{new_income.id} | {item_name}：{amount_val} 元")
                continue

            if re.match(r"^(收入|刪除收入|刪除|修改收入|修改|固定|取消固定|固定清單)\b", line):
                continue

            match = PATTERN.match(line)
            if match:
                item_name = match.group(1).strip()
                price_val = int(match.group(2))
                new_transaction = Transaction(item=item_name, price=price_val)
                db.add(new_transaction)
                db.flush()
                success_records.append(f"💸 支出 ID:{new_transaction.id} | {item_name}：{price_val} 元")

        if success_records:
            db.commit()
            reply_text = "📝 記帳完成！\n" + "\n".join(success_records)
            ai_comment = generate_persona_comment("\n".join(success_records))
            result = [reply_text]
            if ai_comment:
                result.append(ai_comment)
            return result
        return None
    except Exception as e:
        db.rollback()
        return [f"💥 寫入失敗：{str(e)}"]
    finally:
        db.close()


def handle_image(image_bytes: bytes) -> list[str]:
    """處理圖片記帳。回傳 [記帳結果, AI回應]。"""
    prompt = """這是一張消費明細或發票。請幫我列出上面所有的「消費項目」與對應的「金額」。
    請嚴格只回傳 JSON 陣列 (Array) 格式，不要包含任何其他文字或 Markdown 標籤。
    如果遇到折扣或折扣碼，請用負數金額表示，或直接扣除在單項金額內。
    格式範例：
    [
      {"item": "雞胸肉", "price": 150},
      {"item": "高麗菜", "price": 45},
      {"item": "鮮奶", "price": 180}
    ]
    如果完全無法辨識出任何項目，請回傳空陣列 []"""

    result_text = gemini_image(prompt, image_bytes).strip()

    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]

    items_data = json.loads(result_text.strip())

    if not items_data or not isinstance(items_data, list):
        return ["🤔 AI 找不到明細上的具體項目，請確認照片是否清晰。"]

    success_records = []
    discount_records = []
    db = SessionLocal()
    try:
        total_price = 0
        total_discount = 0
        for data in items_data:
            item_name = data.get("item", "未知項目")
            price_val = int(data.get("price", 0))
            if price_val == 0:
                continue

            if price_val < 0:
                discount_amount = abs(price_val)
                new_income = Income(item=f"折扣：{item_name}", amount=discount_amount)
                db.add(new_income)
                db.flush()
                total_discount += discount_amount
                discount_records.append(f"🏷️ 收入 ID:{new_income.id} | {item_name}：-{discount_amount}")
                continue

            new_transaction = Transaction(item=item_name, price=price_val)
            db.add(new_transaction)
            db.flush()
            success_records.append(f"✅ ID:{new_transaction.id} | {item_name}：{price_val}")
            total_price += price_val

        if success_records:
            db.commit()
            actual_total = total_price - total_discount
            reply_text = f"📸 影像辨識完成！共 {len(success_records)} 筆項目"
            if discount_records:
                reply_text += f"\n小計：{total_price} 元\n" + "\n".join(discount_records) + f"\n實付總計：{actual_total} 元"
            else:
                reply_text += f" (總計 {total_price} 元)"
            reply_text += "：\n" + "\n".join(success_records)

            ai_comment = generate_persona_comment(f"影像辨識記帳，總計 {total_price} 元：\n" + "\n".join(success_records))
            result = [reply_text]
            if ai_comment:
                result.append(ai_comment)
            return result
        else:
            return ["⚠️ 有辨識到文字，但沒有抓到有效的金額項目。"]
    except Exception as e:
        db.rollback()
        return [f"💥 寫入資料庫失敗：{str(e)}"]
    finally:
        db.close()


def process_text_message(msg: str, user_id: str = None, base_url: str = None) -> list[str] | None:
    """統一處理文字訊息的路由。回傳回覆訊息列表，或 None（無法識別的訊息）。"""
    msg = msg.strip()

    if msg in ["說明", "幫助", "help", "指令"]:
        return [handle_help()]

    if msg == "分類":
        return [handle_categorize()]

    match_fetch = PATTERN_FETCH_INVOICE.match(msg)
    if match_fetch:
        days = int(match_fetch.group(1) or 1)
        return [handle_fetch_invoices(days)]

    if msg == "報表" and user_id and base_url:
        return [handle_report(user_id, base_url)]

    match_recurring = PATTERN_RECURRING.match(msg)
    if match_recurring:
        result = handle_add_recurring(
            match_recurring.group(1),
            match_recurring.group(2).strip(),
            int(match_recurring.group(3)),
            int(match_recurring.group(4)),
        )
        return [result]

    if msg == "固定清單":
        return [handle_list_recurring()]

    match_recurring_del = PATTERN_RECURRING_DELETE.match(msg)
    if match_recurring_del:
        return [handle_delete_recurring(int(match_recurring_del.group(1)))]

    if msg in ["查詢", "本月", "本月花費"]:
        return [handle_query_monthly()]

    if msg == "最近":
        return [handle_query_recent()]

    match_income_delete = PATTERN_INCOME_DELETE.match(msg)
    if match_income_delete:
        return [handle_delete_income(int(match_income_delete.group(1)))]

    match_delete = PATTERN_DELETE.match(msg)
    if match_delete:
        return [handle_delete_expense(int(match_delete.group(1)))]

    match_income_update = PATTERN_INCOME_UPDATE.match(msg)
    if match_income_update:
        return [handle_update_income(
            int(match_income_update.group(1)),
            match_income_update.group(2).strip(),
            int(match_income_update.group(3)),
        )]

    match_update = PATTERN_UPDATE.match(msg)
    if match_update:
        return [handle_update_expense(
            int(match_update.group(1)),
            match_update.group(2).strip(),
            int(match_update.group(3)),
        )]

    # 一般記帳
    return handle_record_text(msg)


# ────────────────────────────────────────────────────────────────
# Data API for Discord embeds (回傳結構化資料，不格式化字串)
# ────────────────────────────────────────────────────────────────


def query_monthly_data() -> dict:
    db = SessionLocal()
    try:
        now = datetime.now()
        total_expense = db.query(func.sum(Transaction.price)).filter(
            func.extract('year', Transaction.created_at) == now.year,
            func.extract('month', Transaction.created_at) == now.month,
        ).scalar() or 0
        total_income = db.query(func.sum(Income.amount)).filter(
            func.extract('year', Income.created_at) == now.year,
            func.extract('month', Income.created_at) == now.month,
        ).scalar() or 0
        cat_rows = db.query(
            Transaction.category, func.sum(Transaction.price),
        ).filter(
            func.extract('year', Transaction.created_at) == now.year,
            func.extract('month', Transaction.created_at) == now.month,
        ).group_by(Transaction.category).all()
        categories = sorted(
            [{"name": (c or "未分類"), "amount": int(a or 0)} for c, a in cat_rows],
            key=lambda x: x["amount"],
            reverse=True,
        )
        return {
            "year": now.year,
            "month": now.month,
            "income": int(total_income),
            "expense": int(total_expense),
            "net": int(total_expense - total_income),
            "categories": categories,
        }
    finally:
        db.close()


def query_recent_data(limit: int = 5) -> list[dict]:
    db = SessionLocal()
    try:
        expenses = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(limit).all()
        incomes = db.query(Income).order_by(Income.created_at.desc()).limit(limit).all()
        combined = []
        for r in expenses:
            combined.append({
                "type": "expense", "id": r.id, "item": r.item,
                "amount": r.price, "category": r.category,
                "created_at": r.created_at,
            })
        for r in incomes:
            combined.append({
                "type": "income", "id": r.id, "item": r.item,
                "amount": r.amount, "category": r.category,
                "created_at": r.created_at,
            })
        combined.sort(key=lambda x: x["created_at"], reverse=True)
        return combined[:limit]
    finally:
        db.close()


def record_expense_data(item: str, price: int) -> dict:
    db = SessionLocal()
    try:
        tx = Transaction(item=item, price=price)
        db.add(tx)
        db.commit()
        db.refresh(tx)
        persona = generate_persona_comment(f"💸 支出：{item} {price} 元") or ""
        return {
            "success": True, "id": tx.id, "item": tx.item,
            "amount": tx.price, "category": tx.category, "persona": persona,
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def record_income_data(item: str, amount: int) -> dict:
    db = SessionLocal()
    try:
        inc = Income(item=item, amount=amount)
        db.add(inc)
        db.commit()
        db.refresh(inc)
        persona = generate_persona_comment(f"💰 收入：{item} {amount} 元") or ""
        return {
            "success": True, "id": inc.id, "item": inc.item,
            "amount": inc.amount, "category": inc.category, "persona": persona,
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def update_expense_data(target_id: int, new_item: str, new_price: int) -> dict:
    db = SessionLocal()
    try:
        rec = db.query(Transaction).filter(Transaction.id == target_id).first()
        if not rec:
            return {"success": False, "error": f"找不到支出 ID: {target_id}"}
        old = {"item": rec.item, "amount": rec.price}
        rec.item = new_item
        rec.price = new_price
        db.commit()
        return {
            "success": True, "id": target_id,
            "old": old, "new": {"item": new_item, "amount": new_price},
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def update_income_data(target_id: int, new_item: str, new_amount: int) -> dict:
    db = SessionLocal()
    try:
        rec = db.query(Income).filter(Income.id == target_id).first()
        if not rec:
            return {"success": False, "error": f"找不到收入 ID: {target_id}"}
        old = {"item": rec.item, "amount": rec.amount}
        rec.item = new_item
        rec.amount = new_amount
        db.commit()
        return {
            "success": True, "id": target_id,
            "old": old, "new": {"item": new_item, "amount": new_amount},
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def delete_expense_data(target_id: int) -> dict:
    db = SessionLocal()
    try:
        rec = db.query(Transaction).filter(Transaction.id == target_id).first()
        if not rec:
            return {"success": False, "error": f"找不到支出 ID: {target_id}"}
        item, amount = rec.item, rec.price
        db.delete(rec)
        db.commit()
        return {"success": True, "id": target_id, "item": item, "amount": amount}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def delete_income_data(target_id: int) -> dict:
    db = SessionLocal()
    try:
        rec = db.query(Income).filter(Income.id == target_id).first()
        if not rec:
            return {"success": False, "error": f"找不到收入 ID: {target_id}"}
        item, amount = rec.item, rec.amount
        db.delete(rec)
        db.commit()
        return {"success": True, "id": target_id, "item": item, "amount": amount}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def list_recurring_data() -> list[dict]:
    db = SessionLocal()
    try:
        records = db.query(RecurringRecord).filter(
            RecurringRecord.active == 1,
        ).order_by(RecurringRecord.day_of_month).all()
        return [{
            "id": r.id, "type": r.type, "item": r.item,
            "amount": r.amount, "day_of_month": r.day_of_month,
        } for r in records]
    finally:
        db.close()


def add_recurring_data(type_str: str, item: str, amount: int, day: int) -> dict:
    if day < 1 or day > 28:
        return {"success": False, "error": "日期請設 1~28（避免大小月問題）"}
    r_type = "income" if type_str in ("收入", "income") else "expense"
    db = SessionLocal()
    try:
        rec = RecurringRecord(type=r_type, item=item, amount=amount, day_of_month=day)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return {
            "success": True, "id": rec.id, "type": r_type,
            "item": item, "amount": amount, "day_of_month": day,
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def delete_recurring_data(target_id: int) -> dict:
    db = SessionLocal()
    try:
        rec = db.query(RecurringRecord).filter(
            RecurringRecord.id == target_id,
            RecurringRecord.active == 1,
        ).first()
        if not rec:
            return {"success": False, "error": f"找不到啟用中的固定項目 ID: {target_id}"}
        rec.active = 0
        info = {"id": target_id, "type": rec.type, "item": rec.item, "amount": rec.amount}
        db.commit()
        return {"success": True, **info}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def handle_image_data(image_bytes: bytes) -> dict:
    """處理圖片記帳，回傳結構化資料。"""
    prompt = """這是一張消費明細或發票。請幫我列出上面所有的「消費項目」與對應的「金額」。
    請嚴格只回傳 JSON 陣列 (Array) 格式，不要包含任何其他文字或 Markdown 標籤。
    如果遇到折扣或折扣碼，請用負數金額表示，或直接扣除在單項金額內。
    格式範例：
    [
      {"item": "雞胸肉", "price": 150},
      {"item": "高麗菜", "price": 45}
    ]
    如果完全無法辨識出任何項目，請回傳空陣列 []"""

    result_text = gemini_image(prompt, image_bytes).strip()
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]

    try:
        items_data = json.loads(result_text.strip())
    except Exception as e:
        return {"success": False, "error": f"AI 回傳無法解析：{e}"}

    if not items_data or not isinstance(items_data, list):
        return {"success": False, "error": "AI 找不到明細上的具體項目，請確認照片是否清晰。"}

    expenses, discounts = [], []
    db = SessionLocal()
    try:
        for data in items_data:
            item_name = data.get("item", "未知項目")
            price_val = int(data.get("price", 0))
            if price_val == 0:
                continue
            if price_val < 0:
                amt = abs(price_val)
                inc = Income(item=f"折扣：{item_name}", amount=amt)
                db.add(inc)
                db.flush()
                discounts.append({"id": inc.id, "item": item_name, "amount": amt})
                continue
            tx = Transaction(item=item_name, price=price_val)
            db.add(tx)
            db.flush()
            expenses.append({"id": tx.id, "item": item_name, "amount": price_val})

        if not expenses and not discounts:
            return {"success": False, "error": "有辨識到文字，但沒有抓到有效的金額項目。"}

        db.commit()
        total_e = sum(e["amount"] for e in expenses)
        total_d = sum(d["amount"] for d in discounts)
        actual = total_e - total_d
        persona = generate_persona_comment(
            f"影像辨識記帳，共 {len(expenses)} 項，總計 {total_e} 元"
        ) or ""
        return {
            "success": True, "expenses": expenses, "discounts": discounts,
            "total_expense": total_e, "total_discount": total_d,
            "actual": actual, "persona": persona,
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()
