from datetime import date
from discordbot.embeds import invoice_sync_failed_embed


def test_failed_embed_lists_failure_and_retry():
    result = {
        "summary": "🧾 發票補拓（2026-06-16 ~ 2026-06-18）\n  載具2 0987***21 2026-06 近 3 天：❌ RuntimeError: 登入失敗",
        "failures": [{"label": 2, "masked": "0987***21", "month": "2026-06 近 3 天",
                      "error": "RuntimeError: 登入失敗"}],
        "last_covered": date(2026, 6, 15),
        "retry_from": date(2026, 6, 16),
    }
    e = invoice_sync_failed_embed(result)
    blob = e.title + (e.description or "") + " ".join(f"{f.name}{f.value}" for f in e.fields)
    assert "失敗" in e.title
    assert "登入失敗" in blob
    assert "未推進" in blob
    assert "2026-06-15" in blob and "2026-06-16" in blob   # 仍停在 + 下次重抓起點
