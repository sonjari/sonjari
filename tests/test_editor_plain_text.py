"""리치 에디터에는 마크다운이 없다. 넣기 전에 평문으로 바꾼다.

2026-08-05 사용자님 블로그 화면 실물: `### ② 입시/진로 전략`, `- **타겟:**` 이 글자
그대로 찍혔다. 스마트에디터는 마크다운을 해석하지 않는다.

같은 화면에서 더 나쁜 것도 나왔다 — **문단 순서가 뒤섞였다.** 보낸 원문은
`## 1 → ## 2 → ① ② ③ → ## 3` 로 멀쩡했는데(external_actions 에 남은 979자로 확인),
화면에서는 `## 2` 절이 맨 뒤로 가고 한 줄이 중간에서 잘려 앞쪽에 붙어 있었다.
줄머리의 `- `/`1. ` 이 자동 목록 변환을 깨우고, 그 변환이 DOM 을 다시 그리는 사이에도
타이핑이 계속 들어간 것으로 보인다. 기호를 걷어내면 그 방아쇠도 함께 사라진다.
"""

from __future__ import annotations

from alture_jarvis.browser import markdown_to_editor_text


def test_headings_lose_their_hashes_but_keep_their_words() -> None:
    assert markdown_to_editor_text("## 2. 핵심 포지셔닝 전략") == "2. 핵심 포지셔닝 전략"
    assert markdown_to_editor_text("### ① 운영 효율화") == "① 운영 효율화"


def test_bold_markers_go_away() -> None:
    assert markdown_to_editor_text("- **타겟:** 중소형 학원 원장님") == "· 타겟: 중소형 학원 원장님"


def test_bullets_become_a_character_the_editor_will_not_reformat() -> None:
    # `- ` 로 시작하는 줄이 자동 목록 변환을 깨운다. `·` 는 그냥 글자다.
    assert markdown_to_editor_text("- 첫째\n- 둘째") == "· 첫째\n· 둘째"


def test_numbered_lists_too() -> None:
    assert markdown_to_editor_text("1. Phase 1\n2. Phase 2") == "1) Phase 1\n2) Phase 2"


def test_links_keep_the_address_visible() -> None:
    # 블로그 글에서 주소가 사라지면 근거가 사라진다.
    assert markdown_to_editor_text("[로보메타핏](https://robometafit.com)") == "로보메타핏 (https://robometafit.com)"


def test_fences_and_rules_disappear() -> None:
    assert markdown_to_editor_text("```python\n") == ""
    assert markdown_to_editor_text("---") == ""


def test_ordinary_korean_prose_is_untouched() -> None:
    line = "RoboMetaFit은 '학생의 학습 파편'을 입시 역량으로 치환합니다. 1등급, 2*3 같은 것도 그대로."
    assert markdown_to_editor_text(line) == line


def test_the_real_post_comes_out_clean() -> None:
    """사용자님 화면에 찍혔던 그 글 그대로."""
    source = (
        "# [RoboMetaFit 전략] AI SaaS 시장에서의 3가지 핵심 포지셔닝 제안\n"
        "\n"
        "## 1. 개요\n"
        "RoboMetaFit은 'AI 에이전트'를 지향합니다.\n"
        "\n"
        "### ① 운영 효율화: Admin Agent (학원 운영 자동화)\n"
        "- **타겟:** 행정 업무 부담이 큰 중소형 학원 원장님\n"
        "\n"
        "## 3. 실행 로드맵 (Roadmap)\n"
        "1. **Phase 1 (Quick Win):** 빠른 시장 진입.\n"
    )

    plain = markdown_to_editor_text(source)

    assert "#" not in plain
    assert "**" not in plain
    for line in plain.splitlines():
        assert not line.startswith("- "), "자동 목록 변환을 깨우는 줄머리가 남았다"
    # 순서는 원문 그대로여야 한다 — 뒤섞인 것은 편집기였지 이 변환이 아니다.
    assert plain.index("1. 개요") < plain.index("① 운영 효율화") < plain.index("3. 실행 로드맵")
