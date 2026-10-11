"""機密只能經 app_secrets.get_secret 讀：程式碼裡對機密名稱寫 os.getenv / os.environ 就失敗。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET_NAMES = [
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "DISCORD_BOT_TOKEN", "GEMINI_API_KEY",
    "GOOGLE_PLACES_SERVER_KEY", "DATABASE_URL", "EINVOICE_PHONE_", "EINVOICE_PASSWORD_",
    "GMAIL_APP_PASSWORD", "NATIONAL_ID",
]
# 豁免：一次性 probe 容器沒有 /run/secrets，autofix/bin/probe 只把單一載具帳密經 env 帶進去
EXEMPT = {"autofix/probes/einvoice_probe.py"}
SKIP_PARTS = {"tests", "frontend", "node_modules", "docs", "data", "__pycache__", "venv"}
ENV_READ = re.compile(r"\bos\.(getenv|environ)\b")


def find_violations(root: pathlib.Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if rel.as_posix() in EXEMPT or rel.as_posix() == "app_secrets.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if ENV_READ.search(line) and any(n in line for n in SECRET_NAMES):
                out.append(f"{rel.as_posix()}:{i}: {line.strip()}")
    return out


def test_no_direct_env_reads_of_secrets():
    v = find_violations(ROOT)
    assert v == [], "機密要經 app_secrets.get_secret 讀，不能 os.getenv / os.environ：\n" + "\n".join(v)


def test_guard_detects_patterns(tmp_path):
    (tmp_path / "bad.py").write_text(
        'import os\n'
        'a = os.getenv(f"EINVOICE_PHONE_{i}")\n'
        'b = os.environ["GEMINI_API_KEY"]\n'
        'c = os.environ.get("NATIONAL_ID", "")\n',
        encoding="utf-8")
    (tmp_path / "ok.py").write_text(
        'import os\n'
        'from app_secrets import get_secret\n'
        'a = get_secret("GEMINI_API_KEY")\n'
        'b = os.getenv("MODEL_NAME")\n'
        'print("未設定 DISCORD_BOT_TOKEN")\n',
        encoding="utf-8")
    v = find_violations(tmp_path)
    assert [x.split(":")[0:2] for x in v] == [["bad.py", "2"], ["bad.py", "3"], ["bad.py", "4"]]


def test_guard_skips_tests_and_hidden_dirs(tmp_path):
    for d in ("tests", ".claude/worktrees/x"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "t.py").write_text('import os\nos.getenv("GEMINI_API_KEY")\n', encoding="utf-8")
    assert find_violations(tmp_path) == []
