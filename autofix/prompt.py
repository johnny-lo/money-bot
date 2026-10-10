"""組 Claude 的 prompt（主機 python3 執行 → 只准標準函式庫）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build_prompt(incident: dict, af_dir: str) -> str:
    rules = (HERE / "rules" / f"{incident['sensor']}.md").read_text(encoding="utf-8")
    tpl = (HERE / "prompt.md").read_text(encoding="utf-8")
    return (tpl.replace("{{AF}}", af_dir)
               .replace("{{RULES}}", rules.strip())
               .replace("{{INCIDENT_JSON}}", json.dumps(incident, ensure_ascii=False, indent=2)))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(build_prompt(json.load(f), sys.argv[2]))
