"""굵은 이름 뒤에 같은 줄로 값이 오는 꼴도 「이름 붙은 자리」다 (2026-10-24 Flint 조사 판 d0e5fd4c).

답에 다섯 칸이 다 있었는데 영수증이 「필요한 것 6개 · 채움 2 · 확인 못 함 4」였다 — 「**④ 라이선스** — Apache 2.0」처럼
굵은 이름 뒤에 값이 이어지는 줄을 제목으로도 「이름: 값」으로도 못 읽었다. 같은 줄의 「확인 못 함」은 채움이 아니라 빈 자리다.
"""
from __future__ import annotations

from alture_jarvis.outbound import check_needs

FLINT_ANSWER = """**Recursive Flint 모델 성능 조사**

**① 벤치마크 점수** (unsloth 가이드의 공식 비교표, 0~100)

| 모델 | Terminal-Bench 2.1 | IFEval |
|---|---|---|
| **Flint BF16** | **54.9** | **95.1** |

**② 필요 메모리 · 속도 · GPU**
- 양자화별: 2-bit 11.9GB / 3-bit 18.5GB

**③ 한국어 지원** — 확인 못 함. 공식·사용자 자료 어디에도 명시 없음.

**④ 라이선스** — Apache 2.0 (호스팅 API 약관은 별도)

**⑤ 사용자 평가** — 극명하게 갈림
- **긍정**: 도구 호출 잘됨
"""


def _met(needs: list[str], answer: str) -> dict[str, object]:
    return {item["label"]: item["met"] for item in check_needs(needs, answer)}


def test_bold_names_with_the_value_on_the_same_line_are_found() -> None:
    got = _met(["벤치마크 점수", "필요 메모리", "속도", "한국어 지원", "라이선스", "사용자 평가"], FLINT_ANSWER)
    assert got == {"벤치마크 점수": True, "필요 메모리": True, "속도": True,
                   "한국어 지원": False, "라이선스": True, "사용자 평가": True}


def test_a_bold_name_with_only_a_note_takes_the_lines_below() -> None:
    answer = "**① 벤치마크 점수** (공식 표)\n\n| 모델 | 점수 |\n|---|---|\n| Flint | 54.9 |\n\n**② 라이선스**"
    assert _met(["벤치마크 점수"], answer) == {"벤치마크 점수": True}


def test_a_bold_name_that_is_not_the_need_does_not_fill_it() -> None:
    assert _met(["라이선스"], "**② 필요 메모리** — 18.5GB\n본문에 라이선스 이야기는 없다") == {"라이선스": None}
