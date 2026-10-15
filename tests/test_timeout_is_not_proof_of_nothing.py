"""시간이 끊긴 것은 "아무 일도 안 일어났다"의 증거가 아니다.

2026-08-09 사고. 블로그 글을 올려 달라는 요청에서 `naver_blog_fill_editor` 가
`browser_action_timeout` 으로 실패 처리됐는데, **본문은 편집기에 그대로 다 들어가
있었다**(화면으로 확인). 그런데 자비스는 이렇게 답했다:

    "⚠ 아직 실제로 실행되지 않았습니다 … 화면에는 아무것도 반영되어 있지 않습니다."

세상에 대한 거짓 진술이다. 그리고 그 말을 믿고 다시 실행하면 본문이 두 번 들어간다.

원인은 둘이다.

**1. 시간 초과는 동작을 멈추지 못한다.** `Future.cancel()` 은 큐에서만 빼고, 이미
돌기 시작한 작업은 계속 끝까지 간다. 브라우저 스레드는 타이핑을 마쳤다.

**2. `_commit_reality_check` 가 "실패"와 "안 부름"을 같게 봤다.** 판정에 쓰는
`called` 집합이 **성공한 도구만** 담기 때문이다. 불렀다가 실패한 도구는 그 집합에
없고, 그래서 아예 안 부른 것과 구별되지 않았다.

여기서 지키는 것 셋:

  1. 시도했다가 확인 못 한 것은 "안 했다"가 아니라 "모른다"로 말한다
  2. 정말 안 부른 경우에는 예전 문구가 그대로 나온다
  3. 모를 때는 다시 실행하기 전에 화면을 보라고 말한다 — 두 번 들어가는 것을 막는다
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent


def _step(tool: str, ok: bool) -> dict[str, object]:
    return {"tool": tool, "ok": ok, "error": "" if ok else "browser_action_timeout", "status": ""}


_CLAIM = "블로그에 글을 작성 완료했습니다."


def test_a_timed_out_step_is_not_reported_as_never_happened() -> None:
    note = BrowserAgent._commit_reality_check(
        _CLAIM,
        [_step("naver_blog_prepare_post", True), _step("naver_blog_fill_editor", False)],
    )
    assert "아무것도 반영되어 있지 않습니다" not in note, "안 해 봤다고 단언하고 있다"
    assert "확인하지 못했습니다" in note
    # 다시 실행하면 두 번 들어간다는 것을 반드시 말해야 한다.
    assert "두 번" in note


def test_never_calling_the_consumer_still_says_so_plainly() -> None:
    note = BrowserAgent._commit_reality_check(_CLAIM, [_step("naver_blog_prepare_post", True)])
    assert "아직 실제로 실행되지 않았습니다" in note
    assert "naver_blog_fill_editor" in note


def test_a_finished_commit_draws_no_warning() -> None:
    note = BrowserAgent._commit_reality_check(
        _CLAIM,
        [_step("naver_blog_prepare_post", True), _step("naver_blog_fill_editor", True)],
    )
    assert note == ""


def test_the_timeout_message_itself_says_the_work_may_have_landed() -> None:
    """도구가 내는 문구도 같은 사실을 담아야 한다 — 모델은 그 문자열만 본다."""
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig
    import pathlib
    import tempfile

    root = pathlib.Path(tempfile.mkdtemp())
    worker = BrowserWorker(
        JarvisConfig(runtime_root=root, data_dir=root / "data", output_dir=root / "out")
    )
    try:
        worker._submit(lambda: __import__("time").sleep(5), 0.2)
    except RuntimeError as exc:
        assert "browser_action_timeout" in str(exc)
        assert "계속 진행됐을 수 있습니다" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("시간 초과가 안 났다")
    finally:
        worker.stop()
