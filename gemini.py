import os
import json
import base64
import urllib.request

from codex_cli import codex_text

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


def gemini_text(prompt: str, model: str | None = None) -> str:
    """透過 HTTP 呼叫 Gemini，傳入純文字 prompt。可指定 model（如週評語用更強模型）。"""
    api_key = os.getenv("GEMINI_API_KEY")
    model = model or os.getenv("MODEL_NAME")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def gemini_image(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """透過 HTTP 呼叫 Gemini 多模態，傳入文字 + 圖片。"""
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("MODEL_NAME")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": b64}}
            ]
        }]
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def generate_persona_comment(transaction_summary: str, context: str | None = None) -> str:
    """記帳完成後，讓 AI 以 persona.md 角色對帳目做出有趣的回應。

    context：三桶（投資/生活/爽）水位，由 core.bucket_context() 產生。

    **算不出來就傳 None，不要傳空字串或編造的數字。** persona.md 對「沒有水位
    資訊」定義了保守模式（預設沒超支、禁止告誡）；餵假資料會讓那條防線失效，
    退回舊版「只看單筆金額 → 每筆稍大的都被唸」的行為。
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
        # 訂閱、無計費配額）雖然慢很多（實測 ~7 秒），但總比整天沒有角色回應好。
        print(f"⚠️ Gemini 角色回應失敗，改用 codex：{e}")
    try:
        return codex_text(prompt).strip()
    except Exception as e:
        print(f"⚠️ codex 角色回應也失敗，本次略過：{e}")
        return ""
