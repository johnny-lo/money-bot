import pytest
from autofix.prompt import build_prompt

INC = {"id": 7, "sensor": "einvoice_login", "signature": "載具1", "title": "t",
       "context": {"attempts": ["x"]}, "hit_keys": [], "escalated": False}


def test_prompt_含事件資料_規則_與_skill_指示():
    p = build_prompt(INC, "/home/u/linebot/autofix")
    assert '"signature": "載具1"' in p
    assert "最多送出 3 次" in p                              # einvoice 規則
    assert "superpowers:systematic-debugging" in p
    assert "/home/u/linebot/autofix/bin/test" in p
    assert "{{" not in p                                      # 沒有殘留佔位符


def test_未知感測器_明確失敗():
    with pytest.raises(FileNotFoundError):
        build_prompt({**INC, "sensor": "nope"}, "/x")
