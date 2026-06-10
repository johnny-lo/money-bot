"""28 個 slash commands 的註冊（記帳/查詢/固定收支/美食/食譜/測試報表）。

慢 commands（/記帳、/收入、/分類、/抓發票…）必 defer 避免 3 秒超時。
"""
import os

import discord
from discord import app_commands

from core import (
    handle_categorize, fetch_invoices_data,
    record_expense_data, record_income_data,
    query_monthly_data, query_recent_data,
    update_expense_data, update_income_data,
    delete_expense_data, delete_income_data,
    list_recurring_data, add_recurring_data, delete_recurring_data,
)
from auth import generate_report_token
from .embeds import (
    COLOR_INFO,
    persona_embed, error_embed, help_embed,
    expense_recorded_embed, income_recorded_embed,
    monthly_summary_embed, recent_records_embed, report_embed,
    update_embed, delete_record_embed,
    recurring_list_embed, recurring_added_embed, recurring_deleted_embed,
    food_place_embed, food_list_embed, food_reco_embed, food_map_embed,
    recipe_random_embed, recipe_list_embed,
    build_items_embed,
)
from .reports import notify_weekly_summary, notify_monthly_summary

BASE_URL = os.getenv("BASE_URL", "https://your-ngrok-domain.ngrok-free.dev").rstrip("/")


