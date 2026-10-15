"""문서 도구가 **제대로 만든 것을 틀렸다고 말하면 안 된다** (2026-09-21 실전).

## 무슨 일이 있었나

「깃허브 오픈소스 10개 찾아서 문서로」 판에서 모델이 `text` 로 마크다운을 통째로
줬다. 파일은 **완벽하게** 나왔다 — 제목 `#` 도, 표도, 빈 줄까지 정확했다.
그런데 도구가 세 가지를 말했다:

    shape_notes: ["제목이 없다 — 첫 블록을 …", "글 한 덩어리로 저장했다 — blocks 로 …"]
    preview:     빈 줄이 다 빠져 표가 뭉개져 보임

셋 다 거짓이었다. 모델은 안내를 믿고 `blocks` 로 바꿨다가, 미리보기에서 표가
안 서 보이니 다시 `text` 로 돌아오기를 **여섯 번** 되풀이하며 10분을 태웠다.
산출물 파일만 6개가 쌓였다.

## 왜 이 시험이 필요한가

`_shape_notes` 가 제목을 **`blocks` 에서만** 찾았다. `text` 로 온 마크다운은
쳐다보지도 않으니, 제목이 있든 없든 언제나 「없다」였다.

이 저장소가 아는 병이다 — **눈금을 먼저 의심한다.** 그리고 사고 S: 재는 자에도
같은 병이 있다. 안내문이 틀리면 모델은 맞는 답을 버리고 틀린 쪽으로 간다.
「막기만 하면 같은 벽에 부딪친다」보다 나쁘다 — **벽이 아닌 곳을 벽이라고 한 것**이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.documents import write_document

#: 실전에서 모델이 보낸 것과 같은 모양 — 제목·문단·절·표가 다 든 마크다운 한 덩어리.
GOOD_MARKDOWN = """# 온텔릭 오픈소스 2026

이 PC 에서 바로 쓸 만한 것만 골랐습니다.

## 고른 것

| 순위 | 이름 | 왜 좋은가 |
| --- | --- | --- |
| 1 | Serena | LSP 로 심볼 단위 수정 |
| 2 | Probe | 토큰 예산을 지켜 함수만 꺼냄 |

## 남은 것

- 격리 실행
- 도구 검색
"""


def _write(tmp_path: Path, payload: dict) -> dict:
    return write_document(tmp_path / "out.md", "md", payload)


# ── ① 제목이 있는데 없다고 하면 안 된다 ──────────────────────────────────────
def test_a_markdown_title_in_text_is_seen(tmp_path: Path) -> None:
    result = _write(tmp_path, {"text": GOOD_MARKDOWN})
    notes = " ".join(result.get("shape_notes", []))
    assert "제목이 없다" not in notes, f"제목이 있는데 없다고 했다: {result.get('shape_notes')}"


def test_structured_markdown_is_not_called_one_lump(tmp_path: Path) -> None:
    result = _write(tmp_path, {"text": GOOD_MARKDOWN})
    notes = " ".join(result.get("shape_notes", []))
    assert "한 덩어리" not in notes, f"제목·표가 다 있는데 덩어리라고 했다: {result.get('shape_notes')}"


def test_a_good_markdown_document_gets_no_complaint_at_all(tmp_path: Path) -> None:
    """★ 이것이 진짜 잰 것 — 제대로 낸 판에 지적이 하나도 없어야 고리가 안 생긴다."""
    result = _write(tmp_path, {"text": GOOD_MARKDOWN})
    assert result.get("shape_notes", []) == [], result.get("shape_notes")


# ── ② 진짜 없을 때는 여전히 말해야 한다 ─────────────────────────────────────
def test_text_without_a_title_still_says_so(tmp_path: Path) -> None:
    """고친 뒤에도 **진짜 빠진 것**은 짚어야 한다 — 안 그러면 반대쪽으로 고장 난다."""
    result = _write(tmp_path, {"text": "그냥 한 줄짜리 메모입니다."})
    assert any("제목이 없다" in note for note in result.get("shape_notes", []))


def test_blocks_without_a_heading_still_says_so(tmp_path: Path) -> None:
    result = _write(tmp_path, {"blocks": [{"type": "paragraph", "text": "제목 없이 문단만"}]})
    assert any("제목이 없다" in note for note in result.get("shape_notes", []))


# ── ③ 미리보기가 표를 뭉개 보이면 모델이 다시 쓴다 ───────────────────────────
def test_the_preview_keeps_the_table_readable(tmp_path: Path) -> None:
    """모델은 미리보기를 보고 「표가 안 섰다」고 판단해 여섯 번 다시 썼다."""
    result = _write(tmp_path, {"text": GOOD_MARKDOWN})
    preview = result["preview"]
    assert "| 순위 | 이름 | 왜 좋은가 |" in preview
    # 마크다운에서 표는 **앞에 빈 줄이 있어야** 표로 선다. 미리보기가 그걸 지워
    # 버리면 사람도 모델도 「뭉쳤다」고 읽는다.
    head = preview.index("| 순위")
    assert preview[:head].rstrip(" ").endswith("\n\n"), "표 앞 빈 줄이 사라져 뭉쳐 보인다"


# ── ④ 파일 자체는 원래도 멀쩡했다 — 그 사실을 못 박아 둔다 ───────────────────
def test_the_file_itself_was_always_fine(tmp_path: Path) -> None:
    _write(tmp_path, {"text": GOOD_MARKDOWN})
    written = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert written.startswith("# 온텔릭 오픈소스 2026")
    assert "| --- | --- | --- |" in written
    assert "\n\n| 순위" in written, "표 앞 빈 줄이 파일에서도 빠지면 진짜로 안 선다"


@pytest.mark.parametrize("fmt", ["docx", "hwpx"])
def test_other_shaped_formats_see_the_title_too(tmp_path: Path, fmt: str) -> None:
    """워드·한글도 같은 안내를 쓴다 — 한 형식만 고치면 나머지가 계속 거짓말한다."""
    result = write_document(tmp_path / f"out.{fmt}", fmt, {"text": GOOD_MARKDOWN})
    notes = " ".join(result.get("shape_notes", []))
    assert "제목이 없다" not in notes, notes
