"""三桶水位（投資/生活/爽）的純函式。不連 DB、不出網。

存在理由見 report_helpers 的區塊註解：助理只看得到單筆金額時，就只能用金額大小
論斷，於是每筆稍大的都被唸。這組函式把「桶位」算出來給它當判斷依據。
"""
import pytest

from report_helpers import (
    BUCKET_FUN,
    BUCKET_INVEST,
    BUCKET_LIVING,
    bucket_totals,
    format_bucket_context,
    parse_bucket_ratios,
)


# ── parse_bucket_ratios ──────────────────────────────────────

def test_三分法正規化成三等份():
    a, b, c = parse_bucket_ratios("1:1:1")
    assert a == pytest.approx(1 / 3) and b == pytest.approx(1 / 3) and c == pytest.approx(1 / 3)


def test_任意比例都正規化到加總為一():
    ratios = parse_bucket_ratios("2:5:3")
    assert sum(ratios) == pytest.approx(1.0)
    assert ratios[0] == pytest.approx(0.2) and ratios[1] == pytest.approx(0.5)


def test_斜線也接受():
    assert parse_bucket_ratios("1/1/1") == parse_bucket_ratios("1:1:1")


@pytest.mark.parametrize("bad", [None, "", "1:2", "abc:1:1", "1:1:1:1", "-1:1:1", "0:0:0"])
def test_設定寫壞就退回等分而不是壞掉(bad):
    """設定打錯不該讓整個功能消失——退回三等份，行為可預測。"""
    assert parse_bucket_ratios(bad) == pytest.approx((1 / 3, 1 / 3, 1 / 3))


# ── bucket_totals ────────────────────────────────────────────

def test_細類正確落桶():
    cats = [
        {"name": "投資", "amount": 10000},
        {"name": "三餐", "amount": 3000},
        {"name": "居住水電", "amount": 15000},
        {"name": "娛樂", "amount": 800},
        {"name": "飲料零食", "amount": 400},
    ]
    totals, uncategorized = bucket_totals(cats)
    assert totals[BUCKET_INVEST] == 10000
    assert totals[BUCKET_LIVING] == 18000
    assert totals[BUCKET_FUN] == 1200
    assert uncategorized == 0


def test_未分類單獨回報不併入任何桶():
    """記帳當下 category 是 NULL，要等週日 AI 分類。併進桶會讓水位假性偏低。"""
    cats = [{"name": "未分類", "amount": 5000}, {"name": "三餐", "amount": 1000}]
    totals, uncategorized = bucket_totals(cats)
    assert uncategorized == 5000
    assert sum(totals.values()) == 1000


def test_沒見過的分類算未分類不硬塞():
    totals, uncategorized = bucket_totals([{"name": "外星消費", "amount": 700}])
    assert uncategorized == 700
    assert sum(totals.values()) == 0


def test_其他歸生活桶而不是爽桶():
    """兜不到類的保守處理：不灌爽桶，免得使用者被無辜唸。"""
    totals, _ = bucket_totals([{"name": "其他", "amount": 999}])
    assert totals[BUCKET_LIVING] == 999 and totals[BUCKET_FUN] == 0


def test_空清單不炸():
    totals, uncategorized = bucket_totals([])
    assert uncategorized == 0 and sum(totals.values()) == 0


# ── format_bucket_context ────────────────────────────────────

_R = (1 / 3, 1 / 3, 1 / 3)


def test_沒有收入基準就回_None():
    """沒基準就不要瞎猜——呼叫端會因此完全不傳 context，角色走保守模式。"""
    assert format_bucket_context(0, [{"name": "三餐", "amount": 100}], _R,
                                 day_of_month=10, days_in_month=31) is None


def test_算得出每桶的用量與百分比():
    out = format_bucket_context(
        60000, [{"name": "娛樂", "amount": 10000}], _R,
        day_of_month=15, days_in_month=30,
    )
    assert "$60,000" in out
    assert "🎉 爽：$10,000 / $20,000（50%）" in out
    assert "🏦 投資：$0 / $20,000（0%）" in out
    assert "月份進度：15/30 天（50%）" in out


def test_有未分類就明講低估():
    out = format_bucket_context(
        60000, [{"name": "未分類", "amount": 3000}], _R,
        day_of_month=1, days_in_month=31,
    )
    assert "尚未分類 $3,000" in out and "低估" in out


def test_沒有未分類就不出現那行():
    out = format_bucket_context(
        60000, [{"name": "三餐", "amount": 3000}], _R,
        day_of_month=1, days_in_month=31,
    )
    assert "尚未分類" not in out


@pytest.mark.parametrize("basis", ["本月收入", "上月收入", "設定的月收入"])
def test_基準來源要標示出來(basis):
    """基準有三種來源（本月實收/上月實收/設定值），角色要知道自己在拿什麼比。"""
    out = format_bucket_context(50000, [], _R, day_of_month=2, days_in_month=31, basis=basis)
    assert basis in out


# ── 全域不變式（加新細類時最容易漏掉的那條）──────────────────

def test_每個細類都必須有對應的桶():
    """categorize.CATEGORIES 是單一真相；新增細類卻忘了給桶，那筆錢就會被
    默默算成「未分類」，水位永遠低估。這條測試就是為了讓那個疏忽變成紅燈。
    """
    from categorize import CATEGORIES
    from report_helpers import CATEGORY_BUCKETS

    missing = set(CATEGORIES) - set(CATEGORY_BUCKETS)
    extra = set(CATEGORY_BUCKETS) - set(CATEGORIES)
    assert not missing, f"這些細類沒有對應的桶：{sorted(missing)}"
    assert not extra, f"這些桶映射的細類已不存在：{sorted(extra)}"


def test_桶的值只能是三個合法桶():
    from report_helpers import BUCKET_ORDER, CATEGORY_BUCKETS
    assert set(CATEGORY_BUCKETS.values()) <= set(BUCKET_ORDER)
