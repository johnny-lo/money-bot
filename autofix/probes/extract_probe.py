"""bin/probe extract <url>：只呼叫 extract 層（不碰 ingest/repo、不寫 DB）。"""
import sys
import traceback

sys.path.append("/app")
from food.links import classify_platform   # noqa: E402
from food import extract                   # noqa: E402

url = sys.argv[1]
platform = classify_platform(url)
print(f"平台：{platform}")
try:
    blob = extract.from_url(url, platform)
    print(f"✅ blob {len(blob or '')} 字：\n{(blob or '')[:2000]}")
except Exception:
    print("❌ 抽取失敗：")
    traceback.print_exc()
    sys.exit(1)
