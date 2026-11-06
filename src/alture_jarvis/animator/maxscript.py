# -*- coding: utf-8 -*-
"""엇박자 루프의 맥스 스크립트 두 장 (2026-11-02 · 애니메이터 팩).

나눔(설계 §3-2): **계산은 파이썬 한 곳**(offset.py, 시험 통과)에만 둔다. 맥스 스크립트는 「키 읽어 파일로」와
「계산된 키를 그대로 쓰기」만 한다 — 그래서 맥스 쪽과 계산이 어긋날 수가 없다.

- 읽기(read): 고른 뼈 줄의 위치 · 회전 X/Y/Z 키(시각 · 값 · 탄젠트)와 루프 구간의 프레임마다 곡선 값을 파일로 쓴다.
  아무것도 바꾸지 않는다. 바이페드 몸은 건너뛰고 까닭을 적는다(흔한 리그: 몸은 바이페드, 꼬리 · 옷 · 장식은 포인트 · 본).
- 쓰기(apply): 한 번의 되돌리기 묶음(Ctrl+Z 한 번) 안에서, 구간 [S, E] 의 키를 지우고 계산된 키를 놓는다.
  읽은 뒤 사람이 키를 고쳤으면(구간 안 키 수가 다르면) 그 트랙은 쓰지 않고 알린다. 쓴 뒤 이음매(S 와 E 값)를 다시 확인한다.

맥스와 주고받는 것은 파일이다 — 키를 클로드 대화에 통째로 싣지 않는다(한도가 닳는다).
클로드는 3dsmax-mcp 의 execute_maxscript 로 한 줄(`run_line`)만 보낸다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

#: 트랙 이름 — r/p(회전 · 위치) + 축
TRACKS = ("rx", "ry", "rz", "px", "py", "pz")
UNDO_LABEL = "Sonjari offset loop"

# 위치 · 회전 컨트롤러에서 X/Y/Z 낱개 곡선을 찾는다. 「변형 고정(Freeze Transform)」을 하면 목록 컨트롤러가 되므로
# 그 안의 켜진 칸(active)을 따라간다. XYZ 로 나뉘지 않은 것(TCB · 쿼터니언 · 경로 등)은 다루지 않는다(undefined).
_COMMON = r'''
fn sjXYZ c = (
  local found = undefined
  if c != undefined do (
    if classOf c == Position_List or classOf c == Rotation_List do (
      local a = 0
      try (a = c.active) catch (a = 0)
      c = if a > 0 then c[a].controller else undefined
    )
    if c != undefined and (classOf c == Position_XYZ or classOf c == Euler_XYZ) do found = c
  )
  found
)
fn sjTrack n id = (
  local base = undefined
  try (base = if id[1] == "r" then sjXYZ n.rotation.controller else sjXYZ n.position.controller) catch (base = undefined)
  local fc = undefined
  if base != undefined do (
    local k = case id[2] of ("x": 1; "y": 2; "z": 3; default: 0)
    if k > 0 do try (fc = base[k].controller) catch (fc = undefined)
  )
  fc
)
fn sjIsBiped n = (
  local yes = false
  try (
    local cl = classOf n.controller
    yes = (cl == BipSlave_Control) or (cl == Vertical_Horizontal_Turn) or (cl == Footsteps) or (classOf n == Biped_Object)
  ) catch (yes = false)
  yes
)
fn sjNum v = (formattedPrint (v as float) format:".6f")
fn sjEsc s = (
  local r = substituteString (s as string) "\\" "\\\\"
  substituteString r "\"" "\\\""
)
'''

_READ = r'''-- 손자리 애니메이터 팩: 엇박자 루프용 키 읽기 (읽기만 한다 — 장면을 바꾸지 않는다)
(
__COMMON__
local outPath = @"__OUT__"
local S = __START__
local E = __END__
local wantNames = #(__NODES__)
local axes = #(__AXES__)
local chain = #()
local skipped = #()
if wantNames.count == 0 then (
  -- 이름을 안 줬으면 지금 고른 것을 뿌리 → 끝(계층 깊이) 순서로
  local picked = selection as array
  local depthOf = for n in picked collect (local d = 0; local p = n.parent; while p != undefined do (d += 1; p = p.parent); d)
  for d = 0 to 200 do for i = 1 to picked.count where depthOf[i] == d do append chain picked[i]
) else (
  for nm in wantNames do (
    local n = getNodeByName nm exact:true
    if n == undefined then append skipped #(nm, "not_found") else append chain n
  )
)
local ss = stringStream ""
format "{\"version\":1,\"start\":%,\"end\":%,\"fps\":%,\"nodes\":[" S E frameRate to:ss
local first = true
local readN = 0
for n in chain do (
  if sjIsBiped n then (append skipped #(n.name, "biped"); continue)
  if not first do format "," to:ss
  first = false
  readN += 1
  format "{\"name\":\"%\",\"handle\":%,\"tracks\":{" (sjEsc n.name) n.inode.handle to:ss
  local firstT = true
  for id in axes do (
    local fc = sjTrack n id
    if not firstT do format "," to:ss
    firstT = false
    if fc == undefined then (format "\"%\":null" id to:ss; continue)
    -- 키 값과 곡선 값의 단위가 다를 수 있어(회전) 키 하나로 비율을 잰다
    local unitK = 1.0
    for k in fc.keys while unitK == 1.0 do (
      if abs k.value > 0.0001 do (
        local cv = at time k.time fc.value
        if abs cv > 0.000000001 do unitK = k.value / cv
      )
    )
    format "\"%\":{\"class\":\"%\",\"scale\":%,\"keys\":[" id (classOf fc) (sjNum unitK) to:ss
    for j = 1 to fc.keys.count do (
      local k = fc.keys[j]
      local it = ""; local ot = ""; local iv = 0.0; local ov = 0.0; local il = 0.0; local ol = 0.0
      try (it = k.inTangentType as string; ot = k.outTangentType as string) catch ()
      try (iv = k.inTangent; ov = k.outTangent; il = k.inTangentLength; ol = k.outTangentLength) catch ()
      if j > 1 do format "," to:ss
      format "[%,%,\"%\",\"%\",%,%,%,%]" (sjNum k.time.frame) (sjNum k.value) it ot (sjNum iv) (sjNum ov) (sjNum il) (sjNum ol) to:ss
    )
    format "],\"samples\":[" to:ss
    for fr = S to E do (
      if fr > S do format "," to:ss
      format "%" (sjNum ((at time (fr * 1f) fc.value) * unitK)) to:ss
    )
    format "]}" to:ss
  )
  format "}}" to:ss
)
format "],\"skipped\":[" to:ss
for i = 1 to skipped.count do (
  if i > 1 do format "," to:ss
  format "[\"%\",\"%\"]" (sjEsc skipped[i][1]) skipped[i][2] to:ss
)
format "]}" to:ss
-- 손자리 애니메이터 폴더(outPath)에만 쓴다. BOM 없는 UTF-8.
makeDir (getFilenamePath outPath) all:true
(dotNetClass "System.IO.File").WriteAllText outPath (ss as string) (dotNetObject "System.Text.UTF8Encoding" false)
"sonjari: read " + (readN as string) + " nodes, skipped " + (skipped.count as string) + " -> " + outPath
)
'''

_APPLY = r'''-- 손자리 애니메이터 팩: 엇박자 루프 쓰기 (Ctrl+Z 한 번으로 통째로 되돌린다)
(
__COMMON__
local S = __START__
local E = __END__
-- #(손잡이, 트랙, 읽을 때 구간 안 키 수, #(#(시각, 값, 들어오는 탄젠트, 나가는 탄젠트, 안 기울기, 밖 기울기, 안 길이, 밖 길이), ...))
local plan = #(
__PLAN__
)
local done = 0
local notes = #()
undo "__UNDO__" on (
  for item in plan do (
    local n = maxOps.getNodeByHandle item[1]
    if n == undefined do (append notes ("no node " + (item[1] as string)); continue)
    local fc = sjTrack n item[2]
    if fc == undefined do (append notes (n.name + " " + item[2] + ": no XYZ track"); continue)
    local before = 0
    for k in fc.keys where k.time.frame >= S - 0.0001 and k.time.frame <= E + 0.0001 do before += 1
    if before != item[3] do (append notes (n.name + " " + item[2] + ": keys changed since read, skipped"); continue)
    for j = fc.keys.count to 1 by -1 do (
      local t = fc.keys[j].time.frame
      if t >= S - 0.0001 and t <= E + 0.0001 do deleteKey fc j
    )
    for kk in item[4] do (
      local k = addNewKey fc (kk[1] * 1f)
      k.value = kk[2]
      if kk[3] != "" do try (
        k.inTangentType = kk[3] as name
        k.outTangentType = kk[4] as name
        if kk[3] == "custom" do (k.inTangent = kk[5]; k.inTangentLength = kk[7])
        if kk[4] == "custom" do (k.outTangent = kk[6]; k.outTangentLength = kk[8])
      ) catch ()
    )
    try (sortKeys fc) catch ()
    -- 다시 확인: 구간 안 키 수 · 이음매(S 와 E 값이 같은가)
    local after = 0; local vs = undefined; local ve = undefined
    for k in fc.keys where k.time.frame >= S - 0.0001 and k.time.frame <= E + 0.0001 do (
      after += 1
      if abs (k.time.frame - S) < 0.0001 do vs = k.value
      if abs (k.time.frame - E) < 0.0001 do ve = k.value
    )
    if after != item[4].count do append notes (n.name + " " + item[2] + ": wrote " + (after as string) + " of " + (item[4].count as string))
    if vs == undefined or ve == undefined or abs (vs - ve) > 0.0001 do append notes (n.name + " " + item[2] + ": seam not closed")
    done += 1
  )
)
local msg = "sonjari: wrote " + (done as string) + " tracks"
if notes.count == 0 then msg += ", check OK" else (
  msg += ", notes " + (notes.count as string) + ":"
  for x in notes do msg += " | " + x
)
msg
)
'''


def _ms_string(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value: float) -> str:
    return f"{float(value):.6f}"


def read_script(out_path: Path, start: int, end: int, nodes: Sequence[str] = (), tracks: Sequence[str] = TRACKS) -> str:
    """맥스에서 키를 읽어 out_path 에 JSON 으로 쓰는 스크립트."""
    bad = [t for t in tracks if t not in TRACKS]
    if bad:
        raise ValueError(f"모르는 트랙: {bad} — {list(TRACKS)} 중에서")
    return (_READ.replace("__COMMON__", _COMMON.strip())
            .replace("__OUT__", str(out_path).replace('"', ""))
            .replace("__START__", str(int(start))).replace("__END__", str(int(end)))
            .replace("__NODES__", ", ".join(_ms_string(n) for n in nodes))
            .replace("__AXES__", ", ".join(_ms_string(t) for t in tracks)))


def apply_script(start: int, end: int, items: Sequence[dict[str, Any]]) -> str:
    """계산된 키를 그대로 쓰는 스크립트. items: {handle, track, before, keys:[{t,v,in,out,iv,ov,il,ol}]}"""
    rows = []
    for item in items:
        keys = ", ".join(
            "#(" + ", ".join([_num(k["t"]), _num(k["v"]), _ms_string(k.get("in", "")), _ms_string(k.get("out", "")),
                              _num(k.get("iv", 0.0)), _num(k.get("ov", 0.0)), _num(k.get("il", 0.0)), _num(k.get("ol", 0.0))]) + ")"
            for k in item["keys"])
        rows.append(f"  #({int(item['handle'])}, {_ms_string(item['track'])}, {int(item['before'])}, #({keys}))")
    return (_APPLY.replace("__COMMON__", _COMMON.strip())
            .replace("__START__", str(int(start))).replace("__END__", str(int(end)))
            .replace("__UNDO__", UNDO_LABEL)
            .replace("__PLAN__", ",\n".join(rows)))


def run_line(script_path: Path) -> str:
    """클로드가 execute_maxscript 로 보낼 한 줄 — 파일을 읽어 실행하고 마지막 값(요약 한 줄)을 돌려받는다."""
    return f'execute ((dotNetClass "System.IO.File").ReadAllText @"{script_path}")'


def write_script(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")       # 맥스가 한글 이름을 깨지 않게 BOM
    return path


def load_dump(path: Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"읽은 파일을 해석하지 못했다: {path}")
