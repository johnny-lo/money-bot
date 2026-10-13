"""影像辨識退避鏈的測試（純單元，不出網、不真的跑 codex）。

真實限制（決定了這條鏈的形狀）：
- codex CLI 0.148.0 支援 `-i/--image`，一般照片抽欄位沒問題。
- 但 codex **政策上拒絕辨識 CAPTCHA**（回「抱歉，我無法協助破解驗證碼。」），
  所以 CAPTCHA 只能靠「換 Gemini 模型」退避，不能退到 codex。
"""
import pytest

import codex_cli
import gemini


# ── codex_image：把圖片餵給 codex exec -i ──────────────────────

def test_codex_image_passes_image_flag(monkeypatch):
    seen = {}

    def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        seen["cmd"] = cmd
        seen["prompt"] = input
        # codex 把最終訊息寫到 -o 指定的檔案
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("辨識結果")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    got = codex_cli.codex_image("看圖", b"\x89PNG fake", mime_type="image/png")

    assert got == "辨識結果"
    assert seen["prompt"] == "看圖"
    assert "-i" in seen["cmd"]
    img_path = seen["cmd"][seen["cmd"].index("-i") + 1]
    assert img_path.endswith(".png")


def test_codex_schema_becomes_output_schema_file_and_is_cleaned_up(monkeypatch):
    """給 schema → codex 帶 --output-schema <暫存檔>，檔案內容就是那份 schema，用完即刪。"""
    import json
    import os
    seen = {}

    def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        schema_path = cmd[cmd.index("--output-schema") + 1]
        with open(schema_path, encoding="utf-8") as f:
            seen["schema"] = json.load(f)
        seen["schema_path"] = schema_path
        assert cmd[-1] == "-"                     # stdin 旗標仍在最後
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write('{"name":"x"}')
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    schema = {"type": "object", "properties": {"name": {"type": "string"}},
              "required": ["name"], "additionalProperties": False}
    assert codex_cli.codex_text("抽菜名", schema=schema) == '{"name":"x"}'
    assert seen["schema"] == schema
    assert not os.path.exists(seen["schema_path"])


def test_codex_without_schema_has_no_output_schema_flag(monkeypatch):
    seen = {}

    def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        seen["cmd"] = cmd
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("自由文字")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    codex_cli.codex_text("寫評語")
    assert "--output-schema" not in seen["cmd"]


def test_gemini_image_schema_goes_into_generation_config(monkeypatch):
    import json as _json
    seen = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode()

    def fake_urlopen(req, timeout=None):
        seen["body"] = _json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    gemini.gemini_image("看圖", b"img", model="m", schema=schema)
    assert seen["body"]["generationConfig"] == {
        "responseMimeType": "application/json", "responseJsonSchema": schema,
    }
    gemini.gemini_image("看圖", b"img", model="m")
    assert "generationConfig" not in seen["body"]


