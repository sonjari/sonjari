"""사람에게 묻는 카드는 「일하는 중」 **아래**, 입력칸 바로 위에 그린다 (2026-10-01 AWS, 대표).

카드를 「일하는 중」 글 위에 두었더니 모델 생각이 그 아래로 계속 흘러, 「여기서 막혔습니다」 카드가 뜬 줄도 몰랐다
(바닥 따라가기가 화면을 아래로 끌고 가 카드는 위로 밀려났다). 질문·승인·막힘 카드 셋 다 같은 자리다.
"""

from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "ui" / "src" / "WorkspaceApp.tsx"


def test_cards_come_after_the_working_message() -> None:
    source = APP.read_text(encoding="utf-8")
    # 2026-10-07: 판이 끝난 뒤에도 답이 마저 칠해지는 동안(`settlingJobId`) 같은 풍선을 쓴다 — 조건식만 넓어졌다.
    # 2026-10-09: 가운데 칸은 **이 방의 판**만 그린다(`hereJobId` — 다른 방에서 도는 맡긴 판의 생각이 사람의 대화에 흘렀다).
    working = source.index("{(streaming || thinking) && (hereJobId || settlingJobId) && (")
    for card in ("<QuestionCard", "<ApprovalCard", "<ContinuationCard"):
        assert source.index(card) > working, f"{card} 가 「일하는 중」 위에 있다 — 뜬 줄 모른다"
