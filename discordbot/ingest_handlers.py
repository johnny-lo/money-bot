"""#美食輸入 / #🍳-食譜 / 圖片記帳 的 on_message 處理（從 MoneyBot 方法抽出的 module 函式）。"""
import asyncio

import aiohttp
import discord

from core import handle_image_data
from food import ingest, pending
from food.links import detect_links, strip_urls, classify_platform
from food.repo import set_message_id
from .embeds import (
    persona_embed, error_embed, image_recorded_embed,
    food_place_embed, food_missing_embed, food_batch_summary_embed,
    recipe_card_embed, recipe_missing_embed,
    video_card_embed, video_help_embed, video_missing_embed,
)


async def do_image_recording(message: discord.Message, att: discord.Attachment):
    async with message.channel.typing():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(att.url) as resp:
                    image_bytes = await resp.read()
            data = handle_image_data(image_bytes, source="discord")
            embeds = [image_recorded_embed(data)]
            pe = persona_embed(data.get("persona", ""))
            if pe:
                embeds.append(pe)
            await message.channel.send(embeds=embeds)
        except Exception as e:
            await message.channel.send(embed=error_embed(f"視覺大腦失敗：{e}"))


async def handle_food_message(message: discord.Message):
    # reply 補件：上一張 ⚠️ 卡片的補件回覆
    ref = getattr(message, "reference", None)
    if ref and ref.message_id and pending.get(ref.message_id):
        ctx = pending.consume(ref.message_id)
        async with message.channel.typing():
            merged = (ctx.get("raw_text") or "") + " " + (message.content or "")
            p, missing = ingest.from_text(merged.strip(),
                                          source_url=ctx.get("source_url"))
        if p:
            sent = await message.channel.send(
                embed=food_place_embed(p, created=p.get("_created", True))
            )
            set_message_id(p["id"], sent.id)
        else:
            sent = await message.channel.send(embed=food_missing_embed(missing))
            pending.remember(sent.id, original_message_id=message.id,
                             raw_text=merged.strip(),
                             source_url=ctx.get("source_url"),
                             missing_reason=missing)
        return

    # 圖片 ingest
    images = [a for a in message.attachments
              if a.content_type and a.content_type.startswith("image/")]
    if images:
        att = images[0]
        async with message.channel.typing():
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(att.url) as resp:
                        image_bytes = await resp.read()
                p, missing = ingest.from_image(
                    image_bytes,
                    mime_type=att.content_type or "image/jpeg",
                    source_url=att.url,
                )
            except Exception as ex:
                await message.channel.send(embed=error_embed(f"處理截圖失敗：{ex}"))
                return
        if p:
            sent = await message.channel.send(
                embed=food_place_embed(p, created=p.get("_created", True))
            )
            set_message_id(p["id"], sent.id)
        else:
            sent = await message.channel.send(embed=food_missing_embed(missing))
            pending.remember(sent.id, original_message_id=message.id,
                             attachment_url=att.url,
                             missing_reason=missing)
        return

    # 連結 ingest(YouTube / IG / TikTok / Google Maps / 一般網站)
    links = detect_links(message.content or "")
    if links:
        caption = strip_urls(message.content or "")
        async with message.channel.typing():
            # 多連結平行抽取(asyncio.gather + to_thread)
            results = await asyncio.gather(
                *[asyncio.to_thread(ingest.from_url, lk["url"], caption=caption) for lk in links],
                return_exceptions=True,
            )
            # 一個連結→一張結果卡
            for lk, res in zip(links, results):
                url = lk["url"]
                platform = lk["platform"]
                if isinstance(res, Exception):
                    p, missing = None, f"處理失敗:{res}"
                else:
                    p, missing = res
                if p:
                    sent = await message.channel.send(
                        embed=food_place_embed(p, created=p.get("_created", True))
                    )
                    set_message_id(p["id"], sent.id)
                else:
                    hint = ""
                    if platform in ("threads", "facebook"):
                        hint = "貼文文字常只說地區、店名在圖裡 — reply 補上店名最快"
                    sent = await message.channel.send(embed=food_missing_embed(missing, hint=hint))
                    pending.remember(
                        sent.id,
                        original_message_id=message.id,
                        raw_text=caption,
                        source_url=url,
                        missing_reason=missing,
                    )
        return

    # 純文字 ingest
    if message.content and message.content.strip():
        text = message.content.strip()
        # 批次偵測：非空行數 ≥ 2 → 批次匯入（單行維持單筆，spec §5/§7）
        if ingest.is_batch(text):
            async with message.channel.typing():
                buckets = await ingest.batch_from_text(text)
            await message.channel.send(embed=food_batch_summary_embed(buckets))
            return
        async with message.channel.typing():
            p, missing = ingest.from_text(text)
        if p:
            sent = await message.channel.send(
                embed=food_place_embed(p, created=p.get("_created", True))
            )
            set_message_id(p["id"], sent.id)
        else:
            sent = await message.channel.send(embed=food_missing_embed(missing))
            pending.remember(sent.id, original_message_id=message.id,
                             raw_text=text,
                             missing_reason=missing)


async def _send_recipe_card(channel, rec: dict, *, created: bool) -> None:
    """送出食譜卡片並記下訊息 ID（給 reply 改名回查）。"""
    from recipe import repo as recipe_repo
    sent = await channel.send(embed=recipe_card_embed(rec, created=created))
    recipe_repo.set_message_id(rec["id"], sent.id)


