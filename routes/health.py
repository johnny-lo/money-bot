"""對外健康檢查端點（給主機上的 `scripts/healthcheck.sh` 每 5 分鐘打一次）。

**為什麼免 token**：健康檢查器要在「服務已經壞掉」時還問得到答案，讓它持有憑證
等於多一個會過期、會外洩的東西。所以這支端點不驗身分——代價是**回應必須當成
公開資訊**：不回版本號、不回路徑、不回環境變數、不回 DB 連線字串，連例外訊息
都不轉出去（SQLAlchemy 的錯誤字串裡就有帳密與主機名）。壞掉的細節只寫進伺服器
log，對外永遠只有固定的那兩個字串。

**為什麼要查 DB**：只回「app 活著」的健康檢查會在 Postgres 掛掉時繼續回綠燈，
那就跟這支端點誕生的原因（本地全綠、外面連不上）是同一種謊。一次 `SELECT 1`
夠輕，五分鐘一次的成本可以忽略。
"""
from fastapi import APIRouter, Response
from sqlalchemy import text

from database import engine

router = APIRouter()


def _db_ok() -> bool:
    """`SELECT 1` 探一下 DB。任何例外都吞掉、只寫 log——細節不能出去。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        # 只印在伺服器 log（連線字串含帳密，絕不能進 HTTP 回應）
        print(f"⚠️ /healthz DB 檢查失敗：{type(e).__name__}: {e}", flush=True)
        return False


@router.get("/healthz")
def healthz(response: Response):
    """DB 通 → 200 `{"status":"ok"}`；不通 → 503 `{"status":"unavailable"}`。

    `no-store`：健康檢查最怕拿到快取的舊答案——那會讓「已經壞了」看起來還是綠的。
    """
    response.headers["Cache-Control"] = "no-store"
    if not _db_ok():
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ok"}
