# -*- coding: utf-8 -*-
"""모션 창고 — 애니메이터 요청 「여러 개를 저장해 두고 필요한 모션을 말로 꺼내 적용」(11-03) (2026-11-03).

창고 한 칸 = 폴더 하나:  <root>/library/<id>/ { entry.json · motion.bip · shots/s0~s3.jpg · max.txt }
- entry.json 은 손자리가 먼저 쓴다(이름 · 꼬리표 · 출처). 맥스는 .bip · 사진 · max.txt(구간 · 루프 여부)만 쓴다.
- motion.bip 이 생겨야 「찾기」에 나온다(맥스 스크립트가 아직 안 돌았거나 실패한 칸은 pending).
- 출처(origin)는 넷: company(회사 작업물) · own(내가 만든 것) · bip_file(받아 온 .bip, 예: 퀵매직) · video_draft(영상에서 뽑은 초안).
  video_draft 는 찾기 결과 · 입히기 결과에 늘 「초안」 경고가 붙는다(철칙: 출처를 숨기지 않는다).

맥스는 손자리가 띄우지 않는다. 열린 맥스에는 클로드가 3dsmax-mcp 로 한 줄을 보내고, 폴더 일괄은 사람이 3dsmaxbatch 로 돌린다.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

ORIGINS = {
    "company": "회사 작업물",
    "own": "직접 만든 것",
    "bip_file": "받아 온 .bip",
    "video_draft": "영상 변환 초안",
}

# 동작 이름 조각 → 한국어 꼬리표(검색용). 게임 애니 파일 이름 관례(idle · run · hit …)에서.
NAME_TAGS: dict[str, tuple[str, ...]] = {
    "idle": ("대기", "숨쉬기", "서있기"), "stand": ("대기", "서있기"), "astand": ("전투대기", "대기"),
    "run": ("달리기", "이동"), "sprint": ("전력질주", "달리기", "이동"), "walk": ("걷기", "이동"), "dash": ("대시", "돌진", "이동"),
    "jump": ("점프",), "hit": ("공격",), "attack": ("공격",), "atk": ("공격",), "skill": ("스킬", "공격"),
    "active": ("스킬",), "auto": ("기본공격", "평타"), "base": ("기본공격", "콤보"), "combo": ("콤보", "공격"),
    "awakening": ("각성", "필살기", "궁극기"), "ult": ("궁극기", "필살기"), "cutscene": ("컷신", "연출"),
    "airborne": ("공중", "띄워짐", "피격"), "down": ("다운", "쓰러짐"), "recover": ("기상", "일어나기"),
    "die": ("사망", "죽음"), "death": ("사망", "죽음"), "stun": ("기절", "스턴"), "rigor": ("경직", "피격"),
    "damage": ("피격",), "victory": ("승리", "세리머니"), "win": ("승리",), "entry": ("등장",), "intro": ("등장",),
    "loop": ("루프", "반복"), "common": ("공용", "기본"), "possession": ("빙의", "변신"), "expire": ("종료", "해제"),
    "finish": ("멈춤", "정지"), "turn": ("돌기", "회전"), "guard": ("방어", "막기"), "kick": ("발차기", "공격"),
    "punch": ("주먹", "공격"), "slash": ("베기", "공격"), "shoot": ("사격", "공격"), "cast": ("시전", "마법"),
}

# 사람이 말하는 낱말 → 같은 뜻 꼬리표(찾기에서 넓혀 본다)
SYNONYMS: dict[str, tuple[str, ...]] = {
    "공격": ("공격", "스킬", "평타", "기본공격", "콤보", "베기", "발차기", "주먹", "사격"),
    "때리기": ("공격",), "치기": ("공격",), "필살기": ("필살기", "궁극기", "각성"), "궁극기": ("궁극기", "필살기", "각성"),
    "대기": ("대기", "서있기", "숨쉬기", "전투대기"), "서있기": ("서있기", "대기"),
    "달리기": ("달리기", "전력질주"), "뛰기": ("달리기", "전력질주"), "이동": ("이동", "걷기", "달리기"),
    "맞기": ("피격", "경직"), "피격": ("피격", "경직", "띄워짐", "다운"), "죽기": ("사망", "죽음"),
    "승리": ("승리", "세리머니"), "등장": ("등장",), "점프": ("점프", "공중"),
}

_ID_SAFE = re.compile(r"[^0-9A-Za-z가-힣_-]+")

# ★ 2026-11-04: 회사 .max 폴더에는 동작이 아닌 모델 파일(「Hero_X_Mesh_…_스킨수정」 같은 모델링 · 스킨 · UV 수정본)이
#   섞여 있다. 바이페드 기본 자세가 「600프레임 루프 동작」으로 들어가 말로 찾기에 섞였다(창고 532개 중 23개 · 23개 모두
#   이름에 「Mesh」 마디 · 거꾸로 동작 이름 509개에는 그 마디가 0). 지우지 않고 「모델 파일」로 표시해 찾기에서만 뺀다.
_MODEL_FILE = re.compile(r"(?:^|[_\s-])mesh(?:[_\s-]|$)", re.I)
#: 찾는 말에 이 낱말이 있으면 모델 파일도 보여 준다(「메쉬 수정본 찾아 줘」).
_MODEL_WORDS = ("mesh", "메쉬", "메시", "모델", "모델링", "스킨")


def template_words(entry: dict[str, Any]) -> list[str]:
    from .template import words

    return words(entry)


def is_model_file(name: str) -> bool:
    return bool(_MODEL_FILE.search(name or ""))


def lib_dir(root: Path) -> Path:
    return root / "library"


# ── 작업 습관(사람마다 다르다 — 첫 현업 애니메이터의 답을 기준점으로) ───────────────
#: 11-05 현업 애니메이터 답이 기본값이다. 애니메이터마다 다르므로 규칙이 아니라 **기준점** —
#: 처음 쓰는 사람은 창고(회사 맥스 폴더)에서 짐작한 숫자를 들고 짧게 확인받아 이 파일에 남긴다.
PREFS_DEFAULT: dict[str, Any] = {
    "bookend": True,             # 「첫 번째, 마지막 포즈가 무조건 내가 지금 작업하는 캐릭터의 포즈」 — 입히기 전 자세를 첫 · 끝 키에
    "blend": 0.5,                # 섞는 비율은 사람이 고른다 — 안 정했을 때만 쓰는 값
    "body_fit": {"stride": 0.5, "arm_spread": 35.0},   # 8등신 → 2~3등신 「보정 B」
    "reference_query": "무기 + 무게감 + 성별 + 동작 (예: 한손검 여자 캐릭터 공격모션 · 무거운 양손검 남자 캐릭터 모션) 또는 정확한 캐릭터 이름",
    "source": "기준점(첫 현업 애니메이터 11-05) — 이 사람에게 아직 확인 안 함",
}


def prefs_path(root: Path) -> Path:
    return root / "animator_prefs.json"


def prefs(root: Path) -> dict[str, Any]:
    out = dict(PREFS_DEFAULT)
    p = prefs_path(root)
    if p.is_file():
        try:
            out.update(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            pass
    out["confirmed"] = p.is_file()
    return out


def loop_share(root: Path) -> dict[str, Any]:
    """창고에서 짐작: 동작 중 처음 = 끝(루프)인 몫. 콜드 스타트에 「이 팀은 끝을 닫나」를 숫자로 묻기 위해."""
    motions = [e for e in entries(root) if e.get("kind") == "motion" and "loop" in e]
    looped = sum(1 for e in motions if str(e["loop"]).lower() == "true")
    return {"motions": len(motions), "looped": looped,
            "share": round(looped / len(motions), 2) if motions else None}


def tags_from_name(name: str) -> list[str]:
    low = name.lower()
    out: list[str] = []
    for key, words in NAME_TAGS.items():
        if re.search(rf"(^|[^a-z]){key}", low):
            out += [w for w in words if w not in out]
    return out


def new_entry(root: Path, *, name: str, origin: str, character: str = "", tags: Sequence[str] = (),
              source: str = "", note: str = "") -> dict[str, Any]:
    if origin not in ORIGINS:
        raise ValueError(f"origin 은 {list(ORIGINS)} 중 하나 — 이 동작이 어디서 왔는지 사람에게 물어라")
    name = name.strip() or "이름없음"
    slug = _ID_SAFE.sub("_", f"{character}_{name}" if character else name).strip("_")[:60] or "motion"
    eid = f"{slug}_{uuid.uuid4().hex[:6]}"
    folder = lib_dir(root) / eid
    (folder / "shots").mkdir(parents=True, exist_ok=True)
    auto = tags_from_name(name)
    entry = {
        "id": eid, "name": name, "character": character.strip(), "origin": origin, "origin_label": ORIGINS[origin],
        "draft": origin == "video_draft", "tags": list(dict.fromkeys([*(t.strip() for t in tags if t.strip()), *auto])),
        "source": source, "note": note, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (folder / "entry.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**entry, "folder": folder}


def import_bip(root: Path, bip: Path, **kw: Any) -> dict[str, Any]:
    if bip.suffix.lower() != ".bip" or not bip.is_file():
        raise FileNotFoundError(f".bip 파일이 아니거나 없다: {bip}")
    entry = new_entry(root, name=kw.pop("name", "") or bip.stem, source=kw.pop("source", "") or str(bip), **kw)
    shutil.copyfile(bip, entry["folder"] / "motion.bip")
    return entry


def _read_max_meta(folder: Path) -> dict[str, Any]:
    p = folder / "max.txt"
    if not p.is_file():
        return {}
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}
    meta: dict[str, Any] = {}
    for part in text.split():
        k, _, v = part.partition("=")
        if k in ("start", "end", "fps"):
            try:
                meta[k] = int(float(v))
            except ValueError:
                pass
        elif k == "loop":
            meta["loop"] = v.lower() == "true"
        elif k == "loopgap":
            try:
                meta["loopgap"] = round(float(v), 4)   # 처음 · 끝 손발 차이 ÷ 키(11-05)
            except ValueError:
                pass
        elif k == "biped":
            meta["biped"] = v
    if "start" in meta and "end" in meta:
        meta["frames"] = meta["end"] - meta["start"]
    return meta


def entries(root: Path, include_pending: bool = False) -> list[dict[str, Any]]:
    out = []
    base = lib_dir(root)
    if not base.is_dir():
        return out
    for folder in sorted(base.iterdir()):
        ej = folder / "entry.json"
        if not ej.is_file():
            continue
        try:
            e = json.loads(ej.read_text(encoding="utf-8"))
        except ValueError:
            continue
        ready = (folder / "motion.bip").is_file()
        if not ready and not include_pending:
            continue
        e.update(_read_max_meta(folder))
        e["ready"] = ready
        e["kind"] = "model" if is_model_file(e.get("name", "")) else "motion"
        e["bip"] = str(folder / "motion.bip") if ready else None
        e["shots"] = [str(p) for p in sorted((folder / "shots").glob("s*.jpg"))]
        out.append(e)
    return out


def _words(query: str) -> list[str]:
    return [w for w in re.split(r"[\s,·/]+", query.strip().lower()) if w]


def find(root: Path, query: str, k: int = 5, character: str = "", origin: str = "") -> list[dict[str, Any]]:
    """낱말마다: 꼬리표에 그대로 있으면 3점 · 같은 뜻 꼬리표면 2점 · 이름 · 캐릭터 · 메모에 들어 있으면 1점."""
    words = _words(query)
    want_models = any(m in w for w in words for m in _MODEL_WORDS)
    scored = []
    for e in entries(root):
        if e.get("kind") == "model" and not want_models:
            continue
        if character and character.strip() and character.strip() not in e.get("character", ""):
            continue
        if origin and e.get("origin") != origin:
            continue
        # 회사 템플릿 칸(목록 · 상태 · 클립명 · 변형 — template.py)도 꼬리표로 친다: 「다운」 · 「기본 공격」 · 「Lobby_Get」 같은 클립명
        tags = {t.lower() for t in e.get("tags", [])} | set(template_words(e))
        hay = " ".join([e.get("name", ""), e.get("character", ""), e.get("note", ""), *tags]).lower()
        score = 2 if (want_models and e.get("kind") == "model") else 0
        for w in words:
            if w in tags:
                score += 3
            elif any(s in tags for s in SYNONYMS.get(w, ())):
                score += 2
            elif w in hay:
                score += 1
        if score or not words:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1].get("draft", False), x[1].get("name", "")))
    return [e for _s, e in scored[:max(1, k)]]


def get(root: Path, eid: str) -> dict[str, Any]:
    for e in entries(root, include_pending=True):
        if e["id"] == eid:
            return e
    raise KeyError(f"창고에 {eid} 가 없다 — anim_library_find 로 id 를 받아라")


# ── 맥스 스크립트 ────────────────────────────────────────────────────────────

def _q(path: Path | str) -> str:
    return '@"' + str(path).replace('"', "") + '"'


_FIND_BIPED = r'''
fn sjFindBiped want = (
  local n = undefined
  if want != "" do n = getNodeByName want exact:true
  if n == undefined do (
    for o in objects while n == undefined do
      if classof o.controller == Vertical_Horizontal_Turn do n = o
  )
  if n != undefined and classof n.controller != Vertical_Horizontal_Turn do n = undefined
  n
)
'''

_SAVE_ONE = r'''
fn sjSaveMotion com folder batch = (
  local bip = folder + "\\motion.bip"
  biped.saveBipFile com.controller bip
  local S = animationRange.start.frame as integer
  local E = animationRange.end.frame as integer
  -- 루프 여부: 손 · 발 · 머리가 몸통(COM) 기준으로 처음과 끝이 같은 자리면 루프
  -- 11-05: 기준이 장면 단위 1.0 으로 박혀 있었다 — 키 2.9 짜리 쿠키와 키 큰 캐릭터에 같은 잣대라 창고 511개 중 50% 만 루프로 나왔다
  --   (현업 애니메이터는 「첫 · 끝은 무조건 캐릭터 포즈」). 키(바이페드 height)의 2% 로 바꾸고, 잰 값(키 대비)도 남긴다.
  local tips = for o in objects where (classof o.controller == BipSlave_Control) and \
      (matchPattern o.name pattern:"*Hand" or matchPattern o.name pattern:"*Foot" or matchPattern o.name pattern:"*Head") collect o
  local gap = 0.0
  for t in tips do (
    local a = at time S (t.transform.pos - com.transform.pos)
    local b = at time E (t.transform.pos - com.transform.pos)
    gap = amax gap (distance a b)
  )
  local bh = try (com.controller.height) catch (0.0)
  if bh < 0.001 do bh = 100.0
  local loopGap = gap / bh
  local loopOK = loopGap <= 0.02
  -- 대표 장면 4장(처음 · 1/3 · 2/3 · 끝): 임시 카메라로 작게 렌더하고 카메라는 지운다
  -- 11-03 열린 맥스 시험: 뷰포트 찍기는 지금 고른 좁은 뷰포트 귀퉁이만 찍혀 못 쓴다 → 렌더로 통일.
  -- 장면 렌더러(Arnold 등)는 무거울 수 있어 찍는 동안만 기본 Scanline 으로 바꿨다가 되돌린다.
  local keep = sliderTime
  local keepR = renderers.current
  try (renderers.current = Default_Scanline_Renderer()) catch ()
  -- 11-05 현업 파일 시험: 텍스처가 회색 — .max 는 회사 PC 경로를 가리키고 그림은 캐릭터 폴더(…\PNG)에 있다.
  --   이 세션만 그림 찾는 자리에 캐릭터 폴더 아래를 더한다(sessionPaths — 맥스 설정에 남지 않는다).
  if maxFilePath != "" do try (
    local top = pathConfig.removePathLeaf (pathConfig.removeTrailingBackslash maxFilePath)
    local dirs = #(top)
    for d in getDirectories (top + "\\*") do (append dirs d; for d2 in getDirectories (d + "*") do append dirs d2)
    for d in dirs do sessionPaths.add #map d
    -- 찾는 자리를 더해도 맥스는 열 때 정한 「없음」을 다시 찾지 않았다(현업 파일: 원래 작업자 바탕화면 경로). 일괄(저장 안 함)일 때만
    -- 없는 그림을 같은 이름으로 캐릭터 폴더에서 찾아 바꿔 끼운다 — 사람이 연 장면은 건드리지 않는다.
    if batch do for b in (getClassInstances BitmapTexture) where b.filename != undefined and not (doesFileExist b.filename) do (
      local nm = filenameFromPath b.filename
      for d in dirs while not (doesFileExist b.filename) do (
        local p = (pathConfig.appendPath d nm)
        if doesFileExist p do b.filename = p
      )
    )
  ) catch ()
  local tgt = Targetobject pos:[0, 0, 72]
  local cam = Targetcamera pos:[70, -240, 110] target:tgt fov:40
  -- 11-05 현업 파일 시험: 카메라가 늘 같은 거리(240)라 작은 캐릭터는 작게 찍혔다 → 프레임마다 몸(스킨 메쉬 · 없으면 뼈) 크기에 맞춘다
  local body = for o in geometry where not o.isHidden and (o.modifiers[#Skin] != undefined or o.modifiers[#Physique] != undefined) collect o
  if body.count == 0 do body = for o in objects where classof o.controller == BipSlave_Control collect o
  local dir = normalize [70, -240, 38]
  try (
    for k = 0 to 3 do (
      local f = S + ((E - S) * k / 3)
      at time f (
        local lo = [1e9, 1e9, 1e9]
        local hi = [-1e9, -1e9, -1e9]
        for o in body do (
          lo = [amin lo.x o.min.x, amin lo.y o.min.y, amin lo.z o.min.z]
          hi = [amax hi.x o.max.x, amax hi.y o.max.y, amax hi.z o.max.z]
        )
        local c = if lo.x < 1e8 then (lo + hi) / 2 else com.transform.pos
        local h = if lo.x < 1e8 then (hi.z - lo.z) else 72.0
        local w = if lo.x < 1e8 then (amax (hi.x - lo.x) (hi.y - lo.y)) else 40.0
        -- 가로 화각 40° · 320x400(세로가 길다): 세로 화각 ≈ 48.9°. 키와 폭 중 더 먼 쪽에 맞추고 1.2배 여유
        local d = 1.2 * (amax ((h / 2) / (tan 24.45)) ((w / 2) / (tan 20.0)))
        d = amax d 10.0
        tgt.pos = c
        cam.pos = c + dir * d
      )
      render camera:cam frame:(f * 1f) outputSize:[320,400] vfb:false quiet:true outputfile:(folder + "\\shots\\s" + (k as string) + ".jpg")
    )
  ) catch ()
  delete #(cam, tgt)
  try (renderers.current = keepR) catch ()
  sliderTime = keep
  (dotNetClass "System.IO.File").WriteAllText (folder + "\\max.txt") \
    ("start=" + (S as string) + " end=" + (E as string) + " fps=" + (frameRate as string) + " loop=" + (loopOK as string) + " loopgap=" + (loopGap as string) + " biped=" + com.name)
  "ok"
)
'''


def add_scene_script(folder: Path, biped: str = "") -> str:
    """열린 맥스의 지금 장면에서 한 동작을 창고에 넣는다. 키는 바꾸지 않는다(임시 카메라만 만들었다 지운다)."""
    return (
        "-- 손자리 애니메이터 팩: 모션 창고에 넣기(지금 장면 · 키를 바꾸지 않는다)\n(\n" + _FIND_BIPED + _SAVE_ONE +
        f'local com = sjFindBiped "{biped}"\n'
        f'if com == undefined then "sonjari: no biped — 바이페드(COM)를 못 찾았다" else (\n'
        f'  sjSaveMotion com {_q(folder)} false\n'
        f'  "sonjari: added " + com.name + " → {folder.name}"\n)\n)\n'
    )


BATCH_CHUNK = 20  # 맥스 하나가 여는 파일 수. 11-04 한 맥스로 수백 개를 열다 60개 언저리에서 연달아 죽었다 → 조각마다 새 맥스


def add_folder_batch_script(jobs: Sequence[tuple[Path, Path]], biped: str = "", log_path: Path | None = None) -> str:
    """3dsmaxbatch 용: .max 파일마다 열어 창고 칸 하나씩. 열린 맥스는 건드리지 않는다(따로 도는 맥스).

    기록은 파일마다 **바로** 덧붙인다(11-04: 끝에 한 번 쓰던 기록은 맥스가 죽으면 통째로 사라졌다).
    「start」 다음 줄이 없으면 그 파일에서 맥스가 죽은 것이다.
    """
    log = _q(log_path or (jobs[0][1].parent / "_batch_log.txt"))
    lines = ["-- 손자리 애니메이터 팩: .max 폴더를 모션 창고로(3dsmaxbatch 전용)", "(", _FIND_BIPED, _SAVE_ONE,
             f'fn sjLog s = (dotNetClass "System.IO.File").AppendAllText {log} (s + "\\r\\n")']
    for src, folder in jobs:
        lines.append(f'sjLog ("start " + {_q(src.name)})')
        lines.append(
            f'try (loadMaxFile {_q(src)} quiet:true useFileUnits:true; local com = sjFindBiped "{biped}"; '
            f'if com == undefined then sjLog ("nobiped " + {_q(src.name)}) '
            f'else (sjSaveMotion com {_q(folder)} true; sjLog ("ok " + {_q(src.name)}))) '
            f'catch (sjLog ("error " + {_q(src.name)} + " " + (getCurrentException() as string)))'
        )
        lines.append("resetMaxFile #noPrompt")
        lines.append("gc light:true")
    lines.append(")")
    return "\n".join(lines) + "\n"


COM_MATCH = r'''
-- ★ 11-04 현업 애니메이터: 「모션 들고 올 때 알아서 COM 위치를 기존 mesh 파일에 맞춰서」.
--   불러오기 전 COM 자리(앞뒤 · 좌우)와 발 높이를 적어 두고, 불러온 동작의 첫 프레임을 거기에 맞춘다.
--   높이는 COM 이 아니라 발로 맞춘다 — 첫 프레임이 웅크린 자세여도 몸이 뜨지 않게.
--   옮기기는 바이페드 Move All(키 전체를 한 번에) → 접기. 키를 새로 찍지 않는다. 안 되면 첫 프레임 키만 민다.
fn sjFootZ com t = (
  local z = 1e9
  for s in #(" L Foot", " R Foot") do (
    local n = getNodeByName (com.name + s) exact:true
    if n != undefined do z = amin z (at time t n.transform.pos.z)
  )
  if z > 1e8 then undefined else z
)
fn sjComMatch com S keepPos keepFoot = (
  local p = at time S com.transform.pos
  local fz = sjFootZ com S
  local dz = if keepFoot != undefined and fz != undefined then keepFoot - fz else 0.0
  local d = [keepPos.x - p.x, keepPos.y - p.y, dz]
  if (length d) < 0.0001 do return "COM 맞춤: 이미 맞음"
  local how = "Move All"
  try (
    -- 11-04 시험: 바이페드 COM 은 .position 이 없다(Unknown property) → move. Move All 켠 채 옮기면 0 · 50프레임이 똑같이 움직였다.
    -- ★ 그런데 동작을 입히고 구간을 바꾼 장면에서는 **두 배로** 옮겨졌다(2.06 을 옮기라 했는데 4.12). 까닭은 아직 모른다 —
    --   그래서 결과를 재서 맞춘다: 옮긴 뒤 실제로 간 만큼을 재고, 그 비율(얼마나 더 가나)로 남은 만큼을 다시 옮긴다. 세 번까지.
    local want = p + d
    local step = d
    for k = 1 to 3 while (length (want - (at time S com.transform.pos))) > 0.001 do (
      local before = at time S com.transform.pos
      com.controller.moveAllMode = true
      at time S (move com step)
      biped.collapseMoveAllMode com.controller
      com.controller.moveAllMode = false
      local got = (at time S com.transform.pos) - before
      local gain = if (length step) > 0.000001 then (dot got step) / (dot step step) else 1.0
      if gain < 0.1 do gain = 1.0
      step = (want - (at time S com.transform.pos)) / gain
    )
  ) catch (
    how = "첫 프레임 키"
    try (com.controller.moveAllMode = false) catch ()
    with animate on (at time S (biped.setTransform com #pos (p + d) true))
  )
  local p2 = at time S com.transform.pos
  local fz2 = sjFootZ com S
  "COM 맞춤(" + how + "): 수평 어긋남 " + ((distance [p2.x, p2.y, 0] [keepPos.x, keepPos.y, 0]) as string) + \
    " · 발 높이 어긋남 " + (if keepFoot != undefined and fz2 != undefined then (abs (fz2 - keepFoot)) as string else "-") + \
    " · 옮긴 거리 " + ((length d) as string)
)
'''


BODY_FIT = r'''
-- ★ 11-04 체형 보정(8등신 동작 → 3등신 캐릭터). 맥스 기본 키 맞춤(#retargetHeight · #retargetLimbSizes)은 각도를 그대로 둬서
--   2.1등신 캐릭터에서 팔이 큰 머리 뒤로 숨었다. 현업 애니메이터가 고른 판: 다리 보폭 0.5 · 위팔 벌림 35° · COM 맞춤(한 동작).
fn sjRotToward n target ang = (
  -- 위팔 길이 방향(row1)을 target 쪽으로 ang 도. 돌린 뒤 target 과의 내적이 커졌는지 재고, 아니면 반대로(회전 부호를 믿지 않는다).
  local cur = normalize n.transform.row1
  local t = normalize target
  local ax = cross cur t
  if (length ax) < 0.00001 do return 0
  ax = normalize ax
  local base = n.transform
  local d0 = dot cur t
  for sgn in #(1, -1) do (
    local r = (angleaxis (ang * sgn) ax) as matrix3
    local tm = copy base
    tm.row1 = base.row1 * r; tm.row2 = base.row2 * r; tm.row3 = base.row3 * r
    biped.setTransform n #rotation tm.rotation true
    if (dot (normalize n.transform.row1) t) > d0 then return sgn
    biped.setTransform n #rotation base.rotation true
  )
  0
)
fn sjKeyTimes ctrls S E = (
  -- 애니메이터가 찍은 키 자리만(구간 안). 11-04: 2프레임마다 찍던 초안은 키가 너무 촘촘해 받아서 다듬기 어렵다.
  local r = #()
  for c in ctrls where c != undefined do try (
    for i = 1 to c.keys.count do (local f = c.keys[i].time.frame as integer; if f >= S and f <= E do appendIfUnique r f)
  ) catch ()
  if r.count == 0 do r = #(S, E)
  sort r
)
fn sjBodyFit com S E stride spread = (
  -- 기존 키 자리에서만 고친다(키 개수 그대로). stride: 시작 자리 기준 몸통 이동 배율 · spread: 위팔을 몸 바깥쪽(골반 좌우 선)으로 벌리는 도.
  local pre = com.name
  local lua = getNodeByName (pre + " L UpperArm") exact:true
  local rua = getNodeByName (pre + " R UpperArm") exact:true
  local lt = getNodeByName (pre + " L Thigh") exact:true
  local rt = getNodeByName (pre + " R Thigh") exact:true
  local p0 = at time S com.transform.pos
  local nCom = 0
  local nArm = 0
  if stride != 1.0 do (
    local ts = sjKeyTimes #(com.controller.horizontal.controller, com.controller.vertical.controller) S E
    local pts = for f in ts collect (at time f com.transform.pos)
    with animate on (for i = 1 to ts.count do at time ts[i] (biped.setTransform com #pos (p0 + (pts[i] - p0) * stride) true))
    nCom = ts.count
  )
  if spread > 0 and lua != undefined and rua != undefined and lt != undefined and rt != undefined do (
    local ts = sjKeyTimes #(lua.controller, rua.controller) S E
    with animate on (for f in ts do at time f (
      local side = normalize (rt.transform.pos - lt.transform.pos)
      sjRotToward lua (-side) spread
      sjRotToward rua side spread
    ))
    nArm = ts.count
  )
  "체형 보정: 다리 보폭 " + (stride as string) + "배 · 위팔 벌림 " + (spread as string) + "° (원래 키 자리만 · 몸통 " + (nCom as string) + " · 팔 " + (nArm as string) + "곳)"
)
'''


POSE_FN = r'''
fn sjBones com = (
  -- 부모가 먼저 오게(부모 회전을 먼저 고쳐야 자식이 그 위에서 계산된다)
  local out = #()
  local q = #(com)
  while q.count > 0 do (
    local n = q[1]; deleteItem q 1
    if n != com and classof n.controller == BipSlave_Control do append out n
    for c in n.children do append q c
  )
  out
)
fn sjLocalQ n = (
  local tm = n.transform
  if n.parent != undefined do tm = tm * (inverse n.parent.transform)
  tm.rotation
)
fn sjQDot a b = a.x*b.x + a.y*b.y + a.z*b.z + a.w*b.w
fn sjCapture com = (
  -- 지금 시각의 자세: 뼈마다 부모 기준 회전 + COM 변환
  local bones = sjBones com
  #(bones, (for n in bones collect (sjLocalQ n)), com.transform)
)
fn sjBookend com cap S E = (
  -- ★ 11-05 현업 애니메이터: 「첫 번째, 마지막 포즈가 무조건 내가 지금 작업하는 캐릭터의 포즈」 — 찾은 모션을
  --   이식하는 캐릭터의 첫 포즈와 이어 준다. 입히기 전에 적어 둔 이 캐릭터의 자세를 첫 키 · 끝 키에 박는다.
  --   COM: 회전과 높이는 그 자세로, 수평은 첫 키는 원래 자리 · 끝 키는 동작이 간 곳 그대로.
  local bones = cap[1]
  local gap = 0.0
  with animate on (
    for f in #(S, E) do at time f (
      local pe = com.transform.pos
      local c0 = cap[3]
      biped.setTransform com #rotation c0.rotation true
      biped.setTransform com #pos (if f == S then c0.pos else [pe.x, pe.y, c0.pos.z]) true
      for i = 1 to bones.count where isValidNode bones[i] do (
        local n = bones[i]
        local tm = cap[2][i] as matrix3
        if n.parent != undefined do tm = tm * n.parent.transform
        biped.setTransform n #rotation tm.rotation true
      )
    )
  )
  for f in #(S, E) do for i = 1 to bones.count where isValidNode bones[i] do (
    local q = at time f (sjLocalQ bones[i])
    gap = amax gap (1.0 - abs (sjQDot q cap[2][i]))
  )
  "첫 · 끝 = 이 캐릭터 포즈(어긋남 " + (gap as string) + ")"
)
'''

BLEND = r'''
-- ★ 11-05 섞기(현업 애니메이터 흐름: 비슷한 것 찾기 → 섞기, 비율은 사람). A 를 입힌 뒤 B 를 w 만큼 섞는다.
--   시간은 길이 비율로 맞춘다(A 의 u 지점 = B 의 u 지점). 팔다리는 부모 기준 회전을 slerp, COM 은 시작 자리 기준 이동량을 섞는다.
--   키는 A 의 원래 키 자리에서만 고친다(키 개수 그대로 — 받아서 다듬기 쉽게).
fn sjSample com bones S E = (
  -- 정수 프레임마다 COM 위치 · 회전과 뼈마다 부모 기준 회전
  local fr = #()
  for f = S to E do at time f (
    append fr #(com.transform.pos, com.transform.rotation, (for b in bones collect (sjLocalQ b)))
  )
  fr
)
fn sjBlend com bipB w SB EB = (
  local bones = sjBones com
  local S = animationRange.start.frame as integer
  local E = animationRange.end.frame as integer
  biped.saveBipFile com.controller (sysInfo.tempdir + "sonjari_blend_A.bip")
  -- B 를 읽어 표본을 뜬다. loadBipFile 은 재생 구간을 안 바꾼다(11-03) → B 의 구간은 창고 기록에서 받는다(없으면 COM 키 처음~끝)
  biped.loadBipFile com.controller bipB
  if SB < 0 or EB <= SB do (
    local kt = sjKeyTimes #(com.controller.horizontal.controller, com.controller.vertical.controller) -100000 100000
    SB = kt[1]; EB = kt[kt.count]
    if EB <= SB do EB = SB + 1
  )
  local smB = sjSample com bones SB EB
  -- A 를 다시 입히고 같은 구간으로
  biped.loadBipFile com.controller (sysInfo.tempdir + "sonjari_blend_A.bip")
  animationRange = interval S E
  local pA0 = at time S com.transform.pos
  local pB0 = smB[1][1]
  -- ★ 11-06 현업 애니메이터 판정: 반반 섞기에서 73프레임부터 COM 이 180° 돌아 몸 전체가 뒤돌았다(맥스 2026).
  --   위치는 시작 자리를 빼고 섞었는데 회전은 월드 방향 그대로 slerp 했다 — A · B 가 처음부터 다른 쪽을 보면 「한가운데」가 엉뚱하고,
  --   반대에 가까우면 부호 보정이 키마다 다른 쪽을 골라 튄다. → B 동작 전체를 「B 시작 방향 → A 시작 방향」(Y)만큼 돌려 맞춘 뒤 섞는다.
  --   Y = inverse(B 시작) * A 시작(행 벡터: 방향 * Y 는 월드에서 돌림). B 의 이동량도 같은 Y 로 돌린다.
  local Y = inverse ((smB[1][2]) as matrix3) * ((at time S com.transform.rotation) as matrix3)
  local span = amax 1 (E - S)
  local nB = smB.count
  fn pick sm u n = sm[amax 1 (amin n ((1 + (u * (n - 1))) as integer))]
  local nCom = 0
  local nBone = 0
  local rotNote = ""
  with animate on (
    -- COM: 이동량 · 회전
    local ts = sjKeyTimes #(com.controller.horizontal.controller, com.controller.vertical.controller, com.controller.turning.controller) S E
    -- ★ 11-06 맥스 실측(현업 판정 재현): A · B 둘 다 몸을 여러 바퀴 도는 공격이라 프레임마다 「가까운 쪽 slerp」를 하면
    --   두 방향 차가 180° 를 넘는 순간 가까운 쪽이 반대편으로 바뀌어 몸이 홱 뒤돈다(반반 판 69~73프레임).
    --   → A 에서 B 까지 돌 각(축 · 각)을 키마다 **이어서** 따라간다(축이 뒤집히면 둘 다 뒤집고, 각은 앞 키에서 ±180° 안으로 펼친다).
    --   ★ 따라가기는 **프레임마다** 한다 — 키 자리에서만 하면 키 사이에 180° 넘게 돌아(이 동작은 한 프레임 86° 까지) 방향을 헷갈려
    --     한 바퀴를 잘못 세고, 그 절반(180°)만큼 몸이 돌았다(11-06 맥스 재현 · 32~36프레임). 키 자리 값은 그 표에서 꺼낸다.
    local prevAx = undefined
    local prevAng = 0.0
    local dAng = #()
    local dAx = #()
    for f = S to E do (
      local u = (f - S) as float / span
      local b = pick smB u nB
      local Ra = (at time f com.transform.rotation) as matrix3
      local Rb = (b[2] as matrix3) * Y
      local aa = ((inverse Ra) * Rb).rotation as angleaxis
      local ax = aa.axis
      local ang = aa.angle
      if prevAx != undefined and (dot ax prevAx) < 0 do (ax = -ax; ang = -ang)
      if prevAx != undefined do (
        while ang - prevAng > 180.0 do ang -= 360.0
        while ang - prevAng < -180.0 do ang += 360.0
      )
      prevAx = ax
      prevAng = ang
      append dAng ang
      append dAx ax
    )
    -- ★ 두 동작의 몸 방향 차가 끝까지 120° 안이면 섞고, 넘으면 **몸 방향은 A 그대로**(팔다리 · 이동만 섞는다). 서로 다르게 도는
    --   두 공격의 방향을 반반 섞는 데는 정답이 없다 — 짧은 쪽을 따르면 홱 뒤돌고(현업 판정), 이어서 따르면 반 바퀴 돌아간 채로 간다(11-06 재현).
    local maxGap = 0.0
    for a in dAng do maxGap = amax maxGap (abs a)
    local fullB = w >= 0.999                       -- 100% 는 「B 그대로」 — 헷갈릴 것이 없다
    local rotW = if maxGap <= 120.0 or fullB then w else 0.0
    rotNote = if rotW == 0.0 and w > 0 then (" · 몸 방향은 A 그대로(두 동작 방향 차 최대 " + ((maxGap as integer) as string) + "°)") else ""
    local plan = for f in ts collect (
      local u = (f - S) as float / span
      local b = pick smB u nB
      local pa = at time f com.transform.pos
      local Ra = (at time f com.transform.rotation) as matrix3
      local k = f - S + 1
      local Rw = if fullB then ((b[2] as matrix3) * Y) else (Ra * ((angleaxis (dAng[k] * rotW) dAx[k]) as matrix3))
      #(f, pA0 + ((pa - pA0) * (1 - w)) + (((b[1] - pB0) * Y) * w), Rw.rotation)
    )
    for p in plan do at time p[1] (biped.setTransform com #pos p[2] true; biped.setTransform com #rotation p[3] true)
    nCom = plan.count
    -- 뼈: 부모 기준 회전
    for i = 1 to bones.count do (
      local n = bones[i]
      local kt = sjKeyTimes #(n.controller) S E
      for f in kt do at time f (
        local u = (f - S) as float / span
        local qb = (pick smB u nB)[3][i]
        local qa = sjLocalQ n
        if (sjQDot qa qb) < 0 do qb = quat -qb.x -qb.y -qb.z -qb.w
        local q = slerp qa qb w
        local tm = q as matrix3
        if n.parent != undefined do tm = tm * n.parent.transform
        biped.setTransform n #rotation tm.rotation true
        nBone += 1
      )
    )
  )
  -- ★ 11-05 현업 애니메이터: 「마지막 포즈는 항상 맨 첫 번째 포즈여야 해」 — 섞으면 끝이 처음과 어긋나 다음 동작으로 이을 때 튄다.
  --   끝 프레임에 첫 프레임 자세를 그대로 박는다: 뼈는 부모 기준 회전, COM 은 회전과 높이(수평 자리는 그 동작이 간 곳 그대로).
  "섞기: B " + ((w * 100) as integer) as string + "% (원래 키 자리만 · 몸통 " + (nCom as string) + " · 뼈 " + (nBone as string) + "곳)" + rotNote
)
'''


def apply_script(bip: Path, biped: str = "", label: str = "", frames: tuple[int, int] | None = None,
                 *, match_height: bool = True, stride: float = 1.0, arm_spread: float = 0.0,
                 blend_bip: Path | None = None, blend: float = 0.0,
                 blend_frames: tuple[int, int] | None = None, bookend: bool = True) -> str:
    """지금 장면의 바이페드에 .bip 를 입힌다. 입히기 전에 holdMaxFile — 맘에 안 들면 편집 › 가져오기(Fetch)로 되돌린다.

    11-03 시험: loadBipFile 은 시간 구간을 바꾸지 않는다(78프레임 공격을 120프레임 대기 장면에 입히니 0~120 그대로) →
    창고에 적힌 구간으로 맞춘다. 그리고 키가 정말 바뀌었는지 손 · 발 위치를 입히기 전후로 대 본 결과를 같이 돌려준다.
    """
    rng = (f'  animationRange = interval {int(frames[0])} {int(frames[1])}\n' if frames and frames[1] > frames[0] else "")
    stride = max(0.1, min(float(stride or 1.0), 2.0))
    arm_spread = max(0.0, min(float(arm_spread or 0.0), 60.0))
    load_opts = " #retargetHeight" if match_height else ""
    fit = ""
    if stride != 1.0 or arm_spread > 0:
        fit = (f'  local fitNote = sjBodyFit com (animationRange.start.frame as integer) (animationRange.end.frame as integer) '
               f'{stride:.3f} {arm_spread:.1f}\n')
    else:
        fit = '  local fitNote = "체형 보정 없음"\n'
    blend = max(0.0, min(float(blend or 0.0), 1.0))
    blending = blend_bip is not None and blend > 0
    if blending:
        # 섞기는 체형 보정 전에 — 섞은 동작 위에 이 캐릭터 몸을 맞춘다
        sb, eb = (int(blend_frames[0]), int(blend_frames[1])) if blend_frames else (-1, -1)
        fit = (f'  local blendNote = sjBlend com {_q(blend_bip)} {blend:.3f} {sb} {eb}\n' + fit +
               '  fitNote = blendNote + " · " + fitNote\n')
    if bookend:
        fit += ('  fitNote = fitNote + " · " + (sjBookend com cap (animationRange.start.frame as integer) '
                '(animationRange.end.frame as integer))\n')
    return (
        "-- 손자리 애니메이터 팩: 창고 동작 입히기(입히기 전 장면을 보관(Hold)한다)\n(\n" + _FIND_BIPED + COM_MATCH + BODY_FIT + POSE_FN + (BLEND if blending else "") +
        r'''fn sjProbe = (
  local pts = #()
  for o in objects where (classof o.controller == BipSlave_Control) and (matchPattern o.name pattern:"*Hand" or matchPattern o.name pattern:"*Foot") do (
    local S = animationRange.start.frame as integer
    local E = animationRange.end.frame as integer
    for f in #(S, (S + E) / 2, E) do append pts (at time f o.transform.pos)
  )
  pts
)
''' +
        f'local com = sjFindBiped "{biped}"\n'
        f'if com == undefined then "sonjari: no biped — 바이페드(COM)를 못 찾았다" else (\n'
        f'  local before = sjProbe()\n'
        f'  local S0 = animationRange.start.frame as integer\n'
        f'  local keepPos = at time S0 com.transform.pos\n'
        f'  local keepFoot = sjFootZ com S0\n'
        f'  local cap = at time S0 (sjCapture com)\n'
        f'  holdMaxFile()\n'
        f'  biped.loadBipFile com.controller {_q(bip)}{load_opts}\n' + rng +
        f'  local comNote = sjComMatch com (animationRange.start.frame as integer) keepPos keepFoot\n' + fit +
        f'  local after = sjProbe()\n'
        f'  local moved = 0.0\n'
        f'  for i = 1 to (amin before.count after.count) do moved = amax moved (distance before[i] after[i])\n'
        # 11-04: 「바뀜」 기준을 장면 단위 0.5 로 박아 두면 키 2.9 짜리 쿠키 장면에서는 입혀져도 「안 바뀐 것 같다」가 된다 → 키의 1%.
        f'  local h = try (com.controller.height) catch (100.0)\n'
        f'  local verdict = if moved > (0.01 * h) then "키 바뀜" else "키가 안 바뀐 것 같다 — 확인 필요"\n'
        f'  "sonjari: applied {label} → " + com.name + " (" + (animationRange.start.frame as integer) as string + "~" + '
        f'(animationRange.end.frame as integer) as string + ") · " + verdict + " · " + comNote + " · " + fitNote + '
        f'" · 되돌리기: 편집 › 가져오기(Fetch)"\n)\n)\n'
    )
