"""아무도 준 적 없는 숫자를 여럿 단정한 직답은 **찾아보고 다시 답한다** (2026-09-30 정직 벤치).

「업스테이지 솔라 최신 모델 이름이 뭔지 확인해서 알려줘」— 화면·MCP 둘 다 도구 0회로 「Solar Pro 4 · 512K · 입력 $0.30 ·
Solar Open 2 250B」를 단정했다. 「확인해서」를 낱말표에 넣으면 다음 낱말이 샌다. 그래서 낱말이 아니라 **숫자의 출처**로 가른다 —
MCP 의 `unsupported_numbers` 와 같은 눈금. 지난 직답 485개 중 26개(5%)가 걸린다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis import plan
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import UNSOURCED_PARTICULARS_MIN, _unsourced_particulars

SOLAR = (
    "업스테이지의 최신 모델은 **Solar Pro 4**입니다.\n\n2026년 6월경 공개된 이 모델은 512K 컨텍스트를 지원하고, "
    "API 가격은 1M 토큰당 입력 $0.30 / 출력 $1.20입니다. 오픈웨이트로는 **Solar Open 2**(250B MoE)가 있습니다."
)
ASKED = "업스테이지 솔라 최신 모델 이름이 뭔지 확인해서 알려줘"


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _Model:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {"content": self.content, "tool_calls": []}

    chat_message_stream = chat_message


def test_the_solar_draft_has_numbers_nobody_gave() -> None:
    assert len(_unsourced_particulars(SOLAR, ASKED)) >= UNSOURCED_PARTICULARS_MIN


def test_numbers_that_were_given_are_not_unsourced() -> None:
    """역방향 — 질문이나 앞 대화에 있던 숫자를 되풀이한 것은 창작이 아니다."""
    given = "512K 컨텍스트, 입력 0.30달러, 출력 1.20달러, 250B 짜리 모델이 있다고 치자. 이걸로 요약해줘"
    assert _unsourced_particulars(SOLAR, given) == []


def test_the_router_sends_it_to_look_instead_of_answering(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model(SOLAR)

    # 사슬(「확인해서 알려줘」) 없이 물어도 초안의 숫자로 잡는다 — 두 그물이 따로 선다.
    route, answer, observation = runtime._general_route("업스테이지 솔라 최신 모델 이름이 뭐야?", "s1", job_id="job-1")

    assert route == "agent" and answer == ""
    assert (observation or {}).get("route_reason") == "unsourced_particulars"


# ── 사이트를 짚어 물은 값은 숫자 하나로도 찾으러 간다 (2026-10-12) ────────────────────────
#
# 같은 대화의 둘째 질문 「아까 그거 ○○ 값도 알려줘」가 도구 0번 · 5초로 값과 순위 표를 지어냈다. 지어낸 숫자가 셋이라
# 문턱(넷)에 안 걸렸다. 표본의 가게 · 상품 · 값은 지어낸 것이고, 초안의 모양은 그 판의 답 그대로다.
PRICE_DRAFT = (
    "다나와에서 가상 게임기 2 본체의 현재 최저가는 **689,000원**입니다.\n\n"
    "| 순위 | 가격 | 배송비 |\n| --- | --- | --- |\n| 1위 | **689,000원** | 무료배송 |\n\n앞서 본 곳보다 조금 더 저렴합니다."
)


def test_a_price_made_up_for_a_named_shop_goes_to_look(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model(PRICE_DRAFT)
    assert 1 <= len(_unsourced_particulars(PRICE_DRAFT, "아까 그거 다나와 값도 알려줘")) < UNSOURCED_PARTICULARS_MIN
    route, answer, observation = runtime._general_route("아까 그거 다나와 값도 알려줘", "s1", job_id="job-shop")
    assert route == "agent" and answer == ""
    assert (observation or {}).get("route_reason") == "unsourced_particulars"


def test_the_same_draft_about_no_site_in_particular_keeps_the_old_threshold(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model(PRICE_DRAFT)
    route, _, _ = runtime._general_route("아까 그거 값 다시 말해줘", "s1", job_id="job-no-site")
    assert route != "agent", "사이트를 짚지 않은 말까지 숫자 하나로 찾으러 보내지 않는다"


def test_a_site_that_is_only_the_topic_is_still_answered_when_nothing_is_made_up(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model("다나와는 여러 가게의 값을 한데 모아 견주어 보여 주는 가격 비교 서비스입니다.")
    route, answer, _ = runtime._general_route("다나와가 어떤 서비스인지 한마디로 말해줘", "s1", job_id="job-topic")
    assert route != "agent" and "가격 비교" in answer


def test_a_number_the_person_gave_is_not_made_up_even_with_a_site() -> None:
    """사람이 준 숫자를 되받은 것은 지어낸 것이 아니다 — 사이트를 짚었어도 숫자 문은 그것을 세지 않는다."""
    assert _unsourced_particulars("말씀하신 689,000원이면 다나와에서 본 값보다 낮은 편입니다.", "다나와 689,000원이면 싼 편이야?") == []


def test_asking_for_memory_only_is_respected(tmp_path: Path) -> None:
    """「아는 대로만」이라고 했으면 사람 말이 먼저다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model(SOLAR)

    route, answer, _ = runtime._general_route("업스테이지 솔라 최신 모델 아는 대로만 알려줘", "s1", job_id="job-2")

    assert route == "answer" and answer == SOLAR


def test_a_plain_answer_with_few_numbers_stays_a_plain_answer(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model("피타고라스 정리는 직각삼각형에서 빗변의 제곱이 나머지 두 변 제곱의 합과 같다는 것입니다. 예: 3, 4, 5.")

    route, _, _ = runtime._general_route("피타고라스 정리 설명해줘", "s1", job_id="job-3")

    assert route == "answer"


def test_act_then_tell_goes_to_look_even_with_a_numberless_draft(tmp_path: Path) -> None:
    """같은 질문 두 번째 판은 「최신 모델은 Solar 3입니다」 — 숫자 하나에 **틀린 이름**. 숫자 눈금으로는 못 잡는다.
    그래서 초안이 아니라 요청의 사슬(「확인해서 알려줘」)로도 본다 — 모델을 부르기 전에 에이전트로 간다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model("업스테이지의 최신 솔라 모델은 **Solar 3**입니다.")

    route, answer, _ = runtime._general_route(ASKED, "s1", job_id="job-4")

    assert route == "agent" and answer == ""


def test_things_done_in_the_head_stay_a_plain_answer() -> None:
    from alture_jarvis.runtime import _asks_to_act_before_telling

    assert _asks_to_act_before_telling("지금 이 PC에 열려 있는 창 목록을 도구로 확인해서 알려줘")
    for prompt in (
        "이 내용 정리해서 알려줘",
        "세 줄로 요약해서 말해줘",
        "17 곱하기 23 계산해서 알려줘",
        "너의 벤치마크 성능에 대해서 얘기해줄 수 있을까?",  # 「대해서」는 조사다
        "솔라 최신 모델 아는 대로만 확인해서 알려줘",      # 사람이 기억으로만 하라고 했다
    ):
        assert not _asks_to_act_before_telling(prompt), prompt


def test_the_escalation_must_actually_look() -> None:
    """올려 보낸 판은 「근거 읽기」가 걸린다 — 안 그러면 에이전트가 또 기억으로 답한다."""
    reqs = plan.extract(ASKED, must_observe=True, observe_from={"unsourced"})
    assert any(r.kind == "observe" for r in reqs)
