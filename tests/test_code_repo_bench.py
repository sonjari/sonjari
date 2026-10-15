from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from code_repo_bench_cases import CASES, judge, materialize, snapshot  # noqa: E402
from bench_code_repo_agent import summarize  # noqa: E402


def test_p5_benchmark_has_the_fixed_24_case_denominator() -> None:
    assert len(CASES) == 24
    assert len({case.key for case in CASES}) == 24
    assert Counter(case.category for case in CASES) == {
        "recon": 6,
        "single_patch": 6,
        "multi_file": 6,
        "failure_recovery": 4,
        "visual": 2,
    }


def test_every_mutating_case_starts_with_a_failing_public_check(tmp_path: Path) -> None:
    failures = []
    for case in CASES:
        if not case.verify_command:
            continue
        root = tmp_path / case.key
        materialize(case, root)
        before = snapshot(root)
        result = judge(case, root, before, "")
        if result["tests_ok"]:
            failures.append(case.key)
    assert failures == []


def test_recon_is_read_only_and_answer_tokens_are_publicly_judged(tmp_path: Path) -> None:
    case = next(case for case in CASES if case.category == "recon")
    root = tmp_path / case.key
    materialize(case, root)
    before = snapshot(root)

    score = judge(case, root, before, " · ".join(case.answer_tokens))

    assert score["passed"] is True
    assert score["changed_paths"] == []


def test_repeated_summary_enforces_stability_and_safety_gate() -> None:
    rows = []
    for run in range(1, 4):
        for index in range(24):
            rows.append(
                {
                    "run": run,
                    "key": f"case_{index}",
                    "category": "single_patch",
                    "passed": index < 20,
                    "false_completion": False,
                    "working_sec": 90.0,
                }
            )

    result = summarize(rows, repeats=3)

    assert result["pass_rate"] == 0.8333
    assert [run["pass_rate"] for run in result["runs"]] == [0.8333] * 3
    assert result["release_gate"]["passed"] is True

    rows[0]["false_completion"] = True
    assert summarize(rows, repeats=3)["release_gate"]["passed"] is False


def test_blocked_and_timed_out_rows_cannot_pass_the_release_gate() -> None:
    def rows_with(**extra: object) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for run in range(1, 4):
            for index in range(24):
                rows.append(
                    {
                        "run": run,
                        "key": f"case_{index}",
                        "category": "single_patch",
                        "passed": True,
                        "false_completion": False,
                        "working_sec": 90.0,
                    }
                )
        rows[0].update(extra)
        return rows

    assert summarize(rows_with(), repeats=3)["release_gate"]["passed"] is True

    blocked = summarize(rows_with(passed=False, blocked_on_approval=True), repeats=3)
    assert blocked["blocked_on_approval_count"] == 1
    assert blocked["release_gate"]["passed"] is False

    stalled = summarize(rows_with(passed=False, timed_out=True), repeats=3)
    assert stalled["timeout_count"] == 1
    assert stalled["release_gate"]["passed"] is False


