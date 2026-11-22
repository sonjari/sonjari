"""범위로 말한 개수(「5~10개」 · 「두세 개 더」)도 개수 요구다 · 개수를 못 채웠으면 쓸 차례를 미룬다 (2026-11-16 맥 판 3655b7e4 · e44e4720).

두 판 다 계획에 개수 요구가 없었다(「주소 읽기」 · 「산출물 파일」뿐). 몇 개를 읽든 「읽기 끝」 → 파일 차례가 다른 후보 열기를
`not_this_stage` 로 두 번 막았고, 도구 목록이 107 → 14 로 좁혀져 Strata 가 앞부분 3.1만 토큰을 다시 읽었다(20초씩 두 번).
좁히기 자체(10-03 · `_offered_and_allowed`)는 그대로 두고 뿌리 둘을 고친다:
  (1) 개수 인식 — 범위 수 토큰 · 찾는 말에 붙은 개수 · 「로컬 PC에서 돌릴」의 PC · 「N개 더」 + 적어 준 주소의 합.
  (2) 개수 칸이 안 찼으면 `_artifact_turn_is_due` 가 쓸 차례를 걸지 않는다(접기 전 차례는 그대로).
"""
from __future__ import annotations

import inspect

import pytest

from alture_jarvis import plan
from alture_jarvis.answer_gate import named_sources
from alture_jarvis.plan_nudges import count_reads_owed
from alture_jarvis.tool_roster import _artifact_turn_is_due

# 맥 운영 판 3655b7e4 의 과제 글 그대로(돌려받을 항목 줄은 MCP 문이 붙인 것).
TASK_3655 = (
    "로컬 PC에서 돌릴 수 있는 공개 가중치 영상 생성 모델(글→영상 · 그림→영상)을 2026년 기준으로 조사해 엑셀 표로 정리해 줘. "
    "이미 검토한 Wan2.2-TI2V-5B · LTX-2.5 · MiniMax-H3 · HunyuanVideo · Wan2.2-Lightning 은 빼고, 그 밖의 쓸 만한 모델을 "
    "5~10개 찾아. 모델마다 공식 페이지(허깅페이스 모델 카드나 깃허브)를 직접 열어서 확인한 것만 적어: 모델 이름 · 만든 곳 · "
    "파라미터 크기 · 라이선스(상업 사용 가능 여부와 한국 사용 제한이 있는지) · 글→영상/그림→영상 지원 · 한 번에 만드는 길이와 "
    "해상도 · 공식 권장 그래픽카드 메모리 · 양자화판(GGUF 등) 있는지 · stable-diffusion.cpp 나 ComfyUI 에서 돌아가는지 · "
    "공개 날짜 · 출처 주소. 모르는 칸은 비워 두고 짐작으로 채우지 마.\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 모델 이름 · 라이선스 · "
    "권장 그래픽카드 메모리 · 양자화판 · 출처)"
)
# 맥 운영 판 e44e4720 — 주소 넷을 다시 열고, 그다음 두세 개 더.
TASK_E44 = (
    "앞 판에서 읽은 영상 생성 모델 카드(https://huggingface.co/Lightricks/LTX-Video · https://huggingface.co/zai-org/CogVideoX-5b · "
    "https://huggingface.co/genmo/mochi-1-preview · https://huggingface.co/Lightricks/LTX-2)를 다시 열어, 먼저 엑셀 파일 "
    "「영상모델_후보_1116.xlsx」를 만들어 모델마다 한 줄씩 적어 줘: 모델 이름 · 만든 곳 · 파라미터 크기 · 라이선스(상업 사용 가능 "
    "여부) · 글→영상/그림→영상 · 길이와 해상도 · 권장 그래픽카드 메모리 · 양자화판 여부 · 공개 날짜 · 출처 주소. 그다음 허깅페이스에서 "
    "2025~2026년에 나온 공개 영상 생성 모델(Wan2.2 · HunyuanVideo · MiniMax 는 빼고)을 두세 개 더 찾아 같은 표에 줄을 더해. "
    "카드에 없는 칸은 비워 둬.\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 모델 이름 · 라이선스 · 양자화판)"
)


def _as_run(prompt: str) -> list[plan.Requirement]:
    """에이전트가 부르는 꼴 그대로(`agent.py` 의 `extract_plan(plan_text, has_named_source=…, must_observe=…)`)."""
    return plan.extract(prompt, has_named_source=bool(named_sources(prompt)), must_observe=True, own_from=prompt)


def _counts(requirements: list[plan.Requirement]) -> list[plan.Requirement]:
    return [item for item in requirements if item.kind == "count"]


