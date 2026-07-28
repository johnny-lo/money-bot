"""Discord embed builders：顏色常數、金額/時間格式化、所有卡片組裝（純呈現層，無 I/O）。"""
import discord

from food import ingest

COLOR_EXPENSE = 0xE74C3C   # 紅
COLOR_INCOME  = 0x2ECC71   # 綠
COLOR_INFO    = 0x3498DB   # 藍
COLOR_PERSONA = 0x9B59B6   # 紫（木須龍）
COLOR_WARN    = 0xF1C40F   # 黃
COLOR_FOOD    = 0xE67E22   # 美食橘
COLOR_RECIPE  = 0x16A085   # 食譜青綠
COLOR_VIDEO   = 0x8E44AD   # 歷史影片紫


def fmt_money(n: int) -> str:
    return f"${n:,}"


def fmt_dt(dt) -> str:
    return dt.strftime("%m/%d %H:%M")


def persona_embed(text: str):
    if not text:
        return None
    return discord.Embed(description=f"🐉 {text}", color=COLOR_PERSONA)


def error_embed(msg: str) -> discord.Embed:
    return discord.Embed(title="⚠️ 錯誤", description=msg, color=COLOR_WARN)


def expense_recorded_embed(d: dict) -> discord.Embed:
    e = discord.Embed(title="💸 支出已記錄", color=COLOR_EXPENSE)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    if d.get("category"):
        e.add_field(name="分類", value=d["category"], inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def income_recorded_embed(d: dict) -> discord.Embed:
    e = discord.Embed(title="💰 收入已記錄", color=COLOR_INCOME)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    if d.get("category"):
        e.add_field(name="分類", value=d["category"], inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def monthly_summary_embed(d: dict) -> discord.Embed:
    income, expense, net = d["income"], d["expense"], d["net"]
    color = COLOR_EXPENSE if net > 0 else COLOR_INCOME
    e = discord.Embed(title=f"📊 {d['year']}/{d['month']:02d} 結算", color=color)
    e.add_field(name="💰 收入", value=fmt_money(income), inline=True)
    e.add_field(name="💸 支出", value=fmt_money(expense), inline=True)
    e.add_field(name="📋 淨支出", value=fmt_money(net), inline=True)
    cats = d.get("categories") or []
    if cats and expense > 0:
        lines = []
        for c in cats[:6]:
            pct = c["amount"] / expense * 100
            lines.append(f"`{c['name'][:8]:<8}` {fmt_money(c['amount'])} ({pct:.0f}%)")
        e.add_field(name="📂 支出分類", value="\n".join(lines), inline=False)
    return e


def recent_records_embed(records: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🔍 最近紀錄", color=COLOR_INFO)
    if not records:
        e.description = "目前還沒有任何記帳紀錄。"
        return e
    lines = []
    for r in records:
        icon = "💸" if r["type"] == "expense" else "💰"
        cat = f" `{r['category']}`" if r.get("category") else ""
        lines.append(
            f"{icon} `#{r['id']}` **{r['item']}** {fmt_money(r['amount'])}{cat}\n"
            f"　　_{fmt_dt(r['created_at'])}_"
        )
    e.description = "\n".join(lines)[:4096]
    return e


def report_embed(url: str) -> discord.Embed:
    return discord.Embed(
        title="📊 互動式報表",
        description=f"[👉 點此開啟報表]({url})\n_30 分鐘內有效_",
        color=COLOR_INFO,
    )


def update_embed(kind: str, d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "修改失敗"))
    color = COLOR_EXPENSE if kind == "expense" else COLOR_INCOME
    label = "支出" if kind == "expense" else "收入"
    e = discord.Embed(title=f"✏️ {label}已更新", color=color)
    e.add_field(name="原本", value=f"{d['old']['item']} {fmt_money(d['old']['amount'])}", inline=False)
    e.add_field(name="更新", value=f"{d['new']['item']} {fmt_money(d['new']['amount'])}", inline=False)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def delete_record_embed(kind: str, d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "刪除失敗"))
    color = COLOR_EXPENSE if kind == "expense" else COLOR_INCOME
    label = "支出" if kind == "expense" else "收入"
    return discord.Embed(
        title=f"🗑️ {label}已刪除",
        description=f"`#{d['id']}` {d['item']} {fmt_money(d['amount'])}",
        color=color,
    )


def recurring_list_embed(records: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🔄 固定收支清單", color=COLOR_INFO)
    if not records:
        e.description = "目前沒有任何固定收支項目。"
        return e
    lines = []
    for r in records:
        icon = "💰" if r["type"] == "income" else "💸"
        lines.append(
            f"{icon} `#{r['id']}` **{r['item']}** {fmt_money(r['amount'])}"
            f" _每月 {r['day_of_month']} 號_"
        )
    e.description = "\n".join(lines)[:4096]
    return e


def recurring_added_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "建立失敗"))
    color = COLOR_INCOME if d["type"] == "income" else COLOR_EXPENSE
    label = "收入" if d["type"] == "income" else "支出"
    e = discord.Embed(title=f"🔄 固定{label}已建立", color=color)
    e.add_field(name="品項", value=d["item"], inline=True)
    e.add_field(name="金額", value=fmt_money(d["amount"]), inline=True)
    e.add_field(name="日期", value=f"每月 {d['day_of_month']} 號", inline=True)
    e.set_footer(text=f"ID: {d['id']}")
    return e


