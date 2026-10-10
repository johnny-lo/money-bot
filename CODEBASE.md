# Codebase Index (AI Quick Reference)

> 供 AI 快速理解專案結構，每次 commit 時更新。
> Last updated: 2026-09-22

## Stack

Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL 15 / Gemini API / LINE Bot SDK 2.4.3 / discord.py / APScheduler / Playwright (Chromium) / ECharts 5 / Docker Compose + Tailscale Funnel

## File Map

```
.
├── main.py              # 入口：FastAPI app 建立、DB 初始化、APScheduler 排程、Discord Bot 監管式啟動（run_discord_bot）
├── core.py              # 核心業務邏輯：文字指令解析/處理、圖片記帳、訊息路由 + Data API（Discord embeds 用） + `bucket_context()`/`_month_categories_with_shared()`(算四桶水位;收入基準是**個人的**,所以共同分攤支出只計 `SHARED_SPLIT` 那一份,否則全額房租拿去比個人收入會灌水;基準優先序 本月實收→上月實收→`MONTHLY_INCOME`;**任何失敗回 None**,記帳絕不能因為算水位失敗而失敗)
├── line_handler.py      # LINE Bot：webhook /callback、文字/圖片訊息事件處理（純文字介面）。**憑證可選**：`LINE_ENABLED` 為假時整段跳過掛載,不再 import 期崩潰拖垮全站（測試 tests/test_line_optional.py）
├── discordbot/          # Discord Bot package（原 discord_handler.py 拆分，邏輯不變；不能叫 discord 會遮蔽套件）
│   ├── bot.py           # MoneyBot client：on_message 頻道分流、on_raw_reaction_add(✅ 標去過)、create_discord_bot、run_discord_bot（監管迴圈：暫時性失敗退避重試、壞 token 停手；on_ready/重試訊息 flush=True 即時可見）
│   ├── commands.py      # 28 個 slash commands 註冊（記帳/查詢/固定收支/美食/食譜/測試報表）；BASE_URL 在此
│   ├── embeds.py        # 全部 embed builders + 顏色常數 + fmt_money/fmt_dt（純呈現層）
│   ├── ingest_handlers.py # 美食/食譜/圖片記帳的 on_message 處理（handle_food_message/handle_recipe_message/do_image_recording）
│   ├── reports.py       # 週報/月報/發票通知：_query_period 彙總 + _generate_ai_comment + notify_*
│   ├── bridge.py        # sync→async 橋接：set_bot/post_embeds_sync（排程 thread 投遞 embeds）
│   └── autofix_ui.py    # 自動修復 Discord 端：`can_act`（只限 AUTOFIX_OWNER_USER_ID、狀態 reported、7 天內）、`AutofixButton`（DynamicItem，custom_id `autofix:deploy|abandon:<id>`，bot.setup_hook add_dynamic_items → 重啟後仍可按）、`process_outbox`（bot 每 30 秒輪詢 autofix/outbox/，同事件先報告後部署結果，壞檔改名 .bad）。測 tests/test_autofix_ui.py
├── gemini.py            # Gemini API 封裝：gemini_image(model=, schema=)（單次呼叫；schema → generationConfig.responseJsonSchema）、gemini_text()、generate_persona_comment()（錢鼠阿財記帳評論，走 Gemini 文字）。
│                        # **影像一律走 vision_text()**：MODEL_NAME → GEMINI_FALLBACK_MODELS 逐個退避 →（allow_codex=True 才）codex_image。
│                        # validate= 可傳「答案合不合格」檢查——模型拒答時是 HTTP 200 回一段道歉文，不驗內容退避會有一半是假的
├── captcha_ocr.py       # 本地 CAPTCHA 辨識（ddddocr，4ms/張、不出網）+ 樣本收集。
│                        # recognize() 回 5 位數字或 None；digitize() 把誤認的字母換回數字（7 常被認成 t/z）。
│                        # save_sample() 只在**登入成功後**存（那時答案才確定對），檔名即標註；
│                        # 目錄容量上限 CAPTCHA_SAMPLE_MAX_BYTES（預設 1GB），超過從最舊刪起。
│                        # ddddocr 是**可選依賴**：沒裝就回 None，退回 gemini.vision_text
├── codex_cli.py         # codex_text(prompt, schema=) / codex_image(prompt, bytes, schema=)（schema → `--output-schema`；`codex exec -i`，影像退避的最後一層；**CAPTCHA 不能用**，codex 政策上拒答）：shell 出去呼叫本機 `codex exec`（ChatGPT 訂閱制，模型見 ~/.codex/config.toml），用 --output-last-message 取乾淨輸出。供「分類 + 週/月報評語」的文字生成用，取代計費的 Gemini 文字 API（CODEX_MODEL env 可覆蓋模型）
├── database.py          # SQLAlchemy engine/SessionLocal/Base 建立（讀 DATABASE_URL）
├── models.py            # ORM 模型：Transaction(支出)、Income(收入)、RecurringRecord(固定收支)
├── categorize.py        # AI 分類（走 codex_text / 訂閱制）：CATEGORIES(15 細類,含投資與家電3C)/CATEGORY_GROUPS(細→大組)/GROUP_ORDER、run_weekly_categorization()(只處理 NULL)、run_full_recategorization()(清掉全部重跑)、**classify_one(item, amount)**(單筆即時分類,重用 CATEGORIZE_RULES;給固定支出建立時用——品名每月都一樣,沒必要每筆留 NULL 等週日重猜,那會害「固定」桶每個月初空著、未分類暴增;越界值回 None 不硬塞)、category_group()。AI 分批 50 筆送，避免單次 prompt 太長
├── report_helpers.py    # 報表純函式（無 DB / 無網路）：compare(對比)、top_n_expenses、detect_anomalies、sparkline/daily_heatmap、savings_rate、budget_status、日期工具(week_range/month_range/is_first_sunday 等)。全部由 tests/test_report_helpers.py 覆蓋（49 個測試）。**另有四桶水位純函式**：`CATEGORY_BUCKETS`(細類→投資/固定/生活/爽,跟 6 大組是不同的軸——大組答「花在什麼」,桶答「該不該花」)、`parse_bucket_ratios`(「投資:固定:生活:爽」如 2:4:2:2 →正規化;數量不符或寫壞退回等分)、`bucket_totals`(回 (每桶金額, **未分類金額**);未分類要單獨回,因為記帳當下 category 是 NULL、要等週日 AI 分類才落桶,不揭露會讓水位低估)、`format_bucket_context`(組給 AI 角色讀的文字,income<=0 回 None)、`split_shared(rows, ratio)`(把 shared=1 的支出折成自己那一份再依分類重新加總;**DB 存全額、到這裡才折**——家庭總支出仍正確,改分攤比例不必重寫歷史)
├── tests/               # pytest 測試。跑法：`docker compose exec app pytest tests/ -v`
├── recurring.py         # 固定收支：run_daily_recurring() 每日自動寫入到期項目
├── auth.py              # 認證兩層：短效報表 token(30min,in-memory)generate/validate_report_token + PWA 長效裝置 token(DB,無期限,記 last_used_at)create/validate/revoke_device_token。require_token 收 query token 或 X-Device-Token header 擇一。**短效 token 帶 `can_mint_device` 旗標**(`report_token_can_mint_device()` 查詢,預設 False)：LINE/Discord 發的邀請函 True,PWA 用裝置 token 鑄來開報表頁的那顆 False——否則 device→short→device 成環,`routes/device.py`「洩漏的裝置 token 無法自我繁殖」就不成立。測 tests/test_report_token.py
├── einvoice.py          # 財政部電子發票同步：Playwright 登入 → CAPTCHA(Gemini) → 抓發票 → 寫 transactions。`sync_invoices()` 回傳 `{"summary": str, "new_items": list[dict]}`，支援多組載具（EINVOICE_PHONE_1/2 + PASSWORD_1/2）。**明細逐品項抓取**：清單與明細同一 SPA URL，明細開在 Bootstrap modal；`_parse_current_page` 對每筆「點號碼→等 modal→`_fetch_detail_items`(限定 modal 內品名表)→`_close_detail_modal`(關 modal,**嚴禁 go_back**)→下一筆」，故每張發票的每個品項各寫一筆 transaction（抓不到明細才退化成賣方+總額一筆）。回歸測試 tests/test_einvoice_detail.py（Playwright 靜態 fixture，主機無 Playwright 則 skip）。**歷史月份回填**：`_scrape_carrier(..., month=(y,m))` 用 `_set_query_month` 操作 vue-datepicker 把查詢區間設成『單月』(政府站限制每次查詢須同月，跨月會被擋)；翻頁用 `_NEXT_PAGE_FIND/_NEXT_PAGE_CLICK`(Bootstrap `a.page-link「下一頁」`，舊版 aria-label/rel=next 從沒中過 → 多頁只抓第 1 頁)。回歸測 tests/test_einvoice_pagination.py。**`_save_invoices()` 兩條寫入路徑（逐品項 / 抓不到明細的保底）都會存 `seller`＝賣方原始全名**（不是 `simplify_seller()` 的結果——簡化有損且讀取時隨時能做，原始值沒存就救不回來；空字串→NULL）。寫入契約測 tests/test_invoice_seller.py。**登入落地判斷**：`_login_landing(url, body)` 分 search／elsewhere／unknown——財政部可能把帳號導到資料設定頁（btc508w），已登入（有「登出」）就由 `_goto_search_page` 點「發票查詢及捐贈」轉去查詢頁，測 tests/test_einvoice_login_landing.py。**登入全敗拋 `LoginFailed(attempts)`**（`_login` 逐次呼叫 `_login_attempt` 回 True/False/None；以前全敗回 `[]` 被當「抓 0 張成功」、高水位照推→漏抓），補拓記失敗、高水位不推進，測 tests/test_einvoice_login_failed.py
├── invoice_backfill.py  # 發票智能補拓：`build_month_plan(gap_start,today)`(純函式,缺口拆逐月查詢計畫,政府站同月限制)、`get/set_last_covered`(invoice_sync_state 高水位 repo)、`sync_with_backfill(today=None)`(算缺口→`_scrape_one` 複用 einvoice `_scrape_carrier`/`_save_invoices`→去重存→全成功才推進高水位;失敗回 failures、不推進)。BACKFILL_CAP_DAYS=60、bootstrap=today-1。測 tests/test_invoice_backfill.py(純 plan + monkeypatch 編排)
├── autofix/             # 自動修復流水線（spec: docs/superpowers/specs/2026-10-10-autofix-pipeline-design.md）：持續性 bug 到門檻 → 喚醒主機 Claude 修 → Discord 核可 → 部署
│   ├── policy.py        # 純函式決策：`decide(latest Snapshot, key, now, Policy)`→noop/new/count/dispatch/escalate；門檻 `POLICIES`、修好 7 天內再犯升級人工、`merge_context`。測 tests/test_autofix_policy.py
│   ├── incidents.py     # DB 外殼：`raise_incident(sensor,signature,title,context,dedupe_key)`（with_for_update 鎖列防重複派發；到門檻原子寫 `autofix/inbox/<id>.json`）、`clear(prefix=)`、`get`、`mark`。**對外函式全吞例外**（感測器不能讓業務失敗）；`AUTOFIX_ENABLED!=1` 全 no-op；交接目錄不存在只印 log 不建立。測 tests/test_autofix_incidents.py
│   ├── sensors.py       # 三種感測器：`login_failed/login_ok`（invoice_backfill 捕 LoginFailed，台北日期去重，同載具其他月份直接 break 不燒登入次數）、`extract_failed/extract_ok`（food/recipe/video ingest 抽取點，網址去重、簽名 模組:平台）、`job_failed/job_ok`（main.py APScheduler EVENT_JOB_ERROR|EXECUTED 監聽器；簽名 `job|例外|檔案:函式` 刻意不含行號）。測 tests/test_autofix_sensors.py
│   ├── prompt.md / rules/<sensor>.md / prompt.py  # Claude 的 prompt：明確載入 superpowers systematic-debugging→TDD→verification、無頭改寫（不能問人→questions_for_human）、可用指令與禁區、各感測器重現規則。prompt.py **只用 stdlib**（主機 python3 跑）
│   ├── report.py        # **stdlib only**：`validate` 把「宣稱 fixed 但測試沒全綠/沒 commit/改到禁區」降級 inconclusive；`finalize` 讀 worktree 的 .autofix-report.json + git 資訊 → outbox 訊息與 state/<id>.diff。測 tests/test_autofix_report.py
│   ├── claude-settings.template.json  # claude -p 權限白名單（__AF__ 由 run.sh 代換）：只准讀/編輯 worktree、git 唯讀+commit、bin/test、bin/probe、Skill；禁 docker/.env/push/merge/上網/AskUserQuestion
│   ├── run.sh           # 主機：取最舊 inbox → git worktree ../linebot-autofix-<id>（drill 先套 drill.patch）→ timeout 45m claude -p → report.py finalize → outbox。AUTOFIX_DRY_RUN=1 用 testing/fake-claude.sh
│   ├── bin/test         # 一次性容器跑 worktree 的 import 預檢＋全套測試；附拋棄式 Postgres（--internal 網路，不能對外；main.py import 時就 create_all）
├── persona.md           # AI 角色設定（**本機私人檔,.gitignore 不入版控**）。gemini.py 找不到就退回 `persona.example.md`,全新 clone 也能跑。判斷基準是**四桶（投資/固定/生活/爽）桶位**而非金額大小;摘要沒帶桶位資訊時**預設沒超支、禁止說教**（舊版只看金額→每筆稍大的都被念）。寫法與踩過的坑見 persona.example.md
├── resource/            # Discord 頻道歡迎 banner 圖（手動放入，由 _setup_discord 一次性上傳；已 .gitignore 不入版本控制）
├── food/
│   ├── __init__.py
│   ├── tw_divisions.py  # 台灣行政區劃資料表（純資料）：TW_CITIES(22 縣市,台-form)、CITY_ALIASES(升格舊名+無歧義簡稱;刻意不收「新竹」「嘉義」——市/縣歧義)、TW_DISTRICTS(368 鄉鎮市區)、DISTRICT_ALIASES(五都升格舊名,由現行區名機械換後綴推導,零打字風險)
│   ├── regions.py       # 地名正規化（純函式）。**兩套正規化別搞混**：canon()=模糊比對鍵(去後綴,只給 region_matches 用,剝完至少留兩字否則「東區」→「東」會讓「台東」亂命中)；normalize_city()/normalize_district()/parse_tw_address()=**儲存格式**(縣市全名+合法鄉鎮市區)。resolve_region(address, components)=唯一入口,台灣以地址文字為單一真相(Google 的行政區 component 時有時無、竹北市/竹東鎮從沒給過),國外走 components 原邏輯。行政區用**錨定前綴比對**而非 regex 掃描——里名與行政區同形是常態(中壢區中壢里、東區南市里)。region_matches(query,country,city,district=None)：全名精確 > 帶市/縣後綴只認全名 > canon 後互相包含
│   ├── places.py        # Google Places (New) 整合：search_text(query)→dict|None、maps_url(place_id)→str、fetch_reviews(place_id)→list、caution_for_place_id(place_id)→str(低星評論 AI 雷點摘要)、recommended_for_place_id(place_id)→str(評論萃取推薦菜)、fetch_place_photo(place_id)→(bytes,ext)|None(抓一張 Google 照片)。
│                        # **失敗看得見**(2026-09 免費試用到期整個專案被停用,每發 403 但 log 一行都沒有,撐了好幾天)：`PlacesUnavailable`(帶 status/reason/**detail**)讓呼叫端分得出「服務掛了」vs「Google 查無此店」——兩者給的建議完全相反;
│                        # 純函式 `describe_api_error(status, body)` 把 Google 回應翻成人話——**有 `details.reason`＝金鑰層**(限制清單/referer/IP),**沒有 reason 的 403＝專案層**(帳單/試用到期/服務未啟用),後者最會騙人;
│                        # `_log_failure` 統一格式 `⚠️ Places <做什麼> 失敗（連續第 N 次）：<人話>`,**連續次數＝壞多久了**(成功即歸零);訊息分層：短訊息進 Discord 卡片、`detail` 只進 log(補件卡片兩個人都看得到,「帳單失效」不是使用者的待辦)。測 tests/test_places_errors.py
│   ├── photos.py        # 店家照片庫：檔案存 media/food/<id>/、DB(food_photos) 只記相對路徑。add_photo()/list_photos()/photos_by_place()(批次防 N+1,回 {id,url,source})/delete_photo()/delete_files_for_place()
│   ├── enrich.py        # 店家自動補強 orchestrator：enrich_place()(推薦菜空才補、google 照片沒有才抓,idempotent)、backfill_all(max_api_calls=200)(一次性補全部,docker exec 跑;API 呼叫預算超過即停,重跑自動接續)
│   ├── links.py         # URL 偵測 + 平台判斷（純函式，無 I/O）：find_urls()、classify_platform()(youtube/instagram/threads/tiktok/facebook/gmaps/other,子網域邊界比對防釣魚)、strip_urls()、detect_links()、first_link()
│   ├── extract.py       # 截圖/文字/連結 → 欄位 JSON（**deep_extract_via_codex 跑 `-s read-only` + `tools.web_search=true`,絕不可改回 danger-full-access——它處理的是攻擊者可控的網頁內容;prompt 內另有不可信資料聲明當第二層**）：parse_extracted_json()(純函式)、from_image()(Gemini Vision)、from_text()(codex)、parse_video_id()(YouTube 11 碼 ID,純函式)、gmaps_place_name()(Google Maps URL path 解店名,純函式)、parse_og()(HTML body 抽 og:title/description,純函式)、from_url(url, platform)(I/O wrapper,yt-dlp 主 + og fetch 備援,Maps follow redirect→gmaps_place_name；og fetch 用 facebookexternalhit UA 才拿得到 Threads/Meta 平台 og 標籤)、deep_extract_via_codex()(全 access codex CLI 深度振查,看圖+搜尋交叉驗證,前兩層抽不到店名才動用)。**SSRF 守門 `_is_safe_fetch_url`**:`_http_get` 與 `deep_extract_via_codex` 入口都先過它,只放行公網 http(s),擋掉 file://、非 http(s) scheme、localhost/127.x/169.254(metadata)/10.x/192.168.x 等內網位址(防被誘導抓內網或讓 full-access codex 被指向 localhost)。三個 prompt(_TEXT_PROMPT/_IMAGE_PROMPT/_DEEP_PROMPT)精準區分 recommended_items(文中明確稱讚/必點/招牌的具體菜名,例:歐巴豬五花) vs cuisine_type(店家主要販售的料理類型,例:拉麵/咖啡/早午餐),避免把料理類別誤塞進推薦欄 + `parse_place_list`（一次 codex 批解析）
│   ├── pending.py       # 需補件 in-memory 暫存(無 TTL,重啟丟失)：remember()/get()/consume()/clear()
│   ├── ingest.py        # orchestrator：extract → places → upsert → 事後雷點(best-effort)。回 (place|None, missing_reason)。**`PlacesUnavailable` 單獨接**：單則回「服務暫時不可用…不是這家店的問題」(訊息裡不准出現「找不到」);批次 `_resolve_one` 回 `unavailable: True`、`batch_from_text` 聚成 `buckets["unavailable"]` 計數,`food_batch_summary_embed` 據此改口不再說「加上地區再重貼」(服務掛掉時那是錯的建議)。測 tests/test_food_ingest_unavailable.py。`from_url(url, *, caption='')` 用 extract.from_url 抽 blob → codex from_text → 抽不到店名再 deep_extract_via_codex → _from_fields 入庫 + `batch_from_text`（批次匯入 orchestrator）、`strip_checkbox`/`is_batch`/`take_capped`/`bucket_line`/`dedupe_resolved`（純函式）
│   ├── cuisine.py       # 料理兩層分類（純函式）：MAJORS(12 大類)、normalize_major()(持久化邊界守門員,越界值一律清空)、classify(raw,*,name,items)→(大類,細類)。三層優先序 A 店型(咖啡甜點/飲料冰品) > B 菜系國別 > C 弱品類(火鍋/燒烤/早午餐/酒吧)：日式燒肉→日式(B勝C)、法式甜點→咖啡甜點(A勝B)。**分層只套用在 cuisine_type(描述店)**；店名/推薦菜(描述菜)純最左命中,否則推薦菜提到蛋糕的餐廳會變甜點店。詞彙表只住這裡,不進 LLM prompt(兩份必漂移)
│   ├── repo.py          # food_places 表 CRUD：upsert_place()(**唯一寫入咽喉點**：內含 normalize_region + classify + 「非空不被空覆寫」守衛,混格式列結構性不可能出現)、normalize_region()(純函式,台灣收斂全名、國外原樣)、list_places(status)、set_visited()、to_dict()、set_message_id()、update_caution()、set_visited_by_message_id() + `delete_place`
│   ├── backfill_taxonomy.py # 一次性回填（docker exec 跑）：純規劃器 plan_region_rows/plan_cuisine_rows(可單測不連 DB) + 薄寫入器 run(kind,dry_run=True,mode,force)。dry_run 預設、寫入前備份 .backups/、解不出縣市即中止(除非 force)、逐列 commit、冪等(重跑 0 changed)。另有 verify_invariants() 全表掃越界值、restore_from(path) 一鍵還原
│   ├── map_data.py      # build_map_places(places)(純函式)：過濾無座標、整形地圖 marker JSON、status→visited、組 maps_url、帶 district/cuisine_major/cuisine_minor（cuisine_type 仍保留：舊 SW 快取殼還在讀）
│   └── recommend.py     # 推薦邏輯（純函式）：filter_for_recommendation()(命中國家/縣市/行政區)、sort_recent()、pick_random()
├── recipe/
│   ├── __init__.py
│   ├── extract.py       # blob/文字→乾淨菜名：parse_name_json 純函式 + name_from_text codex
│   ├── repo.py          # Recipe DB 存取：add_recipe url 去重+IntegrityError 防護 / list / pick_random / delete / rename / set_message_id / get_by_message_id
│   └── ingest.py        # 連結→菜名→入庫 orchestrator：gmaps 略過 + None/空白-blob guard
├── video/               # 歷史教學影片（連結收集器；複用 food.extract yt-dlp）
│   ├── __init__.py
│   ├── extract.py       # 純函式：parse_video_meta(LLM JSON→{topic,tags},安全降級) + meta_from_text codex + youtube_thumbnail(複用 food.extract.parse_video_id)
│   ├── commands.py      # 純函式 parse_reply_command（#主題/+標籤/-標籤/改標題/noop）+ CHEAT_SHEET 小抄文字（卡片 footer 與 help 共用單一真相）
│   ├── repo.py          # HistoryVideo+VideoTag DB 存取：add_video url 去重 / list_videos(附 tags) / rename / set_topic / add_tag(冪等)/remove_tag / tags_by_video(批次防 N+1) / delete / set_message_id / get_by_message_id
│   └── ingest.py        # 連結→{topic,tags}+標題→入庫+掛標籤 orchestrator：AI 失敗不擋入庫(標題退 blob 第一行)
├── .github/workflows/ci.yml  # GitHub Actions：backend(pytest + **import 預檢** + `scripts/healthcheck.sh --self-test`,帶 postgres service + Chromium——einvoice 兩個回歸測試會真的開瀏覽器,不裝是 fail 不是 skip) / frontend(npm ci + build)。CI 必須給 DATABASE_URL 與假的 LINE 憑證,否則 database.py / line_handler.py 在 **import 期**就炸
├── .env.example         # 環境變數範本（README 的 `cp .env.example .env` 用）；真 .env 不入版控
├── persona.example.md   # persona.md 的**寫法教學**（怎麼寫判斷規則、為什麼不能給口頭禪清單、資料不足時的預設行為）
├── requirements.txt     # Python 依賴
├── Dockerfile           # python:3.11-slim，pip install → uvicorn 啟動
├── docker-compose.yml   # **兩個**服務：app(127.0.0.1:8000)、db(PostgreSQL，僅 docker network；帳密可由 .env POSTGRES_* 覆蓋)。**對外出口是主機上的 Tailscale Funnel**（`tailscale funnel --bg 8000`），不是容器——原本的 ngrok service 已移除，因為免費版攔截頁會讓瀏覽器抓 sw.js 時拿到 HTML、SW 註冊靜默失敗（詳見 AGENTS.md）
├── routes/
│   ├── __init__.py
│   ├── report.py        # 報表 API：/api/report/monthly|category|summary|ledger + /report 頁面（year/month Query ge/le 驗證,違規回 422）+ **POST /api/report-token**(PWA 用裝置 token 換 30 分鐘短效 token 開報表頁,`can_mint_device=False`) + **GET /report/ledger_filter.js**(直接吐 `frontend/src/ledgerFilter.js` 原始碼,不經 build——報表頁與 PWA 共用同一份篩選純函式,複製第二份的下場是兩邊語意漂移)
│   ├── record.py        # CRUD API：POST/PUT/DELETE /api/record（供網頁報表使用）
│   ├── food_map.py      # 美食地圖：GET /food/map(舊 HTML 頁) + GET /api/food/places(每家帶 photos [{id,url,source}]) + PWA 寫操作：POST .../{id}/visited(評分1-5/心得,超範圍當沒給)、POST .../{id}/photos(multipart,5MB/張,10張/店,Content-Type 白名單)、DELETE /api/food/photos/{id}
│   ├── recipes.py       # 食譜 JSON API（PWA 用）：GET /api/recipes、PUT /api/recipes/{id}(改名,空白名 422)、DELETE /api/recipes/{id}。新增仍走 Discord（要連結抽取 pipeline）；隨機抽在前端做
│   ├── videos.py        # 影片 JSON API（PWA 🎥 用）：GET /api/videos(附 tags+thumbnail) / PUT /api/videos/{id}(改標題或設主題,空白名 422) / POST .../{id}/tags(加標籤) / DELETE .../{id}/tags/{tag}(刪標籤) / DELETE .../{id}。新增走 Discord
│   ├── health.py        # GET /healthz：**免 token** 的對外健康檢查（app 活著 + DB `SELECT 1`）→ 200 `{"status":"ok"}` / DB 不通 503 `{"status":"unavailable"}`。**回應被當公開資訊**：不回版本號/路徑/env/連線字串，DB 例外只 print 進伺服器 log（SQLAlchemy 錯誤字串含帳密與主機名）。帶 `Cache-Control: no-store`——健康檢查拿到快取的舊答案＝謊報健康。測 tests/test_health_api.py（7 個，含「不洩漏」斷言）
│   └── device.py        # POST /api/device-token：用「有效短效 token」換發長效裝置 token（只收短效,洩漏的裝置 token 無法自我繁殖；**且那顆短效 token 必須 `can_mint_device`**,PWA 自鑄的回 403,封住 device→short→device 的環）。前端 api.js ensureAuth 換發後存 localStorage、清掉網址 token,之後走 X-Device-Token header
├── frontend/            # 手機版 PWA（React+Vite+vite-plugin-pwa）：**四 tab 全實裝**——美食(Food/Nearby/FoodList/FoodMap/PlaceSheet/geo.js/cuisine.js；**預設「附近」模式**：定位→範圍滑桿(1/3/5/10/30km,車程標註是手工校準常數表**不是公式**——長程走國道,km×3 會把 30km 算成 90 分而那一檔就沒人按)→料理磚塊帶家數→點磚塊才列店。定位失敗**自動退回清單**+banner,絕不卡首屏。附近模式整排隱藏第二列篩選(範圍由滑桿決定、料理由磚塊決定,再擺一套只會打架)。三態切換 附近/清單/地圖 用**分段控制**(目前模式高亮)——原本是顯示「下一個模式」圖示的循環鈕,使用者看不出自己在哪個模式,又因為地區篩選只在清單/地圖渲染,導致「行政區不見了」被回報兩次;附近模式另加一行指路文字。右下角有 build 時間戳(vite define __BUILD_ID__),用來一眼判斷手機拿到的是不是新版。清單/地圖模式才有地區 select + 12 大類 chips。**地區是單一分組選單(optgroup 依縣市)不是兩個級聯 select**——級聯版的行政區被兩道預設關著的關卡擋住(要 view!=='nearby' 且已選特定縣市才渲染),使用者根本找不到;合併後一次點擊就到,且「換縣市忘了重置行政區」那類 bug 結構性消失(一個控制項＝一個真相來源)。geo.js 是無 React 純函式(haversineKm 缺座標回 Infinity 不回 0,否則沒座標的店會出現在每個範圍),可用 `node --input-type=module` 直接跑驗,不必為三個函式引入 JS 測試框架)、消費(Spend 吃 /api/report/ledger 整月前端算+RecordSheet CRUD;**點分類長條/日期標頭＝篩選**,三格頭與分類占比刻意吃整月不跟著篩——篩選後的數字只放摘要列,而且分類長條自己就是篩選器,被自己篩到剩一條就點不回去;右上 📊 報表鈕先 `window.open('')` 同步開空分頁再填網址,等 await 回來才開會被當非使用者手勢擋掉)、食譜(Recipe.jsx 拉霸隨機抽=前端 random+減速動畫,清單/改名/刪除)、歷史(Videos.jsx 主題書架 chips **依影片數排序並顯示數量**（21 書架/33 影片,不排序的話有東西的會被埋在只有一支的後面）+標籤/關鍵字搜尋,useMemo 衍生過濾,點卡片 sheet 改主題/加刪標籤/開連結/刪除)。**更新機制三層**(手機主畫面 App 沒有重整鈕、iOS 是暫停非終止 → 瀏覽器的 SW 更新檢查永遠不觸發): ①main.jsx 在 visibilitychange/focus/30min 主動 `registration.update()` ②update.js 直接 fetch index.html 比對 bundle 檔名(不依賴 SW 自我回報)→ 落後跳更新條 ③forceUpdate() 清快取+unregister+reload(**保留 media\*照片**);右下角 build 時間戳供一眼判版。manifest+SW(injectManifest 自製 src/sw.js:precache+API NetworkFirst+media CacheFirst-v2 帶 ngrok 跳過 header——img 標籤帶不了 header,SW 重發才繞得過攔截頁)、icons 在 public/。build:`cd frontend && npm run build`(script 內含 NODE_OPTIONS webcrypto flag,Node 18 需要)→ dist/ 由 main.py 掛 /m/（目錄不存在自動跳過;.webmanifest MIME 已註冊）。node_modules/dist/.env(VITE_* 金鑰) 不入版控。
│                        # **`src/ledgerFilter.js`＝流水帳篩選純函式**(applyFilters/toggleCond/summarize/chips/hasCond,無 React 無 DOM)：PWA 走 vite build import,報表頁走 `/report/ledger_filter.js` 載同一份原始碼。測試 `src/ledgerFilter.test.mjs` 用 Node 內建 runner(`cd frontend && npm test`,16 個),CI frontend job 會跑
├── scripts/             # **跑在主機上**的維運腳本（不是容器內——對外出口 Tailscale Funnel 就在主機上）
│   ├── healthcheck.sh   # 對外健康檢查 + 自動修復 Funnel + Discord webhook 通知。**一定從公開路徑打**：`dig +short @1.1.1.1 <host> A` 拿入口 IP（**不寫死，每次重查**）→ `curl --resolve <host>:443:<ip>` 強制走它。用系統解析會走 MagicDNS 解到 100.x 內網＝沒走 Funnel＝驗了等於沒驗（2026-08-29 就是這樣誤判整站對外中斷）。**連續 2 次**失敗才動作 → `tailscale funnel --https=443 off` + `--bg 8000` → 等 6s 重驗 → 通知；修好也通知；修不好就 latch **停手**（不無限重試踢服務）；自己好了通知並解閂。**核心判斷 `classify()`：TLS 握手成功（curl `%{time_appconnect}`>0）＝入口正常＝app 問題 → 只通知不碰 Funnel；沒握到手＝入口沒註冊（`no peer certificate available`，事故簽名）→ 才修**。純函式 `env_value`/`host_of`/`classify`/`decide` + 修復路徑（假 tailscale 驗指令順序）全由內建 `--self-test` 覆蓋（31 項，不出網不碰真 funnel）。另有 `--status`/`--reset`/`--help`。狀態檔在 `$XDG_STATE_HOME/linebot-healthcheck/state`，flock 防重入
│   └── systemd/         # systemd **user** timer 範本（免 sudo）：linebot-healthcheck.{service,timer}，開機後 2 分鐘 + 每 5 分鐘。**不自動安裝**，安裝步驟見 README
├── media/               # 使用者/Google 店家照片（.gitignore 只留 .gitkeep）；main.py 掛 /media/
└── templates/
    ├── report.html      # 互動式報表 SPA：ECharts 圖表 + 流水帳 CRUD（純前端 JS）。品名/分類經 esc() 跳脫再進 innerHTML（防發票品名 stored XSS）,編輯/刪除用 index 回查不塞 JSON 進屬性。
    │                     # **圖表點擊→篩明細**：單一 `conds` 物件({type,category,day,month})當唯一真相,圖表/鈕/下拉都寫進它(兩個真相來源遲早打架);疊加語意來自共用純函式 LF(`/report/ledger_filter.js`)。
    │                     # 折線與長條**不綁 series click**(只有戳中那顆小圓點才算,手機戳不到)→ 改 `getZr().on('click')` + `containPixel('grid')` + `convertFromPixel()` 換算欄位,整欄可點。單月模式點長條＝跳月(那個月的資料不在當月流水帳裡,加條件只會篩出空白)。換月/切全部月份會 `dropDateConds()`。
    │                     # 啟動點 `bootReport()` 由尾端的 `<script type="module">` import 完 LF 再呼叫——module 必定晚於 classic script,順序天然保證,不會有「模組還沒到就開始 render」的競態
    └── food_map.html    # 美食地圖頁：Google Maps JS、想去藍/去過綠 AdvancedMarker、點 pin InfoWindow(含雷點)、想去去過 toggle
```