def test_range_request_from_mac_run_3655_is_a_firm_web_count_of_five() -> None:
    counts = _counts(_as_run(TASK_3655))
    assert [item.target for item in counts] == [5]
    # 「로컬 PC에서 돌릴 수 있는」의 PC 는 돌릴 자리 — 로컬 자료 다섯으로 갈리면 웹 페이지를 아무리 읽어도 0개다.
    assert counts[0].source_scope != "local"
    assert counts[0].grade == plan.GRADE_FIRM


def test_more_on_top_of_listed_urls_adds_up_in_mac_run_e44() -> None:
    counts = _counts(_as_run(TASK_E44))
    # 주소 넷 + 「두세 개 더」(아래 끝 2) = 6. 2 로 바꿔 세우면 주소 넷 읽을 몫이 사라지고, 4 만 세우면 다섯째 후보가 막힌다.
    assert [item.target for item in counts] == [6]
    assert len(counts[0].listed_urls) == 4
    assert counts[0].grade == plan.GRADE_FIRM


@pytest.mark.parametrize(
    ("prompt", "target"),
    [
        ("깃허브에서 쓸 만한 MCP 서버를 5~10개 찾아 표로 정리해 줘", 5),
        ("깃허브에서 쓸 만한 MCP 서버를 5-10개 찾아 표로 정리해 줘", 5),
        ("깃허브에서 쓸 만한 MCP 서버를 3 ~ 5개 찾아 읽어 줘", 3),
        ("레딧에서 이 문제 겪은 글을 두세 개 찾아 읽어 줘", 2),
        ("여수 국밥집을 서너 곳 찾아 알려줘", 3),
        ("레딧 글을 대여섯 개 찾아 읽고 요약해 줘", 5),
        ("레딧 글을 최소 3개 이상 찾아 읽어 줘", 3),
    ],
)
def test_korean_count_ranges_take_the_lower_end(prompt: str, target: int) -> None:
    assert [item.target for item in _counts(_as_run(prompt))] == [target]


@pytest.mark.parametrize(
    "prompt",
    [
        # 「몇 개」는 수가 없다 — 무엇을 세워도 지어낸 목표다.
        "레딧에서 이 문제 겪은 글을 몇 개 더 찾아 읽어 줘",
        # 범위가 기간을 세면(「2-3개월」) 개수가 아니다.
        "2-3개월 안에 나온 글을 읽고 정리해 줘",
        # 아래 끝이 1 이면 개수 요구가 아니다(「한두 개」 = 「하나」와 같은 자리).
        "이 페이지를 열어 한두 개만 알려줘",
        # 거꾸로 쓴 범위는 버린다.
        "깃허브에서 MCP 서버를 10-3개 찾아 읽어 줘",
        # 09-21 AURORA — 만들 모양의 수는 여전히 읽을 몫이 아니다(찾는 말이 아니라 「만들어」에 붙었다).
        "관측 목적지 카드 3개를 담은 HTML 페이지를 만들어 줘",
    ],
)
def test_counterexamples_raise_no_count(prompt: str) -> None:
    assert _counts(_as_run(prompt)) == []


# 역검증(운영 요청 3,436개)에서 처음 판이 헛걸었던 둘 — 범위가 시키는 말에 안 붙은 자리.
# PC 운영 요청: 「핵심 주장 5~8개」는 영상 한 편 안의 항목이다. 맞던 「댓글 상위 10개」 요구를 밀어내면 안 된다.
TASK_PC_2912 = (
    "유튜브 영상 https://youtu.be/I7aC7RHs4kA 를 실제 크롬으로 열어서 (1) 영상 제목, 채널명, 올린 시각, 조회수, 댓글 수를 적고 "
    "(2) 자막(대본)을 열어 끝까지 읽어서 영상이 무엇을 말하는지 핵심 주장 5~8개를 시간대와 함께 정리하고 (3) 지금 달려 있는 "
    "댓글 상위 10개를 좋아요 수와 함께 적어 주세요. 자막을 못 열면 못 열었다고 적고, 읽지 않은 부분을 추측해서 채우지 마세요. "
    "결과는 마크다운 파일 하나로 저장해 주세요."
)
# 맥 운영 요청: 괄호 속 「별 많은 것 2~3개」가 「① ~ ⑥ 각 곳마다 … 직접 읽고」(6)를 밀어내면 안 된다.
TASK_MAC_224 = (
    "MCP 서버 「sonjari」(깃허브 github.com/sonjari/sonjari · 파이썬 · 로컬 stdio · 윈도우/맥)를 올릴 수 있는 공개 목록·디렉터리를 "
    "조사해 엑셀 표로 정리해 줘. 대상: ① 공식 MCP 레지스트리(registry.modelcontextprotocol.io) ② Smithery ③ mcp.so ④ PulseMCP "
    "⑤ 깃허브의 다른 awesome MCP 목록들(punkpeye 말고 별 많은 것 2~3개) ⑥ 앤트로픽 공식 경로 — Claude 데스크톱 확장(Desktop "
    "Extensions · .mcpb) 디렉터리 제출, Claude 커넥터 디렉터리, Claude Code 플러그인 마켓플레이스. 각 곳마다 공식 문서·제출 페이지를 "
    "직접 읽고: 등록 방법(PR · 폼 · CLI 명령), 요구 조건(원격 서버만 받는지 · 로컬 stdio 도 되는지 · 검사나 배지 필요 여부 · 심사 "
    "기간), 비용, 지금 sonjari 가 이미 올라가 있는지(검색해서), 근거 주소를 칸으로. 확인 못 한 칸은 비우고 「확인 못 함」이라고 적어 줘."
)


