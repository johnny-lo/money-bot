"""既有店家的地區/料理欄位一次性回填（照 food/enrich.py 的形狀，用 docker exec 跑）。

結構：**純規劃器 + 薄寫入器**。planner 不連 DB、可單測；
DB 只在 run() 裡碰，逐列 commit。

安全機制（這會改情侶共用的正式 DB，每一項都是刻意的）：
- `dry_run=True` 是**預設**。要寫入必須明講。
- 第一次寫入前備份到 `.backups/food_taxonomy_pre_<時間>.json`。
- **中止閘**：有台灣列解不出縣市就拒絕寫入（除非 force=True）——
  靜默的半吊子解析才是會爛資料的失敗模式。
- 逐列 try/except + 逐列 commit：第 57 列爆炸不影響前 56 列。
- **冪等**：目標值與現值相同就跳過 → 跑第二次必須是 0 changed。
  那個 0 就是冪等的證明，是必做步驟不是選配。

用法：
    docker exec -w /app money-bot python -c \
      "from food import backfill_taxonomy as b; b.run('all')"              # dry-run
    docker exec -w /app money-bot python -c \
      "from food import backfill_taxonomy as b; b.run('all', dry_run=False)"
    docker exec -w /app money-bot python -c \
      "from food import backfill_taxonomy as b; b.verify_invariants()"
"""
import json
import os
import traceback
from collections import Counter
from datetime import datetime

from food import cuisine
from food.regions import parse_tw_address, normalize_district
from food.tw_divisions import TW_CITIES, TW_DISTRICTS

BACKUP_DIR = ".backups"
_SNAPSHOT_FIELDS = ("id", "place_id", "city", "district",
                    "cuisine_type", "cuisine_major", "cuisine_minor")


def _change(row, field, old, new, source, ok=True, reason="") -> dict:
    return {
        "id": row.get("id"), "name": row.get("name", ""), "address": row.get("address", ""),
        "field": field, "old": old, "new": new, "source": source,
        "ok": ok, "reason": reason,
    }


# ── 規劃器（純函式，不連 DB）──────────────────────────────────

def plan_region_rows(rows: list[dict]) -> list[dict]:
    """算出 city/district 要改成什麼。只處理台灣列，國外一律不碰。"""
    out: list[dict] = []
    for row in rows:
        if (row.get("country") or "") != "台灣":
            continue
        city, district = parse_tw_address(row.get("address"))
        if not city:
            out.append(_change(row, "city", row.get("city"), None, "addr",
                               ok=False, reason="地址解不出縣市"))
            continue
        # 地址沒給行政區，但現值剛好是這個縣市的合法行政區 → 留著（別把好資料洗掉）；
        # 現值是里 → normalize 回空 → 寫 None（里比 NULL 更糟，這是刻意清除）
        if district is None:
            district = normalize_district(city, row.get("district")) or None
        if city != row.get("city"):
            out.append(_change(row, "city", row.get("city"), city, "addr"))
        if district != row.get("district"):
            out.append(_change(row, "district", row.get("district"), district, "addr"))
    return out


def plan_cuisine_rows(rows: list[dict], mode: str = "missing") -> list[dict]:
    """算出 cuisine_major/minor 要填什麼。

    mode="missing"：只補空的（預設）。
    mode="rules"  ：規則改良後整批重推。兩種模式都**永不用空值覆蓋既有值**。
    """
    out: list[dict] = []
    for row in rows:
        if mode == "missing" and (row.get("cuisine_major") or ""):
            continue
        raw = row.get("cuisine_type") or ""
        major, minor = cuisine.classify(
            raw, name=row.get("name") or "", items=row.get("recommended_items") or "")
        source = "raw" if cuisine.classify(raw)[0] else "name"
        if major and major != row.get("cuisine_major"):
            out.append(_change(row, "cuisine_major", row.get("cuisine_major"), major, source))
        if minor and minor != row.get("cuisine_minor"):
            out.append(_change(row, "cuisine_minor", row.get("cuisine_minor"), minor, source))
    return out


# ── 報表（設計成給人讀，不是給人略過）──────────────────────────

def print_plan(changes: list[dict]) -> None:
    """依 (欄位, 舊→新) 分組：`桃園 → 桃園市 ×57` 只佔一行，異常值才會跳出來。"""
    if not changes:
        print("   （無變更）")
        return
    groups: dict[tuple, list[dict]] = {}
    for c in changes:
        groups.setdefault((c["field"], c["old"], c["new"], c["ok"]), []).append(c)
    for (field, old, new, ok) in sorted(groups, key=lambda k: (k[0], str(k[1]))):
        rows = groups[(field, old, new, ok)]
        mark = "  " if ok else "❌"
        line = f"{mark} {field:14s} {str(old):10s} → {str(new):10s} ×{len(rows)}"
        # 單筆或有問題的，把店名印出來讓人真的看得到是哪一家
        if len(rows) <= 3 or not ok:
            line += "   " + "、".join(f"#{r['id']} {r['name'][:16]}" for r in rows)
        print(line)


