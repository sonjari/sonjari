"""정찰기는 **경고를 지울 수만 있고**, 지우려면 원문을 내야 한다.

근거 대조는 문자열 포함으로 이름을 찾는다. 대부분 맞지만 같은 곳을 다르게 적으면
헛경고가 난다 — 「(주)미르」와 「미르테크놀로지」.

그 자리에 3060의 작은 모델을 쓴다. 다만 **판정을 시키지 않는다.**

    코드    「없다」고 나온 이름만 넘긴다
    정찰기  그 이름이 나오는 **본문 문장을 그대로** 옮겨 적는다
    코드    그 문장이 본문에 글자 그대로 있는지 확인한다      ← 여기가 전부다
            없으면 정찰기 답을 버린다. 경고는 그대로 선다.

그래서 정찰기가 지어내도 아무 일도 일어나지 않는다. 이 저장소가 여러 번 배운
「모델은 읽고 판정은 코드가」이고, 작업계약의 「원문 span 없는 소유권은 안 받는다」와
같은 불변식이다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.grounding_scout import confirm_names

#: ★ 결정론 대조가 **놓치는 모양**이다. `_ENTITY_NOISE` 는 괄호·공백만 지우기
#: 때문에 가운뎃점이 낀 「미르·테크놀로지」를 「미르테크놀로지」와 같은 곳으로 못 본다.
#: 이 층이 메우는 자리가 정확히 거기다 — 그 밖의 경우엔 코드가 이미 맞힌다.
BODY = (
    "미르·테크놀로지 채용 공고입니다. 연구비 관리 담당자를 모집합니다.\n"
    "코드나루은 별도 공고를 냈습니다."
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"content": json.dumps(self._payload, ensure_ascii=False)}}


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def post(self, url: str, json: dict) -> _FakeResponse:  # noqa: A002
        self.calls += 1
        return _FakeResponse(self.payload)

    def close(self) -> None:
        return None


def _config(*, enabled: bool = True, tmp: Path | None = None) -> JarvisConfig:
    root = tmp or Path(".")
    return JarvisConfig(
        runtime_root=root,
        data_dir=root / "d",
        output_dir=root / "o",
        documents_dir=root / "docs",
        code_scout_enabled=enabled,
    )


def test_a_real_quote_erases_the_warning(tmp_path: Path) -> None:
    """헛경고를 지우는 것이 이 층의 유일한 일이다."""
    client = _FakeClient(
        {"found": [{"name": "미르테크놀로지", "quote": "미르·테크놀로지 채용 공고입니다."}]}
    )
    found = confirm_names(
        ["미르테크놀로지"], BODY, config=_config(tmp=tmp_path), client=client
    )

    assert found == {"미르테크놀로지": "미르·테크놀로지 채용 공고입니다."}


def test_an_invented_quote_is_thrown_away(tmp_path: Path) -> None:
    """★ 이게 전부다. 지어낸 근거로는 경고를 못 지운다."""
    client = _FakeClient(
        {"found": [{"name": "바름터", "quote": "바름터 채용 공고입니다."}]}
    )
    found = confirm_names(["바름터"], BODY, config=_config(tmp=tmp_path), client=client)

    assert found == {}, "본문에 없는 문장을 인용했는데 경고가 지워졌다"


def test_a_quote_that_exists_but_does_not_carry_the_name_is_rejected(tmp_path: Path) -> None:
    """인용만 진짜고 이름은 딴 데서 온 경우를 막는다."""
    client = _FakeClient(
        {"found": [{"name": "바름터", "quote": "코드나루은 별도 공고를 냈습니다."}]}
    )
    found = confirm_names(["바름터"], BODY, config=_config(tmp=tmp_path), client=client)

    assert found == {}


def test_a_name_that_was_never_asked_about_cannot_sneak_in(tmp_path: Path) -> None:
    """정찰기는 **주어진 이름만** 다룬다. 새 주장을 보태지 못한다."""
    client = _FakeClient(
        {"found": [{"name": "코드나루", "quote": "코드나루은 별도 공고를 냈습니다."}]}
    )
    found = confirm_names(
        ["미르테크놀로지"], BODY, config=_config(tmp=tmp_path), client=client
    )

    assert found == {}


def test_a_too_short_quote_is_not_evidence(tmp_path: Path) -> None:
    """「아」 한 글자가 본문에 있다고 근거가 되지는 않는다."""
    client = _FakeClient({"found": [{"name": "미르", "quote": "미르"}]})

    assert confirm_names(["미르"], BODY, config=_config(tmp=tmp_path), client=client) == {}


def test_it_stays_quiet_when_the_scout_is_off(tmp_path: Path) -> None:
    """꺼져 있으면 부르지도 않는다 — 안 뜬 서버를 기다리며 판을 늦추지 않는다."""
    client = _FakeClient({"found": [{"name": "미르테크놀로지", "quote": "미르·테크놀로지 채용 공고입니다."}]})
    found = confirm_names(
        ["미르테크놀로지"], BODY, config=_config(enabled=False, tmp=tmp_path), client=client
    )

    assert found == {} and client.calls == 0


def test_a_dead_scout_leaves_the_warning_standing(tmp_path: Path) -> None:
    """미기동·시간초과·깨진 응답 — 전부 빈 결과다. 안전한 쪽으로 넘어진다."""

    class _Broken:
        def post(self, url: str, json: dict):  # noqa: A002
            raise ConnectionError("11435 응답 없음")

        def close(self) -> None:
            return None

    assert confirm_names(["미르"], BODY, config=_config(tmp=tmp_path), client=_Broken()) == {}


def test_the_check_only_ever_shrinks_the_warning() -> None:
    """★ 배선이 뒤집히면 정찰기가 **경고를 만들 수** 있게 된다. 그건 안 된다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    answer = "- **미르테크놀로지**\n- **바름터**\n"
    messages = [{"role": "tool", "tool_name": "browser_extract", "content": BODY}]

    without = BrowserAgent._listed_entity_grounding_check(answer, messages)
    assert "바름터" in without and "미르테크놀로지" in without

    with_scout = BrowserAgent._listed_entity_grounding_check(
        answer,
        messages,
        None,
        None,
        lambda names, body: {"미르테크놀로지": "미르·테크놀로지 채용 공고입니다."},
    )
    assert "바름터" in with_scout, "진짜 미확인은 남아야 한다"
    assert "미르테크놀로지" not in with_scout, "확인된 것은 지워져야 한다"


