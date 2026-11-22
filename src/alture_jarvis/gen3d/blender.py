"""블렌더 다리 — 찾기 · 따로 실행 · 결과 받기 (2026-11-15 · 설계 `설계_3D작업대_블렌더마무리` §4-③ · §4-⑤ · §7).

★ 라이선스 경계(대표 11-15 결정): 블렌더 안에서 도는 스크립트는 `blender_host/scripts/`(GPL-3.0-or-later) 에만 있다(11-18 공통 층으로 옮김). 이 파일은
  그 스크립트 경로와 JSON 을 블렌더에 넘겨 **따로 실행**하고 결과 파일만 읽는다(bpy 를 import 하지 않는다).
- 블렌더는 일마다 켜고 끈다(`-b --factory-startup` · 창 없음 · 사용자 설정 · 애드온과 섞이지 않음).
- 11-15 실측(PC · 5.2.3): 리락쿠마 GLB 읽기 + 다시 뜨기 최고 579MB · 0.8초.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..blender_host import SCRIPTS  # noqa: E402 — 블렌더 안 스크립트(GPL) 폴더는 공통 층 한 곳(2026-11-18)
from ..blender_host import find as _find  # noqa: E402
#: 쓸 수 있는 가장 낮은 판(LTS).
MIN_VERSION = (4, 5)
TIMEOUT_SEC = 600


def find_blender() -> dict[str, Any]:
    """{found, exe, version, why}. 공통 찾기(`blender_host.find`)에 4.5 이상으로 묻는다(2026-11-18 · 두 벌을 하나로).

    예전 이 자리의 찾기는 맥 `Blender 4.5.app` 같은 이름을 못 찾았고 경로 앞쪽 숫자를 판으로 오독할 수 있었다(설계 §13-1).
    """
    got = _find.find(MIN_VERSION)
    return {"found": got["found"], "exe": got["exe"], "version": got["version"], "why": got["why"]}


def _run_normal(cmd: list[str], timeout: float, **kw: Any) -> subprocess.CompletedProcess:
    """`subprocess.run` 과 같지만, 띄운 직후 블렌더를 「보통」 순위로 올린다(11-18 실측: 본체가 작업 스케줄러에서 BelowNormal 로 떠
    블렌더가 그 순위를 물려받아 768px 한 장이 2.6초 → 5.8초 · 영상 실행기에서 찾은 것과 같은 뿌리 · `pack_ram.lift_to_normal`)."""
    from ..pack_ram import lift_to_normal

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)
    lift_to_normal(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_script(script: str, job: dict[str, Any], *, exe: str | None = None, timeout: int = TIMEOUT_SEC) -> dict[str, Any]:
    """`blender_scripts/<script>` 를 따로 실행한다. job 에 result 경로를 붙여 넘기고, 블렌더가 쓴 결과 JSON 을 돌려준다."""
    if exe is None:
        found = find_blender()
        if not found["found"]:
            raise FileNotFoundError(found["why"])
        exe = found["exe"]
    with tempfile.TemporaryDirectory(prefix="sonjari_bl_") as tmp:
        job_file = Path(tmp) / "job.json"
        result = Path(tmp) / "result.json"
        job_file.write_text(json.dumps({**job, "result": str(result)}, ensure_ascii=False), encoding="utf-8")
        proc = _run_normal([str(exe), "-b", "--factory-startup", "--python", str(SCRIPTS / script), "--", str(job_file)], timeout)
        if result.is_file():
            out = json.loads(result.read_text(encoding="utf-8"))
        else:
            tail = (proc.stdout or b"")[-400:].decode("utf-8", "replace") + (proc.stderr or b"")[-400:].decode("utf-8", "replace")
            out = {"ok": False, "error": f"블렌더가 결과를 안 남겼다(rc {proc.returncode}): {tail.strip()[-300:]}"}
        out["rc"] = proc.returncode
        return out


def run_finish(src: Path, dst: Path, ops: list[dict[str, Any]], *, exe: str | None = None) -> dict[str, Any]:
    """`blender_scripts/finish.py` 를 따로 실행해 src GLB 를 ops 대로 고쳐 dst 에 쓴다. 결과 JSON 을 돌려준다."""
    return run_script("finish.py", {"input": str(src), "output": str(dst), "ops": ops}, exe=exe)
