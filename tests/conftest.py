"""全測試共用的安全設定。"""
import pytest


@pytest.fixture(autouse=True)
def _autofix_off(monkeypatch):
    """測試一律關閉自動修復感測器。

    標準測試指令是 `docker exec money-bot pytest`——在正式容器裡跑，AUTOFIX_ENABLED=1、
    DATABASE_URL 指向正式 DB。不關掉的話，測試裡模擬的失敗會被記成真的事件，
    累積到門檻還會真的派發、叫醒 Claude（部署 drill 時真的發生過：事件 #3「yt-dlp 掛了」）。
    要測 autofix 本身的測試自己 setenv 回 "1"，並把 SessionLocal 換成假的。
    """
    monkeypatch.delenv("AUTOFIX_ENABLED", raising=False)


@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch, tmp_path_factory):
    """測試一律讀不到正式容器的 /run/secrets。

    標準測試指令在正式容器裡跑，/run/secrets 有真值；get_secret 檔案優先，
    不隔離的話 monkeypatch.delenv 的「未設定」測試會讀到真金鑰而失敗，甚至拿真金鑰出網。
    要測讀檔的測試自己 setenv SECRETS_DIR 到自己的 tmp 目錄。
    """
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path_factory.mktemp("no-secrets")))
