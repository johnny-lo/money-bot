"""build 時驗證已安裝的 OkLine 帶的 LTSM 檔案跟審過的版本逐位元相同；不符就 exit 1 讓 build 失敗。

ltsm.wasm／ltsmSandbox.js 是 OkLine 裡唯一不是 Python 原始碼的大檔，換 OKLINE_COMMIT 時要重審、重算這兩個值。
"""
import hashlib
import importlib.util
import sys
from pathlib import Path

EXPECTED = {
    "ltsm.wasm": "58bb4e189ab9bbd7d72ed415258da36afd50e306cb019bab75329d4f5f1b65b3",
    "ltsmSandbox.js": "5c66cba945cc039d817e87fef2aa1e28c8adb7be0f94fca5b95bb6bcf5a07c94",
}


def main() -> int:
    # find_spec 不執行 okline 的 __init__，只找安裝位置
    spec = importlib.util.find_spec("okline")
    if spec is None or not spec.submodule_search_locations:
        print("okline 沒有安裝", file=sys.stderr)
        return 1
    ltsm = Path(list(spec.submodule_search_locations)[0]) / "ltsm"
    ok = True
    for name, want in EXPECTED.items():
        path = ltsm / name
        try:
            got = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as e:
            print(f"{path}: 讀不到（{type(e).__name__}）", file=sys.stderr)
            ok = False
            continue
        if got != want:
            print(f"{path}: sha256 {got} ≠ {want}", file=sys.stderr)
            ok = False
        else:
            print(f"{path}: sha256 OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