## DB Schema

| Table | Columns | Notes |
|-------|---------|-------|
| `transactions` | id(PK), item(str), price(int), category(str?), invoice_no(str?), **source(str?, index)**, **seller(str?, index)**, **shared(int, 預設0)**, created_at(datetime) | 支出。invoice_no 是發票去重 key。**source＝資料通道**（`載具1`/`載具2`/`discord`/`line`/`app`/`recurring`）——兩組載具分屬兩人，所以它同時回答「這筆是誰花的」；載具編號在 einvoice 同步時就知道，接進 `_save_invoices(source=...)` 即全自動。**seller＝賣方店名**（發票同步帶入，手動記帳為 NULL）——存**原始全名**「全家便利商店股份有限公司」而非 `simplify_seller()` 的結果：簡化是純函式、讀取時隨時能套，原始值沒存就永遠救不回來；空字串正規化成 NULL（「不知道」不該在 group by 裡變成一家假店）。有 index 是因為它的用途就是 group by 賣方 / 未來 join `food_places`（「這家店去過幾次、總共花多少」）。⚠️ **歷史資料救不回來**：`_save_invoices()` 一直拿得到 `inv["seller"]`（`format_item()` 用它補品名前綴、保底那筆直接拿它當品名）卻從沒寫進 DB，賣方在爬蟲當下就丟了——既有 697 筆發票消費永遠是 NULL，這欄**從上線那天起才開始累積**。**shared=1＝兩人共同分攤**，DB 存**全額**，算「我的份」時才除以 2（家庭總支出仍正確，改分攤比例不必重寫歷史） |
| `incomes` | id(PK), item(str), amount(int), category(str?), created_at(datetime) | 收入 |
| `recurring_records` | id(PK), type("expense"/"income"), item, amount, category?, day_of_month(1-28), active(1/0), **shared(int)**, created_at | 固定收支；shared 會被每月自動產生的 Transaction 繼承。建立時會呼叫 `categorize.classify_one()` 分類一次並存在 record 上,每月產生的 Transaction 直接繼承。設定方式：LINE `固定 支出 房租 12000 5 共同`（尾綴可選）/ Discord `/固定支出` 的 `共同分攤` 選項；`固定清單` 會顯示 🤝 標記 |
| `food_places` | id(PK), place_id(str?), name, address?, lat?, lng?, country?, city?, district?, cuisine_type?, recommended_items?, caution_summary?, status("想去"/"去過"), my_rating(int?), my_note?, source_url?, updated_at, created_at | 美食地圖（Phase 1A+） |
| `recipes` | id(PK), name(str), url(str, UNIQUE 去重鍵), discord_message_id(str?, index), created_at | 食譜收錄；url UNIQUE 防重複收錄；discord_message_id 供 reply 卡片更名用 |
| `device_tokens` | id(PK), token(UNIQUE index), label?, created_at, last_used_at? | PWA 長效裝置 token；撤銷=刪列（auth.revoke_device_token） |
| `food_photos` | id(PK), food_place_id(FK→food_places.id, ON DELETE CASCADE, index), path(str, media/ 相對路徑), source("app"/"bot"/"google"), created_at | 店家照片；檔案在 media/，DB 只記路徑 |
| `invoice_sync_state` | id(PK,恆1), last_covered_date(Date?), updated_at | 發票打卡高水位（單列）；已成功涵蓋到的最後一天，驅動智能補拓 |
| `autofix_incidents` | id, sensor, signature, title, status, hit_keys(JSON), context(JSON), first_seen, last_seen, verdict, report_message_id, reported_at, closed_at | 自動修復事件；同 (sensor, signature) 同時最多一筆未結案。新表，開機 create_all 自動建 |
| `history_videos` | id(PK), title(str), url(str, UNIQUE 去重鍵), topic(str?, index, 主分類書架), channel(str?, v1 不自動填), platform(str?), discord_message_id(str?, index), created_at | 歷史教學影片；topic=單一書架 |
| `video_tags` | id(PK), video_id(FK→history_videos.id, ON DELETE CASCADE, index), tag(str, index) | 影片標籤（去正規化多對多）：標籤直接存字串，查=WHERE tag=?、全部=DISTINCT tag |