def test_vision_passes_same_schema_to_every_layer(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    got = []

    def fake_gemini_image(prompt, image_bytes, mime_type="image/jpeg", model=None, schema=None):
        got.append(("gemini", schema))
        raise RuntimeError("503")

    def fake_codex_image(prompt, image_bytes, mime_type="image/jpeg", schema=None):
        got.append(("codex", schema))
        return "{}"

    monkeypatch.setattr(gemini, "gemini_image", fake_gemini_image)
    monkeypatch.setattr(gemini, "codex_image", fake_codex_image)
    schema = {"type": "object"}
    gemini.vision_text("p", b"img", schema=schema)
    assert got == [("gemini", schema), ("codex", schema)]


def test_codex_image_writes_real_bytes_and_cleans_up(monkeypatch):
    captured = {}

    def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        img_path = cmd[cmd.index("-i") + 1]
        with open(img_path, "rb") as f:
            captured["bytes"] = f.read()
        captured["img_path"] = img_path
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    codex_cli.codex_image("看圖", b"IMGDATA", mime_type="image/jpeg")

    assert captured["bytes"] == b"IMGDATA"
    assert captured["img_path"].endswith(".jpg")
    # 暫存圖檔用完要刪掉——不然每張發票 CAPTCHA / 每張收據都在容器裡積一個檔
    import os
    assert not os.path.exists(captured["img_path"])


def test_codex_image_cleans_up_even_when_codex_fails(monkeypatch):
    captured = {}

    def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        captured["img_path"] = cmd[cmd.index("-i") + 1]
        return type("P", (), {"returncode": 1, "stderr": "boom"})()

    monkeypatch.setattr(codex_cli.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        codex_cli.codex_image("看圖", b"IMGDATA")

    import os
    assert not os.path.exists(captured["img_path"])


# ── 退避模型清單 ─────────────────────────────────────────────

def test_fallback_models_starts_with_primary(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "gemini-flash-latest")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "model-a, model-b")
    assert gemini._fallback_models() == ["gemini-flash-latest", "model-a", "model-b"]


def test_fallback_models_dedupes(monkeypatch):
    """備援清單重複列到主模型時不該讓同一個模型被試兩次。"""
    monkeypatch.setenv("MODEL_NAME", "model-a")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "model-a,model-b")
    assert gemini._fallback_models() == ["model-a", "model-b"]


# ── vision_text：主模型 → 備援 Gemini → codex ─────────────────

def _stub_gemini(monkeypatch, behaviour):
    """behaviour: {model: 回傳值 or Exception}"""
    calls = []

    def fake_gemini_image(prompt, image_bytes, mime_type="image/jpeg", model=None, schema=None):
        calls.append(model)
        result = behaviour[model]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gemini, "gemini_image", fake_gemini_image)
    return calls


def _stub_codex(monkeypatch, result):
    calls = []

    def fake_codex_image(prompt, image_bytes, mime_type="image/jpeg", schema=None):
        calls.append(mime_type)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gemini, "codex_image", fake_codex_image)
    return calls


