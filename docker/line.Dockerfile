# money-line：疊在 money-bot 上再裝 OkLine，跑 LINE 收件匣 listener（python -m lineinbox.listener）。
# 不動 requirements.txt、不重 build money-bot：重 build 會把沒鎖版本的套件一起升級。
# money-bot 重 build 之後，這個 image 也要跟著重 build（它疊在上面）。
FROM money-bot

# OkLine 從 GitHub 裝審過的 commit：commit SHA 鎖定內容（PyPI 上沒有這個版本）。
# --no-deps：它要的 requests、cryptography money-bot 已經有，不讓 pip 順手升級。換 commit＝重審＋重算 verify_okline.py 的 hash。
ARG OKLINE_COMMIT=2e3437977368802edcc2219798b9d5333665ebca
RUN pip install --no-cache-dir --no-deps \
        "okline @ https://github.com/NiceDayZc/OkLine/archive/${OKLINE_COMMIT}.tar.gz" \
    && pip install --no-cache-dir --no-deps qrcode==8.2 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn

# LTSM 的 wasm／js 跟審過的版本逐位元比對，不符 build 失敗
COPY verify_okline.py /opt/verify_okline.py
RUN python /opt/verify_okline.py

# 以主機使用者的 uid 執行（compose 的 user:），HOME 要可寫；/app 唯讀掛載，不寫 .pyc
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "-m", "lineinbox.listener"]