main.py 啟動時自動 `CREATE TABLE` + 檢查/補上既有表的新欄位（`transactions` 的 category / invoice_no /
source / shared / **seller**、`recurring_records.shared`、`food_places` 的料理兩層分類、`food_photos` 的 FK）
＋建對應索引。**`create_all` 只建新表不改既有表結構**，所以既有表加欄一定要在那段 inspector + `ALTER TABLE`
補一筆；那段 try 會吞例外 → 重啟後跑 `docker logs money-bot | grep -E '✅|⚠️'` 確認真的加成功
（ALTER 沒成功但 model 已有欄位 = 之後每次查 transactions 都 SELECT 不存在的欄位而炸）。

## Request Flow

```
LINE/Discord 訊息
  → line_handler.py / discordbot/bot.py
    → core.process_text_message(msg)  # 文字指令路由
    → core.handle_image(bytes)        # 圖片記帳
      → gemini.py (AI 呼叫)
      → database → models (ORM 寫入)
      → gemini.generate_persona_comment() (角色回應)
  ← 回覆訊息列表
```

```
網頁報表
  → /report?token=xxx (auth.validate_report_token)
    ↑ token 來源二選一：
      ① LINE「報表」/ Discord /報表 → generate_report_token(user_id)          # can_mint_device=True
      ② PWA 消費分頁「📊 報表」→ POST /api/report-token (帶 X-Device-Token)   # can_mint_device=False
    → templates/report.html (前端 SPA)
      → /report/ledger_filter.js (與 PWA 共用的篩選純函式)
      → /api/report/* (報表資料 API，require_token)
      → /api/record/* (CRUD API，require_token)
```

