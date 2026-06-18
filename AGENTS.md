# AGENTS.md — 在這個 repo 工作的避坑指南

> 給未來在這個 repo 動手的 AI agent（或我自己）。記錄**踩過的坑 + 根因 + 解法思路**，
> 避免重踩。新坑請往下加。搭配看 `README.md`（功能）、`CODEBASE.md`（檔案地圖）。

## 0. 這個專案怎麼跑（先讀這段）

- **一切跑在 Docker，不在 host。** host 沒有 `python`（`rtk: Failed to spawn process`）。
  Python / pytest 一律：`docker exec -w /app money-bot python -m pytest <檔> -v`。
- **container live-mount `.:/app`** → 改完原始碼，container **立刻看得到**，不用 rebuild image。
- **三個容器**：`money-bot`（FastAPI+Discord）、`money-db`（Postgres，無對外 port）、`money-tunnel`（ngrok）。
- **部署節奏（記熟，省最多時間）**：
  - **後端改** → `docker restart money-bot`（**不是** `docker compose up`，那是改 env 才用）。
  - **前端改** → `npm run build --prefix frontend`（host 跑得動 npm；live-mount 直接生效，免重啟）。
  - `frontend/dist` 是 build 產物、**被 gitignore** → 只 commit `frontend/src`。
- **每個功能 commit 必更新 `README.md` + `CODEBASE.md`**（專案鐵律）。純設計/計畫文件 commit 可豁免。

## 頭號鐵則：先全局，後新增（別讓功能野蠻生長）

**加任何新功能前，先讀 codebase 想全局 → 再想怎麼接 → 最後才動手。順序不能反。**

1. **先找最近的既有範式**：要做的東西，repo 裡有沒有「形狀最像」的模組？照它的分層、命名、慣例做。
   - 正例（本 session）：歷史影片模組 = 先把「食譜」連結收集模組**整條讀懂**才設計，能複用的全複用
     （`classify_platform`、`food.extract.from_url`、repo/ingest/embed 骨架、PWA sheet 模式）。
2. **再想全局不變式**：新表/欄/API 會不會跟既有慣例衝突？是不是又造一個輪子？能不能**共用同一組 repo 函式**
   （一個真相、多個薄客戶端）而非各寫一套？（例：影片的 AI/Discord/PWA 三層都呼叫同一組 `video/repo.py`。）
3. **最後才設計新增**：讓它「長得像本來就在這」——介面清楚、責任單一、跟既有風格一致，而不是硬接上去。
4. **為什麼**：功能各自獨立加 → 重複範式、慣例分歧、耦合糾纏（＝野蠻生長）。先全局，每次新增才收斂、可追溯。
5. **流程上**：這就是 `brainstorming → spec → plan` 的用意；spec 第一步永遠是「先 explore 既有模組怎麼做」。

## 1. 部署 & 快取的坑

### 坑：前端改了、手機/網頁看不到新版（最常踩）
- **根因**：PWA 的 service worker 把 app 殼 precache 住，**所有導覽都從 precache 的
  `/m/index.html` 出**（`frontend/src/sw.js` 的 `NavigationRoute`）。新 SW 雖然是
  `autoUpdate` + `skipWaiting` + `clientsClaim`，仍要 **1~2 次重開**才在裝置上接管。
- **診斷思路（先排除伺服器，再怪快取）**：
  ```bash
  # 伺服器送的 index.html 指向哪個 bundle？該 bundle 含不含你的新字串？
  curl -s -H "ngrok-skip-browser-warning: true" http://127.0.0.1:8000/m/index.html | grep -oE "assets/index-[A-Za-z0-9_-]+\.(js|css)"
  curl -s -H "ngrok-skip-browser-warning: true" http://127.0.0.1:8000/m/assets/index-XXXX.js | grep -c "你的新字串"
  ```
  伺服器送的是新 bundle + 含新字串 → **問題在裝置端快取，不是程式**。
- **解法**：使用者端強制更新——瀏覽器連按兩次重新整理；裝在主畫面的 App 整個滑掉重開（必要時兩次）；
  iOS 最固執時刪 icon → Safari 重開 `/m/` → 重新加入主畫面。
- **教訓**：前端部署後「我看不到」≈ 99% 是 SW 快取，**先 curl 確認伺服器端**，別急著改碼。
- **已實作**：`main.jsx` 加了 `controllerchange` 監聽——新 SW 接管時**自動重整一次**，未來前端部署免手動清快取
  （只有「載入時已被舊 SW 控制」才掛、`refreshing` 旗標防迴圈 → 首次安裝不會多閃）。
  注意：這次部署你**仍要手動清一次**快取拿到含此邏輯的新殼；之後才自動。

