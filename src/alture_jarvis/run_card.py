"""판 카드 — 한 판이 시작할 때 **한 번** 정해 판 내내 읽는 것 (2026-10-24 · 전략안 §55-41).

10-23 하네스 전수조사의 뿌리 ②: 판 종류 · 언어를 여러 자리에서 따로 짐작하고, 뿌리 ①: 요구의 확실성을 가르지 않았다.
이 카드는 그 둘을 담을 그릇이다. 첫 판에는 **요구 목록과 그 확실성 등급**만 채운다 — 판 종류(`work_kind`) · 언어(`language`)
칸은 자리만 있고 비어 있다(안 2 를 채울 자리 · 보고서 6절 순서 2). 빈 칸은 「모름」이라 지금처럼 다 허용한다는 뜻이다.

규칙 하나: **확실한 요구만 판 도중에 밀고, 확실한 요구만 완료를 가른다.** 흐린 요구는 판 기록에만 남는다(측정용).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .plan import GRADE_SOFT, Requirement


@dataclass(frozen=True)
class RunCard:
    #: 이 판의 요구(등급이 매겨진 것) — `plan.extract` 가 뽑고, 판 시작 때의 거르기(꺼진 팩 · 읽기 전용 · 이어받기)를 지난 것.
    requirements: tuple[Requirement, ...] = ()
    #: 판 종류 — 대화 · 웹 조사 · 내 PC · 코드 · 바깥 행위(안 2). **아직 비어 있다**: 빈 값 = 모름 = 지금처럼 다 허용.
    work_kind: str = ""
    #: 이 판의 경고 · 안내 언어(안 2). **아직 비어 있다**: 지금은 `agent.reply_language` 가 정한다.
    language: str = ""

    @classmethod
    def of(cls, requirements: list[Requirement] | tuple[Requirement, ...]) -> "RunCard":
        return cls(requirements=tuple(requirements or ()))

    def firm(self) -> list[Requirement]:
        """판 도중에 밀고 완료를 가르는 요구."""
        return [req for req in self.requirements if getattr(req, "grade", "") != GRADE_SOFT]

    def soft(self) -> list[Requirement]:
        """판 기록에만 남기는 요구 — 시키는 문장 밖에서만 나왔거나, 배운 표에서만 아는 이름이다."""
        return [req for req in self.requirements if getattr(req, "grade", "") == GRADE_SOFT]

    def summary(self) -> dict[str, Any]:
        """판 기록에 남길 한 줄 — 몇 개가 확실 · 흐림이었고 흐린 것은 어디서 섰나."""
        soft = self.soft()
        return {
            "firm": len(self.requirements) - len(soft),
            "soft": len(soft),
            "soft_origins": sorted({str(getattr(req, "origin", "") or "") for req in soft}),
            "work_kind": self.work_kind,
            "language": self.language,
        }
