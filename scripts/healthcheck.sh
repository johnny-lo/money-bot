#!/usr/bin/env bash
#
# scripts/healthcheck.sh —— 從**公開路徑**確認服務真的對外活著；壞了自動重掛
# Tailscale Funnel 並通知 Discord。跑在**主機**上（不是容器內），由 systemd
# user timer 每 5 分鐘叫一次。
#
# ─────────────────────────────────────────────────────────────────────────────
# 為什麼需要它
#
#   主機重開機後可能出現：docker ps 全 Up、curl localhost:8000 回 200、
#   `tailscale status` Online 無警告、`tailscale funnel status` 顯示 "Funnel on"
#   ——**每一項本地指標都是綠的，可是外面的裝置完全連不上**（TLS 回
#   `no peer certificate available`）。原因：Funnel 的**設定**會活過重開機，
#   但**入口註冊**不一定；`funnel status` 讀的是設定，所以它照樣說 on。
#
#   最陰險的是：在主機上 `curl https://<name>.ts.net/...` 也會回 200——
#   **MagicDNS 把它解析到 tailnet 內網 IP（100.x），根本沒走 Funnel**。
#   所以「我在主機上 curl 過了」這句話對這個故障完全沒有證據力。
#
# 因此本腳本的鐵律：
#   1. **一定用公開解析器查 IP**（`dig @1.1.1.1`），再 `curl --resolve` 強制走它。
#      絕不用系統解析（那是 MagicDNS）。
#   2. **IP 不寫死**，每次重查——Tailscale 的入口 IP 會換。
#   3. 查不到公開 IP 本身就是一種失敗（Funnel 沒註冊時公開 DNS 就沒有 A 記錄）。
#
# ─────────────────────────────────────────────────────────────────────────────
# 用法
#   ./scripts/healthcheck.sh              # 跑一次檢查（systemd timer 用這個）
#   ./scripts/healthcheck.sh --self-test  # 只跑純邏輯自測，不出網、不碰 funnel
#   ./scripts/healthcheck.sh --status     # 印出目前狀態檔內容
#   ./scripts/healthcheck.sh --reset      # 清掉狀態（解除「已停手」閂鎖）
#
# 環境變數（都選填，可寫進 repo 的 .env）
#   HEALTHCHECK_DISCORD_WEBHOOK  Discord webhook；沒設就只寫 log
#   BASE_URL                     對外網址；預設從 repo 的 .env 讀
#   HEALTHCHECK_RESOLVER         公開 DNS，預設 1.1.1.1
#   HEALTHCHECK_FAIL_THRESHOLD   連續失敗幾次才動作，預設 2
#   HEALTHCHECK_FUNNEL_PORT      Funnel 要轉到的本機 port，預設 8000
#   HEALTHCHECK_TAILSCALE        tailscale 執行檔（自測時換成假指令）
#   HEALTHCHECK_STATE_DIR        狀態檔目錄
#
# 退出碼：0 = 健康（或已修好）／1 = 不健康／2 = 設定或前置工具有問題
#
set -uo pipefail
# 刻意不用 `set -e`：這支腳本的日常就是「指令會失敗」，錯誤要被分類而不是讓行程消失。

# ── 設定 ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(dirname -- "$SCRIPT_DIR")
ENV_FILE="$REPO_DIR/.env"

STATE_DIR="${HEALTHCHECK_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/linebot-healthcheck}"
STATE_FILE="$STATE_DIR/state"
LOCK_FILE="$STATE_DIR/lock"

RESOLVER="${HEALTHCHECK_RESOLVER:-1.1.1.1}"
FAIL_THRESHOLD="${HEALTHCHECK_FAIL_THRESHOLD:-2}"
FUNNEL_PORT="${HEALTHCHECK_FUNNEL_PORT:-8000}"
TAILSCALE_BIN="${HEALTHCHECK_TAILSCALE:-tailscale}"
HEALTH_PATH="${HEALTHCHECK_PATH:-/healthz}"
CONNECT_TIMEOUT=5
MAX_TIME=15
REPAIR_SETTLE_SECONDS="${HEALTHCHECK_SETTLE:-6}"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# ── 純函式（--self-test 驗的就是這幾支）──────────────────────────────────────