### 坑：`docker restart` 後 curl 回 HTTP 000，以為掛了
- **根因**：開機會跑發票同步（Playwright），**阻塞 server ready ~30–90s**，這段 curl 回 000 是正常。
- **解法**：用背景輪詢等 ready，別用固定 sleep：
  ```bash
  for i in $(seq 1 60); do
    log=$(docker logs --tail 40 money-bot 2>&1)
    echo "$log" | grep -q "Application startup complete" && { echo READY; break; }
    echo "$log" | grep -qE "Traceback|ModuleNotFound|ImportError" && { echo ERROR; echo "$log"|tail -25; break; }
    sleep 3
  done
  ```
- **教訓**：判斷健康看 `docker ps` 是 `Up` 不是 `Restarting` + log 有 `Application startup complete` / `🐉 Discord Bot 已上線`。

## 2. FastAPI / import 的坑

### 坑：加上傳端點導致 import 崩潰，整個 bot 連 webhook 一起掛（曾使生產中斷）
- **根因**：FastAPI 用 `File(...)`/`UploadFile` 需要 `python-multipart`；沒裝 → **import 時** RuntimeError
  → `main.py` 起不來 → 崩潰迴圈 → bot + webhook 全掛。**import 崩潰 = 全站掛**。
- **解法**：先 `pip install python-multipart` + 寫進 `requirements.txt`，**再**加端點。
- **教訓**：**重啟前先做 import 預檢**，把崩潰擋在重啟之外：
  ```bash
  docker exec -w /app money-bot python -c "import main" && echo OK   # 或 import 你動到的模組
  ```

## 3. 資料庫的坑

### 坑：以為加欄位/表會自動生效
- **根因**：`main.py:28` 的 `Base.metadata.create_all` **只建新表，不改既有表結構**。
- **規則**：
  - **新表**（如 `history_videos`/`video_tags`）→ 開機自動建，**免 migration**。
    （`models.py` 在 `main.py:9` 經 `categorize` 被 import，create_all 前就註冊到 metadata。）
  - **既有表加欄位/FK** → 要**手動 ALTER**，照 `main.py:30-57` 那段 inspector + `ALTER TABLE` 寫法。
- **教訓**：新表免錢、舊表加欄要手動補。

### 坑：out-of-process 產的 token，server 不認
- **根因**：`auth.generate_report_token()` 存在**伺服器行程的記憶體**。用
  `docker exec python -c "..."` 是**另一個行程**，產的 token server 看不到 → API 回 401。
- **解法**：smoke API 時改用 **DB 裡持久的 `device_tokens`**（跨行程），帶 header：
  ```bash
  DTOK=$(docker exec -w /app money-bot python -c "from database import SessionLocal; from models import DeviceToken; s=SessionLocal(); t=s.query(DeviceToken).order_by(DeviceToken.id.desc()).first(); print(t.token if t else 'NONE'); s.close()")
  curl -s -H "X-Device-Token: $DTOK" -H "ngrok-skip-browser-warning: true" http://127.0.0.1:8000/api/videos
  ```
- **教訓**：記憶體型 token 不能跨行程鑄造；要驗 API 用 DB 型 device token。

### 注意：smoke 會寫進共用正式 DB
- 用真連結跑 `ingest.from_url(...)` 會**真的寫一筆進情侶共用的正式 DB**。挑正經、可刪的資料，**並主動告知使用者**。

## 4. 前端 / PWA 佈局的坑

### 坑：手機上 tab bar 沒貼底、下面露空白
- **根因**：shell 用 `height:100%` / `100vh`，在手機瀏覽器解析成「工具列縮起後的大高度」，
  跟實際可見高度對不上 → 底部 tab bar 掉出可見區。
- **解法**（`frontend/src/index.css`）：
  ```css
  .app    { height: 100vh; height: 100dvh; }  /* dvh=動態視窗高度，跟工具列縮放；100vh 當 fallback */
  .screen { flex: 1; min-height: 0; overflow: auto; }  /* min-height:0 → flex 內部才正確內捲 */
  body    { overflow: hidden; }                /* 整頁不滾，只有 .screen 滾 → tab bar 不被頂走 */
  ```
- **教訓**：手機滿版 shell 一律用 `100dvh`，不要 `%`/`vh`。
- **驗證限制**：手機 CSS 算繪**沒有自動化測試**（本 repo 無視覺/DOM 測試框架）→ 改完要**使用者親眼確認**，
  不可擅自宣稱修好（遵守 verification-before-completion）。