def test_the_agent_hands_the_confirmer_in() -> None:
    """배선이 빠지면 이 층이 죽은 코드가 된다."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert "scout_confirm_names(names, body, config=self.config)" in source
    assert source.count("confirm_names(missing, source)") == 1


def test_a_dead_scout_is_not_knocked_on_over_and_over(tmp_path: Path) -> None:
    """★ 실측: 안 떠 있으면 한 번에 2.18초를 버린다. 근거 대조는 판마다 최대 네 번
    불리므로 그냥 두면 죽은 판마다 9초를 잃는다. 첫 실패 뒤에는 건너뛴다."""
    from alture_jarvis import grounding_scout  # noqa: PLC0415

    class _Broken:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, url: str, json: dict):  # noqa: A002
            self.calls += 1
            raise ConnectionError("11435 응답 없음")

        def close(self) -> None:
            return None

    grounding_scout.reset_breaker()
    client = _Broken()
    config = _config(tmp=tmp_path)
    for _ in range(4):
        assert confirm_names(["미르"], BODY, config=config, client=client) == {}

    assert client.calls == 1, "죽은 것을 네 번 두드렸다"
    grounding_scout.reset_breaker()


def test_the_scout_leaves_a_trace_or_nobody_can_measure_it() -> None:
    """★ 안 남기면 이 층이 실제로 도는지 아무도 못 잰다.

    되받기(`plan_pushbacks`)와 대신 읽기(`forced_reads`)가 그래서 한동안 안 보였다.
    물은 개수·확인한 개수·걸린 시간을 남긴다 — 그래야 「헛경고가 줄었나」를 잰다.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert '"agent_grounding_scout"' in source
    for key in ('"asked"', '"confirmed"', '"took_ms"'):
        assert key in source, key