def register_commands(bot) -> None:
    tree = bot.tree

    @tree.command(name="記帳", description="記錄一筆支出")
    @app_commands.describe(品名="支出項目", 金額="花費金額")
    async def cmd_expense(ix: discord.Interaction, 品名: str, 金額: int):
        await ix.response.defer()
        data = record_expense_data(品名, 金額)
        if not data["success"]:
            await ix.followup.send(embed=error_embed(data["error"]))
            return
        embeds = [expense_recorded_embed(data)]
        pe = persona_embed(data.get("persona", ""))
        if pe:
            embeds.append(pe)
        await ix.followup.send(embeds=embeds)

    @tree.command(name="收入", description="記錄一筆收入")
    @app_commands.describe(品名="收入項目", 金額="收入金額")
    async def cmd_income(ix: discord.Interaction, 品名: str, 金額: int):
        await ix.response.defer()
        data = record_income_data(品名, 金額)
        if not data["success"]:
            await ix.followup.send(embed=error_embed(data["error"]))
            return
        embeds = [income_recorded_embed(data)]
        pe = persona_embed(data.get("persona", ""))
        if pe:
            embeds.append(pe)
        await ix.followup.send(embeds=embeds)

    @tree.command(name="查詢", description="本月收支結算")
    async def cmd_query(ix: discord.Interaction):
        data = query_monthly_data()
        await ix.response.send_message(embed=monthly_summary_embed(data))

    @tree.command(name="最近", description="最近的記帳紀錄")
    @app_commands.describe(筆數="顯示筆數（1-10，預設 5）")
    async def cmd_recent(ix: discord.Interaction, 筆數: int = 5):
        limit = max(1, min(10, 筆數))
        records = query_recent_data(limit)
        await ix.response.send_message(embed=recent_records_embed(records))

    @tree.command(name="報表", description="產生互動式網頁報表")
    async def cmd_report(ix: discord.Interaction):
        token = generate_report_token(str(ix.user.id))
        url = f"{BASE_URL}/report?token={token}"
        await ix.response.send_message(embed=report_embed(url))

    @tree.command(name="修改", description="修改一筆支出")
    @app_commands.describe(編號="支出 ID", 品名="新品名", 金額="新金額")
    async def cmd_update_expense(ix: discord.Interaction, 編號: int, 品名: str, 金額: int):
        data = update_expense_data(編號, 品名, 金額)
        await ix.response.send_message(embed=update_embed("expense", data))

    @tree.command(name="修改收入", description="修改一筆收入")
    @app_commands.describe(編號="收入 ID", 品名="新品名", 金額="新金額")
    async def cmd_update_income(ix: discord.Interaction, 編號: int, 品名: str, 金額: int):
        data = update_income_data(編號, 品名, 金額)
        await ix.response.send_message(embed=update_embed("income", data))

    @tree.command(name="刪除", description="刪除一筆支出")
    @app_commands.describe(編號="支出 ID")
    async def cmd_delete_expense(ix: discord.Interaction, 編號: int):
        data = delete_expense_data(編號)
        await ix.response.send_message(embed=delete_record_embed("expense", data))

    @tree.command(name="刪除收入", description="刪除一筆收入")
    @app_commands.describe(編號="收入 ID")
    async def cmd_delete_income(ix: discord.Interaction, 編號: int):
        data = delete_income_data(編號)
        await ix.response.send_message(embed=delete_record_embed("income", data))

    @tree.command(name="固定支出", description="新增每月固定支出")
    @app_commands.describe(品名="項目", 金額="金額", 日期="每月幾號（1-28）")
    async def cmd_recurring_expense(ix: discord.Interaction, 品名: str, 金額: int, 日期: int):
        data = add_recurring_data("支出", 品名, 金額, 日期)
        await ix.response.send_message(embed=recurring_added_embed(data))

    @tree.command(name="固定收入", description="新增每月固定收入")
    @app_commands.describe(品名="項目", 金額="金額", 日期="每月幾號（1-28）")
    async def cmd_recurring_income(ix: discord.Interaction, 品名: str, 金額: int, 日期: int):
        data = add_recurring_data("收入", 品名, 金額, 日期)
        await ix.response.send_message(embed=recurring_added_embed(data))

    @tree.command(name="固定清單", description="查看所有固定收支")
    async def cmd_recurring_list(ix: discord.Interaction):
        records = list_recurring_data()
        await ix.response.send_message(embed=recurring_list_embed(records))

    @tree.command(name="取消固定", description="取消一個固定收支")
    @app_commands.describe(編號="固定收支 ID")
    async def cmd_recurring_delete(ix: discord.Interaction, 編號: int):
        data = delete_recurring_data(編號)
        await ix.response.send_message(embed=recurring_deleted_embed(data))

    @tree.command(name="分類", description="手動觸發 AI 自動分類")
    async def cmd_categorize(ix: discord.Interaction):
        await ix.response.defer()
        try:
            msg = handle_categorize()
            e = discord.Embed(title="🏷️ AI 分類完成", description=msg[:4000], color=COLOR_INFO)
        except Exception as ex:
            e = error_embed(str(ex))
        await ix.followup.send(embed=e)

    @tree.command(name="抓發票", description="同步電子發票（手機條碼載具）")
    @app_commands.describe(天數="抓近 N 天的發票（預設 1，今天）")
    async def cmd_fetch_invoice(ix: discord.Interaction, 天數: int = 1):
        await ix.response.defer()
        try:
            result = fetch_invoices_data(max(1, min(31, 天數)))
            e = discord.Embed(
                title="🧾 發票同步結果",
                description=f"```\n{result['summary'][:3900]}\n```",
                color=COLOR_INFO,
            )
            embeds = [e]
            items_embed = build_items_embed(result.get("new_items", []))
            if items_embed:
                embeds.append(items_embed)
        except Exception as ex:
            embeds = [error_embed(str(ex))]
        await ix.followup.send(embeds=embeds)

    @tree.command(name="說明", description="顯示所有指令")
    async def cmd_help(ix: discord.Interaction):
        await ix.response.send_message(embed=help_embed())

    @tree.command(name="美食新增", description="新增一家想去的店（自動查 Google 正規化）")
    @app_commands.describe(店名="店名", 區域="縣市/城市（幫助定位，選填）", 推薦品項="想吃什麼（選填）")
    async def cmd_food_add(ix: discord.Interaction, 店名: str, 區域: str = "", 推薦品項: str = ""):
        await ix.response.defer()
        from food.places import search_text
        from food.repo import upsert_place
        query = f"{店名} {區域}".strip()
        try:
            place = search_text(query)
        except Exception as ex:
            await ix.followup.send(embed=error_embed(f"查 Google 失敗：{ex}"))
            return
        if not place:
            await ix.followup.send(embed=error_embed(f"找不到「{query}」，換個更完整的店名或加上區域再試。"))
            return
        try:
            p, created = upsert_place(place, recommended_items=推薦品項 or None)
        except Exception as ex:
            await ix.followup.send(embed=error_embed(f"存檔失敗：{ex}"))
            return
        await ix.followup.send(embed=food_place_embed(p, created=created))

    @tree.command(name="美食推薦", description="依縣市/國家推薦想去的店")
    @app_commands.describe(地區="縣市或國家，例如 台中 / 日本")
    async def cmd_food_reco(ix: discord.Interaction, 地區: str):
        await ix.response.defer()
        from food.repo import list_places
        from food.recommend import filter_for_recommendation, sort_recent, pick_random
        matched = sort_recent(filter_for_recommendation(list_places("想去"), 地區))
        pick = pick_random(matched)
        await ix.followup.send(embed=food_reco_embed(地區, matched, pick))

    @tree.command(name="美食清單", description="列出美食清單")
    @app_commands.describe(狀態="想去 / 去過（留空=全部）")
    async def cmd_food_list(ix: discord.Interaction, 狀態: str = ""):
        await ix.response.defer()
        from food.repo import list_places
        status = 狀態 if 狀態 in ("想去", "去過") else None
        places = list_places(status)
        title = f"🍜 美食清單（{狀態 or '全部'}，{len(places)} 家）"
        await ix.followup.send(embed=food_list_embed(places, title))

    @tree.command(name="去過", description="把某家標成去過（可記評分/心得）")
    @app_commands.describe(編號="店家編號", 評分="1-5（選填）", 心得="一句話（選填）")
    async def cmd_food_visited(ix: discord.Interaction, 編號: int, 評分: int = 0, 心得: str = ""):
        await ix.response.defer()
        from food.repo import set_visited
        rating = 評分 if 1 <= 評分 <= 5 else None
        p = set_visited(編號, rating=rating, note=心得 or None)
        if not p:
            await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))
            return
        await ix.followup.send(embed=food_place_embed(p, created=False))

    @tree.command(name="美食刪除", description="依編號刪除一家店（修正批次猜錯的分店）")
    @app_commands.describe(編號="店家編號")
    async def cmd_food_delete(ix: discord.Interaction, 編號: int):
        await ix.response.defer()
        from food.repo import delete_place
        ok = delete_place(編號)
        if ok:
            await ix.followup.send(f"🗑️ 已刪除 #{編號}")
        else:
            await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))

    @tree.command(name="美食地圖", description="開啟想去/去過的美食地圖")
    async def cmd_food_map(ix: discord.Interaction):
        token = generate_report_token(str(ix.user.id))
        url = f"{BASE_URL}/m/?token={token}"
        await ix.response.send_message(embed=food_map_embed(url))

    @tree.command(name="隨機食譜", description="從收錄的食譜裡隨機抽一道")
    async def cmd_recipe_random(ix: discord.Interaction):
        await ix.response.defer()
        from recipe.repo import pick_random
        r = pick_random()
        if not r:
            await ix.followup.send("還沒收錄任何食譜，先去 #🍳-食譜 丟幾個連結 🍳")
            return
        await ix.followup.send(embed=recipe_random_embed(r))

    @tree.command(name="食譜清單", description="列出所有收錄的食譜")
    async def cmd_recipe_list(ix: discord.Interaction):
        await ix.response.defer()
        from recipe.repo import list_recipes
        await ix.followup.send(embed=recipe_list_embed(list_recipes()))

    @tree.command(name="食譜刪除", description="刪除一筆食譜")
    @app_commands.describe(編號="食譜編號")
    async def cmd_recipe_delete(ix: discord.Interaction, 編號: int):
        await ix.response.defer()
        from recipe.repo import delete_recipe
        ok = delete_recipe(編號)
        if ok:
            await ix.followup.send(f"🗑️ 已刪除 #{編號}")
        else:
            await ix.followup.send(embed=error_embed(f"找不到編號 {編號}"))

    @tree.command(name="測試週報", description="立即觸發本週週報推到 #📊-報表查詢")
    async def cmd_test_weekly(ix: discord.Interaction):
        await ix.response.defer(ephemeral=True)
        try:
            notify_weekly_summary()
            await ix.followup.send("✅ 已觸發本週週報，請看 #📊-報表查詢", ephemeral=True)
        except Exception as ex:
            await ix.followup.send(f"⚠️ 失敗：{ex}", ephemeral=True)

    @tree.command(name="測試月報", description="立即觸發上月月報推到 #📊-報表查詢")
    async def cmd_test_monthly(ix: discord.Interaction):
        await ix.response.defer(ephemeral=True)
        try:
            notify_monthly_summary()
            await ix.followup.send("✅ 已觸發上月月報，請看 #📊-報表查詢", ephemeral=True)
        except Exception as ex:
            await ix.followup.send(f"⚠️ 失敗：{ex}", ephemeral=True)
