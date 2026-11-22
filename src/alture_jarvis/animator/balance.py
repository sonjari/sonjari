# -*- coding: utf-8 -*-
"""입힌 뒤 균형 점검 · 키 정렬 보정 — anim_balance_check · anim_key_align (2026-11-19 · 애니메이터 팩 · 시험 중).

MAXScript 본문(`lab_ms/`)은 현업 협업자가 lab 에서 3ds Max 2026 으로 만들고 시험한 것
(sonjari-animator `lab/결과물/균형점검_보정_1119` · balance_check v6 · key_align v1)을 그대로 옮겼다. 바꾼 것은 셋뿐:
 1) 맨 위 변수(바이페드 이름 · 기준 숫자 · 구간)를 인자로 바꿔 끼운다.
 2) 키 정렬 적용 직전에 holdMaxFile 에 더해 **복사본 저장**(saveMaxFile … useNewFile:false)하고 경로를 보고한다(lab 설계 §6-1).
 3) 적용 뒤 키가 거의 매 프레임에 생기면 경고한다(lab 설계 §6-4 「1프레임 단위 키」).
판단(이 프레임이 진짜 문제인가 · 적용할까)은 사람이 한다 — 이 숫자는 「어디를 볼지 짚어 주는 표」다.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent / "lab_ms"

#: 기준 숫자(lab 11-19 임시값) — 이름: (기본값, 설명)
THRESHOLDS: dict[str, tuple[float, str]] = {
    "groundTol": (6.0, "발끝이 지면(구간 최저)보다 이만큼 이내면 딛음"),
    "fwdTol": (25.0, "① COM 앞뒤 어긋남 기준"),
    "holdSpeed": (2.0, "홀딩: COM 이 프레임당 이보다 적게 움직임"),
    "slideRatio": (0.1, "② 밀림 기준 = 다리 길이 × 이 값"),
    "slideMinFrames": (3, "② 홀딩이 이만큼 이어질 때만"),
    "floatLo": (1.5, "③ 애매하게 뜬 발: 발끝 높이 하한"),
    "floatMinFrames": (5, "③ 이만큼 이어지고"),
    "floatAvg": (3.0, "③ 평균이 이를 넘을 때"),
    "latTol": (15.0, "④ 좌우 범위 밖 기준"),
    "accTol": (30.0, "⑤ COM 위치 가속(참고 표시) 기준"),
}

_RANGE = "local fS = animationRange.start.frame as integer; local fE = animationRange.end.frame as integer"


def _read(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def _set_local(text: str, name: str, value: str) -> str:
    """`local <name> = <값>   -- 주석` 줄의 값만 바꾼다(정확히 한 줄이어야 한다)."""
    pat = re.compile(r"^(\s*local " + re.escape(name) + r" = )(\S+)", re.M)
    new, k = pat.subn(lambda m: m.group(1) + value, text, count=1)
    if k != 1:
        raise ValueError(f"스크립트에서 local {name} 을 못 찾았다")
    return new


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "").replace('"', "") + '"'


def check_script(biped: str = "Bip001", start: int | None = None, end: int | None = None,
                 thresholds: dict[str, float] | None = None) -> str:
    t = _set_local(_read("balance_check_v6.ms"), "bipName", _q(biped or "Bip001"))
    for k, v in (thresholds or {}).items():
        if k not in THRESHOLDS:
            raise ValueError(f"모르는 기준 이름: {k} (있는 것: {', '.join(THRESHOLDS)})")
        t = _set_local(t, k, str(int(v)) if k.endswith("Frames") else f"{float(v):g}")
    if start is not None and end is not None:
        if _RANGE not in t:
            raise ValueError("구간 줄을 못 찾았다")
        if int(end) <= int(start):
            raise ValueError("end 는 start 보다 커야 한다")
        t = t.replace(_RANGE, f"local fS = {int(start)}; local fE = {int(end)}", 1)
    return t


def align_script(biped: str = "Bip001", apply: bool = False, backup: Path | None = None) -> str:
    t = _set_local(_read("key_align_v1.ms"), "bipName", _q(biped or "Bip001"))
    t = _set_local(t, "doApply", "true" if apply else "false")
    if not apply:
        return t
    if backup is None:
        raise ValueError("적용에는 복사본 저장 경로가 필요하다")
    hold = "    holdMaxFile()\n"
    if t.count(hold) != 1:
        raise ValueError("holdMaxFile 줄을 못 찾았다")
    bk = str(backup).replace("\\", "/").replace('"', "")
    t = t.replace(hold, f'    local bkPath = "{bk}"\n'
                        "    local bkOk = try (saveMaxFile bkPath useNewFile:false quiet:true) catch (false)\n" + hold, 1)
    said = '    rep += "적용했다 (적용 직전 장면 보관됨'
    if t.count(said) != 1:
        raise ValueError("적용 보고 줄을 못 찾았다")
    guard = (
        '    rep += (if bkOk == false then "★ 복사본 저장 실패 — 되돌리기는 편집 › 가져오기(Fetch)로만\\n" else "복사본: " + bkPath + "\\n")\n'
        "    local nFr = fE - fS + 1\n"
        "    for tg in targets do (local nk = (sjKeyTimes tg[1].controller).count; "
        'if nk >= (0.8 * nFr) and nk > (2 * comKeys.count) then rep += "★ 경고: " + tg[2] + " 키가 거의 매 프레임(" + '
        '(nk as string) + "/" + (nFr as string) + ") — 멈추고 편집 › 가져오기(Fetch)를 권함\\n")\n'
    )
    return t.replace(said, guard + said, 1)
