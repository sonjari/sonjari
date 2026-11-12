# -*- coding: utf-8 -*-
"""애니메이터 팩 v1 도구 설명 — 모션 창고 · 관절 부품 · 포즈 시트 · 영상 → 바이페드 (2026-11-03 · 설계 §13~14)."""
from __future__ import annotations

from .library import ORIGINS

_ORIGIN_DESC = ("이 동작이 어디서 왔나 — company(회사 작업물) · own(직접 만든 것) · bip_file(받아 온 .bip, 예: 퀵매직) · "
                "video_draft(anim_video_to_biped 로 영상에서 뽑은 초안). 모르면 사람에게 물어라")


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


LIBRARY_ADD = _tool(
    "anim_library_add",
    "(클로드 · 코덱스용 · 3ds Max) 모션 창고에 바이페드 동작을 넣는다 — .bip + 대표 장면 4장 + 이름 · 꼬리표 · 출처. "
    "source=scene: 지금 열린 맥스 장면의 바이페드(키는 바꾸지 않는다) → 결과의 run_line 을 execute_maxscript 로 그대로 보낸다. "
    "source=bip_file: path 의 .bip 파일(또는 .bip 가 든 폴더)을 바로 넣는다(맥스 필요 없음 · 퀵매직 결과 등). "
    "source=max_folder: path 폴더의 .max 들을 한꺼번에 — 열린 맥스를 건드리지 않게 3dsmaxbatch 명령(batch_command)을 준다. "
    "그 명령을 사람에게 보여 주고, 사람이 돌리거나 당신에게 셸이 있으면 사람이 허락한 뒤 돌린다(파일 하나에 수십 초). "
    "꼬리표(tags)는 사람이 이 동작을 찾을 때 쓸 말로(예: 돌진 · 베기 · 3타). 파일 이름에서 나온 꼬리표는 자동으로 붙는다.",
    {
        "source": {"type": "string", "enum": ["scene", "bip_file", "max_folder"]},
        "origin": {"type": "string", "enum": list(ORIGINS), "description": _ORIGIN_DESC},
        "name": {"type": "string", "description": "동작 이름(scene 이면 필수). bip_file · max_folder 는 비우면 파일 이름"},
        "character": {"type": "string", "description": "캐릭터 이름(찾을 때 거른다)"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "찾을 때 쓸 한국어 낱말들"},
        "path": {"type": "string", "description": "bip_file: .bip 파일 또는 폴더 · max_folder: .max 가 든 폴더"},
        "biped": {"type": "string", "description": "바이페드 COM 이름(비우면 장면에서 처음 찾은 바이페드)"},
        "note": {"type": "string", "description": "메모(쓰임 · 주의)"},
        "include_backup": {"type": "boolean", "description": "max_folder: backup · old 같은 예전 판 폴더도 넣기(기본 false — 하위 폴더는 다 보되 예전 판은 뺀다)"},
    },
    ["source", "origin"],
)

LIBRARY_TAG = _tool(
    "anim_library_tag",
    "(클로드 · 코덱스용 · 시험 중) 창고 동작에 꼬리표 칸을 단다 — 무기 · 컨셉 · 무게감 · 속도감(현업 애니메이터가 찾을 때 쓰는 기준). "
    "사람이 말한 것만 단다(「22번은 한손검 · 빠른 · 스타일리쉬」). 이름 · 사진으로 무기를 짐작해 달지 마라. "
    "칸마다 통째로 바뀐다 — 빈 목록을 주면 그 칸을 지운다. 사전에 없는 값은 그대로 저장되고 not_in_dictionary 로 알려 준다. "
    "단 뒤에는 anim_library_find 가 「무거운 양손검 평타」 같은 말을 그 칸으로 읽어 찾는다.",
    {
        "id": {"type": "string", "description": "anim_library_find 가 준 id"},
        "무기": {"type": "array", "items": {"type": "string"}, "description": "예: 한손검 · 양손검 · 창 · 도끼 · 총 · 표창 · 활 · 맨손 · 마법 · 늘어나는 무기 · 둔기"},
        "컨셉": {"type": "array", "items": {"type": "string"}, "description": "캐릭터 컨셉. 예: 귀여운 · 스타일리쉬 · 근엄 · 도도 · 코믹"},
        "무게감": {"type": "array", "items": {"type": "string"}, "description": "예: 무거운 · 가벼운"},
        "속도감": {"type": "array", "items": {"type": "string"}, "description": "예: 빠른 · 느린 · 부드러운 · 연타"},
        "by": {"type": "string", "description": "누가 단다고 했나(남김용 · 비우면 「사람 말」)"},
    },
    ["id"],
)

