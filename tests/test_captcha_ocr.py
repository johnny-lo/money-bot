"""本地 CAPTCHA OCR（ddddocr）+ 樣本收集的測試。

不載入真的 ddddocr 模型、不出網：OCR 引擎一律 monkeypatch 掉。

實測背景（30 張財政部真圖，見 AGENTS.md）：
ddddocr 官方通用模型 27/30 = 90%，3 個錯誤全是「7 被認成 t/z」；
補上相似字修正後 30/30，平均 4.4 ms/張（Gemini 是 1~3 秒，且會 503、會政策拒答）。
"""
import os

import pytest

import captcha_ocr


# ── 相似字修正：財政部驗證碼保證純數字，字母一定是誤認 ────────────

@pytest.mark.parametrize("raw,expected", [
    ("77601", "77601"),          # 本來就對
    ("t7601", "77601"),          # 實測 011.png
    ("z5644", "75644"),          # 實測 024.png
    ("5z507", "57507"),          # 實測 027.png
    ("Z1323", "71323"),          # 實測 006.png（beta 模型）
    ("o0O00", "00000"),
    ("l1I23", "11123"),
])
def test_digitize_fixes_confusable_letters(raw, expected):
    assert captcha_ocr.digitize(raw) == expected


def test_digitize_strips_whitespace_and_punctuation():
    assert captcha_ocr.digitize("  12 345 \n") == "12345"


# ── recognize：辨識 + 修正 + 「必須 5 位數字」把關 ────────────────

def _fake_engine(monkeypatch, result):
    class FakeOcr:
        def classification(self, img, png_fix=False):
            if isinstance(result, Exception):
                raise result
            return result
    monkeypatch.setattr(captcha_ocr, "_get_ocr", lambda: FakeOcr())


def test_recognize_returns_digits(monkeypatch):
    _fake_engine(monkeypatch, "t7601")
    assert captcha_ocr.recognize(b"img") == "77601"


def test_recognize_rejects_wrong_length(monkeypatch):
    """辨識成 4 碼或 6 碼就是錯的，回 None 讓呼叫端退到 AI，不要送出去白白消耗帳密錯誤次數。"""
    _fake_engine(monkeypatch, "1234")
    assert captcha_ocr.recognize(b"img") is None


def test_recognize_returns_none_when_engine_raises(monkeypatch):
    _fake_engine(monkeypatch, RuntimeError("boom"))
    assert captcha_ocr.recognize(b"img") is None


def test_recognize_returns_none_when_ddddocr_missing(monkeypatch):
    """ddddocr 沒裝時要安靜退場，不能讓 import 或辨識炸掉整個登入流程。"""
    monkeypatch.setattr(captcha_ocr, "_get_ocr", lambda: None)
    assert captcha_ocr.recognize(b"img") is None


# ── 樣本收集 ─────────────────────────────────────────────────

def test_save_sample_writes_answer_in_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", str(tmp_path))
    captcha_ocr.save_sample(b"PNGDATA", "12345")
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("_12345.png")     # 答案就是標註，不另外存 label 檔
    assert files[0].read_bytes() == b"PNGDATA"


def test_save_sample_rejects_bad_answer(tmp_path, monkeypatch):
    """只存確定正確的樣本。答案不是 5 位數字就不該進資料集——髒標註比沒有更糟。"""
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", str(tmp_path))
    captcha_ocr.save_sample(b"PNGDATA", "abc")
    captcha_ocr.save_sample(b"PNGDATA", "1234")
    assert list(tmp_path.iterdir()) == []


def test_save_sample_never_raises(tmp_path, monkeypatch):
    """收樣本是 best-effort 的附帶行為，壞掉也絕不能影響登入。"""
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", "/proc/nope/cannot-write")
    captcha_ocr.save_sample(b"PNGDATA", "12345")     # 不該丟例外


# ── 容量上限：超過就刪最舊的 ─────────────────────────────────

def test_prune_deletes_oldest_until_under_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", str(tmp_path))
    monkeypatch.setattr(captcha_ocr, "SAMPLE_MAX_BYTES", 300)

    # 每張 100 bytes，寫 5 張 = 500 bytes > 300 上限
    for i in range(5):
        p = tmp_path / f"2026083{i}_120000_1234{i}.png"
        p.write_bytes(b"x" * 100)
        os.utime(p, (1000 + i, 1000 + i))           # 明確排序：i 越小越舊

    captcha_ocr.prune_samples()

    left = sorted(f.name for f in tmp_path.iterdir())
    assert len(left) == 3                            # 300 bytes 剛好塞 3 張
    assert "20260830_120000_12340.png" not in left   # 最舊的先被刪
    assert "20260834_120000_12344.png" in left       # 最新的留著


def test_prune_keeps_everything_under_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", str(tmp_path))
    monkeypatch.setattr(captcha_ocr, "SAMPLE_MAX_BYTES", 10_000)
    for i in range(3):
        (tmp_path / f"a{i}.png").write_bytes(b"x" * 100)
    captcha_ocr.prune_samples()
    assert len(list(tmp_path.iterdir())) == 3


def test_save_sample_prunes_automatically(tmp_path, monkeypatch):
    """上限要在寫入路徑上自動生效，不能指望有人記得手動跑清理。"""
    monkeypatch.setattr(captcha_ocr, "SAMPLE_DIR", str(tmp_path))
    monkeypatch.setattr(captcha_ocr, "SAMPLE_MAX_BYTES", 250)
    for i in range(5):
        captcha_ocr.save_sample(b"x" * 100, f"1234{i}")
    total = sum(f.stat().st_size for f in tmp_path.iterdir())
    assert total <= 250


def test_sample_max_bytes_default_is_1gb():
    assert captcha_ocr.SAMPLE_MAX_BYTES == 1024 ** 3


def test_sample_dir_is_absolute():
    """相對路徑會讓樣本跟著 cwd 跑（排程 / CLI / docker exec 的 cwd 不保證一致）。"""
    assert os.path.isabs(captcha_ocr.SAMPLE_DIR)


# ── einvoice 接線：本地優先、AI 兜底 ─────────────────────────

def test_solve_captcha_tries_local_ocr_first():
    import inspect
    import einvoice
    src = inspect.getsource(einvoice._solve_captcha)
    assert "captcha_ocr.recognize" in src
    # 本地成功就不該再打 AI
    assert src.index("captcha_ocr.recognize") < src.index("vision_text")


def test_login_saves_sample_only_after_success():
    """樣本只在登入成功後存——那一刻才確定答案是對的。辨識完就存會存進錯的標註。"""
    import inspect
    import einvoice
    src = inspect.getsource(einvoice._login_attempt)   # 單次嘗試的成功分支
    assert "save_sample" in src
    save_pos = src.index("save_sample")
    ok_pos = src.index("登入成功")
    assert abs(save_pos - ok_pos) < 400        # 兩者在同一個成功分支裡
    assert "save_sample" not in inspect.getsource(einvoice._solve_captcha)
