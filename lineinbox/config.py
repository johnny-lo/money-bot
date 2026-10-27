"""lineinbox 的常數。"""

WATCHED = {"中國信託": "ctbc"}      # 聯絡人 displayName（完全相等）→ 來源鍵；有個人聯絡人的名字也含「中國信託」
CHARGE_ID_PREFIX = "line:"          # card_charges.message_id ＝ 前綴＋LINE message id，跟 Gmail 的 id 分開
SESSION_PATH = "/data/tokens.json"  # money-line 容器裡的 OkLine session 檔（refresh 後會寫回）
RECENT_COUNT = 200                  # 補讀時要幾則；伺服器只留約兩週，也不能往回翻頁
HEARTBEAT_SEC = 300
STALE_MIN = 60                      # 心跳超過這麼久沒更新就告警
BACKOFF_START = 5                   # 斷線重連：5 秒起、每次加倍
BACKOFF_MAX = 600
STREAM_STABLE_SEC = 60              # 長連線撐過這麼久才斷，下一次退避從頭算（安靜時段也會穩定斷線）
KICKED_POLL_SEC = 60                # 被踢或找不到聊天室時，多久看一次 session 檔有沒有換新
CODEX_FALLBACK_MODEL = "gpt-6.1-sol"  # codex CLI 要 0.164.0 以上才叫得到；舊 CLI 回 model_not_found
FALLBACK_DATE_SLACK_DAYS = 1        # codex 抽出的刷卡日離訊息時間超過這麼多天就不信
FALLBACK_PER_RUN = 5                # watchdog 每次最多送幾則給 codex
