"""用本機 codex CLI(OpenAI Codex，ChatGPT 訂閱制)跑 prompt，
取代計費的 Gemini API —— 走訂閱不必擔心單次計費 / 配額 429。

- codex_text：文字生成（分類、週/月報評語，以及角色即時評論的**備援**——
  記帳當下的角色回應優先走 Gemini 求即時，Gemini 失敗/429 才退到這裡）。
- codex_image：影像辨識的**最後一層備援**（`codex exec -i`），給拍照記帳 / 美食截圖用。
  ⚠️ **CAPTCHA 不能用這條**——codex 政策上拒絕辨識驗證碼（實測回「抱歉，我無法協助
  破解驗證碼。」），所以 einvoice 的 CAPTCHA 走 gemini.vision_text(allow_codex=False)，
  只在 Gemini 的多個模型之間退避。
"""
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager

# 圖片暫存檔的副檔名——codex 靠副檔名認圖片格式，給錯會被當成不支援的檔。
_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# 容器內 codex 執行檔（裝在 PATH 上即可，預設 "codex"）
CODEX_BIN = os.getenv("CODEX_BIN", "codex")
# 選填：覆蓋 codex 預設模型（例如 gpt-5.5）。留空則用 ~/.codex 設定的預設。
CODEX_MODEL = os.getenv("CODEX_MODEL") or None


@contextmanager
def schema_file(schema: dict | None):
    """把 JSON Schema 落成暫存檔給 `codex exec --output-schema` 用；None 就不落檔。

    有給 schema，codex 的最終回覆由 API 約束成符合它的 JSON。OpenAI strict 模式的限制：
    根節點必須是 object、每個 properties 都列進 required、additionalProperties 為 false。
    """
    if schema is None:
        yield None
        return
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False)
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _codex_exec(prompt: str, model: str | None = None,
                image_path: str | None = None,
                schema: dict | None = None) -> str:
    """呼叫 `codex exec` 跑 prompt，回傳模型最終回覆。文字與影像共用這一條路。

    用 --output-last-message 把最終訊息寫到暫存檔取乾淨結果，
    避免 codex 的過程訊息（如「Shell cwd was reset…」）混入 stdout 破壞解析。
    prompt 一律從 stdin 餵（exec 的 `-`），可承載超長 batch 內容。
    schema：要結構化輸出時給 JSON Schema（見 schema_file）。
    """
    fd, out_path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        cmd = [CODEX_BIN, "exec"]
        m = model or CODEX_MODEL
        if m:
            cmd += ["-m", m]
        cmd += [
            "--ephemeral",            # 不落地 session 檔，避免和 host codex 互搶
            "--skip-git-repo-check",  # /tmp 非 git repo
            "-s", "read-only",        # 問答不需寫檔
            "-C", "/tmp",
            "-o", out_path,
        ]
        if image_path:
            cmd += ["-i", image_path]
        with schema_file(schema) as schema_path:
            if schema_path:
                cmd += ["--output-schema", schema_path]
            cmd += ["-"]              # prompt 從 stdin 讀
            proc = subprocess.run(
                cmd, input=prompt, text=True,
                capture_output=True, timeout=180,
            )
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exit {proc.returncode}: {proc.stderr.strip()[-300:]}"
            )
        with open(out_path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            raise RuntimeError(f"codex 無輸出：{proc.stderr.strip()[-300:]}")
        return text
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def codex_text(prompt: str, model: str | None = None,
               schema: dict | None = None) -> str:
    """純文字 prompt → codex 回覆。給 schema 則回覆保證是符合它的 JSON 字串。"""
    return _codex_exec(prompt, model=model, schema=schema)


def codex_image(prompt: str, image_bytes: bytes,
                mime_type: str = "image/jpeg", model: str | None = None,
                schema: dict | None = None) -> str:
    """圖片 + prompt → codex 回覆（`codex exec -i`）。

    codex 只吃檔案路徑不吃 bytes，所以先落一個暫存圖檔，**無論成敗都要刪掉**——
    拍照記帳是每天都在跑的路徑，漏刪就是容器裡緩慢長出一堆孤兒圖檔。

    ⚠️ CAPTCHA 別走這裡：codex 會拒絕辨識驗證碼（見模組 docstring）。
    """
    suffix = _MIME_EXT.get((mime_type or "").lower(), ".png")
    fd, img_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)
        return _codex_exec(prompt, model=model, image_path=img_path, schema=schema)
    finally:
        try:
            os.remove(img_path)
        except OSError:
            pass
