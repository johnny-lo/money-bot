"""pytest 單元測試：report_helpers 純函式。

跑法：
  docker compose exec app pytest tests/ -v
"""
from datetime import date

import pytest

from report_helpers import (
    compare,
    top_n_expenses, format_top_n,
    detect_anomalies, format_anomalies,
    sparkline, daily_heatmap,
    savings_rate, format_savings_rate,
    budget_status,
    week_range, previous_week_range,
    month_range, previous_month, is_first_sunday,
)


# ─── compare ─────────────────────────────────────────────────

class TestCompare:
    def test_increase(self):
        assert compare(12000, 10000) == "↑20% (上期 $10,000)"

    def test_decrease(self):
        assert compare(8000, 10000) == "↓20% (上期 $10,000)"

    def test_flat(self):
        assert compare(10000, 10000) == "持平 (上期 $10,000)"

    def test_near_flat(self):
        # 0.4% 差距視為持平
        assert compare(10040, 10000) == "持平 (上期 $10,000)"

    def test_prev_zero_curr_positive(self):
        assert compare(5000, 0) == "首期 (無上期資料)"

    def test_prev_zero_curr_zero(self):
        assert compare(0, 0) == "—"

    def test_big_jump(self):
        # 200% 上升
        assert compare(30000, 10000) == "↑200% (上期 $10,000)"


# ─── top_n_expenses ──────────────────────────────────────────

class TestTopN:
    def test_sorts_by_amount_desc(self):
        records = [
            {"item": "a", "amount": 100, "category": "三餐", "date": "5/1"},
            {"item": "b", "amount": 500, "category": "交通", "date": "5/2"},
            {"item": "c", "amount": 300, "category": "飲料零食", "date": "5/3"},
        ]
        result = top_n_expenses(records, n=2)
        assert [r["item"] for r in result] == ["b", "c"]

    def test_n_larger_than_list(self):
        records = [{"item": "a", "amount": 100, "category": "三餐", "date": "5/1"}]
        assert len(top_n_expenses(records, n=5)) == 1

    def test_empty(self):
        assert top_n_expenses([], n=3) == []

    def test_format_top_n_empty(self):
        assert format_top_n([]) == "（無）"

    def test_format_top_n_has_category(self):
        records = [{"item": "車貸", "amount": 13611, "category": "分期保險", "date": "5/11"}]
        out = format_top_n(records)
        assert "車貸" in out
        assert "13,611" in out
        assert "分期保險" in out


# ─── detect_anomalies ────────────────────────────────────────

class TestAnomalies:
    def test_detects_high(self):
        current = {"飲料零食": 3000}
        history = [{"飲料零食": 1000}, {"飲料零食": 1200}, {"飲料零食": 800}]
        # 均值 = 1000, current 3000, 高 200%
        result = detect_anomalies(current, history)
        assert len(result) == 1
        assert result[0]["category"] == "飲料零食"
        assert result[0]["avg"] == 1000
        assert result[0]["pct"] == pytest.approx(200.0)

    def test_below_threshold(self):
        current = {"飲料零食": 1200}  # 高 20%
        history = [{"飲料零食": 1000}]
        # 預設閾值 50%，20% 不算
        assert detect_anomalies(current, history) == []

    def test_new_category_no_history(self):
        # 過去沒這個分類 → 不算異常
        current = {"新分類": 5000}
        history = [{"飲料零食": 1000}]
        assert detect_anomalies(current, history) == []

    def test_empty_history(self):
        assert detect_anomalies({"a": 100}, []) == []

    def test_multiple_anomalies_sorted_by_pct(self):
        current = {"A": 200, "B": 500}
        history = [{"A": 100, "B": 100}]  # A 高 100%, B 高 400%
        result = detect_anomalies(current, history)
        assert [r["category"] for r in result] == ["B", "A"]

    def test_zero_current_skipped(self):
        current = {"A": 0}
        history = [{"A": 1000}]
        assert detect_anomalies(current, history) == []


# ─── sparkline / daily_heatmap ───────────────────────────────

class TestSparkline:
    def test_basic(self):
        out = sparkline([1, 3, 2, 5, 4])
        assert len(out) == 5
        # 最高的 5 應該是最後一格的最高 block
        assert out[3] == "█"
        # 最低的 1 應該是 ▁
        assert out[0] == "▁"

    def test_empty(self):
        assert sparkline([]) == "（無資料）"

    def test_all_same(self):
        out = sparkline([5, 5, 5])
        assert all(c == "▄" for c in out)

    def test_zeros(self):
        out = sparkline([0, 0, 0])
        # 全相同處理：中間高度
        assert len(out) == 3


