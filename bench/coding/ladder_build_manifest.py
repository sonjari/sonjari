"""ladder.py 의 과제·씨앗을 드라이버가 읽는 매니페스트(JSON)로 만든다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ladder  # noqa: E402

manifest = {"tasks": [
    {"id": task_id, "prompt": spec["prompt"], "seed": spec["seed"]}
    for task_id, spec in ladder.TASKS.items()
]}
out = Path(sys.argv[1] if len(sys.argv) > 1 else "ladder_manifest.json")
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print(out, out.stat().st_size, "bytes", len(manifest["tasks"]), "tasks")