## Scheduled Jobs (APScheduler)

時區 `Asia/Taipei`。

| Job | Schedule | Function |
|-----|----------|----------|
| daily_recurring | 每日 00:05 | `recurring.run_daily_recurring()` |
| daily_invoice_sync | 週一 ~ 週六 21:00 | `_daily_invoice_with_notify()` — `sync_with_backfill()` 智能補拓 + 通知 Discord `#🧾-發票通知`（含「新增明細」second embed；失敗改發失敗卡） |
| weekly_pipeline | 週日 21:00 | `_weekly_pipeline()` — 一條龍：(1) 補拓+通知 → (2) `run_weekly_categorization()` → (3) `notify_weekly_summary()` 週報。**每月第一個週日**（即 `day ≤ 7` 的週日）會額外串接 (4) `notify_monthly_summary()` 推上月完整月結 |
| startup_catchup | 開機後 3 分鐘（一次性 `date` job） | `_startup_catchup()` — 背景補拓一次（機器關了又開盡快追上）；只在有新發票或失敗才發卡 |

## Category Schema (categorize.py)

15 細類 → 7 大組對應，封閉清單（AI 必須從中選一）：

| 大組 | 細類 |
|---|---|
| 固定 | 居住水電、分期保險 |
| 交通 | 交通 |
| 飲食 | 三餐、聚餐、飲料零食、食材、超商 |
| 生活 | 日用品、家電3C、醫療、服飾 |
| 娛樂 | 娛樂 |
| 投資 | 投資 |
| 其他 | 其他 |

