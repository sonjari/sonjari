# -*- coding: utf-8 -*-
"""애니메이터 팩 — 블렌더 쪽 다리 (2026-11-06).

★ 까닭. 맥스는 손자리가 직접 부를 수 없어(3dsmax-mcp 가 한 줄을 보낸다) 사람 · 클로드가 사이에 껴야 했다. 블렌더는 무료이고 명령줄로
  창 없이 돈다 — **손자리가 직접 띄워 끝까지 한다.** 클로드는 말 · 표 · 「해」만(완성 기준 2층 「클로드가 짠 코드 0줄」).
  그리고 이 PC 맥스는 교육용이라 영리 목적(제품 개발 · 홍보 화면)이 약관 밖이다(11-06 확인) → 공개 시연 · 개발은 블렌더로.

나눔은 맥스 판과 같다: 블렌더 스크립트는 **읽기(뼈 행렬 · 몸 메시 점 → 파일)** 와 **쓰기(계산된 방향을 키로)** 만 한다.
판정 · 계산은 `fitcheck.py` 한 곳(맥스와 같이 쓴다) — 그래서 두 프로그램 결과가 어긋날 수 없다.

- 원본 .blend 는 덮어쓰지 않는다. 쓰기는 늘 새 파일(`<이름>_sonjari_<무엇>.blend`).
- 뼈 이름은 흔한 꼴 셋(리지파이 게임 뼈대 · 리지파이 DEF- · 믹사모)을 자동으로 맞춘다. 못 맞추면 무엇이 없는지 말한다.
- 바이페드와 축이 다르다: 블렌더 뼈의 길이 방향은 Y. 읽을 때 (Y, X, Z, 머리 자리) 순으로 줄을 놓아 fitcheck 의 「row1 = 길이 방향」을 맞춘다.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..blender_host import find as _find
from ..blender_host import script_text

#: fitcheck 의 이름(바이페드 꼬리) → 블렌더 뼈 후보(앞이 이긴다). {s} 는 L/R, {S} 는 Left/Right.
BONE_MAP: dict[str, list[str]] = {
    "Pelvis": ["spine", "DEF-spine", "mixamorig:Hips", "Hips", "hips", "pelvis"],
    "Spine": ["spine.001", "DEF-spine.001", "mixamorig:Spine", "Spine", "spine_01"],
    "Spine1": ["spine.002", "DEF-spine.002", "mixamorig:Spine1", "Spine1", "spine_02"],
    "Spine2": ["spine.003", "DEF-spine.003", "mixamorig:Spine2", "Spine2", "spine_03", "chest"],
    "Neck": ["spine.004", "DEF-spine.004", "mixamorig:Neck", "Neck", "neck", "neck_01"],
    "Head": ["spine.006", "DEF-spine.006", "mixamorig:Head", "Head", "head"],
    "{s} UpperArm": ["upper_arm.{s}", "DEF-upper_arm.{s}", "mixamorig:{S}Arm", "{S}Arm", "upperarm_{l}"],
    "{s} Forearm": ["forearm.{s}", "DEF-forearm.{s}", "mixamorig:{S}ForeArm", "{S}ForeArm", "lowerarm_{l}"],
    "{s} Hand": ["hand.{s}", "DEF-hand.{s}", "mixamorig:{S}Hand", "{S}Hand", "hand_{l}"],
    "{s} Thigh": ["thigh.{s}", "DEF-thigh.{s}", "mixamorig:{S}UpLeg", "{S}UpLeg", "thigh_{l}"],
    "{s} Calf": ["shin.{s}", "DEF-shin.{s}", "mixamorig:{S}Leg", "{S}Leg", "calf_{l}"],
    "{s} Foot": ["foot.{s}", "DEF-foot.{s}", "mixamorig:{S}Foot", "{S}Foot", "foot_{l}"],
}
REQUIRED = ["Pelvis", "Spine", "Head", "L UpperArm", "L Forearm", "L Hand", "R UpperArm", "R Forearm", "R Hand"]


def bone_candidates() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, cands in BONE_MAP.items():
        if "{s}" in key:
            for s, S, l in (("L", "Left", "l"), ("R", "Right", "r")):
                out[key.format(s=s)] = [c.format(s=s, S=S, l=l) for c in cands]
        else:
            out[key] = cands
    return out


def _blender_patterns(platform: str, home: Path) -> list[str]:
    """흔한 설치 자리 — 공통 찾기(`blender_host.find.patterns`)와 같다(2026-11-18 · 두 벌을 하나로)."""
    return _find.patterns(platform, home)


def _blender_version(path: str) -> tuple[int, ...]:
    """판 번호 — 공통 찾기(`blender_host.find.version_of`). 블렌더 폴더 이름 → 맥 Info.plist · 모르면 (0,)."""
    return _find.version_of(path)


def find_blender(*, platform: str | None = None, home: Path | None = None) -> str | None:
    """블렌더 실행 파일 — 설정(JARVIS_BLENDER)이 먼저, 그다음 흔한 설치 자리(새 판이 이긴다). `platform` · `home` 은 시험용.

    애니메이터는 낮은 판을 거르지 않는다(예전 그대로 · 공통 찾기에 `min_version` 없이).
    """
    got = _find.find(None, platform=platform, home=home)
    return got["exe"] if got["found"] else None


# ── 블렌더 안에서 도는 스크립트(읽기 · 쓰기) ────────────────────────────────────────
# ★ 2026-11-18: 글은 `blender_host/scripts/`(GPL-3.0-or-later) 의 파일에 있다 — 블렌더 API(bpy)를 쓰는 스크립트는 배포하면
#   GPL 호환이어야 해서(blender.org) 그 폴더에만 둔다. 이 파일은 글을 읽어 따로 실행만 한다. 옮기기 전 글과 바이트가 같다
#   (읽기 50fa91e282d5 · 고치기 d7693c294c31 · 블로킹 61dd1d364dda — 시험이 맞춰 본다).
_COMMON = script_text("anim_common.py")
READ_PY = _COMMON + script_text("anim_read.py")
WRITE_FIX_PY = _COMMON + script_text("anim_fix.py")
BLOCK_PY = _COMMON + script_text("anim_block.py")


def run(blend: Path, script: str, args: dict[str, Any], work: Path, *, timeout: float = 280.0) -> dict[str, Any]:
    """창 없는 블렌더로 스크립트 하나. 인자는 JSON 파일로(한글 경로가 명령줄에서 깨지지 않게)."""
    exe = find_blender()
    if not exe:
        raise FileNotFoundError("블렌더를 못 찾았다 — 없으면 anim_blender_setup(action=status)으로 사람 동의를 받아 받는다 · 설치돼 있으면 설정의 JARVIS_BLENDER 에 블렌더 실행 파일 경로(윈도우 blender.exe · 맥 Blender.app/Contents/MacOS/Blender)를 넣어 달라고 사람에게 말해라")
    work.mkdir(parents=True, exist_ok=True)
    sp, ap = work / "_script.py", work / "_args.json"
    sp.write_text(script, encoding="utf-8")
    ap.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    from ..gen3d.blender import _run_normal
    from ..pack_ram import heavy_slot

    try:
        # 한 줄 잠금(11-18 §14-2): 맥에서 3D · 영상 굽기가 돌면 기다리지 않고 busy(HeavyBusy) — 사람이 기다리는 일이다.
        with heavy_slot("애니 블렌더", wait=False):
            # 본체의 낮은 순위를 물려받지 않게 「보통」으로(11-18 · `gen3d.blender._run_normal`)
            proc = _run_normal([exe, "-b", str(blend), "--factory-startup", "--python-exit-code", "1", "-P", str(sp), "--", str(ap)],
                               timeout, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"블렌더가 {int(timeout)}초 안에 못 끝냈다 — 구간(start · end)을 줄여라") from exc
    out = proc.stdout or ""
    for line in out.splitlines():
        if "@@ERR@@" in line:
            raise ValueError(line.split("@@ERR@@", 1)[1].strip())
    got = [line.split("@@JSON@@", 1)[1] for line in out.splitlines() if "@@JSON@@" in line]
    if not got:
        raise RuntimeError(f"blender_failed: {(proc.stderr or out)[-500:]}")
    res = json.loads(got[-1])
    if not res.get("ok", True):
        raise ValueError(res.get("error") or "블렌더 쪽 실패")
    return res