def test_vision_uses_primary_and_stops(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    calls = _stub_gemini(monkeypatch, {"primary": "主模型結果"})
    codex_calls = _stub_codex(monkeypatch, "不該被呼叫")

    assert gemini.vision_text("p", b"img") == "主模型結果"
    assert calls == ["primary"]        # 成功就不該再試備援
    assert codex_calls == []


def test_vision_falls_back_to_next_gemini_model(monkeypatch):
    """主模型連續 503、備援模型正常時，要改用備援模型。"""
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    calls = _stub_gemini(monkeypatch, {
        "primary": RuntimeError("HTTP Error 503: Service Unavailable"),
        "backup": "備援結果",
    })
    codex_calls = _stub_codex(monkeypatch, "不該被呼叫")

    assert gemini.vision_text("p", b"img") == "備援結果"
    assert calls == ["primary", "backup"]
    assert codex_calls == []


def test_vision_falls_back_to_codex_when_all_gemini_fail(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    _stub_gemini(monkeypatch, {
        "primary": RuntimeError("503"),
        "backup": RuntimeError("503"),
    })
    codex_calls = _stub_codex(monkeypatch, "codex 結果")

    assert gemini.vision_text("p", b"img", mime_type="image/png") == "codex 結果"
    assert codex_calls == ["image/png"]


def test_vision_skips_codex_when_disallowed(monkeypatch):
    """CAPTCHA 場景：codex 政策上會拒絕，退過去只是白等——所以根本不該呼叫。"""
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    _stub_gemini(monkeypatch, {
        "primary": RuntimeError("503"),
        "backup": RuntimeError("503"),
    })
    codex_calls = _stub_codex(monkeypatch, "不該被呼叫")

    with pytest.raises(RuntimeError):
        gemini.vision_text("p", b"img", allow_codex=False)
    assert codex_calls == []


def test_vision_treats_unusable_answer_as_failure(monkeypatch):
    """模型「HTTP 200 但回一段拒絕文字」也算失敗，要換下一個模型。

    例如 gemini-3.5-flash 對 CAPTCHA 會回「我無法協助辨識或解密驗證碼（CAPTCHA）圖片」，
    這不是例外、是正常回應。只靠 try/except 退避的話，這段廢話會被當成答案傳回呼叫端，
    退避等於沒作用——CAPTCHA 就是這樣一整串模型都「成功」卻登不進去。
    """
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    calls = _stub_gemini(monkeypatch, {
        "primary": "我無法協助辨識或解密驗證碼（CAPTCHA）圖片。",
        "backup": "23964",
    })

    got = gemini.vision_text("p", b"img", allow_codex=False,
                             validate=lambda raw: len(raw.strip()) == 5)
    assert got == "23964"
    assert calls == ["primary", "backup"]


def test_vision_validate_applies_to_codex_too(monkeypatch):
    """codex 那層的答案一樣要過驗證，不然只是把廢話從別的來源丟回去。"""
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    _stub_gemini(monkeypatch, {"primary": "不合格"})
    _stub_codex(monkeypatch, "也不合格")

    with pytest.raises(RuntimeError):
        gemini.vision_text("p", b"img", validate=lambda raw: raw == "合格")


def test_vision_without_validate_accepts_anything(monkeypatch):
    """沒給驗證器就維持原行為：拍照記帳那種自由格式輸出不該被亂擋。"""
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    calls = _stub_gemini(monkeypatch, {"primary": "隨便什麼字"})
    assert gemini.vision_text("p", b"img") == "隨便什麼字"
    assert calls == ["primary"]


def test_captcha_solver_passes_validator(monkeypatch):
    """einvoice 要把「必須是 5 位數字」當驗證器傳下去，而不是自己事後才檢查。"""
    import inspect
    import einvoice
    src = inspect.getsource(einvoice._solve_captcha)
    assert "validate=" in src


def test_vision_error_mentions_every_attempt(monkeypatch):
    """全掛時的錯誤訊息要說得出「誰失敗、為什麼」，否則 log 只剩一句沒用的辨識失敗。"""
    monkeypatch.setenv("MODEL_NAME", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "backup")
    _stub_gemini(monkeypatch, {
        "primary": RuntimeError("503 忙碌"),
        "backup": RuntimeError("404 沒這模型"),
    })
    _stub_codex(monkeypatch, RuntimeError("codex 拒絕"))

    with pytest.raises(RuntimeError) as exc:
        gemini.vision_text("p", b"img")
    msg = str(exc.value)
    assert "primary" in msg and "backup" in msg and "codex" in msg


# ── 呼叫端接上退避鏈 ─────────────────────────────────────────

def test_captcha_solver_disallows_codex(monkeypatch):
    """einvoice 的 CAPTCHA 一定要帶 allow_codex=False。"""
    import inspect
    import einvoice
    src = inspect.getsource(einvoice._solve_captcha)
    assert "vision_text" in src
    assert "allow_codex=False" in src


def test_photo_and_food_use_vision_text():
    """拍照記帳 / 美食截圖走 vision_text（可退 codex），不直接呼叫 gemini_image。"""
    import inspect
    import core
    import food.extract as fx
    assert "vision_text" in inspect.getsource(core._read_receipt)
    assert "_read_receipt" in inspect.getsource(core.handle_image_data)
    assert "_read_receipt" in inspect.getsource(core.handle_image)
    assert "vision_text" in inspect.getsource(fx.from_image)


def test_gemini_logs_token_usage(monkeypatch, capsys):
    """計費 API 要看得到用量——沒有這行 log，就無從量測 prompt 瘦身省了多少。"""
    import json as _json

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({
                "candidates": [{"content": {"parts": [{"text": "嗨"}]}}],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 8,
                                  "totalTokenCount": 128},
            }).encode()

    monkeypatch.setattr(gemini.urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    assert gemini.gemini_text("hi", model="m") == "嗨"
    assert "m tokens：in=120 out=8 total=128" in capsys.readouterr().out
