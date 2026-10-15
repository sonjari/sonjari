"""전사가 무엇을 남기고 무엇을 접는가.

이 파일이 지키는 것은 하나다: **시킨 일이 창 밖으로 밀려나면 안 된다.**

쿠팡 판(2026-08-20)에서 정확히 그 일이 났다. 도구 결과 176,021자가 예산
110,000자를 넘겨 앞쪽이 잘렸고, 그 앞쪽 첫 줄이 사용자님이 시킨 일이었다. 남은 것은
시스템 프롬프트뿐이라 모델은 그것을 요약해 뱉었다 — 25걸음을 제대로 돌고도.
"""

from __future__ import annotations

import json

from alture_jarvis.transcript import NAVIGATION_TOOLS, bounded, estimate_tokens, fold


def tool(name: str, size: int, *, url: str = "") -> dict[str, str]:
    payload = {"ok": True, "result": {"url": url, "text": "가" * size}}
    return {"role": "tool", "tool_name": name, "content": json.dumps(payload, ensure_ascii=False)}


def test_task_survives_even_when_everything_else_overflows() -> None:
    """★ 이 검사가 이 파일의 이유다."""
    messages = [
        {"role": "system", "content": "너는 자비스다"},
        {"role": "user", "content": "쿠팡에서 로켓배송 되는 그래픽카드만 비교해줘"},
        *[tool("browser_extract", 20_000) for _ in range(10)],
    ]
    kept = bounded(messages, max_chars=40_000, tool_result_max=30_000)
    assert kept[0]["role"] == "system"
    assert kept[1]["role"] == "user"
    assert "로켓배송" in kept[1]["content"]


def test_old_navigation_results_are_folded_not_dropped() -> None:
    """스냅샷은 그때 어디를 누를지 정하려고 찍은 것이지 답의 근거가 아니다."""
    messages = [
        {"role": "user", "content": "시킨 일"},
        tool("browser_snapshot", 25_000, url="https://coupang.com/a"),
        tool("browser_extract", 5_000, url="https://coupang.com/b"),
        tool("browser_extract", 5_000, url="https://coupang.com/c"),
        tool("browser_extract", 5_000, url="https://coupang.com/d"),
        tool("browser_extract", 5_000, url="https://coupang.com/e"),
        tool("browser_extract", 5_000, url="https://coupang.com/f"),
        # 묶어서 접는다(09-29) — 최근 4개 뒤로 4개가 쌓여야 한 번에 접힌다.
        tool("browser_extract", 5_000, url="https://coupang.com/g"),
        tool("browser_extract", 5_000, url="https://coupang.com/h"),
    ]
    # 묶음 크기가 아니라 「버리지 않고 접는다」를 보는 시험이라 묶음은 4 로 못 박는다(기본값은 09-30 부터 8).
    kept = bounded(messages, max_chars=200_000, tool_result_max=30_000, keep_recent_tools=4, nav_fold_step=4)
    snapshot = next(item for item in kept if item.get("tool_name") == "browser_snapshot")
    assert snapshot["content"].startswith("[접음]")
    assert "25" in snapshot["content"] or "자" in snapshot["content"]
    # 근거(추출)는 예산이 남는 한 **하나도 안 접는다.** 접기는 길 찾기부터다.
    extracts = [item for item in kept if item.get("tool_name") == "browser_extract"]
    assert extracts and all(not item["content"].startswith("[접음]") for item in extracts)


def test_recent_navigation_stays_whole() -> None:
    """방금 찍은 화면은 지금 누를 곳을 고르는 데 쓴다 — 그건 접으면 안 된다."""
    messages = [
        {"role": "user", "content": "시킨 일"},
        tool("browser_snapshot", 3_000),
    ]
    kept = bounded(messages, max_chars=200_000, tool_result_max=30_000, keep_recent_tools=4)
    snapshot = next(item for item in kept if item.get("tool_name") == "browser_snapshot")
    assert not snapshot["content"].startswith("[접음]")


def test_evidence_is_folded_only_when_the_budget_forces_it() -> None:
    messages = [
        {"role": "user", "content": "시킨 일"},
        *[tool("browser_extract", 20_000) for _ in range(6)],
    ]
    kept = bounded(messages, max_chars=60_000, tool_result_max=30_000, keep_recent_tools=1)
    folded = [item for item in kept if str(item.get("content", "")).startswith("[접음]")]
    whole = [item for item in kept if item.get("role") == "tool" and item not in folded]
    assert whole, "근거가 하나도 안 남으면 답할 것이 없다"
    assert folded, "예산을 넘겼는데 아무것도 안 접었다면 예산이 안 지켜진 것이다"


def test_folding_says_what_it_folded_and_what_to_do() -> None:
    """접었다는 사실을 안 적으면 모델은 그 걸음이 **없었다고** 여긴다."""
    line = fold(tool("browser_snapshot", 9_000, url="https://coupang.com/x"))["content"]
    assert "browser_snapshot" in line
    assert "다시 찍어라" in line


