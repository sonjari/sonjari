"""답에 적힌 산출물 경로가 실제로 있나 (2026-11-17 맥 새 계정 hwp 판 — 도구 0걸음으로 「만들었다 · 경로」).

설계 `docs/설계_맥새계정시험_고칠것_2026-11-17.ko.md` P1.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.artifact_claims import _claims, drop_false_paths, false_paths


def say(ko: str, en: str) -> str:
    return ko


HWP_ANSWER = (
    "네이버 뉴스에서 오늘 경제 기사 3개를 확인하고 한글(hwp) 파일로 정리했습니다.\n"
    "1. 로봇 '근육' 쥔 중국 (뉴스버스)\n"
    "출처:\n* 뉴스버스: https://www.newsverse.kr/news/articleView.html?idxno=11940\n"
    "한글(hwp) 파일 저장 경로:\n"
    "* `/Users/sonjari/Documents/Sonjari/경제_기사_3개.hwp`\n"
    "문서가 생성되었습니다."
)


def nothing_exists(path: str) -> bool:
    return False


def test_hwp_case_zero_steps_gets_the_honest_head_and_loses_the_fake_path() -> None:
    fixed, missing = drop_false_paths(HWP_ANSWER, [], say, exists=nothing_exists)
    assert missing == ["/Users/sonjari/Documents/Sonjari/경제_기사_3개.hwp"]
    assert fixed.startswith("⚠ 요청하신 파일을 만들지 못했습니다")
    assert "경제_기사_3개.hwp" not in fixed
    assert "newsverse.kr" in fixed  # 웹 주소 줄은 그대로


def test_a_path_written_in_this_run_passes() -> None:
    path = "/Users/sonjaritest/Documents/Sonjari/경제_기사_3개.docx"
    steps = [{"tool": "local_write_document", "ok": True, "evidence": {"output_path": path}}]
    answer = f"워드 문서로 정리했습니다.\n* `{path}`"
    assert drop_false_paths(answer, steps, say, exists=nothing_exists) == (answer, [])


def test_wrote_something_but_claims_another_missing_path_drops_only_that_line() -> None:
    real = "/Users/a/Documents/Sonjari/진짜.docx"
    fake = "/Users/a/Documents/Sonjari/가짜.hwp"
    steps = [{"tool": "local_write_document", "ok": True, "evidence": {"output_path": real}}]
    answer = f"두 파일을 만들었습니다.\n* `{real}`\n* `{fake}`"
    fixed, missing = drop_false_paths(answer, steps, say, exists=nothing_exists)
    assert missing == [fake]
    assert fixed.startswith("⚠ 답에 적혀 있던 경로 중 실제로 없는 1곳")
    assert real in fixed and fake not in fixed


def test_a_file_already_on_disk_passes(tmp_path: Path) -> None:
    existing = tmp_path / "보고서.pdf"
    existing.write_bytes(b"%PDF")
    answer = f"이미 있는 파일은 {existing} 입니다."
    assert drop_false_paths(answer, [], say) == (answer, [])


def test_answers_without_paths_are_untouched() -> None:
    answer = "오늘 서울은 맑고 최고 14도입니다. 출처: https://weather.naver.com/today.html"
    assert drop_false_paths(answer, [], say, exists=nothing_exists) == (answer, [])


def test_what_counts_as_a_claimed_path() -> None:
    assert _claims("…/Users/x/Documents/Sonjari/a.hwp에 저장했어요") == ["/Users/x/Documents/Sonjari/a.hwp"]
    assert _claims(r"C:\Users\user\Documents\Sonjari\보고서.v2.docx 를 열어") == [r"C:\Users\user\Documents\Sonjari\보고서.v2.docx"]
    assert _claims("`/Users/x/Library/Application Support/Sonjari/a.docx`") == ["/Users/x/Library/Application Support/Sonjari/a.docx"]
    assert _claims("https://www.newsverse.kr/news/articleView.html?idxno=1") == []  # 웹 주소
    assert _claims("`src/alture_jarvis/agent.py` 를 고쳤습니다") == []  # 상대 경로(코드 판)는 대상 아님
    assert _claims("/Applications/Google Chrome.app 이 있어요") == []  # 앱 묶음 · 확장자 대상 아님


def test_tilde_paths_are_expanded_before_checking() -> None:
    seen: list[str] = []
    false_paths("파일: `~/Documents/a.docx`", [], exists=lambda p: seen.append(p) or True)
    assert seen == ["~/Documents/a.docx"]
