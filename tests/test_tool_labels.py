"""화면에 **영어 도구 이름이 새지 않게** 지키는 검사 (2026-08-24).

## 왜 이 검사가 있나

화면의 라벨표에 21개가 적혀 있었고, 실제로 불린 도구는 76종이었다. 라이브 잡을
세어 보니 **1,881번이 `browser_open_result` 같은 날 이름 그대로** 찍혀 있었다 —
가장 많이 불린 도구가 가장 안 읽히는 이름으로 나오고 있었다.

원인은 하나다: **손으로 관리하는 목록은 새 것이 빠진다.** 이 저장소는 같은 병을
세 번 앓았다(눈금의 도구 분류표 두 번, 관측 종류 한 번). 셋 다 "다음부터 넣자"로
끝냈고 셋 다 재발했다. 안내문은 안 먹는다 — 결정론으로 박을 수 있으면 코드로.

이 검사는 파이썬 쪽 도구 스키마에서 이름을 뽑아 화면의 라벨표와 대조한다.
**새 도구를 만든 날 빨개진다.** 그게 요점이다.

## 새 도구를 만들었는데 여기가 빨개지면

`ui/src/trajectory.ts` 의 `TOOL_LABELS` 에 한 줄 넣으면 된다. 사람이 읽을 말로.
(못 넣어도 `toolLabel` 이 갈래 이름으로 감싸 주긴 하지만, 그건 그물이지 제자리가
아니다.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "alture_jarvis"
LABELS = ROOT / "ui" / "src" / "trajectory.ts"

# 도구 스키마를 만드는 두 가지 모양.
_HELPER = re.compile(r'_function\(\s*"([a-z][a-z0-9_]{2,})"')
_INLINE = re.compile(r'"name":\s*"([a-z][a-z0-9_]{2,})"')

# 화면에 도구로 안 뜨는 것들. 스키마 모양은 같지만 걸음이 되지 않는다.
_NOT_STEPS: set[str] = set()


def declared_tools() -> set[str]:
    names: set[str] = set()
    for path in sorted(SOURCE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        names |= set(_HELPER.findall(text))
        names |= set(_INLINE.findall(text))
    return names - _NOT_STEPS


def labelled_tools() -> set[str]:
    text = LABELS.read_text(encoding="utf-8")
    block = text[text.index("const TOOL_LABELS"):text.index("const FAMILY")]
    return set(re.findall(r"^\s{2}([a-z][a-z0-9_]{2,}):", block, re.MULTILINE))


def test_source_files_are_where_we_think() -> None:
    """경로가 어긋나면 이 검사는 **0개를 비교하고 통과한다.**

    분모부터 확인한다 — 성적표가 완벽할수록 아무것도 안 쟀을 수 있다는 것을
    이 저장소는 세 번 배웠다.
    """
    assert SOURCE.is_dir(), f"도구 소스를 못 찾았다: {SOURCE}"
    assert LABELS.is_file(), f"라벨표를 못 찾았다: {LABELS}"
    assert len(declared_tools()) > 80, "도구가 이렇게 적을 리 없다 — 추출 정규식을 의심하라"
    assert len(labelled_tools()) > 80, "라벨이 이렇게 적을 리 없다 — 블록 잘라내기를 의심하라"


def test_every_tool_has_a_korean_label() -> None:
    missing = sorted(declared_tools() - labelled_tools())
    assert not missing, (
        "화면에 영어 이름 그대로 나갈 도구가 있다. "
        f"`ui/src/trajectory.ts` 의 TOOL_LABELS 에 넣어라: {missing}"
    )


def test_labels_are_actually_korean() -> None:
    """라벨 자리에 영어를 넣어 두면 검사를 통과하면서 화면은 그대로다."""
    text = LABELS.read_text(encoding="utf-8")
    block = text[text.index("const TOOL_LABELS"):text.index("const FAMILY")]
    pairs = re.findall(r'^\s{2}([a-z][a-z0-9_]{2,}):\s*"([^"]+)"', block, re.MULTILINE)
    english = [name for name, label in pairs if not re.search(r"[가-힣]", label)]
    assert not english, f"한글이 한 글자도 없는 라벨: {english}"


def test_no_label_points_at_a_tool_that_no_longer_exists() -> None:
    """지운 도구의 라벨이 남아 있으면 목록이 무엇을 덮는지 알 수 없게 된다."""
    stale = sorted(labelled_tools() - declared_tools())
    # 화면 쪽에서만 쓰는 합성 이름은 봐준다(`file_read` 처럼 여러 도구를 묶어 부르는 것).
    allowed = {"file_read", "file_write", "browser_result_list", "browser_form_submit",
               "evidence_check", "inhouse_lookup", "local_write_text_file", "shell_probe",
               "admission_quant_lookup", "admission_candidates_by_grade",
               "admission_major_profile_lookup", "admission_major_semantic_search",
               "career_strategy_lookup", "github_search", "naver_web", "naver_news",
               "google_trend", "hackernews_top", "reddit_hot",
               # 이름 2단계(2026-09-29) 전 맡기기 문 — 지난 작업 기록을 다시 열 때 이름표가 나오게 남긴다.
               "ontelic_task", "ontelic_task_status", "ontelic_guide"}
    assert not (set(stale) - allowed), f"없는 도구를 가리키는 라벨: {sorted(set(stale) - allowed)}"