def recurring_deleted_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "取消失敗"))
    label = "收入" if d["type"] == "income" else "支出"
    return discord.Embed(
        title=f"🗑️ 固定{label}已取消",
        description=f"`#{d['id']}` {d['item']} {fmt_money(d['amount'])}",
        color=COLOR_INFO,
    )


def image_recorded_embed(d: dict) -> discord.Embed:
    if not d["success"]:
        return error_embed(d.get("error", "辨識失敗"))
    e = discord.Embed(title="📸 影像辨識記帳", color=COLOR_EXPENSE)
    if d["expenses"]:
        lines = [f"`#{x['id']}` {x['item']} {fmt_money(x['amount'])}" for x in d["expenses"]]
        e.add_field(name=f"💸 項目（{len(d['expenses'])} 筆）",
                    value="\n".join(lines)[:1024], inline=False)
    if d["discounts"]:
        lines = [f"`#{x['id']}` {x['item']} -{fmt_money(x['amount'])}" for x in d["discounts"]]
        e.add_field(name=f"🏷️ 折扣（{len(d['discounts'])} 筆）",
                    value="\n".join(lines)[:1024], inline=False)
        e.add_field(name="小計", value=fmt_money(d["total_expense"]), inline=True)
        e.add_field(name="折扣", value=f"-{fmt_money(d['total_discount'])}", inline=True)
        e.add_field(name="實付", value=fmt_money(d["actual"]), inline=True)
    else:
        e.add_field(name="總計", value=fmt_money(d["total_expense"]), inline=False)
    return e


def food_kind(p: dict) -> str:
    """類型顯示字串：`大類 · 細類`。兩層都沒有才退回 LLM 原始文字。"""
    parts = [x for x in (p.get("cuisine_major"), p.get("cuisine_minor")) if x]
    return " · ".join(parts) or (p.get("cuisine_type") or "")


def food_place_embed(p: dict, *, created: bool = True) -> discord.Embed:
    from food.places import maps_url
    name = p.get("name") or "(未知店名)"
    if p.get("status") == "去過":
        title = f"🍜 已標記去過：{name}"
    elif created:
        title = f"🍜 已加入想去：{name}"
    else:
        title = f"🍜 已更新（這家記過了）：{name}"
    e = discord.Embed(title=title, color=COLOR_FOOD)
    kind = food_kind(p)
    if kind:
        e.add_field(name="類型", value=kind, inline=True)
    region = " / ".join(
        x for x in (p.get("country"), p.get("city"), p.get("district")) if x) or "—"
    e.add_field(name="地區", value=region, inline=True)
    e.add_field(name="狀態", value=p.get("status", "想去"), inline=True)
    if p.get("address"):
        e.add_field(name="地址", value=p["address"], inline=False)
    if p.get("recommended_items"):
        e.add_field(name="推薦品項", value=p["recommended_items"], inline=False)
    if p.get("caution_summary"):
        e.add_field(name="⚠️ 雷點", value=p["caution_summary"], inline=False)
    if p.get("place_id"):
        e.add_field(name="地圖", value=maps_url(p["place_id"], p.get("name") or ""), inline=False)
    e.set_footer(text=f"編號 {p['id']}")
    return e


def food_list_embed(places: list[dict], title: str) -> discord.Embed:
    e = discord.Embed(title=title, color=COLOR_FOOD)
    if not places:
        e.description = "（沒有符合的店家）"
        return e
    lines = []
    for p in places[:20]:
        # 一行清單要短 → 只放大類（沒有才退回原始文字）
        short = p.get("cuisine_major") or p.get("cuisine_type") or ""
        cat = f" `{short}`" if short else ""
        items = f" — {p['recommended_items']}" if p.get("recommended_items") else ""
        lines.append(f"`#{p['id']}` **{p['name']}**{cat}{items}")
    e.description = "\n".join(lines)
    if len(places) > 20:
        e.set_footer(text=f"共 {len(places)} 家，只顯示前 20")
    return e


