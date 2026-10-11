"""app_secrets.get_secret：檔案優先、環境變數退路、空值一律 None。"""
import os

import app_secrets
from app_secrets import get_secret


def _secrets(tmp_path, monkeypatch, files: dict[str, str]):
    d = tmp_path / "secrets"
    d.mkdir()
    for name, value in files.items():
        (d / name).write_text(value, encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(d))
    return d


def test_reads_lowercase_file(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "abc"})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_secret("GEMINI_API_KEY") == "abc"


def test_strips_newline_and_crlf(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"gemini_api_key": "abc\r\n"})
    assert get_secret("GEMINI_API_KEY") == "abc"


def test_keeps_inner_spaces_and_hash(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"einvoice_password_1": "p@ss #1 x\n"})
    assert get_secret("EINVOICE_PASSWORD_1") == "p@ss #1 x"


def test_empty_file_is_none_even_if_env_set(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"einvoice_phone_2": ""})
    monkeypatch.setenv("EINVOICE_PHONE_2", "from-env")
    assert get_secret("EINVOICE_PHONE_2") is None


def test_whitespace_only_file_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"national_id": "  \n"})
    assert get_secret("NATIONAL_ID") is None


def test_file_wins_over_env(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {"discord_bot_token": "from-file"})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "from-env")
    assert get_secret("DISCORD_BOT_TOKEN") == "from-file"


def test_missing_file_falls_back_to_env(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.setenv("DISCORD_BOT_TOKEN", " from-env ")
    assert get_secret("DISCORD_BOT_TOKEN") == "from-env"


def test_missing_everywhere_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.delenv("EINVOICE_PHONE_3", raising=False)
    assert get_secret("EINVOICE_PHONE_3") is None


def test_empty_env_is_none(tmp_path, monkeypatch):
    _secrets(tmp_path, monkeypatch, {})
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "")
    assert get_secret("LINE_CHANNEL_SECRET") is None


def test_missing_secrets_dir_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert get_secret("GEMINI_API_KEY") == "from-env"


def test_default_dir_is_run_secrets():
    assert app_secrets.DEFAULT_SECRETS_DIR == "/run/secrets"


def test_conftest_isolates_real_secrets():
    """conftest 的 autouse fixture：測試期間 SECRETS_DIR 指向空目錄，讀不到正式容器的 /run/secrets。"""
    d = os.environ["SECRETS_DIR"]
    assert d != "/run/secrets"
    assert os.path.isdir(d) and os.listdir(d) == []
