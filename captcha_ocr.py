"""本地 CAPTCHA 辨識（ddddocr）+ 樣本收集。

**為什麼要有這一層**：財政部的驗證碼原本只靠 Gemini Vision 辨識，而那條路有兩個
致命弱點——模型會 503（2026/08/24~08/29 連續多天，發票同步整週空轉、抓 0 張），
以及模型會**政策拒答**（實測 gemini-3.5-flash 回「我無法協助辨識驗證碼」）。
本地 OCR 沒有這兩種故障，而且快 300~700 倍。

實測（30 張財政部真圖，人工判讀當 ground truth）：
- ddddocr 官方通用模型：27/30 = 90%，4.9 ms/張
- 加相似字修正：**30/30 = 100%**，4.4 ms/張
- TicketsHunter 自訓的 universal / tixcraft_tm 模型：**0%**——它們是拓元那種
  英文字母驗證碼訓出來的（tixcraft_tm 的字元集根本沒有數字）。**自訓模型不通用。**

所以策略是：**ddddocr 本地第一層 → 失敗才退 gemini.vision_text 的模型退避鏈**。

樣本收集是為了「哪天財政部改字型」的保險：登入成功那一刻答案才確定是對的，
那時才把 (圖, 答案) 存下來，等於用 AI 免費幫你標註訓練資料。有樣本，改版時
用 GPU 幾分鐘就能重訓一個專用模型；沒樣本，得從零開始收。
"""
import os
import re
import time
from datetime import datetime

# 樣本落在專案目錄（live-mount 進容器），容器重建也不會消失。
# 用**絕對路徑**（以本檔位置為基準）而不是相對路徑：排程、CLI、docker exec 的
# cwd 不保證都是 /app，相對路徑會讓樣本散落到各處，而且沒人會發現。
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.getenv("CAPTCHA_SAMPLE_DIR") or os.path.join(_BASE_DIR, "data", "captcha")
# 容量上限，預設 1 GB。單張約 1~2 KB，每天才 2~8 張——這個上限實務上永遠碰不到，
# 但沒有上限的自動收集就是一顆慢慢長大的定時炸彈。
SAMPLE_MAX_BYTES = int(os.getenv("CAPTCHA_SAMPLE_MAX_BYTES", str(1024 ** 3)))

# 驗證碼保證是 5 位純數字，所以模型吐出字母**一定**是誤認。
# 對照表來自實測錯誤：7 會被認成 t/z/Z（那條干擾線讓 7 多一撇），其餘是通用相似字。
_CONFUSABLE = str.maketrans({
    "t": "7", "T": "7", "z": "7", "Z": "7",
    "o": "0", "O": "0", "D": "0", "Q": "0",
    "l": "1", "I": "1", "i": "1", "|": "1",
    "s": "5", "S": "5",
    "b": "6", "G": "6",
    "g": "9", "q": "9",
    "B": "8",
    "A": "4",
    "e": "8",
})

_ocr = None
_ocr_unavailable = False


def _get_ocr():
    """取全域 OCR 引擎（只初始化一次——每次重建都要重載模型，會拖垮效能）。

    ddddocr 是**可選依賴**：沒裝就安靜回 None 退回 AI 那條路。
    可選功能寫成 import 期硬依賴會讓缺套件時整個站起不來（AGENTS.md §2 踩過）。
    """
    global _ocr, _ocr_unavailable
    if _ocr is None and not _ocr_unavailable:
        try:
            import ddddocr
            _ocr = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            _ocr_unavailable = True
            print(f"⚠️ ddddocr 不可用，CAPTCHA 將直接走 AI：{e}")
    return _ocr


def digitize(raw: str) -> str:
    """把辨識結果收斂成純數字：相似字母換回數字，其餘非數字一律丟掉。"""
    return re.sub(r"\D", "", (raw or "").translate(_CONFUSABLE))


def recognize(image_bytes: bytes) -> str | None:
    """本地辨識驗證碼。回 5 位數字字串；辨識不出來或長度不對回 None。

    長度不對就回 None 而不是硬送——送錯的驗證碼會讓財政部把它算成一次
    「帳號或密碼錯誤」，那個計數累積到 40 次會鎖帳號（已經吃過一次苦頭）。
    """
    ocr = _get_ocr()
    if ocr is None:
        return None
    try:
        # png_fix=True：驗證碼是透明背景 PNG，不修的話辨識結果會全空。
        digits = digitize(ocr.classification(image_bytes, png_fix=True))
    except Exception as e:
        print(f"⚠️ 本地 OCR 失敗，改走 AI：{e}")
        return None
    return digits if len(digits) == 5 else None


def prune_samples() -> None:
    """把樣本目錄壓在 SAMPLE_MAX_BYTES 以內，從最舊的開始刪。"""
    try:
        entries = []
        with os.scandir(SAMPLE_DIR) as it:
            for e in it:
                if e.is_file():
                    st = e.stat()
                    entries.append((st.st_mtime, st.st_size, e.path))
        total = sum(size for _, size, _ in entries)
        if total <= SAMPLE_MAX_BYTES:
            return
        for _, size, path in sorted(entries):          # 舊的排前面
            if total <= SAMPLE_MAX_BYTES:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass
    except OSError:
        pass


def save_sample(image_bytes: bytes, answer: str) -> None:
    """存一張「已確認答案正確」的樣本。答案寫在檔名裡，就是標註。

    best-effort：**任何失敗都吞掉**。這是為了未來重訓而順手收的附帶行為，
    不值得讓它有任何機會弄掛正在跑的登入流程。
    """
    if not re.fullmatch(r"\d{5}", answer or ""):
        return                                          # 髒標註比沒有更糟
    try:
        os.makedirs(SAMPLE_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SAMPLE_DIR, f"{stamp}_{int(time.time() * 1000) % 1000:03d}_{answer}.png")
        with open(path, "wb") as f:
            f.write(image_bytes)
        prune_samples()
    except Exception:
        pass