HABIT = _tool(
    "anim_habit",
    "(클로드 · 코덱스용 · 시험 중) 다듬은 것 기억하기. 입히기 · 엇박자 결과에 habit_ask 가 오면(같은 상황에서 같은 손질이 두 번째) 그 한 줄만 사람에게 묻고 멈춰라. "
    "사람이 다음 말에서 「응」이라고 하면 action=save(habit_ask.save_args 그대로) · 「아니」면 action=decline(그 상황 · 그 값은 다시 안 물음). "
    "스스로 정해 저장하지 마라. 남긴 습관은 그 인자를 안 줬을 때만 쓰이고 결과의 habits_applied 로 늘 보인다. forget 으로 지우고 list 로 본다.",
    {
        "action": {"type": "string", "enum": ["save", "decline", "forget", "list"], "description": "save · decline · forget · list(기본)"},
        "where": {"type": "string", "description": "habit_ask 가 준 where(캐릭터 · 목록) 그대로"},
        "values": {"type": "object", "description": "손질 → 값(예: arm_spread → 20). forget 이면 지울 손질 이름들을 열쇠로"},
        "by": {"type": "string", "description": "누가 남기라고 했나(남김용)"},
    },
    [],
)

LIBRARY_FIND = _tool(
    "anim_library_find",
    "(클로드 · 코덱스용) 모션 창고에서 말로 찾는다(이 PC 안 · 맥스 필요 없음). 예: 「돌진 공격」 · 「○○ 대기 루프」. "
    "결과마다 id · 이름 · 캐릭터 · 출처 · 프레임 수 · 루프 여부 · 대표 장면 사진 경로가 온다. 사진을 사람에게 보여 고르게 하고, "
    "고른 id 로 anim_library_apply 를 불러라. 출처가 「영상 변환 초안」인 것은 초안이라고 꼭 말해라. "
    "무기 · 컨셉 · 무게감 · 속도감 낱말(「무거운 양손검」 · 「창으로 빠르게」)은 꼬리표 칸으로 읽는다 — 결과마다 matched 가 무엇이 맞았는지다. "
    "비거나 query_report 가 오면 무엇이 창고에 없는지 그대로 전해라(엉뚱한 동작으로 채우지 않는다).",
    {
        "query": {"type": "string", "description": "찾는 동작을 사람 말 그대로(비우면 전부)"},
        "character": {"type": "string", "description": "이 캐릭터 것만"},
        "origin": {"type": "string", "enum": list(ORIGINS), "description": "이 출처만"},
        "k": {"type": "integer", "description": "몇 개(기본 5, 최대 20)"},
    },
    [],
)

LIBRARY_APPLY = _tool(
    "anim_library_apply",
    "(클로드 · 코덱스용 · 3ds Max) 창고의 동작(.bip)을 지금 열린 장면의 바이페드에 입힌다. 입히기 전에 장면을 보관(holdMaxFile)해 "
    "편집 › 가져오기(Fetch)로 통째로 되돌릴 수 있다. **무엇을 어느 캐릭터에 입히는지 사람에게 말하고 「해」를 받은 뒤에만** run_line 을 "
    "execute_maxscript 로 보내라. 돌아온 「sonjari: applied …」 줄을 그대로 전해라. 다른 체격의 캐릭터에 입히면 발이 뜨거나 미끄러질 수 있다 — "
    "입힌 뒤 재생해 확인해 달라고 말해라. 입힐 때 COM 은 늘 그 캐릭터 원래 자리(수평)와 발 높이에 맞춘다. "
    "**체형이 다른 캐릭터**(예: 8등신 동작 → 2~3등신 캐릭터)면 stride · arm_spread 로 보정한다 — 현업 애니메이터가 고른 판은 "
    "stride 0.5 · arm_spread 35(한 동작 · 「제일 가깝다」). 숫자를 사람에게 묻지 말고 두세 벌(예: 그대로 · 0.5/20 · 0.5/35) 만들어 "
    "재생해 보고 고르게 하라 — 도구는 판단하지 않는다. "
    "**두 동작을 섞기**: blend_with 에 다른 칸 id, blend 에 그 동작 비율(0~1). 비율은 사람이 정한다 — 모르면 두세 벌(예 0.3 · 0.5 · 0.7) 만들어 보이고 고르게 하라.",
    {
        "id": {"type": "string", "description": "anim_library_find 가 준 id"},
        "blend_with": {"type": "string", "description": "섞을 다른 동작의 id(비우면 섞지 않음)"},
        "blend": {"type": "number", "description": "blend_with 동작의 비율(0~1 · 기본은 작업 습관 파일, 없으면 0.5). 0 이면 id 동작 그대로, 1 이면 blend_with 동작의 몸짓"},
        "bookend": {"type": "boolean", "description": "첫 · 끝 키를 입히기 전 이 캐릭터의 포즈로 맞춰 잇기(기본은 작업 습관 파일, 없으면 true)"},
        "biped": {"type": "string", "description": "입힐 바이페드 COM 이름(비우면 장면에서 처음 찾은 바이페드)"},
        "match_height": {"type": "boolean", "description": "키 맞춤(맥스 기본 #retargetHeight). 기본 true"},
        "stride": {"type": "number", "description": "다리 보폭 · 몸통 이동 배율(0.1~2 · 기본 1 = 그대로). 다리가 짧은 캐릭터면 다리 길이 비율쯤(예 0.5)"},
        "arm_spread": {"type": "number", "description": "위팔을 몸 바깥쪽으로 더 벌리는 도(0~60 · 기본 0). 머리가 커서 팔이 가리면(예 20 · 35)"},
        "foot_lock": {"type": "boolean", "description": "발 고정(기본 true): 원본에서 땅에 붙은 발을 입힌 뒤에도 그 자리에(보폭 보정 · 첫끝 덮기가 발을 끌지 않게). 미끄러지는 동작이면 false"},
        "character": {"type": "string", "description": "입힐 캐릭터 이름(다듬은 것 기억하기의 상황 열쇠 — 비우면 바이페드 이름). 같은 캐릭터 · 같은 목록에서 같은 손질을 두 번 하면 남길지 묻는다"},
    },
    ["id"],
)

