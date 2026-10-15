"""스킬 온보딩 분야 (W4) — 분야는 후보만 좁히고, 표의 이름은 실제 수확물에 있다."""

from __future__ import annotations

from _harvest import needs_harvest
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.skill_domains import DOMAINS, allowed_skills, catalog
from alture_jarvis.skills import SKILL_TRIGGERS_KO, SkillLibrary, match_skills

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def library() -> SkillLibrary:
    # 팩 스킬(게임 팩의 game-unity 등)도 표에 이름이 오르므로 **모든 팩**의 스킬 폴더를 같이 읽는다(2026-09-27 팩 0판).
    pack_dirs = sorted(REPO.glob("packs/*/skills"))
    lib = SkillLibrary(JarvisConfig(runtime_root=REPO, skills_dir=REPO / "skills"), extra_dirs=lambda: pack_dirs)
    if not lib.skills:
        pytest.skip("스킬 수확물이 없는 체크아웃")
    return lib


@needs_harvest
def test_every_domain_name_is_a_real_served_skill(library: SkillLibrary) -> None:
    """지어낸 이름이 있으면 그 분야를 골라도 조용히 아무것도 안 붙는다."""
    view = catalog(library, [])
    for row in view["domains"]:
        assert row["missing"] == [], (row["id"], row["missing"])
        assert row["skills"], row["id"]


def test_no_domain_means_no_restriction() -> None:
    assert allowed_skills((), {"a", "b"}) is None
    assert allowed_skills(("unknown",), {"a"}) is None


def test_domain_narrows_candidates_but_does_not_invent_matches(library: SkillLibrary) -> None:
    served = {name for name, doc in library.skills.items() if doc.served}
    prompt = "학원 홍보 카피 문구 써줘"
    everything = match_skills(prompt, available=served)
    assert everything and everything[0][0] == "copywriting"
    career = allowed_skills(("career",), served)
    assert match_skills(prompt, available=career) == []  # 취업만 고른 사람에겐 카피 플레이북이 줄 서지 않는다
    marketing = allowed_skills(("marketing",), served)
    assert match_skills(prompt, available=marketing)[0][0] == "copywriting"
    # 분야를 골라도 트리거·동사가 없으면 안 연다 — 분야는 트리거가 아니다.
    assert match_skills("안녕 오늘 날씨 어때", available=marketing) == []


@needs_harvest
def test_multiple_domains_union(library: SkillLibrary) -> None:
    served = {name for name, doc in library.skills.items() if doc.served}
    both = allowed_skills(("career", "dev"), served)
    assert "career-resume-review" in both and "systematic-debugging" in both and "copywriting" not in both


def test_domain_skills_that_have_no_korean_trigger_are_listed_for_the_reach_report() -> None:
    """트리거가 없는 스킬은 분야를 골라도 결정론으로는 안 닿는다 — 그 수를 숨기지 않는다."""
    untriggered = {name for domain in DOMAINS for name in domain.skills if name not in SKILL_TRIGGERS_KO}
    # 이 목록이 늘면 분야 버튼이 「켰는데 안 붙는」 스킬을 더 품게 된다. 알고 늘린다.
    assert untriggered <= {"python", "testing", "brand-guidelines", "discernment-nudge"}, sorted(untriggered)
