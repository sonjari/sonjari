"""그림 파일 보기 도구 — 손자리에게 「사진을 보라」 해도 볼 도구가 없었다(11-04 잉 배치) (2026-11-04)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from alture_jarvis.image_look import ImageLookTools, VIEW_IMAGE_TOOL, compose


def _png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (300, 400)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _tools(tmp_path: Path, seen: list, cannot: bool = False) -> ImageLookTools:
    def resolve(raw: str) -> Path:
        p = Path(raw)
        if tmp_path not in p.parents:
            raise PermissionError("path_outside_allowed_roots")
        return p

    def look(jpeg: bytes, prompt: str) -> str:
        seen.append((Image.open(io.BytesIO(jpeg)).size, prompt))
        return "칼을 위로 든 자세"

    return ImageLookTools(resolve, look, lambda: cannot)


def test_one_image_is_shown_and_answered(tmp_path: Path) -> None:
    seen: list = []
    out = _tools(tmp_path, seen).view({"paths": [str(_png(tmp_path / "s1.jpg", (200, 10, 10)))], "question": "무슨 자세?"})
    assert out["ok"] and out["seen"] and out["answer"] == "칼을 위로 든 자세"
    assert len(seen) == 1
    assert "무슨 자세?" in seen[0][1] and "확실하지 않음" in seen[0][1]  # 안 보이면 지어내지 말라는 약속이 같이 간다


def test_several_images_go_as_one_numbered_sheet(tmp_path: Path) -> None:
    seen: list = []
    paths = [str(_png(tmp_path / f"s{k}.png", (k * 60, 50, 50))) for k in range(4)]
    out = _tools(tmp_path, seen).view({"paths": paths, "question": "넷의 차이?"})
    assert len(seen) == 1  # 한 번만 부른다
    assert out["cells"] == 4 and seen[0][0][0] <= 1024
    sheet = Image.open(io.BytesIO(compose([Image.new("RGB", (100, 100))] * 3)))
    assert sheet.size[0] == 1024 and sheet.size[1] == 1024  # 3장이면 2×2 중 아래 한 칸 빔


def test_refuses_outside_paths_non_images_and_too_many(tmp_path: Path) -> None:
    tools = _tools(tmp_path, [])
    with pytest.raises(PermissionError):
        tools.view({"paths": [r"C:\Windows\win.ini"], "question": "?"})
    note = tmp_path / "note.txt"
    note.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not_an_image"):
        tools.view({"paths": [str(note)], "question": "?"})
    with pytest.raises(ValueError, match="too_many_images"):
        tools.view({"paths": [str(note)] * 5, "question": "?"})


def test_a_model_that_cannot_see_says_so_instead_of_guessing(tmp_path: Path) -> None:
    seen: list = []
    out = _tools(tmp_path, seen, cannot=True).view({"paths": [str(_png(tmp_path / "a.png", (1, 2, 3)))], "question": "?"})
    assert out["ok"] is False and out["seen"] is False and "짐작하지" in out["note"]
    assert seen == []


def test_the_model_list_is_always_the_same_one_tool() -> None:
    tools = ImageLookTools(lambda r: Path(r), lambda j, p: "")
    # 카탈로그는 active_ollama_tools 를 속성으로 · ollama_tools 를 함수로 읽는다(McpTools 와 같은 모양 — 11-04 회귀가 잡음)
    assert tools.active_ollama_tools == [VIEW_IMAGE_TOOL] == tools.ollama_tools()
