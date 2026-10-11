"""部署後的上線驗證（在正式容器內跑：docker exec money-bot python -m autofix.verify <id>）。"""
import asyncio
import json
import os
import subprocess
import sys


def check(incident: dict, *, scrape, extract_one, run_tests) -> tuple[bool, str]:
    s = incident["sensor"]
    if s == "einvoice_login":
        label = int(incident["signature"].replace("載具", ""))
        try:
            n = scrape(label)
        except Exception as e:
            return False, f"載具{label} 仍然失敗：{type(e).__name__}: {e}"
        return True, f"載具{label} 登入成功，近 1 天抓到 {n} 張"
    if s == "link_extract":
        urls = (incident.get("context") or {}).get("urls") or []
        ok = sum(1 for u in urls if extract_one(u))
        return ok * 2 > len(urls), f"{ok}/{len(urls)} 個當初失敗的網址現在抽得到"
    if s == "scheduler_job":
        return True, "排程類無法安全重放：已上線，待下次排程確認（7 天內再犯會升級人工）"
    if s == "drill":
        good = run_tests("tests/test_einvoice_login_landing.py")
        return good, "演習：登入落地測試" + ("通過" if good else "失敗")
    return False, f"未知感測器 {s}"


def _scrape(label: int) -> int:
    import einvoice
    from app_secrets import get_secret
    phone = get_secret(f"EINVOICE_PHONE_{label}")
    pw = get_secret(f"EINVOICE_PASSWORD_{label}")
    if not (phone and pw):
        # 保留舊的 os.environ[...] 語意：缺帳密就失敗，check() 會接住並回報
        raise KeyError(f"載具{label} 帳密未設定（secrets 檔 einvoice_phone_{label} / einvoice_password_{label}）")
    return len(asyncio.run(einvoice._scrape_carrier(phone, pw, 1)))


def _extract_one(url: str) -> bool:
    from food.links import classify_platform
    from food import extract
    try:
        return bool(extract.from_url(url, classify_platform(url)))
    except Exception:
        return False


def _run_tests(path: str) -> bool:
    return subprocess.run([sys.executable, "-m", "pytest", path, "-q"], cwd="/app").returncode == 0


if __name__ == "__main__":
    iid = sys.argv[1]
    with open(f"/app/autofix/state/{iid}.inbox.json", encoding="utf-8") as f:
        inc = json.load(f)
    ok, msg = check(inc, scrape=_scrape, extract_one=_extract_one, run_tests=_run_tests)
    print(msg)
    sys.exit(0 if ok else 1)
