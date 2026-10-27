# 使用輕量版 Python (3.11 相容 line-bot-sdk 的 aiohttp)
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝依賴 (使用清大 PyPI 鏡像加速)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn

# 安裝 Playwright Chromium 與系統依賴（給發票爬蟲用）
RUN playwright install --with-deps chromium

# 安裝 Node 與 OpenAI Codex CLI
# 週報/月報評語 + 帳目分類的「文字」生成走 codex（ChatGPT 訂閱），取代計費的 Gemini 文字 API；
# 影像辨識（拍照記帳、CAPTCHA）仍由 gemini.py 用 Gemini Vision 處理。
# 版本釘死：~/.codex 與主機共用，主機的 codex 升級後 config.toml 的 model 可能換成新模型，
# 舊 CLI 會被 API 拒絕（"requires a newer version of Codex"）。升級＝改這個數字再 build——
# 不寫版本號的話這層會被 Docker 快取住，`--build` 也不會拉新版。
# apt 換台灣鏡像（build 內直連 deb.debian.org 曾卡在 77 KB/s；只改這層，不動上面已快取的層）
ARG CODEX_VERSION=0.164.0
#（只換主庫；debian-security 台灣鏡像沒有 → 404，留官方）
RUN sed -i 's|deb.debian.org/debian$|ftp.tw.debian.org/debian|' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @openai/codex@${CODEX_VERSION} \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 複製程式碼
COPY . .

# 啟動命令 (Host 設為 0.0.0.0 才能讓外部存取)
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]