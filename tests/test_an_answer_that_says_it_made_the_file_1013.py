"""「만든 파일에는 값이 있는데 답에는 없다」 경고는 답이 **그 종류의 파일을 만들었다고 끝난 말로 말하면** 울리지 않는다.

★ 2026-10-13 영상 촬영 판(27B · 창 128K · 깨끗한 가짜 홈): 가게 세 곳의 가격을 읽어 엑셀을 제대로 만들고(값 셋이 찍힌 화면과
  일치) 「…가격 · 배송비 · 가게 정보를 엑셀 파일로 정리했습니다」라고 답했는데, 그 뒤에 「만든 파일에는 값이 들어 있는데 답 본문에는
  그 값이 하나도 없습니다. 이미 한 일을 안 했다고 적었을 수 있습니다」가 붙었다. 답은 한 일을 안 했다고 한 적이 없다.
  09-28 에 넣은 면제(답이 파일 **이름**을 댄다)는 못 미쳤다 — 「만든 파일:」 줄은 이 검사 뒤에 붙고, 모델은 「엑셀 파일로」라고만 한다.

넣기 전에 운영 기록에 대 봤다(2026-10-13): 이 경고가 울린 43판 중 8판이 이 모양이고, 여덟 판 모두 제대로 말한 답이었다.
나머지 35판(코드 작업의 짧은 끝말 등)은 원인이 달라 여기서 다루지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis import runtime
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.documents import write_document


def _made(tmp_path: Path, name: str = "가격표.docx") -> list[dict]:
    path = tmp_path / name
    write_document(path, "docx", {"blocks": [
        {"type": "table", "rows": [["가게", "판매 가격", "배송비"], ["가람상회", "41,200원", "무료"], ["솔빛마켓", "39,800원", "3,000원"],
                                   ["한울몰", "44,500원", "2,500원"]]},
    ]})
    return [{"tool": "local_write_document", "ok": True, "evidence": {"output_path": str(path)}}]


@pytest.mark.parametrize("answer", [
    "브라우저를 닫았습니다. 세 가게에서 상품을 찾아 가격 · 배송비 · 가게 정보를 엑셀 파일로 정리했습니다.",
    "오늘 날짜 회의록 양식을 워드 파일로 만들었습니다.",
    "상세 분석 내용이 포함된 보고서를 아래 경로에 생성했습니다.",
    "문서가 생성되었습니다.",
])
def test_an_answer_that_says_it_made_the_file_gets_no_warning(tmp_path: Path, answer: str) -> None:
    assert BrowserAgent._artifact_answer_divergence(answer, _made(tmp_path)) == ""


@pytest.mark.parametrize("answer", [
    "검색 결과 목록이 나타나지 않았습니다. 결과를 확인하지 못했습니다.",                      # 09-07 위시켓: 이 검사가 원래 잡으려던 것
    "결과가 나타나면 바로 세 곳을 골라 엑셀 파일로 정리하겠습니다.",                            # 앞으로 하겠다는 말은 만든 것이 아니다
    "가격을 읽지 못해 엑셀 파일을 만들지 못했습니다.",                                        # 만들었다는 말과 못 했다는 말이 한 문장에
    "지금까지 읽은 근거로 최종 엑셀 파일을 만듭니다.",                                        # 끝난 말이 아니다
])
def test_an_answer_that_did_not_say_so_still_gets_the_warning(tmp_path: Path, answer: str) -> None:
    assert "값이 하나도 없습니다" in BrowserAgent._artifact_answer_divergence(answer, _made(tmp_path))


def test_the_done_wording_is_the_same_one_the_direct_answer_check_uses() -> None:
    """「끝난 말」의 모양은 한 벌이어야 한다 — 바로 답하는 길의 검사(runtime._claimed_files)와 어긋나면 한쪽만 샌다."""
    assert agent_module._SAID_IT_IS_DONE.pattern == runtime._CLAIMED_DONE.pattern
