"""스킬 온보딩 — 「주로 무엇에 쓰시나요」 분야 버튼 (W4, 2026-09-15).

## 분야는 트리거가 아니다

이 저장소는 스킬이 **있는 것**과 **닿는 것**이 다르다는 걸 비싸게 배웠다(85종이 11,043판 중 11판에 닿음).
분야 버튼은 새 트리거를 만들지 않는다. 결정론 배급(`skills.match_skills`)의 **후보 범위만 좁힌다** —
사무를 고른 사람의 「카피 써줘」에 마케팅 플레이북 28종이 줄 서지 않게, 개발자의 「계획 세워줘」가 코드 계획으로 가게.

- 고른 분야가 없으면 지금처럼 전부 후보다.
- 표에 적힌 이름 중 **실제로 내줄 수 있는 것**(라이선스·설명이 있는 것)만 보인다. 없는 이름은 조용히 빼지 않고 `missing` 에 적는다.
- 사고 틀(thinking-*)은 어느 분야에나 붙는 것이 아니다 — 「생각 정리」를 고르거나, 분야마다 몇 개만 골라 넣었다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import ui_i18n
from .skills import SKILL_TRIGGERS_EN, SKILL_TRIGGERS_KO


@dataclass(frozen=True)
class Domain:
    id: str
    label: str
    blurb: str
    skills: tuple[str, ...]


DOMAINS: tuple[Domain, ...] = (
    Domain("office", "사무·문서", "보고서·엑셀·공지문·메일 문장 다듬기", (
        "document-craft", "doc-weekly-report", "doc-proposal", "doc-meeting-minutes", "doc-official-letter",
        "doc-quotation", "doc-research-report", "doc-standard-contract", "doc-press-release",
        "internal-comms", "copy-editing", "humanizer", "brand-guidelines",
        "thinking-pre-mortem", "thinking-kepner-tregoe",
    )),
    Domain("research", "조사·리서치", "시장·경쟁사·고객 조사, 근거 있는 비교 정리", (
        "competitors", "competitor-profiling", "customer-research", "analytics", "document-craft",
        "thinking-first-principles", "thinking-probabilistic", "thinking-scientific-method",
        "thinking-steel-manning", "thinking-red-team", "thinking-map-territory",
    )),
    Domain("game", "게임 개발", "유니티 프로젝트 점검·텍스처 설정·빠진 참조 찾기", (
        "game-unity", "verification-before-completion", "systematic-debugging",
        "thinking-five-whys-plus", "document-craft",
    )),
    Domain("dev", "개발", "계획·디버깅·테스트·리뷰, 파이썬·타입스크립트·리액트", (
        "writing-plans", "executing-plans", "systematic-debugging", "test-driven-development",
        "verification-before-completion", "requesting-code-review", "receiving-code-review",
        "using-git-worktrees", "finishing-a-development-branch", "brainstorming",
        "subagent-driven-development", "dispatching-parallel-agents",
        "fastapi-python", "python", "python-testing", "testing", "typescript", "react", "playwright",
        "git-workflow", "ci-cd-best-practices", "security-best-practices", "performance-optimization",
        "logging-best-practices", "webapp-testing", "mcp-builder", "claude-api", "frontend-design",
    )),
    Domain("marketing", "마케팅·영업", "카피·광고·SEO·가격·출시·상담 자료", (
        "copywriting", "copy-editing", "cro", "seo-audit", "ai-seo", "content-strategy",
        "marketing-psychology", "offers", "pricing", "launch", "emails", "social", "ads", "ad-creative",
        "customer-research", "competitors", "competitor-profiling", "lead-magnets", "onboarding", "signup",
        "referrals", "public-relations", "marketing-plan", "marketing-ideas", "ab-testing", "analytics",
        "sales-enablement", "community-marketing", "humanizer", "brand-guidelines",
    )),
    Domain("education", "교육·학원", "학부모 안내·수강료·모집·상담·커뮤니티 홍보", (
        "internal-comms", "document-craft", "doc-syllabus", "doc-event-plan", "customer-research", "pricing", "offers", "onboarding",
        "lead-magnets", "community-marketing", "referrals", "copywriting", "marketing-plan",
        "sales-enablement", "thinking-jobs-to-be-done",
    )),
    Domain("startup", "창업·지원사업", "정부·지자체 지원사업 찾기와 신청 가능 여부 판단", (
        "startup-support-search", "business-plan", "document-craft", "thinking-pre-mortem",
    )),
    Domain("career", "취업·이직", "공고 찾기·이력서 첨삭·지원서 맞추기", (
        "career-job-search", "career-resume-review", "career-application-tailoring", "doc-resume",
        "document-craft", "copy-editing", "humanizer",
    )),
    Domain("thinking", "생각 정리·결정", "막연한 문제 쪼개기·선택지 비교·리스크 점검", (
        "thinking-bounded-rationality", "thinking-circle-of-competence", "thinking-cynefin",
        "thinking-effectuation", "thinking-first-principles", "thinking-five-whys-plus",
        "thinking-jobs-to-be-done", "thinking-kepner-tregoe", "thinking-lindy-effect",
        "thinking-map-territory", "thinking-margin-of-safety", "thinking-model-combination",
        "thinking-model-router", "thinking-ooda", "thinking-opportunity-cost", "thinking-pre-mortem",
        "thinking-probabilistic", "thinking-red-team", "thinking-reversibility",
        "thinking-scientific-method", "thinking-second-order", "thinking-socratic",
        "thinking-steel-manning", "thinking-systems", "thinking-theory-of-constraints",
        "thinking-thought-experiment", "thinking-triz", "thinking-via-negativa",
    )),
)

BY_ID: dict[str, Domain] = {domain.id: domain for domain in DOMAINS}


def allowed_skills(domain_ids: tuple[str, ...] | list[str], served: set[str]) -> set[str] | None:
    """고른 분야의 스킬 이름. 분야가 없거나 전부 모르는 이름이면 None(= 제한 없음)."""
    known = [BY_ID[item] for item in domain_ids if item in BY_ID]
    if not known:
        return None
    names = {name for domain in known for name in domain.skills}
    return names & served


def catalog(library: Any, selected: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """화면용: 분야마다 실제로 켜질 스킬(이름·한 줄)과 없는 이름."""
    served = {name: doc for name, doc in getattr(library, "skills", {}).items() if doc.served}
    # ★ 화면이 영어면 **영어 요청에 실제로 쓰는 표**를 보인다 (2026-10-17 영어 마법사 점검). 한국어 표만 보여서 영어 화면에
    #   「Attached to requests like “문서로」「보고서로」…”」가 나왔다 — 영어 요청은 `SKILL_TRIGGERS_EN` 으로 붙으니 그 낱말이
    #   약속으로 맞다. 영어 표에 없는 스킬(국내 지원사업 등)은 빈 목록 = 「이름으로 지목하면 씁니다」 — 영어 요청에서 실제로 그렇다.
    triggers = SKILL_TRIGGERS_EN if ui_i18n.lang() == "en" else SKILL_TRIGGERS_KO
    rows = []
    for domain in DOMAINS:
        present = [name for name in domain.skills if name in served]
        rows.append({
            "id": domain.id, "label": domain.label, "blurb": domain.blurb,
            "selected": domain.id in selected,
            # ★ 화면에는 영어 설명 대신 **어떤 말에 붙는지**를 보인다. 수확물 설명은 영어 트리거라 사람에게
            #   약속이 되지 못하고, 붙는 낱말은 실제 배급 규칙 그대로다(트리거가 없으면 빈 목록 = 지목해야 쓴다).
            "skills": [{"name": name, "what": served[name].headline, "triggers": list(triggers.get(name, ()))[:4]}
                       for name in present],
            "missing": [name for name in domain.skills if name not in served],
        })
    chosen = allowed_skills(tuple(selected), set(served))
    return {"domains": rows, "selected": [item for item in selected if item in BY_ID],
            "active_count": len(chosen) if chosen is not None else len(served), "total_served": len(served)}


__all__ = ["DOMAINS", "BY_ID", "allowed_skills", "catalog"]
