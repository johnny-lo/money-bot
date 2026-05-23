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
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @openai/codex \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 複製程式碼
COPY . .

# 啟動命令 (Host 設為 0.0.0.0 才能讓外部存取)
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]