async def handle_recipe_message(message: discord.Message):
    from recipe import ingest as recipe_ingest, repo as recipe_repo

    # ── reply：先試改名(get_by_message_id) → 再試補名(pending) → 否則提示 ──
    ref = getattr(message, "reference", None)
    if ref and ref.message_id:
        reply_text = (message.content or "").strip()
        # a) 命中既有 Recipe 卡片 + 有文字 → 改名
        existing = recipe_repo.get_by_message_id(ref.message_id)
        if existing and reply_text:
            updated = recipe_repo.rename(existing["id"], reply_text)
            if updated:
                await _send_recipe_card(message.channel, updated, created=False)
                return
            # rename 失敗(卡片剛被刪)→ 落到下方提示
        # b) 命中 pending（先前抽不到菜名）+ 有文字 → 用 reply 文字 + source_url 建檔
        ctx = pending.get(ref.message_id)
        if ctx and reply_text:
            source_url = ctx.get("source_url")
            if not source_url:
                pending.consume(ref.message_id)
                await message.channel.send("這張卡片少了連結，直接重貼連結就好 🍳")
                return
            platform = classify_platform(source_url)
            async with message.channel.typing():
                rec, created = recipe_repo.add_recipe(reply_text, source_url, platform)
            pending.consume(ref.message_id)   # 成功才消耗,失敗保留可重試
            await _send_recipe_card(message.channel, rec, created=created)
            return
        # c) 收到 reply 但沒能改名/補名（空訊息、卡片過期或已刪）→ 提示,不掉到連結處理
        await message.channel.send("這張卡片過期了，或要改名請 reply 並附上新菜名就好 🍳")
        return

    # ── 連結 ingest（一連結一卡，多連結平行）─────────────────
    links = detect_links(message.content or "")
    if links:
        caption = strip_urls(message.content or "")
        async with message.channel.typing():
            results = await asyncio.gather(
                *[asyncio.to_thread(recipe_ingest.from_url, lk["url"], caption=caption)
                  for lk in links],
                return_exceptions=True,
            )
            for lk, res in zip(links, results):
                url = lk["url"]
                if isinstance(res, Exception):
                    rec, reason = None, f"處理失敗：{res}"
                else:
                    rec, reason = res
                if rec:
                    await _send_recipe_card(
                        message.channel, rec, created=rec.get("_created", True)
                    )
                else:
                    sent = await message.channel.send(embed=recipe_missing_embed(reason))
                    # 只有「抽不到菜名」才需 reply 補名；gmaps 等不建 pending
                    if reason == "抽不到菜名":
                        pending.remember(
                            sent.id,
                            original_message_id=message.id,
                            source_url=url,
                            missing_reason=reason,
                        )
        return

    # ── 無連結、非 reply（純文字 / 純圖片）→ 回提示，不建檔 ──
    await message.channel.send("這個頻道請丟食譜連結 🍳")


async def _send_video_card(channel, v: dict, *, created: bool) -> None:
    """送出影片卡片並記下訊息 ID（給 reply 編輯回查）。"""
    from video import repo as video_repo
    sent = await channel.send(embed=video_card_embed(v, created=created))
    video_repo.set_message_id(v["id"], sent.id)


async def handle_video_message(message: discord.Message):
    from video import ingest as video_ingest, repo as video_repo
    from video.commands import parse_reply_command

    # ── reply：編輯既有卡片（改名 / 設主題 / 加刪標籤）──
    ref = getattr(message, "reference", None)
    if ref and ref.message_id:
        existing = video_repo.get_by_message_id(ref.message_id)
        if not existing:
            await message.channel.send("這張卡片過期了，或重貼連結就好 🎥")
            return
        cmd = parse_reply_command(message.content or "")
        if cmd["mode"] == "rename":
            video_repo.rename(existing["id"], cmd["title"])
        elif cmd["mode"] == "edit":
            if cmd["topic"] is not None:
                video_repo.set_topic(existing["id"], cmd["topic"])
            for t in cmd["remove"]:
                video_repo.remove_tag(existing["id"], t)
            for t in cmd["add"]:
                video_repo.add_tag(existing["id"], t)
        else:  # noop
            await message.channel.send(embed=video_help_embed())
            return
        updated = video_repo.get(existing["id"])
        await _send_video_card(message.channel, updated, created=False)
        return

    # ── 連結 ingest（一連結一卡，多連結平行）──
    links = detect_links(message.content or "")
    if links:
        caption = strip_urls(message.content or "")
        async with message.channel.typing():
            results = await asyncio.gather(
                *[asyncio.to_thread(video_ingest.from_url, lk["url"], caption=caption)
                  for lk in links],
                return_exceptions=True,
            )
            for lk, res in zip(links, results):
                if isinstance(res, Exception):
                    v, reason = None, f"處理失敗：{res}"
                else:
                    v, reason = res
                if v:
                    await _send_video_card(message.channel, v, created=v.get("_created", True))
                else:
                    await message.channel.send(embed=video_missing_embed(reason))
        return

    # ── help / ? / 純文字 → 發小抄（越笨越好）──
    await message.channel.send(embed=video_help_embed())
