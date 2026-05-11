import os
import json
import base64
import urllib.request

# 載入 persona 設定
PERSONA_TEXT = "你是一個記帳助理。"
persona_path = "persona.md"

if os.path.exists(persona_path):
    with open(persona_path, "r", encoding="utf-8") as f:
        PERSONA_TEXT = f.read()
else:
    print(f"⚠️ 找不到 {persona_path}，將使用預設 AI 設定。")


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


def generate_persona_comment(transaction_summary: str) -> str:
    """記帳完成後，讓 AI 以 persona.md 角色對帳目做出有趣的回應。"""
    try:
        prompt = (
            f"{PERSONA_TEXT}\n\n---\n"
            f"主人剛剛完成了一筆記帳，以下是帳目摘要：\n{transaction_summary}\n\n"
            f"請根據你的角色設定，對這次的記帳內容做出簡短、有趣的回應。"
        )
        return gemini_text(prompt).strip()
    except Exception as e:
        print(f"⚠️ AI 角色回應生成失敗：{e}")
        return ""
