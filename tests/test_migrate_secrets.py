"""scripts/migrate_secrets.sh：只在 tmp 目錄跑，驗搬遷結果、權限、冪等、從不印出值。"""
import pathlib
import stat
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate_secrets.sh"
NAMES = [
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "DISCORD_BOT_TOKEN", "GEMINI_API_KEY",
    "GOOGLE_PLACES_SERVER_KEY", "DATABASE_URL", "EINVOICE_PHONE_1", "EINVOICE_PASSWORD_1",
    "EINVOICE_PHONE_2", "EINVOICE_PASSWORD_2", "GMAIL_APP_PASSWORD", "NATIONAL_ID",
]


def _run(tmp_path, env_text: str):
    env = tmp_path / ".env"
    if not env.exists():
        env.write_text(env_text, encoding="utf-8")
    dest = tmp_path / "cfg" / "secrets"
    r = subprocess.run(["bash", str(SCRIPT), "--env", str(env), "--dest", str(dest)],
                       capture_output=True, text=True)
    return r, env, dest


def test_moves_values_and_creates_all_files(tmp_path):
    r, env, dest = _run(tmp_path, "BASE_URL=https://x\nGEMINI_API_KEY=gk-123\nDATABASE_URL=postgresql://u:p@db/x\n")
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == sorted(n.lower() for n in NAMES)
    assert (dest / "gemini_api_key").read_text() == "gk-123"
    assert (dest / "database_url").read_text() == "postgresql://u:p@db/x"
    assert (dest / "national_id").read_text() == ""          # 沒值 → 空佔位
    text = env.read_text()
    assert "BASE_URL=https://x" in text                       # 一般設定不動
    assert "gk-123" not in text and "GEMINI_API_KEY=" not in text
    assert "# GEMINI_API_KEY →" in text


def test_permissions(tmp_path):
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=gk\n")
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    for p in dest.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    baks = list((tmp_path / "cfg").glob("env.bak.*"))
    assert len(baks) == 1 and stat.S_IMODE(baks[0].stat().st_mode) == 0o600
    assert "GEMINI_API_KEY=gk" in baks[0].read_text()          # 備份是搬遷前原樣


def test_never_prints_values(tmp_path):
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=very-secret-value\nNATIONAL_ID=A123456789\n")
    assert r.returncode == 0, r.stderr
    assert "very-secret-value" not in r.stdout + r.stderr
    assert "A123456789" not in r.stdout + r.stderr


def test_value_parsing_hash_and_spaces(tmp_path):
    r, env, dest = _run(tmp_path, "EINVOICE_PASSWORD_1=ab#cd\nEINVOICE_PASSWORD_2=xy  # 行尾註解\n")
    assert r.returncode == 0, r.stderr
    assert (dest / "einvoice_password_1").read_text() == "ab#cd"   # 前面沒空白的 # 是值的一部分
    assert (dest / "einvoice_password_2").read_text() == "xy"


def test_value_parsing_quotes_and_crlf(tmp_path):
    r, env, dest = _run(tmp_path, 'GEMINI_API_KEY="a b #c"\r\nDISCORD_BOT_TOKEN=\'t#1\'\r\nLINE_CHANNEL_SECRET=s1\r\n')
    assert r.returncode == 0, r.stderr
    assert (dest / "gemini_api_key").read_text() == "a b #c"
    assert (dest / "discord_bot_token").read_text() == "t#1"
    assert (dest / "line_channel_secret").read_text() == "s1"


def test_rerun_is_idempotent(tmp_path):
    r1, env, dest = _run(tmp_path, "GEMINI_API_KEY=gk-123\n")
    r2, env, dest = _run(tmp_path, "")          # 第二次：.env 已被改寫過
    assert r1.returncode == 0 and r2.returncode == 0, r2.stderr
    assert (dest / "gemini_api_key").read_text() == "gk-123"
    assert env.read_text().count("# GEMINI_API_KEY →") == 1


def test_conflict_keeps_file_and_env_line(tmp_path):
    dest = tmp_path / "cfg" / "secrets"
    dest.mkdir(parents=True)
    (dest / "gemini_api_key").write_text("old-value")
    r, env, dest = _run(tmp_path, "GEMINI_API_KEY=new-value\n")
    assert r.returncode == 0, r.stderr
    assert (dest / "gemini_api_key").read_text() == "old-value"
    assert "GEMINI_API_KEY=new-value" in env.read_text()          # 衝突的那行留著讓人工比對
    assert "GEMINI_API_KEY" in r.stderr and "new-value" not in r.stderr


def test_missing_env_file_exits_2(tmp_path):
    r = subprocess.run(["bash", str(SCRIPT), "--env", str(tmp_path / "nope"), "--dest", str(tmp_path / "d")],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_compose_lists_same_secrets():
    """docker-compose.yml 的 secrets 清單要跟這 12 個一致（不解析 YAML：image 不保證有 pyyaml）。"""
    text = (SCRIPT.parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    for n in NAMES:
        assert f"/.config/money-bot/secrets/{n.lower()}" in text, n
        assert f"- {n}=" not in text, f"{n} 還在 environment: 白名單裡"


def test_probe_reads_credentials_from_secrets_files():
    """autofix/bin/probe 的 einvoice 帳密來自 secrets 檔，不再 grep .env。"""
    text = (SCRIPT.parent.parent / "autofix" / "bin" / "probe").read_text(encoding="utf-8")
    assert ".config/money-bot/secrets" in text
    assert "einvoice_phone_" in text and "einvoice_password_" in text
    assert '/.env"' not in text
