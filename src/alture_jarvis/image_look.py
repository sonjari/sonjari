"""이 PC 의 그림 파일을 모델이 직접 본다 — `local_view_image` (2026-11-04).

★ 까닭. 애니메이터 팩 템플릿 배치를 손자리에게 맡기며 「shots 폴더 사진을 꼭 열어 보고 판단하라」고 했는데, 손자리 답이
「이 환경에서 JPG 이미지를 시각적으로 확인할 수 없어 이름 · 태그로만 판단」이었다(잉 18개 · 11-04). 운영 모델(Swift 27B)은
눈이 달렸고 본체에도 그림을 모델에게 보이는 길(붙인 사진 · 페이지 그림 · 스캔 PDF)이 있었지만, **모델이 「이 파일을 봐라」라고
부를 도구가 없었다.** 시켜도 못 하는 일은 안내문으로 안 풀린다(사고 R) — 도구를 연다.

- 읽기만 한다(L0). 경로 검사는 파일 도구와 **같은 함수**(`LocalComputerTools._resolve`) — 허용 밖 · 비밀 자리는 똑같이 막힌다.
- 여러 장이면 2×2(최대 4장) 한 장으로 묶어 **한 번** 보인다 — 동작 사진 4장 견주기 · 부르기 횟수 절약.
- 온도 0 · 생각 끔 — 같은 그림에 같은 말. 「안 보이는 것은 지어내지 마라」.
- 그림을 못 읽는 모델이면 시도하지 않고 그렇다고 돌려준다 — 부르는 쪽(클로드)이 직접 보거나 사람에게 넘긴다.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable

from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_IMAGES = 4
MAX_BYTES = 20 * 1024 * 1024
SIDE = 1024  # 한 장일 때 긴 변 · 묶을 때 칸 하나는 그 절반

LOOK_PROMPT = (
    "아래 그림을 보고 질문에 답하라. 그림에 실제로 보이는 것만 말하고, 안 보이거나 확실하지 않은 것은 「확실하지 않음」이라고 적어라. "
    "그림이 여러 칸이면 칸마다 왼쪽 위부터 1 · 2 · 3 · 4 번이다.\n질문: "
)

VIEW_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "local_view_image",
        "description": (
            "이 PC 의 그림 파일(jpg · png · webp · bmp)을 직접 보고 질문에 답한다. 파일 이름 · 꼬리표만으로 판단하지 말고 "
            "그림 내용이 필요할 때 쓴다(예: 동작 사진이 무슨 자세인가 · 캡처 화면에 무엇이 떠 있나). 1~4장 — 여러 장이면 "
            "한 장으로 묶어 칸 번호(1~4)로 답한다. 읽기만 한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "그림 파일 절대 경로 1~4개"},
                "question": {"type": "string", "description": "그림에서 알고 싶은 것(사람 말로)"},
            },
            "required": ["paths", "question"],
        },
    },
}


def _jpeg(img: Any, side: int) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def compose(images: list[Any], side: int = SIDE) -> bytes:
    """한 장이면 그대로 줄이고, 여럿이면 2×2 칸에 붙인다(칸마다 번호)."""
    from PIL import Image, ImageDraw

    if len(images) == 1:
        return _jpeg(images[0], side)
    cell = side // 2
    sheet = Image.new("RGB", (cell * 2, cell * ((len(images) + 1) // 2)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for k, im in enumerate(images):
        im = im.convert("RGB")
        im.thumbnail((cell - 4, cell - 4))
        x, y = (k % 2) * cell, (k // 2) * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        draw.rectangle((x + 2, y + 2, x + 26, y + 26), fill=(240, 200, 40))
        draw.text((x + 9, y + 6), str(k + 1), fill=(0, 0, 0))
    return _jpeg(sheet, side)


class ImageLookTools:
    def __init__(self, resolve: Callable[[str], Path], look: Callable[[bytes, str], str],
                 cannot_see: Callable[[], bool] = lambda: False) -> None:
        self._resolve = resolve
        self._look = look
        self._cannot_see = cannot_see

    def ollama_tools(self) -> list[dict[str, Any]]:
        return [VIEW_IMAGE_TOOL]

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        """늘 같은 하나 — 목록이 판마다 바뀌면 캐시가 깨진다(10-24 사고). 카탈로그는 이것을 **속성**으로 읽는다(McpTools 와 같은 모양)."""
        return [VIEW_IMAGE_TOOL]

    def register(self, gateway: ToolGateway) -> None:
        fn = VIEW_IMAGE_TOOL["function"]
        gateway.register(ToolSpec(
            name=fn["name"], description=fn["description"], risk_level=RiskLevel.L0,
            handler=self.view, parameters=fn["parameters"],
        ))

    def view(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from PIL import Image

        raw = arguments.get("paths") or ([arguments["path"]] if arguments.get("path") else [])
        if isinstance(raw, str):
            raw = [raw]
        paths = [str(p) for p in raw if str(p).strip()]
        if not paths:
            raise ValueError("paths_required: 그림 파일 경로를 1~4개 주세요")
        if len(paths) > MAX_IMAGES:
            raise ValueError(f"too_many_images: 한 번에 {MAX_IMAGES}장까지 — 나눠서 부르세요")
        question = str(arguments.get("question") or "").strip() or "무엇이 보이나?"
        if self._cannot_see():
            return {"ok": False, "seen": False,
                    "note": "지금 손자리 모델은 그림을 못 읽는다 — 이름 · 꼬리표로 짐작하지 말고, 그림 판단이 필요하다고 그대로 돌려줘라."}
        images, used = [], []
        for raw_path in paths:
            path = self._resolve(raw_path)
            if path.suffix.lower() not in IMAGE_EXT:
                raise ValueError(f"not_an_image: {path.name} — jpg · png · webp · bmp 만")
            if path.stat().st_size > MAX_BYTES:
                raise ValueError(f"image_too_large: {path.name}")
            with Image.open(path) as im:
                im.load()
                images.append(im.copy())
            used.append(str(path))
        answer = self._look(compose(images), LOOK_PROMPT + question)
        return {"ok": True, "seen": True, "images": used, "cells": len(used) if len(used) > 1 else 0,
                "question": question, "answer": answer.strip()}