- **居住水電** = 房租、管理費、電費、水費、瓦斯
- **分期保險** = 車貸、手機分期、其他貸款攤提、車險、人壽險、意外險
- **交通** = 加油、停車費、車輛保養、洗車、ETC、大眾運輸
- **三餐** = 正餐外食（單筆通常 ≤ 1500 元）
- **聚餐** = 大額餐廳消費、家人/朋友聚餐請客（單筆通常 > 1500 元）
- **超商** = 萊爾富/7-11/全家 等只看得到店名的發票
- 改規則：改 `CATEGORIES` + `CATEGORY_GROUPS` + `CATEGORIZE_RULES`，再呼叫 `run_full_recategorization()` 重跑歷史

## Core Logic: Text Command Routing (core.py)

`process_text_message(msg)` 依序匹配：
1. `說明`/`help` → HELP_TEXT
2. `分類` → run_weekly_categorization()
3. `報表` → generate_report_token() → 回傳連結
4. `固定 支出/收入 品名 金額 日期` → handle_add_recurring()
5. `固定清單` → handle_list_recurring()
6. `取消固定 ID` → handle_delete_recurring()
7. `查詢` → handle_query_monthly()
8. `最近` → handle_query_recent()
9. `刪除收入 ID` → handle_delete_income()
10. `刪除 ID` → handle_delete_expense()
11. `修改收入 ID 品名 金額` → handle_update_income()
12. `修改 ID 品名 金額` → handle_update_expense()
13. `抓發票` / `抓發票 N` → handle_fetch_invoices(days)
14. fallback: handle_record_text() → regex 解析 `品名 金額` 記帳