### 坑：bottom sheet 關閉時把手露在底部（只有某些分頁）
- **根因**：`.sheet` 用 `position: absolute`，定位錨是「最近有 position 的祖先」。只有 `.food`
  有 `position: relative`；`.spend`/`.video` 根容器沒定位 → sheet 改去貼 layout viewport，
  手機上關閉的 `translateY(100%)` 收不到螢幕外、露出 `.sheet-handle`，看起來像「可往上拉的新增鈕」。
- **解法**：`.sheet { position: fixed }`（錨定視窗本身，不依賴容器 position/捲動，四分頁一致）。
  **別**改成「逐一補 `position: relative`」——`.spend`/`.recipe` 本身會捲動，補了 sheet 會跟內容捲走。
- **教訓**：全螢幕 modal/bottom-sheet 用 `position: fixed`，不要 `absolute` + 靠某個祖先當錨（脆、不一致）。

### 坑：ngrok 免費版攔截頁污染
- **根因**：ngrok 免費版對瀏覽器導覽回攔截頁；`<img>` 帶不了 header。
- **解法**：所有 API/fetch 帶 `ngrok-skip-browser-warning: true`；圖片靠 SW 攔截後重發帶 header
  （`sw.js` 的 `media-v2` CacheFirst + `ngrokBypassPlugin`）。`media-v2` 的 `v2` 是因為 v1 被攔截頁毒過、整鍋拋棄。

## 5. Discord 的坑
- **`tree.sync()` 是 GLOBAL，傳播慢**。要立刻能用時，**改指既有指令**而非加新指令。
- **頻道分流**在 `discordbot/bot.py` 的 `on_message`，比對 `os.getenv("*_CHANNEL_ID")`。
  新模組照食譜那段加一個 `if chan and ch_id == chan: await handle_xxx(message); return`。
- **Discord CDN 圖片網址會過期（~24h）** → 要 bot 收圖請**下載 bytes**，別存連結。

## 6. 測試姿態（照著走，別自創）
- 測試是**純單元**：① model 用 `__table__.columns` introspection（不連 DB）；② 邏輯用 `FakeSession` + monkeypatch。
- **repo/route/handler glue 沒有單元測試** → 靠 curl / Discord / 直呼 orchestrator 的 smoke 驗。
- **TDD 瞄準純函式**：parser、JSON 解析、縮圖、回覆語法。glue 走 pattern + 全套回歸 + smoke。
- **自驗 Discord 功能的後端**：直接在 container 內用**真實連結**呼叫 orchestrator
  （`video.ingest.from_url("https://youtu.be/…")`），一次驗穿 yt-dlp + AI + DB，免等使用者在 Discord 動手。

## 7. 雜項坑
- **`pkill -f 'vite'` 會打到自己的 shell**（exit 144）→ 改用 port 找 PID（`:5173`）再殺特定 PID。
- **rtk hook 會改寫 shell 指令**（`git status`→`rtk git status`，透明 0 token）；meta 指令 `rtk gain/discover/proxy`。
- **雙 docker daemon 危險**：曾同時跑 Docker Desktop + 系統 docker → 排程重複觸發 / 報表數字不一 / ngrok 334。
  **只在 Desktop context 起 stack**。
- **內容型別別用猜的**：Google Places 有時把 PNG 用 .jpg 檔名送 → 破圖「?」。用 `file`/magic bytes 驗，
  依 `Content-Type` 決定副檔名，別假設「太大」。

## 8. 工作流程（這個 session 怎麼推進的）
1. **brainstorming**（skill）→ 一次問一題、定方案 → 寫 spec 到 `docs/superpowers/specs/`。
2. **writing-plans**（skill）→ 拆成可逐步 TDD 的任務 → `docs/superpowers/plans/`。
3. **executing-plans**（skill）→ 每任務 紅→綠→commit，小步快跑；glue 任務加回歸 + smoke。
4. **遇 bug → systematic-debugging**（skill）：先蒐證找根因（curl 排除伺服器、讀 SW/CSS）才動修，最小改動。
5. **宣稱完成前 → verification-before-completion**：拿得出證據才說「好了」；手機視覺類交使用者確認。

## 9. 重啟前 / 宣稱完成前 檢查清單
- [ ] `docker exec -w /app money-bot python -c "import main"` 不崩（import 預檢）。
- [ ] `docker exec -w /app money-bot python -m pytest tests/ -q` 全綠。
- [ ] 重啟後等到 `Application startup complete`，`docker ps` 是 `Up`。
- [ ] 動到 API → curl smoke（帶 device token）；動到前端 → `npm run build --prefix frontend` + curl 確認伺服器送新 bundle。
- [ ] 手機視覺類改動 → **使用者親眼確認**才算完成。
- [ ] commit 有更新 `README.md` + `CODEBASE.md`。
