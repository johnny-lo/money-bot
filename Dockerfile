# 使用輕量版 Python (3.11 相容 line-bot-sdk 的 aiohttp)
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝依賴 (使用清大 PyPI 鏡像加速)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn

# 複製程式碼
COPY . .

# 啟動命令 (Host 設為 0.0.0.0 才能讓外部存取)
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]