## Key Patterns

- **DB session**: FastAPI 路由用 `db: Session = Depends(get_db)`（database.py）；一般程式可用 `with session_scope() as db:`（成功 commit/例外 rollback/必 close）。core.py 等舊碼仍是手寫 `SessionLocal()` + try/finally（待 core 有測試後再轉換）
- **LINE handler**: 同步函式，純文字回覆（`line_bot_api.reply_message`），呼叫 `core.handle_*()` 取 `list[str]`
- **Discord handler**: 非同步，slash commands + embeds，呼叫 `core.*_data()` 取結構化 dict 後組 embed
- **Auth**: in-memory token store (dict)，30 分鐘過期，非持久化
- **Gemini 呼叫**: 直接用 urllib.request（非 SDK），手動組 JSON payload；每次呼叫把 `usageMetadata` 印成一行 `📊 Gemini <model> tokens：…`（計費 API 的用量只看得到這裡）
- **結構化輸出**: 要抽欄位的 AI 呼叫都帶 JSON Schema（`vision_text(schema=)` / `codex_text(schema=)`），prompt 只描述欄位語意；schema 根節點一律是 object（OpenAI strict 限制），陣列包一層（`items` / `results` / `places`）
- **雙介面 API 設計**:
  - LINE 用 `core.handle_*()` 系列 → 回 `list[str]`（既有純文字風格）
  - Discord 用 `core.*_data()` 系列 → 回 `dict` / `list[dict]`（給 embed builder 組卡片）

