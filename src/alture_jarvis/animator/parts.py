# -*- coding: utf-8 -*-
"""관절 부품(모델 파일) 받기 — 사람이 동의한 뒤에만, 공개된 자리에서, 지문을 확인하고 (2026-11-03).

손자리 스토어 판 · 공개 저장소에는 모델 파일을 넣지 않는다(11-03 결정):
- 세 모델 모두 Apache-2.0 표기로 배포되지만 학습 데이터 일부가 연구 · 비상업 조건이다(Human3.6M 계열 · AIC · PoseTrack 등).
  그런 모델의 결과를 상업 작업에 써도 되는지는 법적으로 정리되지 않았다 → 우리가 퍼뜨리지 않고, 쓰는 사람이 안내를 읽고 직접 받는다.
- RTMW3D 는 OpenMMLab 공식 자리가 아니라 허깅페이스 개인 계정(Soykaf/RTMW3D-x)이 올린 판이다 — 안내문에 그대로 적는다.

받은 파일은 sha256 지문이 맞아야 쓴다(11-03 이 PC 에서 받은 파일로 뜬 지문). 지문이 다르면 지우고 실패로 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    url: str
    onnx_name: str
    size: int
    sha256: str
    source: str


PARTS: tuple[Part, ...] = (
    Part("det", "사람 찾기(YOLOX-m · HumanArt)",
         "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip",
         "yolox_m_8xb8-300e_humanart-c2c7a14a.onnx", 101_400_344,
         "3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23", "OpenMMLab 공식(download.openmmlab.com) · Apache-2.0"),
    Part("pose2d", "2D 관절(RTMPose-m · body7)",
         "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip",
         "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx", 54_330_655,
         "5c0a4bf67953e6d2ac43ce15e77dc9d5d354ae18430a47d2c5963a7bc5683e3c", "OpenMMLab 공식(download.openmmlab.com) · Apache-2.0"),
    Part("pose3d", "3D 관절(RTMW3D-x)",
         "https://huggingface.co/Soykaf/RTMW3D-x/resolve/main/onnx/rtmw3d-x_8xb64_cocktail14-384x288-b0a0eab7_20240626.onnx",
         "rtmw3d-x_8xb64_cocktail14-384x288-b0a0eab7_20240626.onnx", 369_330_857,
         "4a289c0e99d47eb595e99679d9d4a2d1def1b4241f9adcbafba44b9ff585ebcd", "허깅페이스 Soykaf/RTMW3D-x(개인 계정이 올린 판) · Apache-2.0 표기"),
)

NOTICE = (
    "관절 부품은 손자리에 들어 있지 않습니다. 받기에 동의하면 아래 세 파일(약 525MB)을 이 PC 로 한 번 내려받습니다.\n"
    "- 사람 찾기 · 2D 관절: OpenMMLab 이 Apache-2.0 으로 배포(download.openmmlab.com)\n"
    "- 3D 관절(영상 → 바이페드에만 씀): 허깅페이스 Soykaf/RTMW3D-x, Apache-2.0 표기, 개인 계정이 올린 판\n"
    "- 세 모델 모두 학습 데이터 일부가 연구 · 비상업 조건입니다(예: Human3.6M 계열, AI Challenger, PoseTrack). "
    "이렇게 학습된 모델의 결과를 상업 작업에 써도 되는지는 법적으로 정리되지 않았습니다. 상업 작업에 쓸지는 회사 기준으로 판단해 주세요.\n"
    "- 영상에서 뽑은 동작은 모션 창고에 「영상 변환 초안」으로 표시됩니다. 영상 · 사진은 이 PC 밖으로 나가지 않습니다."
)

_LOCK = threading.Lock()
_JOB: dict[str, Any] = {}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def part_path(root: Path, part: Part) -> Path:
    return root / "parts" / part.onnx_name


def _record(root: Path) -> Path:
    return root / "parts" / "parts.json"


def status(root: Path) -> dict[str, Any]:
    rec = {}
    try:
        rec = json.loads(_record(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    have = {p.key: part_path(root, p).is_file() for p in PARTS}
    with _LOCK:
        job = dict(_JOB) if _JOB.get("root") == str(root) else {}
    return {
        "ready": all(have.values()),
        "have": have,
        "agreed_at": rec.get("agreed_at"),
        "downloading": job.get("state") == "running",
        "progress": job.get("progress"),
        "error": job.get("error"),
    }


def require(root: Path, keys: tuple[str, ...]) -> dict[str, Path]:
    """쓰기 전에 부르는 문. 없으면 안내문과 함께 거절한다."""
    missing = [p for p in PARTS if p.key in keys and not part_path(root, p).is_file()]
    if missing:
        raise FileNotFoundError(
            "parts_missing: 관절 부품이 아직 없다(" + ", ".join(p.label for p in missing) + "). "
            "anim_parts 를 action=\"status\" 로 불러 안내문을 받고, 그 안내문을 사람에게 그대로 보인 뒤 "
            "사람이 동의하면 action=\"install\", agree=true 로 받아라."
        )
    return {p.key: part_path(root, p) for p in PARTS if p.key in keys}


def _local_copy(part: Part) -> Path | None:
    """이 PC 에 rtmlib 이 이미 받아 둔 같은 파일(지문으로 확인한 뒤에만 쓴다)."""
    cand = Path(os.path.expanduser("~")) / ".cache" / "rtmlib" / "hub" / "checkpoints" / part.onnx_name
    return cand if cand.is_file() and cand.stat().st_size == part.size else None


def _fetch(part: Part, dest: Path, report) -> None:
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(part.url, headers={"User-Agent": "Sonjari-animator/1"})
    with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            report(done, total)
    if part.url.endswith(".zip"):
        with zipfile.ZipFile(tmp) as z:
            names = [n for n in z.namelist() if n.endswith("end2end.onnx")]
            if not names:
                raise RuntimeError(f"{part.label}: 묶음 안에 end2end.onnx 가 없다")
            with z.open(names[0]) as src, dest.with_suffix(".onnx.tmp").open("wb") as out:
                shutil.copyfileobj(src, out)
        tmp.unlink()
        dest.with_suffix(".onnx.tmp").replace(dest)
    else:
        tmp.replace(dest)


def _install(root: Path) -> None:
    folder = root / "parts"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for i, part in enumerate(PARTS, 1):
            dest = part_path(root, part)
            if dest.is_file() and dest.stat().st_size == part.size:
                continue

            def report(done: int, total: int, i=i, part=part) -> None:
                with _LOCK:
                    _JOB["progress"] = f"{i}/{len(PARTS)} {part.label} {done // (1 << 20)}MB/{(total or part.size) // (1 << 20)}MB"

            local = _local_copy(part)
            if local is not None and _sha(local) == part.sha256:
                shutil.copyfile(local, dest)
            else:
                _fetch(part, dest, report)
            if _sha(dest) != part.sha256:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"{part.label}: 받은 파일의 지문이 맞지 않아 지웠다(배포 자리의 파일이 바뀌었을 수 있다)")
        with _LOCK:
            _JOB.update(state="done", progress=f"{len(PARTS)}/{len(PARTS)} 끝")
    except Exception as exc:  # noqa: BLE001 — 실패는 상태로 남겨 사람에게 전한다
        with _LOCK:
            _JOB.update(state="failed", error=f"{type(exc).__name__}: {exc}")


def install(root: Path, agree: bool) -> dict[str, Any]:
    if not agree:
        return {"ok": False, "notice": NOTICE,
                "next": "이 안내문을 사람에게 그대로 보이고, 사람이 「받아」라고 하면 agree=true 로 다시 불러라. 동의 없이 받지 않는다."}
    (root / "parts").mkdir(parents=True, exist_ok=True)
    rec = {"agreed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "notice": NOTICE,
           "parts": [{"key": p.key, "url": p.url, "sha256": p.sha256, "source": p.source} for p in PARTS]}
    _record(root).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    with _LOCK:
        if _JOB.get("state") == "running":
            return {"ok": True, "already_running": True, "progress": _JOB.get("progress")}
        _JOB.clear()
        _JOB.update(root=str(root), state="running", progress="시작")
    threading.Thread(target=_install, args=(root,), name="sonjari-animator-parts", daemon=True).start()
    return {"ok": True, "started": True,
            "next": "뒤에서 받는 중이다. 1~2분 뒤 action=\"status\" 로 진행을 보고 ready=true 가 되면 쓴다."}


def wait(root: Path, timeout: float = 600.0) -> dict[str, Any]:
    """시험 · 스크립트용: 받기가 끝날 때까지 기다린다."""
    end = time.time() + timeout
    while time.time() < end:
        with _LOCK:
            state = _JOB.get("state")
        if state != "running":
            break
        time.sleep(0.2)
    return status(root)
