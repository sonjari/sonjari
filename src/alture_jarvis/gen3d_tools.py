# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 OR PolyForm-Small-Business-1.0.0 (see LICENSE.md next to the gen3d / genvideo pack)
"""3D 생성 팩 도구 — `gen_3d` · `gen_3d_status` (2026-11-14 · 설계 docs/설계_생성팩_3D영상_2026-11-14.ko.md §3-1).

클로드가 지휘하고 손자리 그래픽카드가 근육이다: 클로드가 3D 친화 그림(물체 하나 · 빈 배경 · 부드러운 명암)을 이 PC 에 두고
`gen_3d` 로 맡기면 job_id 가 바로 오고, `gen_3d_status` 로 단계 · 영수증을 받는다. 큰 파일은 경로로만, 미리보기는 작은 webp.

- 팩(`gen3d`)이 꺼져 있으면 모델 목록에도 안 끼고 불러도 거절한다(영상 팩과 같은 결).
- 그림 경로는 파일 도구와 **같은 검사**(`LocalComputerTools._resolve`) — 허용 밖 · 비밀 자리는 똑같이 막힌다.
- 윈도우(CUDA) · 맥(Metal · 2026-11-14)에서 손이 있다(`tool_gateway._PLATFORM_ONLY`). 맥 실행기는 배포처가 없어 직접 빌드해 넣는다 —
  없으면 `gen_3d` 는 「not_ready: 이 맥용 실행기가 없다」로 거절한다(`Gen3DRunner.ready`).
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .blender_host import install as _blender_install
from .config import JarvisConfig
from .gen3d.print_plan import ORIENTATIONS
from .gen3d.runner import (
    DEFAULT_SIZE_MM,
    DETAILS,
    EXPORTS,
    Gen3DError,
    Gen3DRunner,
    models_ready,
)
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

PACK_ID = "gen3d"
#: 플랫폼마다 실행기 자리(`packs/gen3d/pack.json` 의 binary `dir` 과 같아야 한다 — 시험이 맞춰 본다).
BIN_DIRS = {"win32": "trellis-cpp", "darwin": "trellis-cpp-metal"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

_PRINT_PROPS: dict[str, Any] = {
    "printer": {"type": "string", "description": "뱀부 프린터 이름(예: 「Bambu Lab X2D」 · 비우면 사람이 정해 둔 「내 프린터」)"},
    "detail": {"type": "string", "enum": list(DETAILS), "description": "층 세밀도: auto(기본) · fine(곱게 · 느림) · fast(빠르게)"},
    "floor_cut_mm": {"type": "number", "description": "바닥을 이만큼(mm) 평평하게 잘라 판에 잘 닿게(0~30) — 영수증 floor_suggestion 이 제안하면, 아래가 깎인다고 말하고 쓴다"},
    "orientation": {"type": "string", "enum": list(ORIENTATIONS),
                    "description": "놓는 방향 — 영수증의 방향 제안을 사람이 받아들였을 때만 바꾼다(비우면 지금 그대로)"},
}

GEN_3D_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d",
        "description": (
            "이 PC 의 그림 한 장으로 3D 초안(GLB)을 만든다 — 손자리 그래픽카드에서 trellis.cpp(TRELLIS.2 8비트)로. "
            "바로 job_id 를 돌려주고 일은 뒤에서 돈다(512 해상도 · 12GB 카드 실측 약 1분 반~2분 반). 그다음 gen_3d_status 로 받는다. "
            "그림은 물체 하나 · 가운데 · 빈(흰) 배경 · 색면과 부드러운 명암이 좋다 — 선만 있는 낙서는 면이 비어 나온다(11-14 실측). "
            "3D 프린트할 거면 export 에 stl · 3mf 와 size_mm(긴 변)을 준다. 한 번에 하나만 돈다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "그림 파일 절대 경로(png · jpg · webp)"},
                "res": {"type": "integer", "description": "해상도 512(기본 · 빠름) 또는 1024(더 또렷 · 몇 배 오래)"},
                "model": {"type": "string", "description": "trellis(기본) 또는 pixal3d"},
                "seed": {"type": "integer", "description": "같은 결과를 다시 보고 싶을 때 씨앗 값(비우면 무작위)"},
                "gpu": {"type": "integer", "description": "그래픽카드 번호(nvidia-smi 번호 · 비우면 기본 카드 · 맥은 무시)"},
                "export": {"type": "array", "items": {"type": "string"},
                           "description": "만들 파일: glb(늘) · stl · 3mf(프린트용 · 한 색)"},
                "size_mm": {"type": "number", "description": f"프린트 크기 — 긴 변 mm(기본 {DEFAULT_SIZE_MM:g})"},
                **_PRINT_PROPS,
            },
            "required": ["image_path"],
        },
    },
}

GEN_3D_PRINT_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_print",
        "description": (
            "이미 끝난 3D 판(job_id)으로 프린트 파일만 다시 준비한다 — 다시 굽지 않는다(그래픽카드 안 씀 · 보통 1분 안팎). "
            "영수증을 보고 크기 · 프린터 · 세밀도 · 방향을 바꿔 다시 해 볼 때 쓴다: 얇은 곳(thin_share)이 있으면 size_mm 를 키우고, "
            "방향 제안을 사람이 받아들이면 orientation 을 준다. 판 폴더 안 print_v<n>/ 에 새로 쓰고 앞 판은 그대로 둔다. "
            "프린터로 보내지는 않는다 — 출력 시작은 사람이 뱀부 스튜디오에서 누른다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id(state 가 done 인 판)"},
                "size_mm": {"type": "number", "description": f"긴 변 mm(기본 {DEFAULT_SIZE_MM:g})"},
                "export": {"type": "array", "items": {"type": "string"}, "description": "stl · 3mf(기본 둘 다)"},
                **_PRINT_PROPS,
            },
            "required": ["job_id"],
        },
    },
}

GEN_3D_PREP_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_prep",
        "description": (
            "3D 로 굽기 전에 사진을 손질한다(1차 보정 · 1초 안 · 원본은 그대로). 작은 사진은 키우고(긴 변 1024), 번호 격자 그림을 준다. "
            "격자를 보고 지울 칸을 erase=[{cells: 「C3」 또는 「C3:D4」, mode: bg|fill}] 로 다시 부른다 — bg = 흰 바탕으로(딸려 온 배경 · 튀어나온 고리), "
            "fill = 주변 색으로(열쇠고리 구멍 · 반사). 11-15 실측: 넓게 메우거나(볼 네모) 전체를 펴면 오히려 얼굴이 우글거리고 작은 무늬가 사라진다 — 꼭 필요한 작은 칸만. "
            "★ 칸은 반드시 격자 그림(작은 것은 grid 를 키우고 view=「M3:Q8」 확대)을 보고 고른다 — 머릿속 계산으로 고르면 빗나간다(11-15). "
            "돌려준 before_after 로 확인하고 image(손질본)를 gen_3d 에 넣는다. 사람의 원작 그림은 손대기 전에 묻는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "원본 사진 · 그림의 절대 경로"},
                "grid": {"type": "integer", "description": "격자 칸 수(한 변 · 6~48 · 기본 16 · 같은 값으로 다시 불러야 칸 이름이 맞다)"},
                "erase": {"type": "array", "items": {"type": "object"}, "description": "지울 칸 [{cells, mode: bg|fill}]"},
                "smooth": {"type": "integer", "description": "잔무늬 펴기 세기 0~3(기본 0 · 작은 눈 · 코도 뭉개니 꼭 필요할 때만 — 점무늬는 fill 칸으로)"},
                "crop": {"type": "string", "description": "자를 칸 범위(원본 격자 기준 · 예: 「C2:N15」)"},
                "view": {"type": "string", "description": "이 칸 범위만 크게 본 격자 그림을 같이(예: 「M3:Q8」)"},
                "size": {"type": "integer", "description": "긴 변(256~2048 · 기본 1024)"},
            },
            "required": ["image_path"],
        },
    },
}

GEN_3D_VIEWS_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_views",
        "description": (
            "끝난 3D 판을 앞 · 뒤 · 왼쪽 · 오른쪽 · 위 · 아래 여섯 칸 한 장(이름표)으로 찍어 준다(1~2초). "
            "굽고 나면 반드시 이 판을 열어 원본 사진과 대조한다 — 앞 사진 한 장으로는 뒤 · 엉덩이 · 바닥이 짐작이라 엉망일 수 있다(11-15 리락쿠마). "
            "흠(점 · 열쇠고리 고리 · 볼 무늬)·딸려 온 배경 덩어리·안 보이던 쪽을 찾아 다음 칸을 정한다. "
            "source: model(구운 모양 · 색) 또는 print(다시 뜬 프린트 모양). 작아서 안 보이면 zoom 에 방향 이름(앞 · 뒤 · 왼쪽 · 오른쪽 · 위 · 아래)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id(done 인 판)"},
                "source": {"type": "string", "enum": ["model", "shape", "print", "beauty"], "description": "model(기본 · 색) · shape(구운 모양만 회색 — 판단은 이걸로) · print(다시 뜬 프린트 모양) · beauty(조명 있는 앞 · 3/4 색 렌더 두 장 — 영상 첫 장면 · 사람에게 보일 그림 · 블렌더 필요)"},
                "zoom": {"type": "string", "enum": ["앞", "뒤", "왼쪽", "오른쪽", "위", "아래"], "description": "한 방향만 크게"},
                "grid": {"type": "integer", "description": "격자 칸 수(6~32) — 깔면 「뒤 G9:J10」처럼 칸 이름으로 고칠 자리를 짚는다(사진 손질 격자와 같은 이름)"},
            },
            "required": ["job_id"],
        },
    },
}

GEN_3D_BLENDER_TOOL = {
    "type": "function",
    "function": {"name": "gen_3d_blender", "description": _blender_install.TOOL_DESC, "parameters": _blender_install.TOOL_PARAMS},
}

GEN_3D_EXPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_export",
        "description": (
            "끝난 3D 판(또는 GLB 파일)을 게임 엔진으로 내보낸다 — 블렌더(창 없이 · 보통 수 초). 판 폴더 안 export_v<n>/ 에 새로 쓴다. "
            "format=unity_fbx(기본 · 정적 메시 · 단위 FBX All · 앞 -Z 위 Y · Apply Transform · 삼각형 · 그림을 FBX 안에) · glb. "
            "메시는 물체 하나로 합치고 바닥 가운데를 원점에(origin=bottom · 소품). size_m(긴 변 미터) · max_faces(면 수 예산 · 넘으면 줄인다 — "
            "모바일 소품 5천~2만 · PC 2만~10만이 흔한 범위). 내보낸 파일을 빈 장면에 다시 불러와 잰 숫자(삼각형 · 크기 · 배율 · 축 · 재질 · 그림)와 "
            "요청과 어긋난 것(not_done)을 돌려준다. 11-18 PC: 로봇 145,200면 → 2만 FBX 3.7초(n=1). 유니티에서는 재질을 Extract 해 URP Lit 에 다시 잇는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 판(done) — 이것 또는 glb_path"},
                "glb_path": {"type": "string", "description": "판이 아닌 GLB 파일 경로"},
                "base": {"type": "string", "description": "last(기본 · 마지막 마무리 판) · original · finish_v<n>"},
                "format": {"type": "string", "enum": ["unity_fbx", "glb"]},
                "name": {"type": "string", "description": "엔진에서 쓸 이름(영문 · 숫자 · _ · 기본은 파일 이름)"},
                "size_m": {"type": "number", "description": "긴 변 미터(0.01~100) — 비우면 그대로"},
                "max_faces": {"type": "integer", "description": "면 수 예산(200~2,000,000) — 비우면 줄이지 않음"},
                "origin": {"type": "string", "enum": ["bottom", "keep"], "description": "bottom(기본 · 바닥 가운데) · keep"},
            },
        },
    },
}

GEN_3D_RENDER_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_render",
        "description": (
            "끝난 3D 판(또는 GLB 파일)을 블렌더(창 없이 · 그래픽카드 안 씀 · Cycles CPU)로 렌더한다. 판 폴더 안 render_v<n>/ 에 새로 쓴다. "
            "mode=still: 스튜디오 컷 한 장(기본 85mm) — 영상 팩 gen_video_* 의 첫 · 끝 그림 재료. "
            "mode=turntable: 한 바퀴(기본 48장 · 50mm · PNG + mp4 24fps) — 「진짜 3D 컷」 · 끝이 첫 프레임으로 이어진다. "
            "look=color(구운 색 그대로 · 색 손대지 않음) · clay(회색 형체 — 모양만 볼 때). 기본은 마지막 마무리 판(base=original 이면 구운 원본). "
            "11-18 PC 실측: 768px 한 장 약 2.6초(24샘플) — 48장 약 2분(n=1). 영수증 숫자(프레임 · 크기 · 모델이 그림에서 차지하는 몫 · 한 바퀴 이음새)는 "
            "파일을 직접 열어 잰 값이다 — 그래도 그림은 열어 보고 모양을 확인한다. 블렌더가 없으면 까닭을 돌려준다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 판(done) — 이것 또는 glb_path"},
                "glb_path": {"type": "string", "description": "판이 아닌 GLB 파일 경로(옆에 <이름>_render_v<n>/ 를 만든다)"},
                "mode": {"type": "string", "enum": ["still", "turntable"], "description": "still(기본 · 한 장) · turntable(한 바퀴)"},
                "look": {"type": "string", "enum": ["color", "clay"], "description": "color(기본) · clay(회색 형체)"},
                "base": {"type": "string", "description": "last(기본 · 마지막 마무리 판) · original · finish_v<n>"},
                "frames": {"type": "integer", "description": "한 바퀴 장 수(8~240 · 기본 48 = 24fps 2초)"},
                "width": {"type": "integer", "description": "가로(256~2048 · 기본 1024)"},
                "height": {"type": "integer", "description": "세로(256~2048 · 기본 1024) — 영상 팩에 넘길 땐 영상 크기 비율로(예 832×480)"},
                "lens": {"type": "number", "description": "렌즈 mm(18~200 · 기본 still 85 · turntable 50)"},
                "azimuth": {"type": "number", "description": "방위(도 · 0 = 앞 · 양수 = 모델 왼쪽으로) — still 기본 30"},
                "elevation": {"type": "number", "description": "카메라 높이(도) — 기본 10~12"},
                "background": {"type": "string", "description": "바탕색 #RRGGBB(기본 밝은 회백색 · 광고 컷은 #000000 등)"},
                "transparent": {"type": "boolean", "description": "바탕 투명 PNG(합성용)"},
                "engine": {"type": "string", "enum": ["cycles", "eevee"], "description": "cycles(기본 · CPU) · eevee(그래픽카드 · 조금 빠름)"},
            },
        },
    },
}

GEN_3D_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_finish",
        "description": (
            "끝난 3D 판을 블렌더(창 없이 · 그래픽카드 안 씀 · 보통 수 초)로 마무리한다. 판 폴더 안 finish_v<n>/ 에 새 GLB 를 쓰고 원본은 그대로 둔다. "
            "기본 작업은 [{op: \"smooth_surface\"}] — 모양을 지키며 겉면 펴기(8번): 굽기 뒷단계가 남기는 계단 줄무늬를 지운다(11-15 실측: "
            "30번은 입선 · 눈 새김 · 털결까지 지움 · 8번이 절충 · 두 판 그림 대조뿐). 상자 box 를 주면 그 안만. "
            "다른 작업: erase_fill · erase_part · smooth(box 필요) · drop_loose · symmetrize(keep +x|-x). "
            "돌려준 before_after 판(회색 모양 · 방향마다 왼쪽 전 · 오른쪽 후)을 반드시 열어 줄무늬가 줄었는지 · 살릴 새김이 남았는지 본다 — "
            "줄무늬를 재는 숫자는 없다. 이동량 · 부피 숫자는 영수증에서만 옮긴다. 블렌더가 없으면 까닭을 돌려준다(다른 단계는 그대로 된다). "
            "그다음 gen_3d_print 는 마지막 마무리 판을 뽑는다. 한 판에 마무리 왕복은 두 번까지, 넘으면 사람에게 묻는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id(done 인 판)"},
                "ops": {"type": "array", "items": {"type": "object"},
                        "description": "작업 목록(최대 8 · 차례대로). 예: [{op: \"smooth_surface\"}] · [{op: \"smooth_surface\", rounds: 5}]"},
                "base": {"type": "string", "description": "어디서 시작하나: last(기본 · 마지막 마무리 판 · 없으면 구운 원본) · original(구운 원본) · finish_v1 같은 판 이름"},
                "size_mm": {"type": "number", "description": f"이동량을 mm 로 적을 때 긴 변(기본 {DEFAULT_SIZE_MM:g} · 모양은 안 바뀜)"},
                "zoom": {"type": "string", "enum": ["앞", "뒤", "왼쪽", "오른쪽", "위", "아래"], "description": "그 방향 전후 한 쌍을 크게 더(잔결 보기)"},
            },
            "required": ["job_id"],
        },
    },
}

GEN_3D_SPLIT_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_split_plan",
        "description": (
            "끝난 3D 판을 조립 부품으로 나눠 뽑기 전에, 나눌 자리 후보를 손자리가 찾아 준다(그래픽카드 안 씀 · 보통 10~30초). "
            "후보마다 번호 · 종류(목 = 잘록한 곳 · 밑동 = 귀 · 팔 같은 가지가 몸에 붙는 곳 · 갈래 = 몸통에서 여러 가지로 나뉘기 바로 앞) · "
            "자르는 점 · 방향 · 단면 넓이 · 작은 쪽 부피 · 좁음(작을수록 잘록)과, 빨간 선에 번호를 그은 앞 · 옆 · 위 그림(png)을 준다. "
            "그림을 열어 보고 보기 좋은 이음매 · 색 나누기 · 받침이 줄어드는 쪽으로 골라 gen_3d_split 에 번호로 넘긴다. "
            "숫자(좌표 · 지름)를 지어내지 말고 후보 번호를 쓴다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id(done 인 판)"},
                "size_mm": {"type": "number", "description": f"뽑을 크기 — 긴 변 mm(기본 {DEFAULT_SIZE_MM:g} · 나눌 때도 같은 값)"},
                "orientation": _PRINT_PROPS["orientation"],
            },
            "required": ["job_id"],
        },
    },
}

GEN_3D_SPLIT_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_split",
        "description": (
            "끝난 3D 판을 조립 부품으로 나눠 프린트 파일을 만든다(그래픽카드 안 씀 · 모델 크기에 따라 1~5분). "
            "손자리가 계산한다: 자른 단면 한 조각만 끊어 부품을 가르고(평면이 다른 가지를 지나가도 거긴 안 자름), "
            "양쪽 부품에 핀 구멍을 뚫고 핀을 따로 만든다(벽 1.6mm 를 지키는 자리 · 지름 3~8mm · 틈은 끼움 시험으로 정한 값). "
            "부품마다 받침이 가장 적게 놓고(대개 자른 면을 판에) 판에 나눠 담아 뱀부로 썬다. "
            "영수증: 부품별 크기 · 받침 넓이(세운 채와 견줌) · 핀 · 판마다 시간 · 무게 · 조립 순서 · 조립 그림. "
            "핀 자리가 없으면 「접착」으로 물러난다고 notes 에 적는다 — 그대로 전한다. 프린터로 보내지 않는다. "
            "attach 를 주면 따로 구운 부품(예: 햄버거)을 바탕의 정한 자리에 레고처럼 끼우게 한다: 그 쪽(from)에서 밀어 처음 닿는 곳에서 "
            "depth_mm 더 밀어 바탕에 붙일 부품 모양 그대로의 홈을 파고(틈은 끼움 시험 값), 미는 방향으로 핀 하나(양쪽 구멍 + 따로 뽑는 핀). "
            "홈 아래 살이 1.6mm 보다 얇거나 · 바탕이 갈라지거나 · 다른 부품(예: 머리)에 박히면 거절하고 자리 지도 그림(mm 눈금) 경로를 준다. "
            "앉힌 부품은 색이 다를 수 있어 따로 판에 담는다. 영수증 attached: 홈 깊이 · 넓이 · 핀 · seated 그림(다 끼운 모습) · 자리 지도."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id(done 인 판)"},
                "cuts": {"type": "array", "description": "자르기 목록(최대 8). 보통 {candidate: 후보 번호, name: 「목」}. "
                         "후보 밖이면 {point:[x,y,z], normal:[x,y,z], name} — 좌표는 split_plan 의 그림 · 후보 점을 기준으로만",
                         "items": {"type": "object"}},
                "size_mm": {"type": "number", "description": f"긴 변 mm(기본 {DEFAULT_SIZE_MM:g} · split_plan 과 같아야 후보 번호가 맞다)"},
                "pin_d": {"type": "number", "description": "핀 지름 mm 를 정해 줄 때만(비우면 손자리가 단면에 맞춰 고른다)"},
                "attach": {"type": "array", "description": (
                    "따로 구운 부품 앉히기(최대 4 · cuts 를 비우고 이것만 써도 된다). 한 칸: "
                    "{job_id: 붙일 판, size_mm: 그 부품 긴 변 mm, from: top|front|back|left|right(기본 top · 앞 = -y), "
                    "at: [두 수] 또는 \"auto\" — top 이면 [x 가운데, y 가운데], front/back 이면 [x 가운데, z 바닥 높이], "
                    "left/right 면 [y 가운데, z 바닥 높이](mm · 바탕 프린트 자리 · split_plan 그림 · 자리 지도 눈금을 보고), "
                    "depth_mm: 홈 깊이(기본 2), onto: 홈을 팔 바탕 부품 번호(같은 cuts 의 앞 영수증 번호 · 다른 부품에 닿으면 거절), "
                    "pin: true|false, name}. 머리가 몸보다 큰 인형은 위에서 내리면 머리에 닿는다 — 무릎 · 배 앞은 from: front."),
                    "items": {"type": "object"}},
                **_PRINT_PROPS,
            },
            "required": ["job_id"],
        },
    },
}

GEN_3D_FIT_TEST_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_fit_test",
        "description": (
            "끼움 시험 조각을 만든다(막대 하나에 구멍 다섯 · 틈 0.10 / 0.15 / 0.20 / 0.25 / 0.30mm + 핀 하나 · 약 10분 출력). "
            "이 프린터 · 필라멘트에서 핀이 「손으로 눌러 들어가고 흔들리지 않는」 틈을 사람이 끼워 보고 고르게 한다. "
            "고른 값은 gen_3d_fit_set 으로 저장한다 — 그 뒤 나눠 뽑기의 핀 구멍이 그 값을 쓴다. 프린터로 보내지 않는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "printer": _PRINT_PROPS["printer"],
                "pin_d": {"type": "number", "description": "시험할 핀 지름 mm(기본 5)"},
            },
        },
    },
}

GEN_3D_FIT_SET_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_fit_set",
        "description": (
            "사람이 끼움 시험 조각을 끼워 보고 고른 틈(mm)을 저장한다 — 사람이 말한 값만 넣는다(짐작해 넣지 않는다). "
            "그 뒤 gen_3d_split 의 핀 구멍 지름 = 핀 지름 + 2 × 이 틈."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "clearance_mm": {"type": "number", "description": "사람이 고른 구멍의 틈(예: 0.15)"},
                "printer": _PRINT_PROPS["printer"],
                "note": {"type": "string", "description": "사람이 한 말 그대로(예: 「0.15 는 꽉 · 0.20 은 살짝 흔들」)"},
            },
            "required": ["clearance_mm"],
        },
    },
}

GEN_3D_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_check",
        "description": (
            "3D 로 보내기 전에 그림을 잰다(그래픽카드 안 씀 · 1초 안). 숫자만 돌려준다 — 물체 덩어리 수(objects) · 선만 있는 정도(line_like) · "
            "가장자리 잘림(cut_edge) · 바탕(plain/busy) · 색 수. notes 는 표시일 뿐이고 길은 네가 정한다: "
            "line_drawing 이면 색면 · 명암으로 다시 그려 넣는 쪽이 낫다(11-14 실측: 선 낙서는 선이 철사로 나옴) — 단, 사람의 원작 그림 · 사진은 묻고 나서. "
            "several_objects 면 무엇을 만들지 묻거나 하나씩. blocked 가 있으면 그 그림으로는 못 만든다. "
            "★ 명암 없는 평면 아이콘 · 클립아트 · 로고(단색 칸만)는 숫자로 안 잡힌다 — 네 눈으로 보고 3D 렌더처럼 명암 · 그림자를 넣어 다시 그려라. "
            "그대로 구우면 「흰 판에 붙은 검은 그림」이 나온다(11-17 실측 5판 · TRELLIS.2 이슈 #45)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"image_path": {"type": "string", "description": "그림 파일 절대 경로(png · jpg · webp)"}},
            "required": ["image_path"],
        },
    },
}

GEN_3D_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_3d_status",
        "description": (
            "gen_3d 로 맡긴 3D 만들기의 상태 · 영수증. state 가 running 이면 stage(몇 번째 단계 / 7 · 단계 안 비율)를 전하고 "
            "잠시 뒤 다시 부른다. done 이면 receipt 의 measured(면 수 · 크기 · 닫힌 메시 · 그래픽카드 메모리 · 걸린 초)와 "
            "files(glb · 미리보기 webp 경로)를 전한다 — 숫자는 영수증에서만 옮긴다. 모양을 봐야 하면 preview 의 webp 를 연다. "
            "printable.ok 가 false 면 why 를 그대로 전한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "gen_3d 가 돌려준 job_id"}},
            "required": ["job_id"],
        },
    },
}


def gen3d_dirs(config: JarvisConfig, platform: str | None = None) -> tuple[Path, Path]:
    """(실행기 폴더, 모델 폴더). 설정이 비면 팩이 받아 놓는 자리 — 실행기는 플랫폼마다 다른 자리(`BIN_DIRS`).

    ★ 맥에 받아진 윈도우 실행기(`trellis-cpp`)는 맥 자리(`trellis-cpp-metal`)와 섞이지 않는다 — 팩 칸이 「이 기계용 아님」으로 보인다.

    모델은 `hf include ["q8/*"]` 로 받으면 저장소 안 경로가 남아 `…/trellis2-q8/q8/*.gguf` 가 된다(서브 B · 11-14).
    그래서 그 폴더에 GGUF 가 없고 `q8/` 아래에 있으면 그쪽을 실행기 `-m` 에 넘긴다.
    """
    data = Path(config.data_dir)
    root = Path(getattr(config, "pack_files_dir", "") or data)
    folder = BIN_DIRS.get(platform or sys.platform, "trellis-cpp")

    def _pick(*parts: str) -> Path:
        # 「팩 파일 자리」에 있으면 그쪽 · 없고 옛 자리(데이터 폴더)에 있으면 옛 자리(자리를 바꿔도 다시 받지 않게 · 11-16)
        new, old = root.joinpath(*parts), data.joinpath(*parts)
        return old if root != data and not new.exists() and old.exists() else new

    bin_dir = Path(getattr(config, "gen3d_bin_dir", "") or _pick("tools", PACK_ID, folder))
    models = Path(getattr(config, "gen3d_models_dir", "") or _pick("models", PACK_ID, "trellis2-q8"))
    if models_ready(models) and not models_ready(models / "q8"):
        models = models / "q8"
    return bin_dir, models


class Gen3DTools:
    def __init__(self, config: JarvisConfig, resolve: Callable[[str], Path], packs: Any = None) -> None:
        self.config = config
        self._resolve = resolve
        self.packs = packs
        self._runner: Gen3DRunner | None = None
        #: 화면 알림 — runtime 이 `events.publish` 를 꽂는다. 없으면 알림 없이 돈다.
        self.publish: Callable[[str, dict[str, Any]], Any] | None = None
        #: 3D 판 → 그것을 부른 손자리 판(대화). 클로드가 MCP 로 바로 부르면 판이 없어 `gen3d:<번호>` 로 보낸다.
        self._owners: dict[str, str] = {}

    # ── 목록 · 등록 ─────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [GEN_3D_CHECK_TOOL, GEN_3D_BLENDER_TOOL, GEN_3D_PREP_TOOL, GEN_3D_TOOL, GEN_3D_STATUS_TOOL, GEN_3D_PRINT_TOOL,
                GEN_3D_VIEWS_TOOL, GEN_3D_FINISH_TOOL, GEN_3D_RENDER_TOOL, GEN_3D_EXPORT_TOOL, GEN_3D_SPLIT_PLAN_TOOL, GEN_3D_SPLIT_TOOL, GEN_3D_FIT_TEST_TOOL, GEN_3D_FIT_SET_TOOL]

    def enabled(self) -> bool:
        return self.packs is not None and self.packs.is_enabled(PACK_ID)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        return self.ollama_tools if self.enabled() else []

    def register(self, gateway: ToolGateway) -> None:
        for tool, risk, handler in (
            # 그래픽카드를 몇 분 쓰고 새 파일을 만든다(덮어쓰지 않는다) — 읽기만 하는 도구는 아니다.
            (GEN_3D_TOOL, RiskLevel.L1, self.gen_3d),
            (GEN_3D_STATUS_TOOL, RiskLevel.L0, self.gen_3d_status),
            (GEN_3D_CHECK_TOOL, RiskLevel.L0, self.gen_3d_check),
            # 새 프린트 파일을 판 폴더 안 새 칸(print_v<n>)에 쓴다 — 덮어쓰지 않고 프린터로 보내지도 않는다.
            (GEN_3D_PRINT_TOOL, RiskLevel.L1, self.gen_3d_print),
            # 사진 손질: 3D 폴더 안 prep/ 새 칸에 쓴다(원본은 그대로).
            (GEN_3D_PREP_TOOL, RiskLevel.L1, self.gen_3d_prep),
            # 6방향 판: 판 폴더 안 views/ 에 그림만 쓴다.
            (GEN_3D_VIEWS_TOOL, RiskLevel.L1, self.gen_3d_views),
            # 블렌더 마무리: 판 폴더 안 finish_v<n>/ 새 칸에 새 GLB · 그림(원본은 덮어쓰지 않는다).
            (GEN_3D_FINISH_TOOL, RiskLevel.L1, self.gen_3d_finish),
            # 렌더: 판 폴더 안 render_v<n>/ 새 칸에 그림 · mp4 만(원본은 그대로).
            (GEN_3D_RENDER_TOOL, RiskLevel.L1, self.gen_3d_render),
            # 내보내기: 판 폴더 안 export_v<n>/ 새 칸에 FBX · GLB(원본은 그대로).
            (GEN_3D_EXPORT_TOOL, RiskLevel.L1, self.gen_3d_export),
            # 블렌더 받기: 사람 동의(agree) 뒤에만 공식 자리에서 받아 손자리 자리에 푼다.
            (GEN_3D_BLENDER_TOOL, RiskLevel.L1, self.gen_3d_blender),
            # 나눌 자리 찾기: 판 폴더 안 새 칸에 그림만 쓴다.
            (GEN_3D_SPLIT_PLAN_TOOL, RiskLevel.L1, self.gen_3d_split_plan),
            # 나눠 뽑기 · 시험 조각: 새 칸에 새 파일 — 덮어쓰지 않고 프린터로 보내지 않는다.
            (GEN_3D_SPLIT_TOOL, RiskLevel.L1, self.gen_3d_split),
            (GEN_3D_FIT_TEST_TOOL, RiskLevel.L1, self.gen_3d_fit_test),
            # 틈 저장: 이후 나눠 뽑기의 구멍 크기를 바꾸는 설정 하나(사람이 말한 값).
            (GEN_3D_FIT_SET_TOOL, RiskLevel.L1, self.gen_3d_fit_set),
        ):
            spec = tool["function"]
            gateway.register(ToolSpec(
                name=spec["name"], description=str(spec["description"]), parameters=dict(spec["parameters"]),
                risk_level=risk, handler=handler,
                # 만들기는 어느 판(대화)에서 불렀는지 알아야 무대 알림을 그 판으로 보낸다.
                needs_job_context=spec["name"] == "gen_3d",
            ))

    @property
    def runner(self) -> Gen3DRunner:
        if self._runner is None:
            bin_dir, models = gen3d_dirs(self.config)
            out = Path(getattr(self.config, "documents_dir", None) or self.config.output_dir) / "gen3d"
            text_models = None
            # 맥: 굽기 전에 이 기기 Ollama 에 올라간 글 모델을 늘 내린다(통합 메모리 16GB 를 나눠 쓰지 않게 · swap.py).
            # 윈도우: 램이 모자랄 때만 내린다(11-17 · `pack_ram` — 27B 프롬프트 캐시가 램 24GB 를 쥐고 있던 일).
            try:
                from .gen3d.swap import LocalTextModels

                text_models = LocalTextModels()
            except Exception:  # noqa: BLE001
                text_models = None
            self._runner = Gen3DRunner(out, bin_dir, models, text_models=text_models)
            self._runner.on_change = self._emit
        return self._runner

    def _emit(self, gen_id: str) -> None:
        """`gen3d_stage` — 화면의 3D 무대(`ui/src/workspace/gen3dState.ts`)가 받는 모양으로.

        단계 안 비율은 실행기 칸 이름(`sub: {done, total}`)을 화면 칸(`part` · `parts`)으로 옮긴다. 남은 시간은 넣지 않는다.
        """
        publish = self.publish
        if publish is None or self._runner is None:
            return
        found = self._runner.get(gen_id)
        if not found:
            return
        stage = dict(found.get("stage") or {})
        sub = stage.pop("sub", None) or {}
        stage.pop("started_at", None)
        if sub.get("total"):
            stage["part"], stage["parts"] = int(sub.get("done") or 0), int(sub["total"])
        payload: dict[str, Any] = {
            "job_id": self._owners.get(gen_id) or f"gen3d:{gen_id}", "gen_id": gen_id,
            "state": found.get("state"), "res": found.get("res"), "stage": stage or None,
            "stages": found.get("stages") or [], "image": found.get("image"), "vram_mib": found.get("vram_mib"),
            "receipt": found.get("receipt"), "error": found.get("error"), "swap": found.get("swap"),
        }
        publish("gen3d_stage", {key: value for key, value in payload.items() if value is not None})

    def shutdown(self) -> None:
        if self._runner is not None:
            self._runner.shutdown()

    # ── 실행 ────────────────────────────────────────────────────────────
    def _require_enabled(self) -> None:
        if not self.enabled():
            raise PermissionError("pack_disabled: 3D 생성 팩이 꺼져 있다 — sonjari_pack_request(pack=\"gen3d\", why=…) 로 사용자에게 켜 달라고 청해라(사람이 손자리 카드에서 권한을 보고 누른다 · 설정 › 팩에서 직접 켤 수도 있다). 대신 켜지 마라.")

    def submit(self, arguments: dict[str, Any]) -> str:
        """도구 · API 가 같이 쓰는 문. 그림 경로 검사 → 실행기에 넘김 → job_id."""
        self._require_enabled()
        raw = str(arguments.get("image_path") or "").strip()
        if not raw:
            raise ValueError("image_path 가 비었다")
        image = self._resolve(raw)
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXT:
            raise ValueError(f"그림 파일이 아니다({', '.join(sorted(IMAGE_EXT))}) — {image}")
        export = arguments.get("export") or ["glb"]
        if isinstance(export, str):
            export = [export]
        unknown = [str(item) for item in export if str(item).lower() not in EXPORTS]
        if unknown:
            raise ValueError(f"export 는 {list(EXPORTS)} 가운데서 — 모르는 것: {unknown}")

        def _int(name: str) -> int | None:
            value = arguments.get(name)
            return None if value in (None, "") else int(value)

        return self.runner.submit(
            image, res=int(arguments.get("res") or 512), model=str(arguments.get("model") or "trellis"),
            seed=_int("seed"), gpu=_int("gpu"), export=[str(item).lower() for item in export],
            size_mm=float(arguments["size_mm"]) if arguments.get("size_mm") not in (None, "") else None,
            printer=str(arguments.get("printer") or "").strip() or None, detail=str(arguments.get("detail") or "auto"),
            orientation=str(arguments.get("orientation") or "").strip() or None,
            floor_cut_mm=arguments.get("floor_cut_mm"),
        )

    def gen_3d(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner = str(arguments.pop("__job_id", "") or "").strip()
        try:
            job_id = self.submit(arguments)
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        if owner:
            self._owners[job_id] = owner
            # 판 주인이 정해진 뒤 한 번 더 — 처음 알림은 주인 없이 나갔을 수 있다. 실행기와 같은 문(실패를 삼킨다)으로 보낸다.
            self.runner._notify(job_id)
        return {"ok": True, "job_id": job_id,
                "instruction": "뒤에서 돈다. gen_3d_status(job_id) 로 단계 · 영수증을 받아라 — 512 는 보통 1~3분."}

    def gen_3d_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """입력 판정의 「사실」 쪽(ADR-3D-1). 그림 경로는 만들기와 같은 검사를 지난다."""
        from .gen3d.check import check_image

        self._require_enabled()
        raw = str(arguments.get("image_path") or "").strip()
        if not raw:
            raise ValueError("image_path 가 비었다")
        image = self._resolve(raw)
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXT:
            raise ValueError(f"그림 파일이 아니다({', '.join(sorted(IMAGE_EXT))}) — {image}")
        return {"ok": True, **check_image(image)}

    def gen_3d_print(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """끝난 판으로 프린트 파일만 다시(폐루프의 싼 한 바퀴)."""
        self._require_enabled()
        job_id = str(arguments.get("job_id") or "").strip()
        export = arguments.get("export")
        if isinstance(export, str):
            export = [export]
        try:
            out = self.runner.reprint(
                job_id, size_mm=float(arguments["size_mm"]) if arguments.get("size_mm") not in (None, "") else None,
                printer=str(arguments.get("printer") or "").strip() or None, detail=str(arguments.get("detail") or "auto"),
                orientation=str(arguments.get("orientation") or "").strip() or None, export=export,
                floor_cut_mm=arguments.get("floor_cut_mm"))
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **out}

    def gen_3d_prep(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """사진 손질 — 그림 경로는 만들기와 같은 검사를 지난다."""
        self._require_enabled()
        raw = str(arguments.get("image_path") or "").strip()
        if not raw:
            raise ValueError("image_path 가 비었다")
        image = self._resolve(raw)
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXT:
            raise ValueError(f"그림 파일이 아니다({', '.join(sorted(IMAGE_EXT))}) — {image}")
        erase = arguments.get("erase") or []
        if isinstance(erase, dict):
            erase = [erase]
        return {"ok": True, **self.runner.prep(
            image, size=int(arguments.get("size") or 1024), grid=int(arguments.get("grid") or 16),
            crop=str(arguments.get("crop") or "").strip() or None, erase=list(erase),
            smooth=int(arguments["smooth"]) if arguments.get("smooth") not in (None, "") else 0,
            view=str(arguments.get("view") or "").strip() or None)}

    def gen_3d_views(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        try:
            out = self.runner.views(str(arguments.get("job_id") or "").strip(),
                                    source=str(arguments.get("source") or "model"),
                                    zoom=str(arguments.get("zoom") or "").strip() or None,
                                    grid=int(arguments.get("grid") or 0))
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **out}

    def gen_3d_finish(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        ops = arguments.get("ops") or [{"op": "smooth_surface"}]
        try:
            out = self.runner.finish(
                str(arguments.get("job_id") or "").strip(), ops,
                size_mm=float(arguments["size_mm"]) if arguments.get("size_mm") not in (None, "") else None,
                base=str(arguments.get("base") or "").strip() or None,
                zoom=str(arguments.get("zoom") or "").strip() or None)
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return out

    def gen_3d_blender(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        try:
            return _blender_install.tool(arguments)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    def gen_3d_export(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        opts: dict[str, Any] = {}
        for key, arg, cast in (("fmt", "format", str), ("name", "name", str), ("size_m", "size_m", float),
                               ("max_faces", "max_faces", int), ("origin", "origin", str)):
            value = arguments.get(arg)
            if value not in (None, ""):
                opts[key] = cast(value)
        raw_glb = str(arguments.get("glb_path") or "").strip()
        try:
            glb_path = str(self._resolve(raw_glb)) if raw_glb else None
            return self.runner.export(str(arguments.get("job_id") or "").strip() or None, glb_path=glb_path,
                                      base=str(arguments.get("base") or "last").strip() or "last", **opts)
        except (Gen3DError, ValueError, PermissionError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}

    def gen_3d_render(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        opts: dict[str, Any] = {}
        for key, cast in (("mode", str), ("look", str), ("engine", str), ("background", str), ("frames", int), ("width", int),
                          ("height", int), ("lens", float), ("azimuth", float), ("elevation", float)):
            value = arguments.get(key)
            if value not in (None, ""):
                opts[key] = cast(value)
        flag = arguments.get("transparent")
        if flag not in (None, ""):
            # 글자 "false" 를 참으로 읽지 않게(bool("false") 는 True)
            opts["transparent"] = flag if isinstance(flag, bool) else str(flag).strip().lower() in {"1", "true", "yes", "예"}
        raw_glb = str(arguments.get("glb_path") or "").strip()
        try:
            # GLB 경로는 그림 경로와 같은 검사(허용 밖 · 비밀 자리 막힘)
            glb_path = str(self._resolve(raw_glb)) if raw_glb else None
            out = self.runner.render(str(arguments.get("job_id") or "").strip() or None,
                                     glb_path=glb_path,
                                     base=str(arguments.get("base") or "last").strip() or "last", **opts)
        except (Gen3DError, ValueError, PermissionError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}
        return out

    def gen_3d_split_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        try:
            out = self.runner.split_plan(
                str(arguments.get("job_id") or "").strip(),
                size_mm=float(arguments["size_mm"]) if arguments.get("size_mm") not in (None, "") else None,
                orientation=str(arguments.get("orientation") or "").strip() or None)
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **out}

    def gen_3d_split(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        cuts = arguments.get("cuts")
        if isinstance(cuts, dict):
            cuts = [cuts]
        try:
            out = self.runner.split(
                str(arguments.get("job_id") or "").strip(), list(cuts or []),
                size_mm=float(arguments["size_mm"]) if arguments.get("size_mm") not in (None, "") else None,
                printer=str(arguments.get("printer") or "").strip() or None, detail=str(arguments.get("detail") or "auto"),
                orientation=str(arguments.get("orientation") or "").strip() or None,
                pin_d=float(arguments["pin_d"]) if arguments.get("pin_d") not in (None, "") else None,
                floor_cut_mm=arguments.get("floor_cut_mm"),
                attach=[arguments["attach"]] if isinstance(arguments.get("attach"), dict) else list(arguments.get("attach") or []))
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **out}

    def gen_3d_fit_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        try:
            out = self.runner.fit_test(
                printer=str(arguments.get("printer") or "").strip() or None,
                pin_d=float(arguments["pin_d"]) if arguments.get("pin_d") not in (None, "") else None)
        except Gen3DError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **out}

    def gen_3d_fit_set(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        if arguments.get("clearance_mm") in (None, ""):
            raise ValueError("clearance_mm 이 비었다 — 사람이 고른 틈을 넣는다")
        saved = self.runner.fit_set(float(arguments["clearance_mm"]),
                                    printer=str(arguments.get("printer") or "").strip() or None,
                                    note=str(arguments.get("note") or "")[:300])
        return {"ok": True, "saved": saved,
                "instruction": "이제 gen_3d_split 의 핀 구멍이 이 틈을 쓴다(영수증 clearance_from 에 적힌다)."}

    def gen_3d_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        job_id = str(arguments.get("job_id") or "").strip()
        found = self.runner.get(job_id)
        if found is None:
            return {"ok": False, "error": f"job_not_found: {job_id}"}
        return {"ok": True, **found}