## Discord Bot Architecture (discordbot/ package)

- **MoneyBot(discord.Client)** + `app_commands.CommandTree`
- 27 個 slash commands 全用中文名稱（`/記帳`, `/查詢`, `/最近`, `/測試週報`, `/測試月報`, `/美食新增`, `/美食推薦`, `/美食清單`, `/去過`, `/美食地圖`, `/美食刪除`, `/隨機食譜`, `/食譜清單`, `/食譜刪除` 等）
- 每個 command callback 流程：(1) `await ix.response.defer()` 必要時、(2) 呼叫 `core.*_data()`、(3) 用對應 embed builder 組卡片、(4) `ix.followup.send(embeds=...)`
- 慢 commands（`/記帳`, `/收入`, `/分類`, `/抓發票`）必 defer 避免 3 秒超時
- 配色：支出 `#E74C3C` / 收入 `#2ECC71` / 查詢 `#3498DB` / 錢鼠阿財 `#9B59B6` / 警告 `#F1C40F`
- 圖片附件走 `on_message`，依頻道分流：`RECIPE_INGEST_CHANNEL_ID` → `_handle_recipe_message()`（連結→食譜入庫 + `_send_recipe_card` reply 卡片；gmaps 連結擋掉）；`FOOD_INGEST_CHANNEL_ID` → `_handle_food_message()`（截圖/文字 ingest、reply 補件）；`HISTORY_VIDEO_INGEST_CHANNEL_ID` → `handle_video_message()`（連結→影片入庫+AI 判主題標籤；reply 卡片 `#主題`/`+標籤`/`-標籤`/改標題編輯；help/純文字回小抄）；`DISCORD_RECORD_CHANNEL_ID` → `_do_image_recording()`（圖片記帳）；**未設 RECORD 頻道則退回「任意頻道圖片記帳」舊行為**；其他頻道圖片回指引（`_HINT_DEBOUNCE` 30 分鐘防洗版）。recipe 分支複用 `food.links.classify_platform` / `food.extract.from_url` / `food.pending`；3 個 recipe slash 指令（`/隨機食譜`, `/食譜清單`, `/食譜刪除`）+ 4 個 recipe_*_embed embed builders
- `on_raw_reaction_add`：在 `#美食輸入` 對店家卡片按 ✅ → `set_visited_by_message_id()` 標去過 + 追問評分/心得
- **Sync→Async 橋接**：`set_bot()`/`post_embeds_sync()`(discordbot/bridge.py) 讓 APScheduler 排程（同步 thread）能投遞 embeds 到 Discord。原理：把 coroutine 用 `asyncio.run_coroutine_threadsafe(coro, bot.loop)` 排到 bot 的 event loop
- **頻道結構**（由一次性 setup 腳本建立）：
  - `📊 記帳機器人` (category)
    - `#📝-記帳` — slash commands 主場
    - `#📊-報表查詢` — 月結自動 post 到此
    - `#🧾-發票通知` — 每日抓發票結果自動 post 到此
  - 各頻道頂部釘選歡迎卡片（含 banner 圖、用途說明）
  - 對應 channel ID 存在 `.env`：`DISCORD_RECORD_CHANNEL_ID` / `DISCORD_REPORT_CHANNEL_ID` / `DISCORD_INVOICE_CHANNEL_ID`
- **週報 (`notify_weekly_summary`)** — 本週（週一→週日）embed 欄位：三格頭(收/支/淨) → vs 上週對比 → 大組分布 → 細類分布(前 8) → Top 3 單筆 → 每日支出迷你長條 → 異常分類(近 4 週均值+50%) → AI 評語
- **月結 (`notify_monthly_summary`)** — 上月 embed 欄位：三格頭 → vs 上上月對比 → 儲蓄率 → 預算狀態(`MONTHLY_BUDGET`) → 大組 → 細類(前 8) → Top 3 → 近 6 月 sparkline → 異常分類(近 4 月均值+50%) → AI 評語
- **AI 評語**：兩種報表共用 `_generate_ai_comment()`，走 `codex_cli.codex_text()`（ChatGPT 訂閱制，模型見 ~/.codex/config.toml，不再用計費 Gemini，免 429 配額）+ persona.md 錢鼠阿財。會餵入報表已算好的 vs 上期對比 / 儲蓄率（月）/ 異常暴增分類 / 單筆 Top 3，要求講出具體數字與可執行建議；prompt 依 `period_kind` 分流（週報 2–3 句聚焦本週、月報 3–4 句講趨勢+下月行動）。失敗時欄位會顯示「⚠️ AI 評語生成失敗：{錯誤訊息}」，embed 照樣推。註：錢鼠阿財「記帳當下」評論（generate_persona_comment）仍走 Gemini，只有報表評語與分類改用 codex
- **手動測試**：在 Discord 用 `/測試週報` / `/測試月報` 立即觸發推送（**必須在 bot 主進程內呼叫**，因為 `_bot_instance` 是 module 級狀態；從 `docker compose exec` 開的子進程裡呼叫 `notify_*()` 會靜默失敗）
- **DB 查詢輔助** `_query_period(start, end)` 一次撈完一段期間需要的所有彙總（總額/分類/Top N/每日金額），週報跟月報共用

