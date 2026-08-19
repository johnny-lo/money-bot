"""用本機 codex CLI(OpenAI Codex，ChatGPT 訂閱制)跑純文字 prompt，
取代計費的 Gemini 文字 API —— 走訂閱不必擔心單次計費 / 配額 429。

只負責「文字」生成（分類、週月評語、錢鼠阿財評論）；
影像辨識（拍照記帳、CAPTCHA）仍由 gemini.py 的 gemini_image() 用 Gemini Vision 處理。
"""
import os
import subprocess
import tempfile

# 容器內 codex 執行檔（裝在 PATH 上即可，預設 "codex"）
CODEX_BIN = os.getenv("CODEX_BIN", "codex")
# 選填：覆蓋 codex 預設模型（例如 gpt-5.5）。留空則用 ~/.codex 設定的預設。
CODEX_MODEL = os.getenv("CODEX_MODEL") or None


def codex_text(prompt: str, model: str | None = None) -> str:
    """呼叫 `codex exec` 跑純文字 prompt，回傳模型最終回覆。

    用 --output-last-message 把最終訊息寫到暫存檔取乾淨結果，
    避免 codex 的過程訊息（如「Shell cwd was reset…」）混入 stdout 破壞解析。
    prompt 一律從 stdin 餵（exec 的 `-`），可承載超長 batch 內容。
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
            "-s", "read-only",        # 純文字問答不需寫檔
            "-C", "/tmp",
            "-o", out_path,
            "-",                      # prompt 從 stdin 讀
        ]
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