def test_system_message_is_capped_but_kept_first() -> None:
    messages = [
        {"role": "system", "content": "규" * 20_000},
        {"role": "user", "content": "시킨 일"},
    ]
    kept = bounded(messages, max_chars=50_000, tool_result_max=30_000, system_max=7_000)
    assert kept[0]["role"] == "system"
    assert len(kept[0]["content"]) == 7_000


def test_empty_transcript_is_empty() -> None:
    assert bounded([], max_chars=1000, tool_result_max=100) == []


def test_estimate_tokens_is_honest_about_the_ratio() -> None:
    """2자 = 1토큰(실측). 이 값이 틀리면 「창에 얼마 남았다」가 전부 거짓말이 된다."""
    messages = [{"role": "user", "content": "가" * 1_000}]
    assert 450 < estimate_tokens(messages) < 560


def test_navigation_list_covers_the_tools_that_actually_flooded_us() -> None:
    """쿠팡 판에서 창을 먹은 것들이 실제로 목록에 있는가."""
    for name in ("browser_snapshot", "ui_find_target", "browser_click", "browser_back"):
        assert name in NAVIGATION_TOOLS


def test_old_failed_verification_keeps_structured_repair_signal() -> None:
    payload = {
        "ok": True,
        "result": {
            "path": "C:/repo",
            "command": ["python", "-m", "pytest", "-q"],
            "exit_code": 1,
            "verified": False,
            "failure_kind": "test_assertion",
            "failure_fingerprint": "abc123",
            "failed_targets": ["tests/test_service.py::test_total"],
            "stderr": "x" * 20_000 + "AssertionError: expected 3",
        },
    }
    old = {
        "role": "tool",
        "tool_name": "local_run_project_command",
        "content": json.dumps(payload),
    }
    messages = [
        {"role": "user", "content": "고쳐줘"},
        old,
        *[tool("browser_extract", 100) for _ in range(5)],
    ]

    # 예산이 넉넉하면 원문 그대로 둔다. 예전에는 예산이 남아도 최근 4개 밖은
    # 매번 압축했는데, 그 창이 한 걸음씩 미끄러져 전사 중간이 계속 바뀌었다 —
    # 프리픽스 캐시가 깨져 매 스텝 프롬프트를 통째로 다시 읽었다(실측 8.5초/호출).
    roomy = bounded(messages, max_chars=50_000, tool_result_max=30_000, keep_recent_tools=4)
    intact = next(
        item for item in roomy if item.get("tool_name") == "local_run_project_command"
    )
    assert "x" * 1_000 in intact["content"], "예산이 남는데 접었다 — 캐시가 깨진다"

    # 예산이 모자라면 압축한다. 그때도 **고칠 근거는 살아남아야** 한다.
    tight = bounded(messages, max_chars=6_000, tool_result_max=30_000, keep_recent_tools=4)
    compacted = next(
        item for item in tight if item.get("tool_name") == "local_run_project_command"
    )
    assert "abc123" in compacted["content"]
    assert "test_assertion" in compacted["content"]
    assert len(compacted["content"]) < 5_000


def test_only_recent_thinking_is_preserved_when_explicitly_requested() -> None:
    messages = [
        {"role": "user", "content": "고쳐줘"},
        {"role": "assistant", "content": "", "thinking": "old secret"},
        {"role": "assistant", "content": "", "thinking": "recent reasoning"},
    ]

    kept = bounded(
        messages,
        max_chars=20_000,
        tool_result_max=5_000,
        preserve_recent_thinking=1,
    )

    assistants = [item for item in kept if item.get("role") == "assistant"]
    assert "thinking" not in assistants[0]
    assert assistants[1]["thinking"] == "recent reasoning"


def test_a_growing_code_run_keeps_a_stable_prefix() -> None:
    """캐시가 사는 조건은 「접었나」가 아니라 **앞부분이 그대로인가**이다.

    2026-08-27 실측: 미끄러지는 창 때문에 3번째 호출부터 매번 프롬프트를 통째로
    다시 읽었다(8.5초/호출 · 판당 60초 · 72판이면 한 시간).
    """
    def code_result(step: int) -> dict[str, object]:
        payload = {
            "ok": True,
            "result": {"path": f"src/mod_{step}.py", "content": f"line {step}\n" * 200},
        }
        return {
            "role": "tool",
            "tool_name": "local_read_text_file",
            "content": json.dumps(payload, ensure_ascii=False),
        }

    conversation: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "이 저장소를 고쳐줘"},
    ]
    previous: list[dict[str, object]] | None = None
    for step in range(1, 11):
        conversation.append({"role": "assistant", "content": f"step {step}"})
        conversation.append(code_result(step))
        current = bounded(
            conversation, max_chars=128_000, tool_result_max=30_000, keep_recent_tools=4
        )
        if previous is not None:
            shared = min(len(previous), len(current))
            # 겹치는 구간은 한 글자도 달라지면 안 된다 — 달라진 지점부터
            # Ollama 가 전부 다시 prefill 한다.
            drift = [
                index
                for index in range(shared)
                if previous[index] != current[index]
            ]
            assert drift == [], f"{step}번째 호출에서 {drift} 번 메시지가 바뀌었다"
        previous = current