## Environment Variables

BASE_URL (對外網址，報表/地圖連結用；未設=ngrok 保留域名), LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DATABASE_URL, GEMINI_API_KEY, MODEL_NAME, GEMINI_FALLBACK_MODELS (optional, 逗號分隔；影像辨識退避鏈，留空=沒有備援), CAPTCHA_SAMPLE_DIR (optional, 預設 data/captcha), CAPTCHA_SAMPLE_MAX_BYTES (optional, 預設 1GB；樣本目錄上限，超過從最舊刪起), CODEX_MODEL (optional, 留空=用 ~/.codex/config.toml 設定的模型), MONTHLY_BUDGET (optional, 0/不設=不顯示預算進度), DISCORD_BOT_TOKEN (optional), DISCORD_INVOICE_CHANNEL_ID (optional), DISCORD_REPORT_CHANNEL_ID (optional), DISCORD_RECORD_CHANNEL_ID (optional), EINVOICE_PHONE_1, EINVOICE_PASSWORD_1, EINVOICE_PHONE_2 (optional), EINVOICE_PASSWORD_2 (optional), GOOGLE_PLACES_SERVER_KEY (美食地圖；後端 Places API New 用), FOOD_INGEST_CHANNEL_ID (美食地圖；#美食輸入 頻道), RECIPE_INGEST_CHANNEL_ID (optional; #🍳-食譜 頻道；未設則食譜分支不啟用，不影響美食/記帳), HISTORY_VIDEO_INGEST_CHANNEL_ID (optional; #📜-歷史教學 頻道；未設則影片分支不啟用), GOOGLE_MAPS_BROWSER_KEY (美食地圖 Phase 2；前端 Maps JS,限 ngrok referrer), GOOGLE_MAPS_MAP_ID (美食地圖 Phase 2；AdvancedMarker 必需,未申請填 DEMO_MAP_ID), HEALTHCHECK_DISCORD_WEBHOOK (optional; 對外健康檢查告警,沒設就只寫 log), HEALTHCHECK_FAIL_THRESHOLD / HEALTHCHECK_RESOLVER / HEALTHCHECK_FUNNEL_PORT (optional; 預設 2 / 1.1.1.1 / 8000)

自動修復：AUTOFIX_ENABLED（1＝啟用感測器）, AUTOFIX_CHANNEL_ID（報告頻道）, AUTOFIX_OWNER_USER_ID（唯一能按部署的人）——容器讀，已進 docker-compose.yml 白名單；改了要 `docker compose up -d`。

> ⚠️ `HEALTHCHECK_*` 是**主機上的 `scripts/healthcheck.sh` 讀的，不是容器讀的** → 刻意**不**寫進 `docker-compose.yml` 的 `environment:`（跟上面那條「channel ID 忘了寫進 compose」的坑方向相反，這裡是刻意不寫）。腳本只從 `.env` 挑 `BASE_URL` 與 `HEALTHCHECK_DISCORD_WEBHOOK` 兩個 key，**不 source 整個檔**（避免把一堆金鑰灌進環境、也避免執行檔案內容）。

> codex 整合：`codex` CLI 裝在 app 映像內（Dockerfile 用 `npm install -g @openai/codex@${CODEX_VERSION}` **釘版本**，**非獨立 container**；主機 codex 升級後若 API 回 "requires a newer version of Codex"，改 `ARG CODEX_VERSION` 再 `docker compose up -d --build app`），登入憑證以 `docker-compose.yml` 把主機 `${HOME}/.codex` 掛到容器 `/root/.codex`（rw，讓 ChatGPT 訂閱 token 自動刷新可寫回）。`auth_mode=chatgpt`=訂閱制，不走單次計費 API。

> 注意：channel ID + EINVOICE 系列原本在 `.env` 但沒寫進 `docker-compose.yml` 的 `environment:` block，導致 container 內部 `os.getenv()` 拿不到 → 排程通知都會在 `if not chan_id: return` 靜默退出。已於 2026-05-11 修正。

## 規劃中模組（Specs）

- **美食地圖模組**（**Phase 1A + 1B + 2 + 3 已實作**）：
  - Phase 1A（slash）：`/美食新增`、`/美食推薦`（含🎲隨機）、`/美食清單`、`/去過`，手動建清單 + 縣市/國家推薦
  - Phase 1B（自動）：`#美食輸入` 頻道丟截圖/文字 → `food.ingest`（extract → Places 正規化 → upsert → 低星負評 AI 雷點摘要 best-effort）→ 卡片；抽不到走 `food.pending` reply 補件；✅ 反應標去過
  - Phase 2（地圖網頁）：`/美食地圖` → token 連結 → `routes/food_map.py` + `templates/food_map.html`，Google Maps JS、想去藍/去過綠 AdvancedMarker、點 pin InfoWindow（含雷點）、想去/去過 toggle。`food.map_data.build_map_places` 整形、過濾無座標。browser key 限 ngrok referrer
  - Phase 3（連結來源）：`#美食輸入` 貼 IG/YouTube/TikTok/Threads/Facebook/Google Maps/一般網站連結 → `food.links` 偵測 + 平台分類 → `food.extract.from_url` 抽 blob（**yt-dlp `--skip-download` 主力**抽 caption/title/description；Threads/一般網站走 og fetch + `facebookexternalhit` UA；Google Maps follow redirect → 直接解 URL path 店名）→ codex `from_text` 解店名/地區 → 抽不到再 `deep_extract_via_codex`（全 access、看圖+搜尋交叉驗證）→ `_from_fields` 入庫。`discordbot.ingest_handlers.handle_food_message` 在純文字 ingest **之前**插入連結分流，多連結用 `asyncio.gather` + `asyncio.to_thread` **平行處理一次多家入庫**；抽不到店名（常見於 Threads/FB 店名在圖不在文字）→ 走 `pending` 補件卡（reply 補店名最快）
  - 設計見 `docs/superpowers/specs/2026-05-23-food-map-module-design.md`
  - **關鍵接合點**：`on_message` 依 `FOOD_INGEST_CHANNEL_ID` / `DISCORD_RECORD_CHANNEL_ID` 分流（後者未設則退回舊的任意頻道記帳），避免美食截圖被「拍照記帳」誤記成支出
