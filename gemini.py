import os
import json
import base64
import urllib.request
from typing import Callable

from codex_cli import codex_text, codex_image
from app_secrets import get_secret

# 載入 persona 設定。persona.md 是**本機私人角色**（.gitignore，不入版控），
# 找不到就退回 repo 附的範本 persona.example.md，讓全新 clone 也能直接跑。
PERSONA_TEXT = "你是一個記帳助理。"

for persona_path in ("persona.md", "persona.example.md"):
    if os.path.exists(persona_path):
        with open(persona_path, "r", encoding="utf-8") as f:
            PERSONA_TEXT = f.read()
        break
else:
    print("⚠️ 找不到 persona.md / persona.example.md，將使用預設 AI 設定。")


def _log_usage(model: str, data: dict) -> None:
    """Gemini 是計費 API：每次呼叫把 token 用量印進 log，才看得出錢花在哪條路上。"""
    u = data.get("usageMetadata") or {}
    print(f"📊 Gemini {model} tokens：in={u.get('promptTokenCount')} "
          f"out={u.get('candidatesTokenCount')} total={u.get('totalTokenCount')}")


def gemini_text(prompt: str, model: str | None = None) -> str:
    """透過 HTTP 呼叫 Gemini，傳入純文字 prompt。可指定 model（如週評語用更強模型）。"""
    api_key = get_secret("GEMINI_API_KEY")
    model = model or os.getenv("MODEL_NAME")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    _log_usage(model, data)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def gemini_image(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg",
                 model: str | None = None, schema: dict | None = None) -> str:
    """透過 HTTP 呼叫 Gemini 多模態，傳入文字 + 圖片。

    schema：要結構化輸出時給 JSON Schema，走 generationConfig 的
    responseMimeType + responseJsonSchema，回覆保證是符合它的 JSON 字串。
    """
    api_key = get_secret("GEMINI_API_KEY")
    model = model or os.getenv("MODEL_NAME")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    body: dict = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": b64}}
            ]
        }]
    }
    if schema is not None:
        body["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    _log_usage(model, data)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _fallback_models() -> list[str]:
    """影像辨識要試的 Gemini 模型順序：主模型（MODEL_NAME）在前，備援在後。

    備援清單放 GEMINI_FALLBACK_MODELS（逗號分隔）。之所以要有這層：MODEL_NAME 設的
    是 `gemini-flash-latest` 這種 alias，Google 端一忙就整串回 503，可能連續多天
    辨識不出 CAPTCHA、發票同步全空轉。單一模型 = 單點故障。
    """
    models = [os.getenv("MODEL_NAME")]
    models += [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",")]
    seen: set[str] = set()
    ordered: list[str] = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


def vision_text(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg",
                *, allow_codex: bool = True,
                validate: Callable[[str], bool] | None = None,
                schema: dict | None = None) -> str:
    """影像 → 文字，逐層退避：主模型 → 備援 Gemini 模型 →（可選）codex。

    allow_codex=False 是給 **CAPTCHA** 用的：codex 政策上拒絕辨識驗證碼，退過去
    只會白等一輪再失敗一次，而 einvoice 的登入本來就已經重試 4 次。

    validate：可選的「這個答案能不能用」檢查。**沒有它退避會有一半是假的**——
    模型拒絕作答時是 HTTP 200 回一段「我無法協助辨識驗證碼」，不是例外；只 try/except
    的話那段廢話會被當答案傳回去，後面的備援模型永遠輪不到。例如 gemini-3.5-flash
    對 CAPTCHA 就是這種反應，而 gemini-3.6-flash 認得出來。

    schema：要結構化輸出時給 JSON Schema，每一層（Gemini 各模型、codex）都帶同一份，
    所以不論哪層接手，回來的都是同一個形狀的 JSON。

    全掛才丟例外，訊息帶上每一層的失敗原因——否則 log 只剩一句「辨識失敗」，
    根本分不出是模型忙、金鑰過期、還是模型名被 Google 下架（下架的模型回 404，例如 gemini-2.5-flash）。
    """
    errors: list[str] = []

    def _accept(raw: str, who: str) -> bool:
        if validate is None:
            return True
        try:
            ok = validate(raw)
        except Exception as e:                      # 驗證器自己爆掉也當不合格
            errors.append(f"{who}: 驗證器例外 {e}")
            return False
        if not ok:
            errors.append(f"{who}: 回傳內容不合格 {raw.strip()[:40]!r}")
            print(f"⚠️ 影像辨識回傳不合格（{who}）：{raw.strip()[:40]!r}")
        return ok

    for model in _fallback_models():
        try:
            raw = gemini_image(prompt, image_bytes, mime_type, model=model, schema=schema)
        except Exception as e:
            errors.append(f"{model}: {e}")
            print(f"⚠️ Gemini 影像辨識失敗（{model}）：{e}")
            continue
        if _accept(raw, model):
            return raw

    if allow_codex:
        try:
            raw = codex_image(prompt, image_bytes, mime_type, schema=schema)
        except Exception as e:
            errors.append(f"codex: {e}")
            print(f"⚠️ codex 影像辨識也失敗：{e}")
        else:
            if _accept(raw, "codex"):
                return raw

    raise RuntimeError("影像辨識全數失敗 —— " + "；".join(errors))


def generate_persona_comment(transaction_summary: str, context: str | None = None) -> str:
    """記帳完成後，讓 AI 以 persona.md 角色對帳目做出有趣的回應。

    context：四桶（投資/固定/生活/爽）水位，由 core.bucket_context() 產生。

    **算不出來就傳 None，不要傳空字串或編造的數字。** persona.md 對「沒有水位
    資訊」定義了保守模式（預設沒超支、禁止告誡）；餵假資料會讓那條防線失效，
    變成「只看單筆金額 → 每筆稍大的都被唸」。
    """
    try:
        parts = [f"{PERSONA_TEXT}\n\n---\n"]
        if context:
            parts.append(f"【主人目前的財務水位】\n{context}\n\n")
        parts.append(f"主人剛剛完成了一筆記帳，以下是帳目摘要：\n{transaction_summary}\n\n")
        parts.append("請根據你的角色設定，對這次的記帳內容做出簡短、有趣的回應。")
        prompt = "".join(parts)
    except Exception as e:
        print(f"⚠️ 角色 prompt 組裝失敗：{e}")
        return ""

    # Gemini 優先：這是「記帳當下」的回應，使用者在等，~1-2 秒最合適。
    try:
        return gemini_text(prompt).strip()
    except Exception as e:
        # 免費額度用完會回 429，那時 Gemini 這條路整天都不通。退到 codex（吃 ChatGPT
        # 訂閱、無計費配額）雖然慢很多（約 7 秒），但總比整天沒有角色回應好。
        print(f"⚠️ Gemini 角色回應失敗，改用 codex：{e}")
    try:
        return codex_text(prompt).strip()
    except Exception as e:
        print(f"⚠️ codex 角色回應也失敗，本次略過：{e}")
        return ""