PARTS = _tool(
    "anim_parts",
    "(클로드 · 코덱스용) 관절 부품(포즈 시트 · 영상 → 바이페드에 쓰는 모델 파일)의 상태 보기 · 받기. 부품은 손자리에 들어 있지 않다. "
    "action=status 로 상태와 안내문(notice)을 받고, 부품이 없으면 **안내문을 사람에게 그대로 보이고** 사람이 「받아」라고 하면 "
    "action=install, agree=true 로 부른다(약 525MB · 뒤에서 받는다 · 1~2분 뒤 status 로 확인). 사람 동의 없이 agree=true 를 보내지 마라.",
    {
        "action": {"type": "string", "enum": ["status", "install"]},
        "agree": {"type": "boolean", "description": "사람이 안내문을 읽고 받기에 동의했을 때만 true"},
    },
    ["action"],
)

POSE_SHEET = _tool(
    "anim_pose_sheet",
    "(클로드 · 코덱스용) 레퍼런스 포즈 시트: 이 PC 의 영상 파일(mp4 등) 또는 프레임 사진 폴더에서 몸이 멈춘 순간 N 장을 골라 "
    "뼈대를 그린 사진 한 장(sheet)과 속도 곡선을 만든다(관절 부품 필요 — 없으면 anim_parts). 한 번에 450 프레임(30fps 로 15초)까지 — "
    "길면 start_sec · end_sec 로 동작 한 번 구간만 자르거나 stride=2. CPU 로 400장에 2~3분. "
    "고르기 정확도는 아직 주장하지 않는다 — 사진을 사람에게 보이고 쓸 장면을 사람이 고르게 해라. 인터넷 주소는 받지 않는다(내려받지 않는다).",
    {
        "source": {"type": "string", "description": "영상 파일 경로 또는 프레임 사진 폴더"},
        "start_sec": {"type": "number"},
        "end_sec": {"type": "number"},
        "n": {"type": "integer", "description": "고를 장면 수(기본 8, 최대 16)"},
        "stride": {"type": "integer", "description": "몇 장마다 하나 읽나(기본 1)"},
    },
    ["source"],
)

