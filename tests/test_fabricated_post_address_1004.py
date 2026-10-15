"""글 번호를 지어낸 주소 — 엉뚱한 글을 「열었다」고 하지 않는다 (2026-10-04 새벽, 판 df35948f).

레딧 검색 결과를 글자로만 읽은 모델이 「진짜 제목 + 지어낸 글 번호」로 주소를 조립했다. 레딧은 번호만 보고 그 번호의
글로 보낸다 — 운영 기록 1,859번의 열기 가운데 일곱 번(네 판), 여섯이 성인 게시판이었다. 사용자의 실제 크롬에 떴고,
도구는 「열었다」고 돌려줘 그 걸음이 「읽은 글」로 세어졌다.

두 겹으로 막는다:
1. 가기 **전에**: 지금 보는 목록에 같은 제목의 진짜 주소가 있으면 그걸 연다(엉뚱한 글을 한 번도 안 띄운다).
2. 간 **뒤에**: 번호는 같은데 제목이 전혀 다른 글이면 앞 페이지로 돌아가고 실패로 알린다.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from alture_jarvis.browser import ADDRESS_REPAIRED_NOTE, BrowserWorker, real_link_for, wrong_item_redirect

LOCAL = "https://www.reddit.com/r/LocalLLaMA/comments"


# --- 간 뒤: 다른 글인가 ---------------------------------------------------------

@pytest.mark.parametrize("asked, landed", [
    # 운영 기록에서 실제로 난 것(성인 게시판 이름은 지웠다 — 모양은 그대로).
    (f"{LOCAL}/1wq5x2j/who_wants_to_try_a_pi_trick_for_27b_to_reuse_prompt/",
     "https://www.reddit.com/r/SomeOtherSub/comments/1wq5x2j/an_unrelated_post_title_here/"),
    (f"{LOCAL}/1wq7k3j/come_let_your_llms_play_world_of_warcraft/",
     "https://www.reddit.com/r/Piratefolk/comments/1wq7k3j/toadgashi_dropped_a_new_banger/"),
    # 낱말 하나(`you`)가 우연히 겹쳐도 게시판이 바뀌었으면 다른 글이다.
    ("https://www.reddit.com/r/LocalLLM/comments/1wv5w0d/what_gguf_model_are_you_running_today/",
     "https://www.reddit.com/r/theescapists/comments/1wv5w0d/how_do_you_do_the_yellow_key_glitch_on_te1/"),
    # 같은 자리에서도 낱말이 하나도 안 겹치면 다른 글이다(스택오버플로 모양).
    ("https://stackoverflow.com/questions/79012345/how-to-stream-ollama-tool-calls",
     "https://stackoverflow.com/questions/79012345/centering-a-div-with-flexbox"),
])
def test_a_shared_id_with_an_unrelated_title_is_another_post(asked: str, landed: str) -> None:
    wrong = wrong_item_redirect(asked, landed)

    assert wrong is not None
    assert wrong["id"] in asked and wrong["id"] in landed


@pytest.mark.parametrize("asked, landed", [
    # 같은 글 — 꼬리가 조금 다르다(잘림·덧붙음).
    (f"{LOCAL}/1wv9rzc/qwen3827b_q4_k_m_on_one_rtx_3090_opencode/",
     f"{LOCAL}/1wv9rzc/qwen3827b_q4_k_m_on_one_rtx_3090_opencode_throughput/"),
    # 제목을 안 붙인 주소 — 주장이 없으니 판정하지 않는다(게시판만 바뀐 정상 이동일 수 있다).
    ("https://www.reddit.com/r/hermesagent/comments/1wtomu4/",
     "https://www.reddit.com/r/LocalLLM/comments/1wtomu4/how_does_training_an_llm_work_and_will_that/"),
    # 같은 자리에서 제목만 바뀜 — 고친 제목일 수 있다(운영 기록의 statista).
    ("https://www.statista.com/study/104511/digital-trends-in-finance-and-insurance/",
     "https://www.statista.com/study/104511/fintech-trends-2022/"),
    # 그대로 열림 · 다른 사이트로 감 · 번호가 없는 주소.
    (f"{LOCAL}/1wv9rzc/some_title_of_a_post/", f"{LOCAL}/1wv9rzc/some_title_of_a_post/"),
    (f"{LOCAL}/1wv9rzc/some_title_of_a_post/", "https://accounts.example.com/login/1wv9rzc/please_sign_in_first/"),
    ("https://example.com/docs/getting-started-with-tools/", "https://example.com/en/docs/install/"),
])
def test_ordinary_moves_are_left_alone(asked: str, landed: str) -> None:
    assert wrong_item_redirect(asked, landed) is None


# --- 가기 전: 목록의 진짜 주소 ---------------------------------------------------

_LIST = [
    f"{LOCAL}/1abcd9z/who_wants_to_try_a_pi_trick_for_27b_to_reuse/",
    f"{LOCAL}/1zzz111/the_fastest_inference_engine_for_rtx5090/",
    "https://www.reddit.com/r/LocalLLaMA/search/?q=parallel+slots",
    "https://www.reddit.com/r/OtherSub/comments/1qqq222/who_wants_to_try_a_pi_trick_for_27b_to_reuse/",
]


def test_a_made_up_id_is_swapped_for_the_listed_post_with_the_same_title() -> None:
    asked = f"{LOCAL}/1wq5x2j/who_wants_to_try_a_pi_trick_for_27b_to_reuse_prompt/"

    assert real_link_for(asked, _LIST) == _LIST[0]  # 다른 게시판의 같은 제목(넷째)은 고르지 않는다


def test_a_listed_id_is_never_swapped() -> None:
    """요청한 번호가 목록에 그대로 있으면 지어낸 것이 아니다 — 제목 꼬리가 달라도 손대지 않는다."""
    assert real_link_for(f"{LOCAL}/1abcd9z/who_wants_to_try_a_pi_trick/", _LIST) == ""


def test_nothing_is_swapped_when_unsure() -> None:
    # 목록에 그런 제목이 없다.
    assert real_link_for(f"{LOCAL}/1wq5x2j/come_let_your_llms_play_world_of_warcraft/", _LIST) == ""
    # 같은 제목이 둘이다 — 고르지 않는다.
    twice = [*_LIST, f"{LOCAL}/1dup333/who_wants_to_try_a_pi_trick_for_27b_to_reuse/"]
    assert real_link_for(f"{LOCAL}/1wq5x2j/who_wants_to_try_a_pi_trick_for_27b_to_reuse_prompt/", twice) == ""
    # 글 주소 모양이 아니다.
    assert real_link_for("https://www.reddit.com/r/LocalLLaMA/search/?q=parallel", _LIST) == ""
    assert real_link_for("https://example.com/docs/intro", _LIST) == ""


# --- 도구 배선 -----------------------------------------------------------------

class _Frame:
    def __init__(self, hrefs: list[str]) -> None:
        self._hrefs = hrefs

    def evaluate(self, _script: str) -> list[dict[str, str]]:
        return [{"href": href, "text": "글"} for href in self._hrefs]


class _Worker:
    def __init__(self, hrefs: list[str]) -> None:
        self._frame = _Frame(hrefs)

    def _frames_of(self, _page: Any) -> list[Any]:
        return [self._frame]

    @staticmethod
    def _validate_url(url: str) -> str:
        return url


def test_the_worker_reads_the_current_list_only_for_post_shaped_addresses() -> None:
    worker = _Worker(_LIST)
    asked = f"{LOCAL}/1wq5x2j/who_wants_to_try_a_pi_trick_for_27b_to_reuse_prompt/"

    assert BrowserWorker._listed_address_for(worker, object(), asked) == _LIST[0]  # type: ignore[arg-type]

    class _Untouched(_Worker):
        def _frames_of(self, _page: Any) -> list[Any]:
            raise AssertionError("글 주소가 아닌데 페이지를 훑었다")

    assert BrowserWorker._listed_address_for(_Untouched([]), object(), "https://example.com/pricing") == ""  # type: ignore[arg-type]


class _Page:
    def __init__(self, *, back: Any = "ok", back_raises: bool = False) -> None:
        self.calls: list[str] = []
        self._back, self._back_raises = back, back_raises

    def go_back(self, **_kwargs: Any) -> Any:
        self.calls.append("back")
        if self._back_raises:
            raise RuntimeError("no history")
        return self._back

    def goto(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(f"goto:{url}")


def test_the_wrong_page_is_not_left_on_screen() -> None:
    page = _Page()
    BrowserWorker._leave_wrong_page(page)
    assert page.calls == ["back"]

    # 돌아갈 곳이 없으면(새 탭의 첫 주소) 빈 페이지로.
    for stuck in (_Page(back=None), _Page(back_raises=True)):
        BrowserWorker._leave_wrong_page(stuck)
        assert stuck.calls == ["back", "goto:about:blank"]


def test_open_swaps_before_going_and_fails_after_landing_elsewhere() -> None:
    source = inspect.getsource(BrowserWorker._open)

    swap = source.index("self._listed_address_for(page, url)")
    go = source.index("self._goto_with_dates(page, url)")
    check = source.index("wrong_item_redirect(url,")
    visited = source.index("self._mark_visited(url)")
    assert swap < go < check < visited  # 가기 전에 바꾸고, 간 뒤 확인하고, 그다음에야 「가 본 곳」
    assert "self._leave_wrong_page(page)" in source
    assert "address_leads_to_another_post:" in source
    # 사람이 검토한 절차의 주소는 건드리지 않는다.
    assert 'repaired = "" if trusted else' in source and "wrong = None if trusted else" in source
    assert "ADDRESS_REPAIRED_NOTE" in source and "browser_links" in ADDRESS_REPAIRED_NOTE


# --- 뿌리: 사이트 기억의 안내 ----------------------------------------------------

def test_the_site_memory_no_longer_tells_the_model_to_swap_in_a_number() -> None:
    """예전 안내는 「이 모양에 번호만 바꿔 열어라」였다 — 번호를 모르는 판에는 「번호를 지어내라」가 됐다.

    레딧 글 주소(`/r/LocalLLaMA/comments/1ual8at/how_i_got…/`)가 「읽히는 주소 모양」으로 쌓여 있었고, 모델은 그 모양에
    진짜 제목과 지어낸 번호를 넣어 열었다. 모양은 알려 주되 번호는 받은 것만 넣으라고 말한다.
    """
    from alture_jarvis.site_traits import _ADVICE

    advice = _ADVICE["readable_url"].format(n=2, detail="/r/LocalLLaMA/comments/1ual8at/how_i_got_a_speedup/")

    assert "번호만 바꿔 열어라" not in advice
    assert "실제로 받은 번호만" in advice and "browser_links" in advice
    assert "/r/LocalLLaMA/comments/1ual8at/" in advice  # 모양 자체는 그대로 알려 준다


@pytest.mark.parametrize("pattern", [
    "/r/LocalLLaMA/comments/1ual8at/how_i_got_a_24x_realworld_speedup_on_a_dual_rtx/",
    "/r/LocalLLaMA/comments/1wwv0fj/i_built_ninfer_{n}_for_16gb_class_gpus/",
    "/study/{n}/digital-payment-trends-worldwide/",
])
def test_one_posts_address_is_not_a_reusable_shape(pattern: str) -> None:
    from alture_jarvis.site_traits import is_one_item_address

    assert is_one_item_address(pattern)


@pytest.mark.parametrize("pattern", [
    # 번호만 바꾸면 되는 진짜 모양 — 운영 파일에 쌓여 있는 것들.
    "/web/contents/bizpbanc-ongoing.do?pbancClssCd=PBC010&schM=view&pbancSn={n}",
    "/zf_user/jobs/relay/view?view_type=search&rec_idx={n}",
    "/experiences/{n}?adults=2",
    "/pawnee-county-kansas-farms-and-ranches-for-sale/pid/{n}",
    "/cars/audi/a4-allroad/{n}/specs-and-trims/",
    "/abs/{n}.{n}",
    "/hub/pricing",
    "/talks/vijay_kumar_robots_that_fly_and_cooperate",
    "/r/LocalLLaMA/comments/1rysvhe.json",
])
def test_real_shapes_are_kept(pattern: str) -> None:
    from alture_jarvis.site_traits import is_one_item_address

    assert not is_one_item_address(pattern)


def test_the_memory_neither_stores_nor_shows_one_posts_address(tmp_path) -> None:
    from alture_jarvis.site_traits import SiteTraits

    memory = SiteTraits(tmp_path / "traits.json")
    post = "/r/LocalLLaMA/comments/1ual8at/how_i_got_a_24x_realworld_speedup_on_a_dual_rtx/"
    memory.record("https://www.reddit.com/r/LocalLLaMA/", "readable_url", post)

    assert memory.note_for("https://www.reddit.com/r/LocalLLaMA/") == ""

    # 이미 쌓여 있던 것(옛 파일)은 지우지 않지만 알려 주지도 않는다 — 진짜 모양은 그대로 알려 준다.
    memory._data.setdefault("reddit.com", {})["readable_url"] = {"count": 2, "last": __import__("time").time(), "details": [post, "/r/LocalLLaMA/top"]}
    note = memory.note_for("https://www.reddit.com/r/LocalLLaMA/")
    assert "/r/LocalLLaMA/top" in note and "1ual8at" not in note
