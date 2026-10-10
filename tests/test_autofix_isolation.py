"""測試絕不能打進正式的自動修復事件表。

背景：部署時在正式容器（AUTOFIX_ENABLED=1、DATABASE_URL 指向正式 DB）裡跑 pytest，
測試模擬的「yt-dlp 掛了」真的被感測器記成事件 #3；累積 3 條不同網址就會真的派發、叫醒 Claude。
"""
import os

from autofix import incidents


def test_測試期間_autofix_一律停用():
    assert os.getenv("AUTOFIX_ENABLED", "") != "1"
    assert incidents.enabled() is False