VIDEO_TO_BIPED = _tool(
    "anim_video_to_biped",
    "(클로드 · 코덱스용 · 3ds Max) 영상 → 바이페드 블로킹 초안: anim_pose_sheet 가 고른 장면(poses 로 몇 번만 고를 수 있다)마다 3D 관절을 읽어 "
    "지금 열린 장면의 바이페드 척추 · 팔 · 다리 방향을 맞추고 start + i×spacing 프레임에 키를 찍는 맥스 스크립트를 만든다. "
    "**어느 장면을 몇 프레임 간격으로 찍을지 사람에게 말하고 「해」를 받은 뒤에만** run_line 을 execute_maxscript 로 보내라 "
    "(입히기 전 장면 보관 · Ctrl+Z 한 묶음). 그다음 check=true 로 다시 불러 뼈마다 얼마나 맞았는지 받아 전해라. "
    "결과는 블로킹 초안이다(손 · 발 끝 · 머리 방향 · 몸 위치는 안 맞춘다). 창고에 넣으면 origin=video_draft 로.",
    {
        "sheet": {"type": "string", "description": "anim_pose_sheet 가 준 sheet_id(비우면 가장 최근 시트)"},
        "poses": {"type": "array", "items": {"type": "integer"}, "description": "쓸 장면 번호(시트의 1, 2, …). 비우면 전부"},
        "biped": {"type": "string", "description": "바이페드 이름 앞머리(기본 Bip001 — 뼈 이름이 「Bip001 L Thigh」 꼴)"},
        "start": {"type": "integer", "description": "첫 키 프레임(기본 0)"},
        "timing": {"type": "string", "enum": ["video", "even"], "description": "키 자리: video(기본) = 영상 속 시각 그대로(예비 · 타격 · 회복 리듬) · even = spacing 간격"},
        "spacing": {"type": "integer", "description": "timing=even 일 때 키 사이 프레임(기본 10)"},
        "check": {"type": "boolean", "description": "true 면 새로 만들지 않고, 맥스가 쓴 맞춤 보고(가장 최근)를 읽어 준다"},
    },
    [],
)

FIT_CHECK = _tool(
    "anim_fit_check",
    "(클로드 · 코덱스용 · 3ds Max · 시험 중) 입힌 뒤 뚫림 점검표: 손 · 팔이 머리 · 가슴 · 배를, 무릎이 배 · 가슴을 뚫은 프레임 수와 구간. "
    "1걸음: 결과의 run_line 을 execute_maxscript 로 보낸다 — 맥스는 뼈 위치와 몸 메시 점을 파일로 쓰기만 한다(장면을 바꾸지 않는다 · "
    "몸 크기는 피겨 모드에서 재고 원래대로 되돌린다). 2걸음: check=true 로 다시 불러 점검표를 받는다. "
    "**시험 중**이다 — 11-10 부터 몸 크기를 스킨 가중치로 재 머리카락 · 리본 · 치마 같은 장식은 뺀다(결과 body_from.decoration 에 뺀 것). "
    "Skin 이 아닌 피지크 · 점 수가 바뀐 메시는 예전처럼 가까운 뼈로 재서 장식까지 잡힐 수 있다. 표를 사람에게 보이며 "
    "「어디를 볼지 짚어 주는 표 · 숫자는 아직 정확하지 않다」고 말하고, 사람이 실제로 뚫린 프레임이라고 한 것을 그대로 전해라. "
    "calibration_failed 가 오면 점검표를 믿지 말라고 말해라. 고치는 것은 하지 않는다(사람 손 · 또는 anim_library_apply 의 보정).",
    {
        "start": {"type": "integer", "description": "볼 구간 시작(비우면 장면의 애니메이션 구간)"},
        "end": {"type": "integer", "description": "볼 구간 끝"},
        "biped": {"type": "string", "description": "바이페드 이름 접두어(기본 Bip001)"},
        "check": {"type": "boolean", "description": "true 면 맥스가 쓴 파일(가장 최근)을 읽어 점검표를 준다"},
    },
    [],
)

FIT_FIX = _tool(
    "anim_fit_fix",
    "(클로드 · 코덱스용 · 3ds Max · 시험 중) 팔 · 다리 뚫림 자동 수정: 가장 최근 anim_fit_check 읽기 결과로, 뚫린 프레임에서만 "
    "팔은 위팔을 **가장 적게** 돌려(옆 축 넷 중 고름), 다리(무릎 · 정강이 → 배 · 가슴)는 상체(Spine)를 뒤로 젖히거나 허벅지를 내려 푸는 방향을 계산하고 "
    "(몸 좌우 축으로만 돌려 다리를 옆으로 벌리지 않는다 · 두 발이 바닥이면 젖힘 15도까지 · 디딘 다리는 안 건드림) "
    "**원래 키 자리에서만** 바꾸는 스크립트를 준다(키 수 그대로 · 키 없는 뼈는 안 고침). legs=false 면 팔만. "
    "**몇 곳을 몇 도까지 바꾸는지 사람에게 말하고 「해」를 받은 뒤에만** run_line 을 보내라. "
    "되돌리기는 Ctrl+Z 한 번 또는 편집 › 가져오기. 보낸 뒤에는 anim_fit_check 로 다시 재고, 남으면 한 번 더(최대 3번 · 11-06 실측: 팔 칸 162 → 108 → 102 → 88). "
    "남은 곳(unsolved)은 사람 몫이라고 말해라. 자연스러운지는 사람이 재생해 본다.",
    {
        "max_deg": {"type": "integer", "description": "한 번에 위팔을 돌릴 최대 도(기본 45, 10~60)"},
        "legs": {"type": "boolean", "description": "다리 뚫림도 고칠까(기본 true)"},
        "biped": {"type": "string", "description": "바이페드 이름 접두어(기본 Bip001)"},
    },
    [],
)