# env_value KEY FILE —— 從 .env 取一個 key。
# **刻意不 source 整個 .env**：那會把一堆金鑰灌進環境、還會執行檔案裡的任何東西。
# 只挑要的兩三個 key，順手剝掉引號與行尾註解。
env_value() {
    local key="$1" file="$2" line
    [ -f "$file" ] || return 0
    line=$(grep -m1 -E "^[[:space:]]*${key}=" "$file" 2>/dev/null) || return 0
    line=${line#*=}
    line=${line%%$'\r'}                       # 防 CRLF
    line=$(printf '%s' "$line" | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//')
    line=${line#\"}; line=${line%\"}
    line=${line#\'}; line=${line%\'}
    printf '%s' "$line"
}

# host_of URL —— 從 https://host/path 取出 host（不含 port）。
host_of() {
    local u="$1"
    u=${u#*://}
    u=${u%%/*}
    u=${u%%:*}
    printf '%s' "$u"
}

# _gt_zero N —— 浮點數 > 0？（curl 的 time_appconnect 是 "0.000000" 這種字串）
_gt_zero() { awk -v v="${1:-0}" 'BEGIN { exit !(v + 0 > 0) }'; }

# classify EXIT HTTP_CODE TIME_APPCONNECT → ok | app:<原因> | tunnel:<原因>
#
# **這是整支腳本最重要的判斷**：出口壞掉才該重掛 Funnel，app 壞掉重掛 Funnel
# 只是把好的東西關掉再打開（而且會中斷正在用的人）。
# 分界線是 **TLS 有沒有握手成功**（curl 的 time_appconnect）：
#   握手成功 → 憑證是 Funnel 發的，入口註冊正常 → 問題在 app。
#   握手沒成功 → 入口沒註冊的簽名（`no peer certificate available`）。
classify() {
    local exit_code="$1" http_code="${2:-000}" appconnect="${3:-0}"
    if [ "$exit_code" -eq 0 ]; then
        if [ "$http_code" = "200" ]; then
            printf 'ok'
        else
            printf 'app:http_%s' "$http_code"      # 連得到、但 /healthz 說自己不健康（例：DB 掛了）
        fi
        return
    fi
    if _gt_zero "$appconnect"; then
        printf 'app:no_response(curl%s)' "$exit_code"   # TLS 通了卻沒回應 → app 卡住，不是出口
    else
        printf 'tunnel:curl%s' "$exit_code"            # 連不上／TLS 失敗 → 出口壞了，可修
    fi
}

# decide CLASS FAIL LATCHED → "<新fail> <新latched> <action>"
#
# action：none（安靜）/ repair（重掛 Funnel）/ notify_app（通知但別碰 Funnel）
#         / recovered（自己好了，回報一聲）/ silent（已停手，不再吵）
#
# latched=1 是「已經通知過而且**停手**」的閂鎖，用來滿足「不要無限重試」——
# 修一次沒好就不再每 5 分鐘 restart 一次 funnel，直到它自己恢復或人來 --reset。
decide() {
    local class="$1" fail="$2" latched="$3" threshold="${4:-$FAIL_THRESHOLD}"

    if [ "$class" = "ok" ]; then
        if [ "$latched" = "1" ]; then
            printf '0 0 recovered'      # 之前報過壞，現在好了 → 要說一聲
        else
            printf '0 0 none'           # 本來就好的（或只抖了一下自己回來）→ 不吵
        fi
        return
    fi

    fail=$((fail + 1))
    if [ "$latched" = "1" ]; then
        printf '%s 1 silent' "$fail"    # 已停手：繼續記次數，但不再動作也不再通知
        return
    fi
    if [ "$fail" -lt "$threshold" ]; then
        printf '%s 0 none' "$fail"      # 單次失敗常常只是網路抖動 → 先忍
        return
    fi
    case "$class" in
        tunnel:*) printf '%s 1 repair' "$fail" ;;
        *)        printf '%s 1 notify_app' "$fail" ;;
    esac
}

# ── 狀態檔 ───────────────────────────────────────────────────────────────────

FAIL=0
LATCHED=0

read_state() {
    FAIL=0; LATCHED=0
    [ -f "$STATE_FILE" ] || return 0
    local f l
    f=$(sed -n 's/^fail_count=\([0-9][0-9]*\)$/\1/p' "$STATE_FILE" | tail -1)
    l=$(sed -n 's/^latched=\([01]\)$/\1/p' "$STATE_FILE" | tail -1)
    [ -n "$f" ] && FAIL="$f"
    [ -n "$l" ] && LATCHED="$l"
    return 0
}

write_state() {   # fail latched class
    mkdir -p "$STATE_DIR"
    printf 'fail_count=%s\nlatched=%s\nlast_class=%s\nlast_run=%s\n' \
        "$1" "$2" "$3" "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$STATE_FILE"
}

# ── 通知 ─────────────────────────────────────────────────────────────────────

# 為什麼是 Discord webhook 而不是既有的 bot：
#   ① `discordbot/bridge.py` 的 `_bot_instance` 是 module 級狀態，從別的行程
#      呼叫 notify_*() 會**靜默失敗**（AGENTS.md 有記）；
#   ② 更根本的是——健康檢查器不該依賴它正在監控的那個東西。app 掛了正是最需要
#      通知的時候，那時候 bot 也是掛的。webhook 是獨立於本專案的一條路。
notify() {
    local msg="$1"
    log "$msg"
    if [ -z "${WEBHOOK:-}" ]; then
        log "（未設 HEALTHCHECK_DISCORD_WEBHOOK → 只寫 log）"
        return 0
    fi
    if ! command -v jq >/dev/null 2>&1; then
        log "⚠️ 找不到 jq，無法安全組 JSON → 只寫 log"
        return 0
    fi
    local payload
    payload=$(jq -n --arg c "$msg" '{content: $c, username: "🩺 對外健康檢查"}')
    # 用 -s（不是 -sS）：curl 的錯誤訊息會把整條 URL 印出來，而那條 URL 就是密碼。
    if ! curl -s -o /dev/null --max-time 10 \
        -H 'Content-Type: application/json' -d "$payload" "$WEBHOOK"; then
        log "⚠️ Discord 通知送出失敗（webhook 網址不印，避免外洩）"
    fi
    return 0
}

# ── 探測 ─────────────────────────────────────────────────────────────────────

# public_ips HOST —— 用**公開解析器**查 A 記錄。
# 不能用 getent/系統解析：那是 MagicDNS，會回 100.x 內網位址（＝沒走 Funnel）。
public_ips() {
    local host="$1"
    dig +short +time=3 +tries=2 "@$RESOLVER" "$host" A 2>/dev/null \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'
}

# probe URL HOST IP → 印出 "class|http_code|appconnect"
probe() {
    local url="$1" host="$2" ip="$3"
    local out exit_code http_code appconnect
    out=$(curl -s -o /dev/null \
        --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
        --resolve "${host}:443:${ip}" \
        -w '%{http_code} %{time_appconnect}' \
        "$url" 2>/dev/null)
    exit_code=$?
    http_code=$(printf '%s' "$out" | awk '{print $1}')
    appconnect=$(printf '%s' "$out" | awk '{print $2}')
    printf '%s|%s|%s' "$(classify "$exit_code" "${http_code:-000}" "${appconnect:-0}")" \
        "${http_code:-000}" "${appconnect:-0}"
}

# check_once → 設定 CLASS / DETAIL；回 0 代表健康
CLASS=""
DETAIL=""
check_once() {
    local ips ip result
    ips=$(public_ips "$HOST")
    if [ -z "$ips" ]; then
        # 公開 DNS 查不到 A 記錄＝Funnel 沒註冊（或 DNS 還沒傳播）→ 當成出口問題
        CLASS="tunnel:no_public_dns"
        DETAIL="公開解析器 $RESOLVER 查不到 $HOST 的 A 記錄"
        return 1
    fi
    # 入口通常有多個 IP；只要有一個回 200 就算健康，避免單一入口抖動誤判。
    local rest code appconnect
    for ip in $ips; do
        result=$(probe "$URL" "$HOST" "$ip")
        CLASS=${result%%|*}
        rest=${result#*|}
        code=${rest%%|*}
        appconnect=${rest##*|}
        DETAIL="$HOST → $ip｜HTTP $code｜TLS 握手 ${appconnect}s"
        if [ "$CLASS" = "ok" ]; then
            return 0
        fi
    done
    return 1
}

# ── 修復 ─────────────────────────────────────────────────────────────────────

# 重掛 Funnel：先關再開。**只有 class=tunnel:* 才會走到這裡。**
# 為什麼要先 off：這種故障的形狀是「設定還在、入口註冊沒了」，直接再 on 一次
# 對 tailscaled 來說是 no-op（設定沒變），要先把設定拿掉才會真的重新註冊。
repair_funnel() {
    local rc=0
    log "🔧 重掛 Funnel：$TAILSCALE_BIN funnel --https=443 off"
    "$TAILSCALE_BIN" funnel --https=443 off || rc=$?
    log "🔧 重掛 Funnel：$TAILSCALE_BIN funnel --bg $FUNNEL_PORT"
    "$TAILSCALE_BIN" funnel --bg "$FUNNEL_PORT" || rc=$?
    return $rc
}

# ── 自測（純邏輯，不出網、不碰真 funnel）─────────────────────────────────────

self_test() {
    local pass=0 fail=0
    _eq() {   # _eq 實得 期望 說明
        if [ "$1" = "$2" ]; then
            pass=$((pass + 1))
        else
            fail=$((fail + 1))
            printf '  ✗ %s\n    實得：%s\n    期望：%s\n' "$3" "$1" "$2"
        fi
    }

    echo "── classify（哪種壞法該修出口、哪種不該）──"
    _eq "$(classify 0 200 0.12)"  "ok"                    "200 → ok"
    _eq "$(classify 0 503 0.12)"  "app:http_503"          "503（DB 掛）＝app 問題，不動 funnel"
    _eq "$(classify 0 502 0.12)"  "app:http_502"          "502 ＝app 問題"
    _eq "$(classify 35 000 0)"    "tunnel:curl35"         "TLS 失敗（no peer certificate）＝出口沒註冊"
    _eq "$(classify 7 000 0)"     "tunnel:curl7"          "連不上＝出口問題"
    _eq "$(classify 6 000 0)"     "tunnel:curl6"          "DNS 解不出＝出口問題"
    _eq "$(classify 28 000 0.00)" "tunnel:curl28"         "還沒握到手就逾時＝出口問題"
    _eq "$(classify 28 000 0.31)" "app:no_response(curl28)" "TLS 通了才逾時＝app 卡住，不該重掛 funnel"
    _eq "$(classify 0 000 0)"     "app:http_000"          "exit 0 但沒 code（理論上不會）不當出口問題"

    echo "── decide（連續 2 次才動作 / 修一次就停手 / 好了要回報）──"
    _eq "$(decide ok 0 0)"                "0 0 none"      "本來就好 → 安靜"
    _eq "$(decide tunnel:curl35 0 0)"     "1 0 none"      "第 1 次失敗 → 只記次數（可能只是抖動）"
    _eq "$(decide tunnel:curl35 1 0)"     "2 1 repair"    "第 2 次失敗 → 修"
    _eq "$(decide app:http_503 1 0)"      "2 1 notify_app" "app 壞 → 只通知，不碰 funnel"
    _eq "$(decide tunnel:curl35 2 1)"     "3 1 silent"    "已停手 → 不再修也不再吵"
    _eq "$(decide app:http_503 9 1)"      "10 1 silent"   "已停手（app 類）→ 同樣安靜"
    _eq "$(decide ok 3 1)"                "0 0 recovered" "停手後自己好了 → 回報並解除閂鎖"
    _eq "$(decide ok 1 0)"                "0 0 none"      "抖一下自己回來 → 不吵"
    _eq "$(decide tunnel:curl35 0 0 1)"   "1 1 repair"    "門檻可調（threshold=1 → 第 1 次就修）"
    _eq "$(decide tunnel:curl35 2 0 5)"   "3 0 none"      "門檻 5 → 第 3 次仍忍"

    echo "── 一輪完整生命週期（正常 → 壞 → 壞 → 修 → 停手 → 復原）──"
    # 把狀態接回下一輪，驗的是「連續失敗計數真的會累積、閂鎖真的會擋住第二次修」。
    local f=0 l=0 out trace=""
    local seq=("ok" "tunnel:curl35" "tunnel:curl35" "tunnel:curl35" "tunnel:curl35" "ok")
    for cls in "${seq[@]}"; do
        out=$(decide "$cls" "$f" "$l")
        f=$(printf '%s' "$out" | awk '{print $1}')
        l=$(printf '%s' "$out" | awk '{print $2}')
        trace="$trace $(printf '%s' "$out" | awk '{print $3}')"
    done
    _eq "${trace# }" "none none repair silent silent recovered" "整條生命週期只修一次、只通知該通知的兩次"
    _eq "$f $l" "0 0" "跑完一輪回到乾淨狀態"

    echo "── env_value（只挑 key，不 source 整個 .env）──"
    local tmp; tmp=$(mktemp -d)
    printf '# 註解\nBASE_URL=https://atlas.example.ts.net   # 行尾註解\nQUOTED="https://q.example"\nSINGLE=%s\nDISCORD_BOT_TOKEN=super-secret\n' "'https://s.example'" > "$tmp/.env"
    _eq "$(env_value BASE_URL "$tmp/.env")" "https://atlas.example.ts.net" "剝行尾註解與空白"
    _eq "$(env_value QUOTED "$tmp/.env")"   "https://q.example"            "剝雙引號"
    _eq "$(env_value SINGLE "$tmp/.env")"   "https://s.example"            "剝單引號"
    _eq "$(env_value NOPE "$tmp/.env")"     ""                             "不存在的 key 回空"
    _eq "$(env_value BASE_URL "$tmp/沒這個檔")" ""                          "檔案不存在也不爆炸"

    echo "── host_of ──"
    _eq "$(host_of https://atlas.numbat-dojo.ts.net)"        "atlas.numbat-dojo.ts.net" "純網址"
    _eq "$(host_of https://atlas.numbat-dojo.ts.net/healthz)" "atlas.numbat-dojo.ts.net" "含路徑"
    _eq "$(host_of http://127.0.0.1:8000/m/)"                 "127.0.0.1"               "含 port"

    echo "── repair_funnel（用假 tailscale 驗指令順序，絕不碰真的）──"
    printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$FAKE_LOG"\n' > "$tmp/tailscale"
    chmod +x "$tmp/tailscale"
    export FAKE_LOG="$tmp/calls.log"
    : > "$FAKE_LOG"
    TAILSCALE_BIN="$tmp/tailscale" FUNNEL_PORT=8000 repair_funnel >/dev/null
    _eq "$(tr '\n' '|' < "$FAKE_LOG")" "funnel --https=443 off|funnel --bg 8000|" \
        "先 off 再 --bg（順序不能反：設定沒拿掉就再 on 是 no-op）"

    printf '#!/bin/sh\nexit 3\n' > "$tmp/tailscale-broken"
    chmod +x "$tmp/tailscale-broken"
    TAILSCALE_BIN="$tmp/tailscale-broken" repair_funnel >/dev/null 2>&1
    _eq "$?" "3" "tailscale 失敗要回非 0（才知道修不動）"

    rm -rf "$tmp"
    echo
    if [ "$fail" -eq 0 ]; then
        echo "✅ 自測全過（$pass 項）"
        return 0
    fi
    echo "❌ 自測失敗 $fail 項（通過 $pass 項）"
    return 1
}

# ── 主流程 ───────────────────────────────────────────────────────────────────

main() {
    read_state
    log "▶ 檢查 $URL（公開解析器 $RESOLVER；連續 ${FAIL_THRESHOLD} 次失敗才動作；目前 fail=$FAIL latched=$LATCHED）"

    check_once
    log "   判定：$CLASS｜$DETAIL"

    local plan new_fail new_latched action
    plan=$(decide "$CLASS" "$FAIL" "$LATCHED")
    new_fail=$(printf '%s' "$plan" | awk '{print $1}')
    new_latched=$(printf '%s' "$plan" | awk '{print $2}')
    action=$(printf '%s' "$plan" | awk '{print $3}')

    case "$action" in
        none)
            if [ "$CLASS" = "ok" ]; then
                log "✅ 健康"
            else
                log "⚠️ 第 $new_fail 次失敗（未達 $FAIL_THRESHOLD 次門檻，先觀察，可能只是網路抖動）"
            fi
            ;;
        silent)
            log "🔇 仍然不健康（第 $new_fail 次），但已通知過且停手 —— 不再重掛 Funnel。"
            log "   人工處理後跑 $0 --reset 解除閂鎖。"
            ;;
        recovered)
            notify "✅ 對外連線已恢復（$HOST）
先前的告警解除，健康檢查現在從公開路徑拿到 200。"
            ;;
        notify_app)
            notify "⚠️ 外部連得到，但服務自己說不健康（$HOST）
判定：\`$CLASS\`
$DETAIL
連續 $new_fail 次。**Funnel 是好的（TLS 握手成功），所以沒有動它** —— 去看 app／DB：
\`docker ps\` / \`docker logs --tail 50 money-bot\`"
            ;;
        repair)
            log "🚨 連續 $new_fail 次從公開路徑連不上 → 重掛 Funnel"
            if ! repair_funnel; then
                log "⚠️ tailscale 指令回非 0（可能沒有 operator 權限）"
            fi
            log "   等 ${REPAIR_SETTLE_SECONDS} 秒讓入口重新註冊…"
            sleep "$REPAIR_SETTLE_SECONDS"
            local before="$CLASS"
            check_once
            log "   重驗：$CLASS｜$DETAIL"
            if [ "$CLASS" = "ok" ]; then
                new_fail=0; new_latched=0
                notify "🔧 已自動修復（$HOST）
症狀：連續 $((FAIL + 1)) 次從公開路徑連不上（\`$before\`）——本機看起來全綠，但外部連不上。
處置：\`tailscale funnel --https=443 off\` → \`tailscale funnel --bg $FUNNEL_PORT\`
結果：重驗 200，對外恢復。"
            else
                notify "🔴 自動修復失敗，已停手（$HOST）
症狀：\`$before\` → 重掛 Funnel 後仍是 \`$CLASS\`
$DETAIL
**不會再每 5 分鐘重試**（避免一直踢正在用的服務）。請人工處理：
\`tailscale funnel status\` / \`tailscale status\` / \`docker ps\`
處理完跑 \`scripts/healthcheck.sh --reset\` 解除閂鎖。"
            fi
            ;;
    esac

    write_state "$new_fail" "$new_latched" "$CLASS"
    [ "$CLASS" = "ok" ] && return 0
    return 1
}

# ── 進入點 ───────────────────────────────────────────────────────────────────

case "${1:-}" in
    --self-test)
        self_test
        exit $?
        ;;
    --status)
        if [ -f "$STATE_FILE" ]; then cat "$STATE_FILE"; else echo "（還沒有狀態檔：$STATE_FILE）"; fi
        exit 0
        ;;
    --reset)
        rm -f "$STATE_FILE"
        echo "已清掉 $STATE_FILE（閂鎖解除，下次檢查重新開始計數）"
        exit 0
        ;;
    -h|--help)
        sed -n '2,43p' "${BASH_SOURCE[0]}"
        exit 0
        ;;
esac

# 前置工具：dig 是必須的——**不能退回 getent/host**，那會走 MagicDNS 而驗不到公開路徑。
for bin in dig curl flock awk; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        log "❌ 缺少 $bin（Debian/Ubuntu：sudo apt install dnsutils curl）"
        exit 2
    fi
done

BASE_URL_VALUE="${BASE_URL:-$(env_value BASE_URL "$ENV_FILE")}"
if [ -z "$BASE_URL_VALUE" ]; then
    log "❌ 找不到 BASE_URL（環境變數或 $ENV_FILE 都沒有）"
    exit 2
fi
WEBHOOK="${HEALTHCHECK_DISCORD_WEBHOOK:-$(env_value HEALTHCHECK_DISCORD_WEBHOOK "$ENV_FILE")}"

URL="${BASE_URL_VALUE%/}$HEALTH_PATH"
HOST=$(host_of "$BASE_URL_VALUE")

mkdir -p "$STATE_DIR"

# 同時只跑一個：修復要花好幾秒，timer 撞在一起會互相打架。
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "（上一輪還在跑，這次跳過）"
    exit 0
fi

main