def food_reco_embed(query: str, places: list[dict], pick: dict | None) -> discord.Embed:
    e = food_list_embed(places, title=f"🍜 {query} 的想去清單（{len(places)} 家）")
    if pick:
        e.add_field(name="🎲 選擇困難？這家",
                    value=f"**{pick['name']}**" +
                          (f" — {pick['recommended_items']}" if pick.get("recommended_items") else ""),
                    inline=False)
    return e


def food_missing_embed(reason: str, *, hint: str = "") -> discord.Embed:
    """需補件卡片：用 reply 回覆本卡片補上店名/地址即可接回。"""
    e = discord.Embed(
        title="⚠️ 抽不到完整資訊，請補件",
        description=reason or "缺少店名",
        color=COLOR_WARN,
    )
    if hint:
        e.add_field(name="提示", value=hint, inline=False)
    e.set_footer(text="🔁 直接 reply 這張卡片，補上店名或更完整的店名+區域")
    return e


def food_map_embed(url: str) -> discord.Embed:
    return discord.Embed(
        title="🗺️ 美食地圖",
        description=f"[👉 點此開啟地圖]({url})\n_30 分鐘內有效_\n藍 = 想去、綠 = 去過",
        color=COLOR_FOOD,
    )


def recipe_card_embed(r: dict, *, created: bool = True) -> discord.Embed:
    title = (f"🍳 已收錄食譜：{r['name']}" if created
             else f"🍳 你已收錄過：{r['name']}")
    e = discord.Embed(title=title, color=COLOR_RECIPE)
    if r.get("platform"):
        e.add_field(name="📺 平台", value=r["platform"], inline=True)
    e.add_field(name="編號", value=f"#{r['id']}", inline=True)
    if r.get("url"):
        e.add_field(name="連結", value=r["url"], inline=False)
    e.set_footer(text="🔁 reply 這張卡片可改菜名")
    return e


def recipe_random_embed(r: dict) -> discord.Embed:
    e = discord.Embed(title=f"🍳 今天就煮：{r['name']}", color=COLOR_RECIPE)
    if r.get("url"):
        e.add_field(name="連結", value=f"[👉 點開照做]({r['url']})", inline=False)
    e.set_footer(text=f"編號 {r['id']}")
    return e


def recipe_list_embed(recipes: list[dict]) -> discord.Embed:
    e = discord.Embed(title=f"🍳 食譜清單（{len(recipes)} 道）", color=COLOR_RECIPE)
    if not recipes:
        e.description = "還沒收錄任何食譜，先去 #🍳-食譜 丟幾個連結。"
        return e
    lines = []
    for r in recipes[:25]:
        plat = f" `{r['platform']}`" if r.get("platform") else ""
        lines.append(f"`#{r['id']}` **{r['name']}**{plat}")
    e.description = "\n".join(lines)
    if len(recipes) > 25:
        e.set_footer(text=f"共 {len(recipes)} 道，只顯示前 25")
    return e


def recipe_missing_embed(reason: str) -> discord.Embed:
    e = discord.Embed(
        title="⚠️ 沒抽到菜名",
        description=reason or "抽不到菜名",
        color=COLOR_WARN,
    )
    e.set_footer(text="🔁 直接 reply 這張卡片給我一句菜名即可")
    return e


def food_batch_summary_embed(buckets: dict) -> discord.Embed:
    """批次匯入單張總結卡（spec §6.3）。buckets 來自 ingest.batch_from_text。"""
    if buckets.get("error"):
        return error_embed(buckets["error"])
    total = buckets["total_lines"]
    title = (f"🍜 批次匯入完成（共 {total} 行 · "
             f"想去 {buckets['wishlist']} / 去過 {buckets['visited']}）")
    e = discord.Embed(title=title, color=COLOR_FOOD)
    lines = [f"✅ 高信心 {buckets['ok']} 家（已入庫）"]
    review = buckets.get("review") or []
    if review:
        lines.append(f"⚠️ 需確認 {len(review)} 家（沒地區，或 Google 沒給城市/國家，請核對）：")
        for r in review[:15]:
            lines.append(f"　· #{r['id']} {r['raw_name']} → {r['resolved_name']}")
        if len(review) > 15:
            lines.append(f"　…還有 {len(review) - 15} 家")
    fail = buckets.get("fail") or []
    if fail:
        lines.append(f"❌ 找不到 {len(fail)} 家（加上地區再重貼）：")
        for raw in fail[:15]:
            lines.append(f"　· 「{raw}」")
        if len(fail) > 15:
            lines.append(f"　…還有 {len(fail) - 15} 家")
    if buckets.get("dropped"):
        lines.append(f"（超過 {ingest.BATCH_LINE_CAP} 行未處理：{buckets['dropped']} 行，請分批再貼）")
    e.description = "\n".join(lines)[:4000]
    e.set_footer(text="猜錯分店？用 /美食刪除 編號 砍掉，再 /美食新增 帶地區重加")
    return e