def test_a_benchmark_session_does_not_write_to_the_durable_drawer() -> None:
    """벤치가 자비스의 영구 기억을 채우고 있었다.

    2026-08-27 실측: 서랍 202건 중 149건(74%)이 벤치·임시 세션에서 왔고,
    「사용자 선호」 17건은 벤치 프롬프트 문구가 사용자님의 취향으로 박힌 것이었다.
    같은 말("테스트 파일은 수정하지 마")이 17번 들어가 있었다.
    """
    from alture_jarvis.fact_extract import ephemeral_session

    assert ephemeral_session("code-repo-bench-single_1_safe_divide-1787674499573")
    assert ephemeral_session("q4-golden-jarvis_self_upgrade-1787764")
    assert ephemeral_session(
        "jarvis-normal",
        r"C:\RoboMetaFit\tools\alture-jarvis\outputs\code_repo_bench\run_1\case",
    )

    # 사람이 실제로 쓰는 판은 그대로 배운다 — 막기만 하면 기억이 안 는다.
    assert ephemeral_session("jarvis-mt9vkly4") == ""
    assert ephemeral_session("jarvis-mt9vkly4", r"C:\work\monorepo") == ""


def test_navigation_folds_in_batches_so_the_prefix_survives_between_folds() -> None:
    """길 찾기 접기가 한 칸씩 미끄러지면 **매 걸음** 전사 중간이 바뀐다(09-29 저녁 「걸음마다 다시 읽기」).

    묶어서 접으면 바뀌는 걸음은 step 번에 한 번뿐이고, 그 사이 걸음은 앞이 한 글자도 안 바뀐다.
    """
    conversation: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "쿠팡에서 찾아줘"},
    ]
    previous: list[dict[str, object]] | None = None
    drifted_steps: list[int] = []
    for step in range(1, 21):
        conversation.append({"role": "assistant", "content": f"step {step}"})
        conversation.append(tool("browser_snapshot", 3_000, url=f"https://coupang.com/{step}"))
        current = bounded(conversation, max_chars=180_000, tool_result_max=30_000, keep_recent_tools=4)
        if previous is not None:
            shared = min(len(previous), len(current))
            if any(previous[i] != current[i] for i in range(shared)):
                drifted_steps.append(step)
        previous = current
    # 도구 결과 12·20 개째에서만 접는다(묶음 8, 09-30) — 묶음 4 땐 8·12·16·20, 한 칸씩 접던 예전엔 5~20 전부(16번)였다.
    assert drifted_steps == [12, 20]
    # 품질 규칙은 그대로: 오래된 화면은 결국 접히고, 원문 화면은 keep+step-1 개를 넘지 않는다.
    whole = [m for m in current if m.get("role") == "tool" and not str(m["content"]).startswith("[접음]")]
    assert 4 <= len(whole) <= 11


def test_overflow_folds_in_batches_so_the_prefix_survives_between_folds() -> None:
    """예산을 넘은 뒤 걸음마다 가장 오래된 결과를 하나씩 접으면 **매 걸음** 전사 앞쪽이 바뀐다.

    09-29 저녁 64K(예산 8만 자, 시스템 2.1만 자) MS 스토어 판: 판 끝 무렵 걸음마다 2.3만 토큰을 다시 읽었다.
    """
    conversation: list[dict[str, object]] = [
        {"role": "system", "content": "시" * 21_000},
        {"role": "user", "content": "마이크로소프트 스토어에서 메모 앱 3개를 찾아 엑셀로"},
    ]
    previous: list[dict[str, object]] | None = None
    drifted: list[int] = []
    for step in range(1, 25):
        conversation.append({"role": "assistant", "content": f"step {step}"})
        conversation.append(tool("browser_page_data", 6_000, url=f"https://apps.microsoft.com/{step}"))
        current = bounded(conversation, max_chars=80_281, tool_result_max=20_070, keep_recent_tools=4)
        assert "메모 앱" in current[1]["content"], "시킨 일은 어떤 경우에도 남는다"
        if previous is not None:
            shared = min(len(previous), len(current))
            if any(previous[i] != current[i] for i in range(shared)):
                drifted.append(step)
        previous = current
    # 넘기 시작한 뒤로도 4걸음에 한 번꼴로만 바뀐다(예전 규칙은 넘은 뒤 매 걸음).
    assert drifted, "24걸음이면 예산을 넘는다 — 넘지 않았다면 시험이 틀린 것이다"
    assert len(drifted) <= 24 // 4 + 1, f"앞이 바뀐 걸음: {drifted}"
    whole = [m for m in current if m.get("role") == "tool" and not str(m["content"]).startswith("[접음]")]
    assert len(whole) >= 4, "최근 원문은 남는다"