class TestDailyHeatmap:
    def test_seven_days(self):
        out = daily_heatmap([100, 200, 300, 400, 500, 600, 700])
        lines = out.split("\n")
        assert len(lines) == 7
        assert "週一" in lines[0]
        assert "週日" in lines[6]
        assert "$700" in lines[6]

    def test_wrong_length(self):
        assert daily_heatmap([1, 2, 3]) == "（資料異常）"


# ─── savings_rate ────────────────────────────────────────────

class TestSavingsRate:
    def test_positive_rate(self):
        # 收入 50000, 支出 30000 → 儲蓄 20000, 40%
        assert savings_rate(50000, 30000) == pytest.approx(40.0)

    def test_negative_rate(self):
        # 收入 10000, 支出 15000 → -50%
        assert savings_rate(10000, 15000) == pytest.approx(-50.0)

    def test_zero_income(self):
        assert savings_rate(0, 5000) is None

    def test_zero_expense(self):
        assert savings_rate(10000, 0) == pytest.approx(100.0)

    def test_format_savings_rate_no_income(self):
        out = format_savings_rate(0, 5000)
        assert "無收入" in out
        assert "5,000" in out

    def test_format_savings_rate_surplus(self):
        out = format_savings_rate(50000, 30000)
        assert "+40%" in out
        assert "+$20,000" in out

    def test_format_savings_rate_deficit(self):
        out = format_savings_rate(10000, 15000)
        assert "-50%" in out
        assert "-$5,000" in out


# ─── budget_status ───────────────────────────────────────────

class TestBudgetStatus:
    def test_no_budget(self):
        assert budget_status(1000, 0, 15, 30) is None

    def test_over_budget(self):
        out = budget_status(50000, 40000, 20, 30)
        assert "超支" in out
        assert "10,000" in out  # 超支金額

    def test_healthy_progress(self):
        # 月過 50%（15/30），花了 40% 預算 → 健康（落後 10pp）
        out = budget_status(8000, 20000, 15, 30)
        assert "健康" in out

    def test_slightly_fast(self):
        # 月過 33%（10/30），花了 40% 預算 → 略快（差 7pp）
        out = budget_status(8000, 20000, 10, 30)
        assert "略快" in out

    def test_too_fast(self):
        # 月過 20%（6/30），花了 50% 預算 → 過快（差 30pp）
        out = budget_status(10000, 20000, 6, 30)
        assert "過快" in out


# ─── 日期工具 ────────────────────────────────────────────────

class TestDateUtils:
    def test_week_range_on_monday(self):
        mon, sun = week_range(date(2026, 5, 11))  # 週一
        assert mon == date(2026, 5, 11)
        assert sun == date(2026, 5, 17)

    def test_week_range_on_friday(self):
        mon, sun = week_range(date(2026, 5, 15))  # 週五
        assert mon == date(2026, 5, 11)
        assert sun == date(2026, 5, 17)

    def test_week_range_on_sunday(self):
        mon, sun = week_range(date(2026, 5, 17))  # 週日
        assert mon == date(2026, 5, 11)
        assert sun == date(2026, 5, 17)

    def test_previous_week_range(self):
        prev_mon, prev_sun = previous_week_range(date(2026, 5, 14))
        assert prev_mon == date(2026, 5, 4)
        assert prev_sun == date(2026, 5, 10)

    def test_month_range_normal(self):
        start, end = month_range(2026, 5)
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_month_range_feb_leap(self):
        # 2028 是閏年
        start, end = month_range(2028, 2)
        assert end == date(2028, 2, 29)

    def test_month_range_feb_non_leap(self):
        start, end = month_range(2026, 2)
        assert end == date(2026, 2, 28)

    def test_previous_month_normal(self):
        assert previous_month(2026, 5) == (2026, 4)

    def test_previous_month_january(self):
        assert previous_month(2026, 1) == (2025, 12)

    def test_is_first_sunday_yes(self):
        # 2026/5/3 是週日
        assert is_first_sunday(date(2026, 5, 3)) is True

    def test_is_first_sunday_second_sunday(self):
        # 2026/5/10 也是週日，但是第 2 個
        assert is_first_sunday(date(2026, 5, 10)) is False

    def test_is_first_sunday_not_sunday(self):
        # 2026/5/4 週一
        assert is_first_sunday(date(2026, 5, 4)) is False

    def test_is_first_sunday_edge_day_7(self):
        # 2026/6/7 是週日且 day=7，剛好是六月第一個週日
        assert is_first_sunday(date(2026, 6, 7)) is True