# ── 寫入器 ────────────────────────────────────────────────────

def _load_rows() -> list[dict]:
    from database import SessionLocal
    from models import FoodPlace
    db = SessionLocal()
    try:
        return [
            {
                "id": r.id, "place_id": r.place_id, "name": r.name, "address": r.address,
                "country": r.country, "city": r.city, "district": r.district,
                "cuisine_type": r.cuisine_type, "cuisine_major": r.cuisine_major,
                "cuisine_minor": r.cuisine_minor, "recommended_items": r.recommended_items,
            }
            for r in db.query(FoodPlace).order_by(FoodPlace.id).all()
        ]
    finally:
        db.close()


def _backup(rows: list[dict]) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    path = os.path.join(BACKUP_DIR, f"food_taxonomy_pre_{stamp}.json")
    snapshot = [{f: r.get(f) for f in _SNAPSHOT_FIELDS} for r in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
    return path


def _apply(changes: list[dict]) -> int:
    from database import session_scope
    from models import FoodPlace
    done = 0
    for c in changes:
        if not c["ok"]:
            continue
        try:
            with session_scope() as db:          # 逐列 commit：中途爆炸不影響已完成的
                rec = db.query(FoodPlace).filter(FoodPlace.id == c["id"]).first()
                if rec is None:
                    continue
                setattr(rec, c["field"], c["new"])
            done += 1
        except Exception:
            print(f"   ⚠️ #{c['id']} {c['field']} 寫入失敗")
            traceback.print_exc()
    return done


def run(kind: str = "all", *, dry_run: bool = True, mode: str = "missing",
        force: bool = False) -> None:
    """kind: region / cuisine / all。預設 dry-run，只印計畫不寫入。"""
    rows = _load_rows()
    print(f"讀到 {len(rows)} 筆店家\n")

    changes: list[dict] = []
    if kind in ("region", "all"):
        region = plan_region_rows(rows)
        print(f"【地區】{len([c for c in region if c['ok']])} 項變更")
        print_plan(region)
        changes += region
        print()
    if kind in ("cuisine", "all"):
        cui = plan_cuisine_rows(rows, mode=mode)
        print(f"【料理】{len(cui)} 項變更（mode={mode}）")
        print_plan(cui)
        changes += cui
        print()

    broken = [c for c in changes if not c["ok"]]
    if broken and not force:
        print(f"❌ 有 {len(broken)} 筆解不出來 → 拒絕寫入。"
              f"確認過那幾筆可以放著不動再加 force=True。")
        return
    if dry_run:
        print("（dry-run：什麼都沒寫。確認上面的 diff 沒問題再加 dry_run=False）")
        return

    path = _backup(rows)
    print(f"已備份原值 → {path}")
    done = _apply(changes)
    print(f"✅ 寫入 {done} 項。請再跑一次 dry-run 確認是 0 changed（冪等證明）。")


def verify_invariants() -> None:
    """全表掃描，印出任何越界值。回填後與首次重新匯入後都該跑一次。"""
    rows = _load_rows()
    bad = []
    for r in rows:
        if (r.get("country") or "") == "台灣":
            if r.get("city") not in TW_CITIES:
                bad.append((r["id"], r["name"], "city", r.get("city")))
            elif r.get("district") and r["district"] not in TW_DISTRICTS[r["city"]]:
                bad.append((r["id"], r["name"], "district", r.get("district")))
        if r.get("cuisine_major") and r["cuisine_major"] not in cuisine.MAJORS:
            bad.append((r["id"], r["name"], "cuisine_major", r.get("cuisine_major")))

    print(f"掃描 {len(rows)} 筆")
    if bad:
        print(f"❌ {len(bad)} 筆越界：")
        for item in bad:
            print("   ", item)
    else:
        print("✅ 全部符合不變式")

    filled = Counter(r.get("cuisine_major") or "（空）" for r in rows)
    print("\n大類分佈：")
    for k, v in filled.most_common():
        print(f"   {v:4d}  {k}")


def restore_from(path: str) -> None:
    """把備份的原值寫回去（回填出事時的一鍵還原，不用臨場手寫 SQL）。"""
    from database import session_scope
    from models import FoodPlace
    with open(path, encoding="utf-8") as f:
        snapshot = json.load(f)
    for row in snapshot:
        with session_scope() as db:
            rec = db.query(FoodPlace).filter(FoodPlace.id == row["id"]).first()
            if rec is None:
                continue
            for field in _SNAPSHOT_FIELDS:
                if field not in ("id", "place_id"):
                    setattr(rec, field, row[field])
    print(f"✅ 已從 {path} 還原 {len(snapshot)} 筆")
