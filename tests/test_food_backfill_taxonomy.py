"""回填規劃器的測試（純函式，不連 DB）。

寫入器（_apply/run）靠 dry-run + 人工看 diff + 重跑 0 changed 驗，不單測 —— 照
AGENTS.md §6：repo/glue 走 smoke，純邏輯走單元測試。
"""
from food.backfill_taxonomy import plan_region_rows, plan_cuisine_rows


def _row(**kw):
    base = {
        "id": 1, "name": "測試店", "country": "台灣",
        "address": "320台灣桃園市中壢區興南里永樂街97號",
        "city": "桃園市", "district": "中壢區",
        "cuisine_type": None, "cuisine_major": None, "cuisine_minor": None,
        "recommended_items": None,
    }
    base.update(kw)
    return base


# ── 地區 ──────────────────────────────────────────────────────

def test_已正規的列不產生變更():
    """冪等的來源：目標值與現值相同就跳過。"""
    assert plan_region_rows([_row()]) == []


def test_里名與去後綴縣市各產生一項變更():
    changes = plan_region_rows([_row(city="桃園", district="興南里")])
    assert {(c["field"], c["old"], c["new"]) for c in changes} == {
        ("city", "桃園", "桃園市"),
        ("district", "興南里", "中壢區"),
    }


def test_新竹縣市不再糊在一起():
    changes = plan_region_rows([
        _row(id=1, address="300台灣新竹市東區中正里中正路96巷24號", city="新竹", district="中正里"),
        _row(id=2, address="302台灣新竹縣竹北市十興里勝利五路43號", city="新竹", district="十興里"),
    ])
    by_id = {(c["id"], c["field"]): c["new"] for c in changes}
    assert by_id[(1, "city")] == "新竹市"
    assert by_id[(2, "city")] == "新竹縣"
    assert by_id[(2, "district")] == "竹北市"


def test_地址沒行政區但現值合法就留著():
    """別為了「地址說了算」把已經正確的資料洗掉。"""
    changes = plan_region_rows([_row(address="台灣桃園市", district="中壢區")])
    assert [c for c in changes if c["field"] == "district"] == []


def test_地址沒行政區且現值是里就清成None():
    changes = plan_region_rows([_row(address="台灣桃園市", district="興南里")])
    district = [c for c in changes if c["field"] == "district"]
    assert len(district) == 1 and district[0]["new"] is None


def test_國外列完全不碰():
    assert plan_region_rows([
        _row(country="日本", address="日本〒160-0022 東京都新宿区", city="東京", district="新宿區")
    ]) == []


def test_解不出縣市要標成失敗而不是靜默跳過():
    changes = plan_region_rows([_row(address="這不是地址")])
    assert len(changes) == 1
    assert changes[0]["ok"] is False
    assert changes[0]["reason"]


# ── 料理 ──────────────────────────────────────────────────────

def test_補空的大類():
    changes = plan_cuisine_rows([_row(cuisine_type="日式燒肉")])
    assert {(c["field"], c["new"]) for c in changes} == {
        ("cuisine_major", "日式"), ("cuisine_minor", "燒肉"),
    }


def test_missing模式跳過已有大類的列():
    assert plan_cuisine_rows([_row(cuisine_type="日式燒肉", cuisine_major="韓式",
                                   cuisine_minor="燒肉")], mode="missing") == []


def test_rules模式重推已有的列():
    changes = plan_cuisine_rows([_row(cuisine_type="日式燒肉", cuisine_major="韓式",
                                      cuisine_minor="燒肉")], mode="rules")
    assert [(c["field"], c["old"], c["new"]) for c in changes] == [
        ("cuisine_major", "韓式", "日式"),
    ]


def test_永不用空值覆蓋既有值():
    """判不出來時不該產生任何變更——空欄比錯的值好，但別把好的洗掉。"""
    changes = plan_cuisine_rows([_row(cuisine_type="小館", cuisine_major="台式")], mode="rules")
    assert changes == []


def test_判不出就不產生變更():
    assert plan_cuisine_rows([_row(cuisine_type="小館", name="拾旅。食")]) == []


def test_來源標註分得出可信度():
    """從 cuisine_type 推的（描述店）比從店名推的（描述菜）可信 → 報表要分得出來。"""
    from_raw = plan_cuisine_rows([_row(cuisine_type="拉麵")])
    from_name = plan_cuisine_rows([_row(name="極清拉麵")])
    assert all(c["source"] == "raw" for c in from_raw)
    assert all(c["source"] == "name" for c in from_name)