_BLEND = {"type": "string", "description": "이 PC 의 .blend 파일 경로(원본은 덮어쓰지 않는다)"}
_ARM = {"type": "string", "description": "뼈대 오브젝트 이름(비우면 메시가 붙은 뼈대를 알아서 고른다)"}

BLENDER_CHECK = _tool(
    "anim_blender_check",
    "(클로드 · 코덱스용 · 블렌더 · 시험 중) .blend 의 동작에서 손 · 팔이 머리 · 가슴 · 배를, 무릎이 배 · 가슴을 뚫은 프레임 수와 구간 — "
    "손자리가 블렌더를 창 없이 직접 띄워 읽는다(장면을 바꾸지 않는다 · 열린 블렌더와 상관없다). 몸 크기는 쉬는 자세(rest)의 메시에서 잰다. "
    "뼈 이름은 리지파이 · DEF- · 믹사모 꼴을 알아서 맞춘다. 표는 「어디를 볼지」로 보이고, calibration_failed 가 오면 믿지 말라고 말해라.",
    {"blend": _BLEND, "armature": _ARM, "start": {"type": "integer"}, "end": {"type": "integer"}},
    ["blend"],
)

BLENDER_FIX = _tool(
    "anim_blender_fix",
    "(클로드 · 코덱스용 · 블렌더 · 시험 중) 팔 · 다리 뚫림 자동 수정: 뚫린 프레임에서만 팔은 위팔을 가장 적게 돌려, 다리는 상체를 젖히거나 허벅지를 내려 "
    "(옆으로 벌리지 않음 · 두 발이 바닥이면 젖힘 15도까지) 원래 키 자리에서만 바꾼다. "
    "손자리가 「읽기 → 계산 → 쓰기 → 다시 재기」를 최대 passes 번 돌고, **새 파일**(<이름>_sonjari_뚫림고침.blend)로 저장한다 — 원본은 그대로. "
    "**무엇을 몇 번까지 고치는지 사람에게 말하고 「해」를 받은 뒤에만** 불러라. 결과의 전후 숫자를 그대로 전하고, 남은 곳은 사람 몫이라고 말해라. "
    "고칠 뼈(위팔 · 허벅지 · 척추)에 제약(constraint)이 걸린 뼈대(컨트롤 리그가 움직이는 게임 뼈대)는 키를 써도 안 보이니 거절한다.",
    {"blend": _BLEND, "armature": _ARM, "passes": {"type": "integer", "description": "최대 몇 번 돌까(기본 3, 1~3)"},
     "max_deg": {"type": "integer", "description": "한 번에 위팔을 돌릴 최대 도(기본 45)"}},
    ["blend"],
)

BLENDER_BLOCK = _tool(
    "anim_blender_block",
    "(클로드 · 코덱스용 · 블렌더) 영상 → 블렌더 뼈대 블로킹 초안: anim_pose_sheet 가 고른 장면(poses)마다 3D 관절을 읽어 척추 · 팔 · 다리 방향을 맞춘 키를 "
    "영상 속 시각 자리에 찍고 **새 파일**(<이름>_sonjari_블로킹.blend)로 저장한다. 어느 장면을 몇 프레임에 찍는지 말하고 「해」를 받은 뒤에만 불러라. "
    "손 · 발끝 · 머리 · 몸 위치는 맞추지 않는다 — 초안이다. 결과에 facing_unsure 가 있으면 그 장면은 몸 방향이 뒤집혔을 수 있다고 사람에게 말해라.",
    {"blend": _BLEND, "armature": _ARM, "sheet": {"type": "string", "description": "anim_pose_sheet 의 sheet_id(비우면 가장 최근)"},
     "poses": {"type": "array", "items": {"type": "integer"}, "description": "쓸 장면 번호(비우면 전부)"},
     "start": {"type": "integer", "description": "첫 키 프레임(기본 1)"}, "fps": {"type": "number", "description": "기본 30"}},
    ["blend"],
)

V1_TOOLS = (LIBRARY_ADD, LIBRARY_FIND, LIBRARY_TAG, HABIT, LIBRARY_APPLY, PARTS, POSE_SHEET, VIDEO_TO_BIPED, FIT_CHECK, FIT_FIX,
            BLENDER_CHECK, BLENDER_FIX, BLENDER_BLOCK)
