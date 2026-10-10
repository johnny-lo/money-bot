"""bin/probe einvoice：在一次性容器裡用 worktree 的 einvoice 抓一個載具（不寫 DB）。"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from autofix.probes import guard   # 主目錄唯讀副本（PYTHONPATH=/probes-root）

ap = argparse.ArgumentParser()
ap.add_argument("--carrier", type=int, required=True)
ap.add_argument("--days", type=int, default=3)
a = ap.parse_args()
phone = os.environ.get(f"EINVOICE_PHONE_{a.carrier}", "")
password = os.environ.get(f"EINVOICE_PASSWORD_{a.carrier}", "")
phones = [phone] if phone else []
# 每次 probe 只放行 1 次登入送出；跨呼叫的上限（3 次）由主機端 bin/probe 計數，容器看不到也改不到
guard.install(Path("/tmp/login_budget"), phones, Path("/app/.autofix-probe"), limit=1)

sys.path.append("/app")            # guard 裝好之後才 import 被測程式
import einvoice                    # noqa: E402


async def main() -> int:
    try:
        invs = await einvoice._scrape_carrier(phone, password, a.days)
    except Exception as e:
        print(f"❌ {type(e).__name__}: {guard.mask(str(e), phones)}（頁面已存到 .autofix-probe/）")
        return 1
    print(f"✅ 抓到 {len(invs)} 張")
    for i in invs[:5]:
        print(f"   {i.get('date')} {i.get('seller')} {len(i.get('items', []))} 品項")
    return 0

sys.exit(asyncio.run(main()))