def help_embed() -> discord.Embed:
    e = discord.Embed(title="📖 指令說明", color=COLOR_INFO)
    e.description = (
        "**💸 記帳**\n"
        "`/記帳 品名 金額` — 記支出\n"
        "`/收入 品名 金額` — 記收入\n"
        "📸 直接傳圖片 — AI 辨識記帳\n\n"
        "**🔍 查詢**\n"
        "`/查詢` — 本月結算\n"
        "`/最近` — 最近紀錄\n"
        "`/報表` — 互動式報表\n\n"
        "**✏️ 修改 / 刪除**\n"
        "`/修改 編號 品名 金額`\n"
        "`/修改收入 編號 品名 金額`\n"
        "`/刪除 編號`、`/刪除收入 編號`\n\n"
        "**🔄 固定收支**\n"
        "`/固定支出 品名 金額 日期`\n"
        "`/固定收入 品名 金額 日期`\n"
        "`/固定清單`、`/取消固定 編號`\n\n"
        "**🛠️ 其他**\n"
        "`/分類` — 觸發 AI 分類\n"
        "`/抓發票 [天數]` — 同步電子發票\n"
        "`/說明` — 顯示這份說明"
    )
    return e


def video_card_embed(v: dict, *, created: bool = True) -> discord.Embed:
    from video.commands import CHEAT_SHEET
    title = (f"🎥 已收錄：{v['title']}" if created else f"🎥 你已收錄過：{v['title']}")
    e = discord.Embed(title=title, color=COLOR_VIDEO)
    e.add_field(name="📚 主題", value=v.get("topic") or "（未分類）", inline=True)
    e.add_field(name="編號", value=f"#{v['id']}", inline=True)
    tags = v.get("tags") or []
    if tags:
        e.add_field(name="🏷️ 標籤", value="、".join(tags), inline=False)
    if v.get("url"):
        e.add_field(name="連結", value=v["url"], inline=False)
    e.add_field(name="✏️ 怎麼整理", value=CHEAT_SHEET, inline=False)
    return e


def video_help_embed() -> discord.Embed:
    from video.commands import CHEAT_SHEET
    return discord.Embed(title="🎥 歷史影片：怎麼用", description=CHEAT_SHEET, color=COLOR_VIDEO)


def video_missing_embed(reason: str) -> discord.Embed:
    e = discord.Embed(title="⚠️ 沒收進來", description=reason or "抽不到影片資訊", color=COLOR_WARN)
    e.set_footer(text="🔁 重貼連結，或 reply 這張卡片給我新標題")
    return e


def invoice_sync_failed_embed(result: dict) -> discord.Embed:
    """發票同步失敗卡（發到 #🧾-發票通知）。"""
    e = discord.Embed(title="⚠️ 發票同步失敗", color=COLOR_WARN)
    e.description = f"```\n{result.get('summary', '')[:3500]}\n```"
    last = result.get("last_covered")
    retry = result.get("retry_from")
    note = f"涵蓋進度未推進（仍停在 {last if last else '無紀錄'}）"
    if retry:
        note += f"\n→ 下次自動重抓 {retry} ~ 今天"
    e.add_field(name="狀態", value=note, inline=False)
    e.set_footer(text="🐉 發票補拓")
    return e


def build_items_embed(new_items: list[dict]) -> discord.Embed | None:
    """把新增的發票品項排版成 embed（超過 4000 字裁切）。沒有就回 None。"""
    if not new_items:
        return None
    lines = []
    used = 0
    for it in new_items:
        line = f"• {it['date']}　{it['item']}　${it['price']:,}"
        if used + len(line) + 1 > 3900:
            lines.append(f"…還有 {len(new_items) - len(lines)} 筆")
            break
        lines.append(line)
        used += len(line) + 1
    total = sum(it["price"] for it in new_items)
    e = discord.Embed(
        title=f"🆕 新增明細（{len(new_items)} 筆，合計 ${total:,}）",
        description="\n".join(lines),
        color=COLOR_INFO,
    )
    return e
