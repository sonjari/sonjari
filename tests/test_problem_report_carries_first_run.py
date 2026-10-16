"""제보에 **첫 실행 자취**와 **패키지 판 번호**가 실린다 (2026-10-06 스토어판 첫 제보).

마법사 마지막 단추가 안 먹어 「문제 보내기」를 눌렀는데 제보에는 「최근 판 0개」와 판 번호 `0.1.0` 뿐이었다. 그날 나온
세 건이 전부 판을 하나도 못 돌린 자리였다. 판이 없어도 「어디까지 갔나」는 실리고, 경로는 여전히 안 나간다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis import msix
from alture_jarvis.problem_report import build_report, first_run_trace, scrub

HOME = Path(r"C:\Users\tester")


def _stuck_in_the_wizard() -> dict:
    return first_run_trace(
        setup={"completed": False, "steps": ["pc_check"], "path": r"C:\Users\tester\Sonjari\setup_state.json"},
        ollama={"running": False, "version": "", "managed": False, "runner_missing": False, "can_install": True,
                "bundled": r"C:\Users\tester\Sonjari\engine\ollama\v0.35.1\ollama.exe",
                "install_root": r"C:\Users\tester\Sonjari\engine\ollama",
                "install": {"phase": "error", "expected_sha256": "a" * 64,
                            "error": r"PermissionError: [WinError 5] 액세스가 거부되었습니다: "
                                     r"'C:\\Users\\tester\\Sonjari\\engine\\ollama\\v0.35.1.extracting'"}},
        pulls={"qwen35_4b": {"model_key": "hf.co/unsloth/Qwen3.5-4B-GGUF:UD-IQ3_XXS", "status": "failed",
                             "phase": "", "reason": "ollama_not_running", "detail": "URLError: refused",
                             "applied": {"bench": {"tokens_per_sec": 1}}}},
        runners=[{"pid": 1, "parent": 2, "parent_alive": True, "path": r"C:\Users\tester\Sonjari\engine\x\llama-server.exe"},
                 {"pid": 3, "parent": 4, "parent_alive": False, "path": r"C:\Users\tester\Sonjari\engine\x\llama-server.exe"}],
    )


def test_a_person_with_no_jobs_still_sends_where_first_run_got_to() -> None:
    report = build_report(health={"build": "9b54563b790b"}, jobs=[], gpu=None, home=HOME,
                          app_version="0.4.2.0", first_run=_stuck_in_the_wizard())

    assert report["jobs"] == []
    trace = report["first_run"]
    assert trace["setup"] == {"completed": False, "steps": ["pc_check"]}
    assert trace["ollama"]["install_phase"] == "error" and "PermissionError" in trace["ollama"]["install_error"]
    assert trace["pulls"] == [{"model": "hf.co/unsloth/Qwen3.5-4B-GGUF:UD-IQ3_XXS", "status": "failed", "phase": "",
                              "reason": "ollama_not_running", "detail": "URLError: refused"}]
    assert trace["runners"] == {"count": 2, "parent_dead": 1}


def test_no_path_or_user_name_leaves_with_the_trace() -> None:
    report = build_report(health={}, jobs=[], gpu=None, home=HOME, first_run=_stuck_in_the_wizard())
    sent = json.dumps(report, ensure_ascii=False)

    assert "tester" not in sent, "사용자 이름이 든 경로는 안 나간다"
    assert "install_root" not in sent and "bundled" not in sent and "llama-server.exe" not in sent
    assert "a" * 64 not in sent, "해시 같은 긴 값은 안 싣는다"
    assert "tokens_per_sec" not in sent, "적용 결과 전체는 싣지 않는다"


def test_a_trace_with_nothing_readable_is_still_a_trace() -> None:
    trace = first_run_trace(setup=None, ollama=None, pulls=None, runners=None)

    assert trace["setup"] == {"completed": False, "steps": []}
    assert trace["ollama"]["install_phase"] == "" and trace["pulls"] == []
    assert "runners" not in trace, "실행기를 못 셌으면 0 이라고 말하지 않는다"


def test_our_own_error_names_are_not_hidden_as_tokens() -> None:
    for code in ("pull_reported_success_but_model_missing", "ollama_not_answering_after_restart",
                 "old_server_still_answering"):
        assert scrub(code, HOME) == code


def test_real_tokens_are_still_hidden() -> None:
    # 아래 키 모양은 지어낸 값이다 — "sk_" 를 나눠 적어 비밀값 검사기가 진짜 키로 읽지 않게 한다(10-16 깃허브 경고 1).
    for secret in ("AbCdEfGhIjKlMnOpQrStUvWxYz0123", "sk_" + "live_abcdefghijklmnopqrstuvwx1234",
                   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "this-is-a-long-dashed-secret-value",
                   "Zq7TmRw2LkXv9BnHd4PsYc6JfUg3Ae8"):
        assert scrub(secret, HOME) == "<숨김>", secret


def test_the_version_in_a_report_is_the_package_version(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", "RoboMetaFit.Sonjari_0.4.4.0_x64__8wekyb3d8bbwe")
    assert msix.package_version() == "0.4.4.0"

    report = build_report(health={}, jobs=[], gpu=None, home=HOME, app_version=msix.package_version() or "0.1.0")
    assert report["app_version"] == "0.4.4.0"


def test_outside_a_package_there_is_no_package_version(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_FAKE_PACKAGE_FULL_NAME", raising=False)
    monkeypatch.setattr(msix, "_package_string", lambda name: "")
    assert msix.package_version() == ""
