"""모델에게는 셀렉터를 지어낼 자리를 주지 않는다.

`expect` 의 5종 중 넷은 **CSS 셀렉터**를 받는다. 이 저장소의 원칙은
*"모델은 셀렉터를 지어내면 안 된다 — 지어낸 셀렉터가 이틀을 태웠다"* 인데
(`_find_selector` 주석), 예측을 강제한다면서 셀렉터를 짓게 하면 그 원칙을 정면으로 깬다.

특히 `appears` 가 위험하다. 아무 셀렉터나(`"div"`) 주면 count > 0 이 되어
**거짓 성공**이 난다 — 아무 일도 안 일어났는데 "검증됨"이 찍힌다. 이건 예측 강제가
막으려던 바로 그 고장을 예측 강제가 만드는 꼴이다.

사람이 실측해서 못 박은 레시피는 그대로 쓴다(`naver_blog.json` 의
`number_increases: .save_btn__bzc5B`). 거기가 이 지식이 있어야 할 자리다.

신뢰는 **어느 문으로 들어왔는가**로 가른다 — 인자로 넘기면 호출자가 지어낼 수 있고,
실제로 `_approved` 가 그렇게 뚫려 있었다(2026-08-08 수정).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_browser_generic_control import El, Frame, Page, _worker

_SELECTOR_KINDS = ["appears", "disappears", "count_increases", "number_increases"]
_SAFE_KINDS = ["url_changes", "text_appears", "text_disappears"]


def _page_with_button() -> tuple[Page, El]:
    element = El(tag="button", text="저장")
    return Page([Frame(elements=[element], body="본문")]), element


def _ready(tmp_path: Path, page: Page):
    """`_execute` 를 태우려면 페이지를 물려줘야 한다 — 아니면 진짜 브라우저를 띄운다."""
    worker = _worker(tmp_path)
    worker._current_page = lambda: page  # type: ignore[assignment]
    worker._show_visual = lambda *a, **k: None  # type: ignore[assignment]
    worker._snapshot(page, {})
    return worker


@pytest.mark.parametrize("kind", _SELECTOR_KINDS)
def test_the_model_cannot_use_a_selector_expect(tmp_path: Path, kind: str) -> None:
    page, target = _page_with_button()
    worker = _ready(tmp_path, page)

    with pytest.raises(RuntimeError, match="expect_kind_needs_a_recipe"):
        worker._execute("browser_click", {
            "ref": target.ref, "expect": {"kind": kind, "selector": "div"},
        })


def test_the_refusal_says_what_to_use_instead(tmp_path: Path) -> None:
    """막기만 하고 대안을 안 알려 주면 모델은 셀렉터를 더 그럴듯하게 지어낸다."""
    page, target = _page_with_button()
    worker = _ready(tmp_path, page)

    with pytest.raises(RuntimeError) as caught:
        worker._execute("browser_click", {
            "ref": target.ref, "expect": {"kind": "appears", "selector": "div"},
        })

    message = str(caught.value)
    assert "url_changes" in message and "text_appears" in message
    assert "레시피" in message


@pytest.mark.parametrize("kind", _SAFE_KINDS)
def test_selector_free_expects_stay_open_to_the_model(tmp_path: Path, kind: str) -> None:
    """막느라 멀쩡한 것까지 막으면 예측 강제가 통째로 죽는다 — 반대 방향도 잠근다."""
    page, target = _page_with_button()
    worker = _ready(tmp_path, page)

    result = worker._execute("browser_click", {
        "ref": target.ref, "expect": {"kind": kind, "value": "저장되었습니다"},
        "verify_timeout_ms": 600,
    })

    assert result["action"] == "clicked"


@pytest.mark.parametrize("kind", _SELECTOR_KINDS)
def test_a_recipe_may_still_use_them(tmp_path: Path, kind: str) -> None:
    """사람이 실측해 적은 레시피는 막지 않는다 — 거기가 이 지식의 제자리다."""
    page, target = _page_with_button()
    worker = _ready(tmp_path, page)

    result = worker._execute(
        "browser_click",
        {"ref": target.ref, "expect": {"kind": kind, "selector": ".save_btn"},
         "verify_timeout_ms": 600},
        trusted=True,
    )

    assert result["action"] == "clicked"


def test_recipes_actually_go_through_the_trusted_door() -> None:
    """레시피가 평문 execute 를 쓰면 위 보장이 통째로 무의미해진다.

    naver_blog.json 의 저장 스텝이 `number_increases` 다 — 신뢰 문을 안 쓰면
    레시피 자체가 이 게이트에 걸려 죽는다.
    """
    source = (Path(__file__).resolve().parents[1] /
              "src" / "alture_jarvis" / "site_recipes.py").read_text(encoding="utf-8")

    for call in ('"browser_click", payload', '"browser_press", payload'):
        line = next(ln for ln in source.splitlines() if call in ln)
        assert "execute_trusted" in line, f"레시피의 {call} 가 신뢰 문을 안 쓴다: {line.strip()}"
    # verify 는 여러 줄 호출이라 바로 앞 줄을 본다.
    lines = source.splitlines()
    verify_at = next(i for i, line in enumerate(lines) if '"browser_verify"' in line)
    assert "execute_trusted" in lines[verify_at - 1], "레시피의 verify 가 신뢰 문을 안 쓴다"


def test_a_caller_cannot_fake_trust_through_arguments(tmp_path: Path) -> None:
    """`trusted` 는 매개변수다 — 인자로 실어 보내는 값이 아니다."""
    page, target = _page_with_button()
    worker = _ready(tmp_path, page)

    with pytest.raises(RuntimeError, match="expect_kind_needs_a_recipe"):
        worker._execute("browser_click", {
            "ref": target.ref,
            "expect": {"kind": "appears", "selector": "div"},
            "_trusted": True,
            "trusted": True,
        })