def test_a_range_not_attached_to_an_ask_does_not_push_out_the_real_count() -> None:
    assert [item.target for item in _counts(_as_run(TASK_PC_2912))] == [10]
    assert [item.target for item in _counts(_as_run(TASK_MAC_224))] == [6]


def test_a_count_attached_to_a_find_verb_survives_the_artifact_rule() -> None:
    # PC 운영 요청 #2667(앞부분) — 출처 이름이 없는 산출물 요청. 09-21 AURORA 규칙이 「8개 이상 찾아」까지 버렸다.
    prompt = (
        "AI 도구(코딩 도우미, 생성형 AI)를 쓰면 일하는 사람의 생산성이 실제로 얼마나 달라졌는지 측정한 연구를 찾아 엑셀 한 장으로 "
        "정리해 주세요. 늘었다는 연구와 오히려 느려지거나 효과가 없었다는 연구를 둘 다 넣고, 8개 이상 찾아 주세요."
    )
    assert not named_sources(prompt)
    assert [item.target for item in _counts(_as_run(prompt))] == [8]


def test_local_pc_as_a_runtime_is_not_a_local_source() -> None:
    # 출처 이름을 댄 판(「허깅페이스」)에서 「로컬 PC에서 돌릴」이 로컬 자료 범위로 갈리면 웹을 읽어도 0개다.
    counts = _counts(_as_run("로컬 PC에서 돌릴 수 있는 영상 모델을 허깅페이스에서 5개 찾아 엑셀로 정리해 줘"))
    assert [(item.target, item.source_scope != "local") for item in counts] == [(5, True)]


def test_local_pc_as_a_source_is_still_local() -> None:
    # 「로컬 PC에 있는 문서」는 여전히 읽을 로컬 자료다 — 실행 자리(「…에서 돌릴」)만 뺐다.
    counts = _counts(_as_run("로컬 PC에 있는 회의록 문서 3개를 읽고, 웹 자료 2개도 찾아 비교해 줘"))
    assert sorted((item.source_scope, item.target) for item in counts) == [("local", 3), ("web", 2)]


def _read_steps(urls: list[str]) -> list[dict]:
    steps: list[dict] = []
    for url in urls:
        steps.append({"tool": "browser_open", "ok": True, "arguments": {"url": url}, "evidence": {"url": url}})
        steps.append({"tool": "browser_extract", "ok": True, "arguments": {}, "evidence": {"url": url, "text": "본문 " * 50}})
    return steps


def test_artifact_turn_waits_until_the_count_is_read() -> None:
    requirements = _as_run(TASK_3655)
    four = [f"https://huggingface.co/org/model-{index}" for index in range(4)]
    short = plan.check(requirements, sources=four, steps=_read_steps(four))
    assert count_reads_owed(short)
    # 넷만 읽었는데 되받기가 「파일 차례」를 걸려 해도 걸지 않는다 — 다섯째 후보 열기가 not_this_stage 로 막히던 자리.
    assert not _artifact_turn_is_due(
        stage_says=True, deliver_turn=False, web_research=True, read_sources=4, count_short=count_reads_owed(short),
    )
    # 걸음이 바닥나기 전 차례는 그대로 건다 — 못 채운 대로 적어 낸다.
    assert _artifact_turn_is_due(
        stage_says=True, deliver_turn=True, web_research=True, read_sources=4, count_short=count_reads_owed(short),
    )
    five = four + ["https://huggingface.co/org/model-4"]
    full = plan.check(requirements, sources=five, steps=_read_steps(five))
    assert not count_reads_owed(full)
    assert _artifact_turn_is_due(
        stage_says=True, deliver_turn=False, web_research=True, read_sources=5, count_short=count_reads_owed(full),
    )


def test_agent_passes_the_count_shortfall_to_the_turn_gate() -> None:
    from alture_jarvis import agent

    assert "count_short=count_reads_owed(current_plan_results)" in inspect.getsource(agent)
