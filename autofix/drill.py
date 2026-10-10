"""手動觸發演習事件：docker exec -w /app money-bot python -m autofix.drill"""
from autofix import incidents

if __name__ == "__main__":
    if not incidents.enabled():
        raise SystemExit("AUTOFIX_ENABLED 不是 1")
    incidents.raise_incident("drill", "drill", "演習：登入落地判斷壞了",
                             {"symptom": "tests/test_einvoice_login_landing.py 失敗"},
                             dedupe_key=incidents.now_tw().isoformat())
    print("已觸發演習事件（看 docker logs 的 🛠 行與 autofix/inbox/）")
