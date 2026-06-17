"""Discord 回覆語法解析（純函式）+ 回覆小抄文字（單一真相）。

語法（對影片卡片 reply）：
- 整串以 # / + / - 開頭 → 標籤編輯模式，空白切 token：
    #X 設主題、+X 加標籤、-X 刪標籤、裸 token 視為加標籤
- 否則 → 改標題（rename）
- 空字串 → noop
"""

CHEAT_SHEET = (
    "✏️ 想整理？直接「回覆」這則訊息：\n"
    "• 改主題 → 打 #主題        例：#唐朝\n"
    "• 加標籤 → 打 +標籤        例：+經濟 戰爭（空格分多個）\n"
    "• 刪標籤 → 打 -標籤        例：-制度\n"
    "• 改標題 → 直接打新標題（不用任何符號）\n"
    "可混用，例：#唐朝 +經濟 -制度"
)


def parse_reply_command(text: str) -> dict:
    """回覆文字 → 指令 dict。

    - {"mode": "noop"}
    - {"mode": "rename", "title": str}
    - {"mode": "edit", "topic": str|None, "add": [str], "remove": [str]}
    """
    t = (text or "").strip()
    if not t:
        return {"mode": "noop"}
    if t[0] not in "#+-":
        return {"mode": "rename", "title": t}

    topic = None
    add: list[str] = []
    remove: list[str] = []
    for tok in t.split():
        if tok.startswith("#"):
            name = tok[1:].strip()
            if name:
                topic = name
        elif tok.startswith("-"):
            name = tok[1:].strip()
            if name:
                remove.append(name)
        elif tok.startswith("+"):
            name = tok[1:].strip()
            if name:
                add.append(name)
        else:
            # 裸 token（接在前面之後）視為加標籤
            add.append(tok.strip())
    return {"mode": "edit", "topic": topic, "add": add, "remove": remove}