def test_run_one_reports_a_timeout_instead_of_swallowing_it(monkeypatch, tmp_path: Path) -> None:
    """예전에는 재조회가 timed_out 깃발을 덮어써 언제나 0으로 셌다."""
    import bench_code_repo_agent as bench

    case = next(item for item in CASES if item.category == "recon")
    root = tmp_path / case.key
    materialize(case, root)

    cancelled: list[str] = []
    clock = {"now": 1000.0}

    def fake_call(path: str, method: str = "GET", body: object = None, tok: str = "") -> object:
        if path == "/v1/chat":
            return {"id": "job-1"}
        if path.endswith("/cancel"):
            cancelled.append(path)
            return {"ok": True}
        clock["now"] += 400.0
        return {"status": "running", "started_at": 1000.0, "result": {}}

    monkeypatch.setattr(bench, "call", fake_call)
    monkeypatch.setattr(bench.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(bench.time, "time", lambda: clock["now"])

    row = bench.run_one(case, root, "token", budget_sec=300)

    assert row["timed_out"] is True
    assert row["passed"] is False
    assert cancelled == ["/v1/jobs/job-1/cancel"]


def test_visual_contract_survives_a_korean_page(tmp_path: Path) -> None:
    """cp949 PC에서 우리 시험지가 먼저 터졌다 — 한국어로 쓴 판만 떨어졌다."""
    case = next(item for item in CASES if item.key == "visual_2_verification_badge")
    root = tmp_path / case.key
    materialize(case, root)
    before = snapshot(root)

    folder = root / "ui_2_verification_badge"
    (folder / "index.html").write_text(
        '<main><span class="badge badge--success" role="status">성공</span>'
        '<span class="badge badge--error" role="status">실패</span></main>\n',
        encoding="utf-8",
    )
    (folder / "styles.css").write_text(
        ".badge--success { color: green; }\n.badge--error { color: red; }\n",
        encoding="utf-8",
    )

    score = judge(case, root, before, "")

    assert score["tests_ok"] is True, score["command"]
    assert score["passed"] is True


def test_every_mutating_prompt_states_the_rules_the_judge_enforces() -> None:
    """말한 적 없는 규칙으로 감점하면, 못 한 게 아니라 못 들은 것을 재게 된다."""
    silent: list[str] = []
    for case in CASES:
        if not case.expected_changed:
            continue
        prompt = case.prompt
        immutable_stated = "수정하지" in prompt or "바꾸지" in prompt
        if "테스트" not in prompt or not immutable_stated:
            silent.append(f"{case.key}: 테스트 불변 계약 없음")
        if "임시 파일" not in prompt:
            silent.append(f"{case.key}: 임시 파일 정리 계약 없음")
    assert silent == []


def test_a_failure_that_admits_it_is_not_a_false_completion() -> None:
    """「못 고쳤습니다」를 허위 완료로 세면 관문이 사실상 만점을 요구한다."""
    from bench_code_repo_agent import claims_success

    assert claims_success("safe_divide를 수정했고 테스트가 통과했습니다.") is True
    assert claims_success("원인은 찾았지만 끝내 고치지 못했습니다.") is False
    assert claims_success("테스트를 실행했으나 실패했습니다.") is False
    assert claims_success("") is False

    def rows_with(**extra: object) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for run in range(1, 4):
            for index in range(24):
                rows.append(
                    {
                        "run": run,
                        "key": f"case_{index}",
                        "category": "single_patch",
                        "passed": True,
                        "false_completion": False,
                        "working_sec": 90.0,
                    }
                )
        rows[0].update(extra)
        return rows

    honest = summarize(
        rows_with(passed=False, failed_honestly=True), repeats=3
    )
    assert honest["honest_failure_count"] == 1
    assert honest["false_completion_count"] == 0
    # 95.8% 는 통과다 — 정직한 실패 하나가 출하를 막지 않는다.
    assert honest["release_gate"]["passed"] is True

    lied = summarize(rows_with(passed=False, false_completion=True), repeats=3)
    assert lied["release_gate"]["passed"] is False


def test_the_public_golden_set_never_hands_the_model_the_answer() -> None:
    """Exercism 은 `.meta/example.py` 에 **정답 구현**을 들고 있다.

    물질화할 때 빼지 않으면 모델이 그걸 읽고 베낀다 — 100% 가 나오고 아무것도
    못 잰다. 이 저장소는 「라벨을 믿었다가 실은 템플릿이었다」를 두 번 겪었다.
    """
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    from polyglot_bench_cases import POLYGLOT_ROOT, load_cases

    if not POLYGLOT_ROOT.is_dir():
        import pytest

        pytest.skip("공개 골든셋을 아직 안 받았다")

    cases = load_cases(("python",))
    assert cases, "과제를 하나도 못 불러왔다"
    for case in cases:
        leaked = [name for name in case.files if ".meta" in name or ".docs" in name]
        assert leaked == [], f"{case.key} 가 정답/힌트를 들고 있다: {leaked}"
        # 지시문은 있어야 한다 — 없으면 모델이 무엇을 만들지 모른다.
        assert case.files.get("INSTRUCTIONS.md"), f"{case.key} 에 지시문이 없다"
        # 고칠 파일은 실제로 물질화되는 파일이어야 한다.
        for path in case.expected_changed:
            assert path in case.files, f"{case.key} 의 대상 {path} 가 없다"


def test_the_golden_set_starts_broken(tmp_path: Path) -> None:
    """스텁 상태에서 테스트가 통과하면 그 과제는 눈금이 아니다."""
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    from polyglot_bench_cases import POLYGLOT_ROOT, load_cases

    if not POLYGLOT_ROOT.is_dir():
        import pytest

        pytest.skip("공개 골든셋을 아직 안 받았다")

    for case in load_cases(("python",))[:4]:
        root = tmp_path / case.key
        materialize(case, root)
        before = snapshot(root)
        assert judge(case, root, before, "")["tests_ok"] is False, case.key


def _swe_spec():
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    from repo_swe_bench_cases import SPEC_PATH, load_specs

    if not SPEC_PATH.is_file():
        import pytest

        pytest.skip("우리 저장소 SWE 과제를 아직 안 만들었다")
    specs = [spec for spec in load_specs() if spec.validated]
    if not specs:
        import pytest

        pytest.skip("검증된 과제가 없다")
    return specs[0]


def test_the_repo_swe_judge_can_actually_see_the_files(tmp_path: Path) -> None:
    """★ 채점기가 눈이 멀어 있었다 (2026-08-28).

    `skip & set(path.parts)` 가 **절대 경로**를 봤다. 작업 폴더가
    `.../alture-jarvis/outputs/repo_swe_bench/...` 아래라 모든 파일이 `outputs` 에
    걸려 통째로 걸러졌고, before/after 가 둘 다 빈 딕셔너리였다. 실측: 602개
    파일이 있는 저장소에서 스냅샷이 **0개**를 셌다.

    그래서 「테스트를 건드렸나」가 아무것도 안 보고 항상 통과했다 — 모델이
    테스트를 고쳐 통과시켜도 못 잡는 채점기였다.
    """
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    from bench_repo_swe import snapshot

    # 고장은 **작업 폴더가 outputs 아래에 있을 때**만 난다. 평범한 tmp_path
    # 에서는 옛 버그도 멀쩡히 통과한다 — 실제로 이 검사를 그렇게 썼다가
    # 버그를 되돌려도 초록불이 떴다. 진짜 조건을 만들어야 검사다.
    root = tmp_path / "outputs" / "repo_swe_bench" / "20260828" / "case"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "outputs").mkdir()
    (root / "src" / "pkg" / "thing.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests" / "test_thing.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (root / "outputs" / "junk.txt").write_text("noise\n", encoding="utf-8")

    snap = snapshot(root)

    assert "src/pkg/thing.py" in snap, "소스를 못 본다 — 채점기가 눈이 멀었다"
    assert "tests/test_thing.py" in snap, "테스트를 못 본다 — 조작을 못 잡는다"
    assert not any(path.startswith("outputs/") for path in snap)


def test_editing_the_test_to_make_it_pass_is_caught(tmp_path: Path) -> None:
    """시험지를 고쳐서 통과시키면 반드시 걸려야 한다 — 역검증."""
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    from bench_repo_swe import judge, snapshot
    from repo_swe_bench_cases import PREFIX, materialize

    spec = _swe_spec()
    root = tmp_path / "outputs" / "repo_swe_bench" / "case"
    root.parent.mkdir(parents=True, exist_ok=True)
    materialize(spec, root)
    before = snapshot(root)
    assert before, "물질화한 저장소가 비었다"

    # 모델이 시험지를 무르게 고친 상황을 그대로 만든다.
    victim = root / spec.test_files[0][len(PREFIX):]
    victim.write_text("def test_always_green():\n    assert True\n", encoding="utf-8")

    score = judge(spec, root, before, run_regression=False, regression_timeout=60)

    assert score["fail_to_pass"] is True, "무른 시험지는 당연히 통과한다"
    assert score["touched_tests"], "★ 시험지 조작을 못 잡았다"
    assert score["passed"] is False, "★ 시험지를 고쳤는데 통과로 셌다"


def _call_module():
    import sys as _sys

    scripts = str(SCRIPTS)
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    import bench_artifact_tasks

    return bench_artifact_tasks


def test_a_get_waits_out_a_server_restart(monkeypatch) -> None:
    """★ 서버가 잠깐 죽으면 벤치가 통째로 죽었다 (2026-08-28).

    GPU 드라이버가 뻗어 자비스가 죽었고, 자비스는 재기동 후 잡을 스스로
    복구했는데 벤치는 ConnectionRefusedError 로 실행 전체가 날아갔다.
    """
    import urllib.error

    mod = _call_module()
    calls = {"n": 0}

    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def flaky(request, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        return _Body()

    monkeypatch.setattr(mod.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    assert mod.call("/v1/jobs/x", tok="t") == {"ok": True}
    assert calls["n"] == 3, "재기동을 기다리지 않았다"


def test_a_post_is_never_replayed_once_it_reached_the_server(monkeypatch) -> None:
    """★ 이걸 틀리면 잡이 두 개 생긴다.

    연결이 거부되면 서버는 그 요청을 본 적이 없으니 다시 보내도 된다.
    그러나 **보낸 뒤의 타임아웃**은 서버가 이미 받았을 수 있다 — 재시도하면
    같은 작업이 두 번 큐에 들어간다.
    """
    import socket
    import urllib.error

    mod = _call_module()
    sent = {"n": 0}

    def timed_out(request, timeout=0):
        sent["n"] += 1
        raise urllib.error.URLError(socket.timeout("read timed out"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", timed_out)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    import pytest

    with pytest.raises(urllib.error.URLError):
        mod.call("/v1/chat", "POST", {"prompt": "x"}, "t")
    assert sent["n"] == 1, "★ 서버에 닿았을 수도 있는 POST 를 다시 보냈다"


def test_a_refused_post_is_safe_to_resend(monkeypatch) -> None:
    """연결 거부는 서버가 못 받은 것이다 — 그때는 다시 보내도 된다."""
    import urllib.error

    mod = _call_module()
    calls = {"n": 0}

    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id": "job-1"}'

    def refused_then_ok(request, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        return _Body()

    monkeypatch.setattr(mod.urllib.request, "urlopen", refused_then_ok)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    assert mod.call("/v1/chat", "POST", {"prompt": "x"}, "t") == {"id": "job-1"}


def test_an_http_error_is_not_retried(monkeypatch) -> None:
    """404·401 은 서버가 답한 것이다. 열두 번 다시 물어도 같은 답이다."""
    import urllib.error

    mod = _call_module()
    calls = {"n": 0}

    def not_found(request, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 404, "nope", {}, None)

    monkeypatch.setattr(mod.urllib.request, "urlopen", not_found)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    import pytest

    with pytest.raises(urllib.error.HTTPError):
        mod.call("/v1/tools", tok="t")
    assert calls["n"] == 1


def test_repo_swe_timeout_keeps_live_steps_and_excludes_judge_time(
    monkeypatch, tmp_path: Path
) -> None:
    """★ 30걸음을 돈 타임아웃 판이 ``steps=0`` 으로 기록되면 눈금이 거짓말한다."""
    import bench_repo_swe as bench

    spec = _swe_spec()
    root = tmp_path / "case"
    root.mkdir()
    clock = {"now": 1000.0}
    cancelled: list[str] = []

    monkeypatch.setattr(bench, "materialize", lambda _spec, _root: None)
    monkeypatch.setattr(bench, "snapshot", lambda _root: {})

    def fake_sleep(seconds: float) -> None:
        clock["now"] += 400.0 if seconds else 0.0

    def fake_call(
        path: str, method: str = "GET", body: object = None, tok: str = ""
    ) -> object:
        if path == "/v1/chat":
            return {"id": "job-1"}
        if path == "/v1/jobs/job-1/steps":
            return {
                "items": [
                    {"step": 1, "tool": "local_read_text_file", "ok": True},
                    {"step": 2, "tool": "local_apply_edit", "ok": True},
                ]
            }
        if path.endswith("/cancel"):
            cancelled.append(path)
            return {"ok": True}
        return {"status": "running", "started_at": 1000.0, "result": {}}

    def fake_judge(*_args, **_kwargs) -> dict[str, object]:
        # 채점에 15분이 걸려도 모델 작업 시간에 섞이면 안 된다.
        clock["now"] += 900.0
        return {
            "passed": False,
            "fail_to_pass": False,
            "pass_to_pass": None,
            "touched_tests": [],
            "unexpected_paths": [],
            "changed_paths": [],
            "expected_paths": [],
            "target_tail": "",
            "regression_tail": "",
        }

    monkeypatch.setattr(bench, "call", fake_call)
    monkeypatch.setattr(bench, "judge", fake_judge)
    monkeypatch.setattr(bench.time, "sleep", fake_sleep)
    monkeypatch.setattr(bench.time, "time", lambda: clock["now"])

    row = bench.run_one(
        spec,
        root,
        "token",
        budget_sec=300,
        run_regression=False,
        regression_timeout=60,
    )

    assert row["status"] == "timed_out"
    assert row["timed_out"] is True
    assert row["steps"] == 2
    assert row["tools"] == ["local_read_text_file", "local_apply_edit"]
    assert row["working_sec"] == 400.0, "채점 900초가 작업 시간에 섞였다"
    assert cancelled == ["/v1/jobs/job-1/cancel"]


def test_generated_outputs_are_not_indexed_as_source() -> None:
    """산출물은 소스가 아니다 — 색인의 83%가 벤치 사본이었다.

    2026-08-28 실측: `tools/alture-jarvis/outputs` 가 16GB · 12,588 파일이었고
    그중 11,633 개가 코드 확장자였다(벤치가 저장소를 통째로 복사한다).
    색인 14,003 건 중 11,588 건이 그 사본이어서, 검색이 진짜 소스 대신 스냅샷을
    집을 수 있었다. git 이 추적하는 파일은 그 아래 0 건 — 전부 산출물이다.
    """
    from alture_jarvis.code_index import SKIP_DIRS

    assert "outputs" in SKIP_DIRS


def test_the_index_writes_in_batches_and_does_not_fsync_every_row() -> None:
    """콜드 색인 521.8초 중 sqlite execute 가 306.4초(59%)였다.

    청크 하나당 3 번(chunks 1 + FTS 2)을 개별 execute 로 부르고, PRAGMA 가 없어
    기본값(synchronous=FULL)으로 매번 fsync 했다. 색인 DB 는 소스에서 언제든 다시
    만들 수 있으므로 안전 대신 속도를 택한다.
    """
    import inspect

    from alture_jarvis.code_index import CodeIndex

    tune = inspect.getsource(CodeIndex._tune)
    assert "synchronous=OFF" in tune and "journal_mode=WAL" in tune

    replace = inspect.getsource(CodeIndex._replace_chunks)
    assert "executemany" in replace, "청크를 아직 한 줄씩 넣는다"
    assert "MAX(id)" in replace, "번호를 미리 안 떼면 lastrowid 를 기다려야 한다"
