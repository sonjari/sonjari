"""큰 조회 결과를 줄일 때 **구조를 깨지 말 것.**

처음 짠 판은 직렬화한 글자를 그냥 잘랐다. 그러면 모델이 받는 것은 반쪽짜리 JSON
**문자열**이 된다 — 숫자 하나가 중간에서 끊긴 채로. 실측: 경희대 컴퓨터공학과
조회가 24,433 자여서 실제로 그렇게 나갔다.

근거를 반만 보고 답하는 것이 못 보고 모른다고 하는 것보다 나쁘다. 이제는 목록을
짧게 잡을 뿐 구조는 온전히 남기고, **잘랐다는 사실을 결과 안에** 적는다.
"""

from __future__ import annotations

import json

from alture_jarvis.inhouse_data import _RESULT_MAX_CHARS, _cap_lists, _shrink


def _big_lookup() -> dict:
    """실제 `admission_quant_lookup` 과 같은 모양 — 요약 + 아주 긴 행 목록."""
    row = {
        "university_name": "경희대학교",
        "program_name": "컴퓨터공학부 인공지능학과",
        "admission_year": 2025,
        "recruitment_quota": 20.0,
        "competition_rate": 12.3,
        "warning_message": "이 자리에 긴 설명이 붙는다. " * 12,
    }
    return {
        "ok": True,
        "targets": [
            {
                "target_label": "경희대학교 컴퓨터공학과",
                "years": [2023, 2024, 2025],
                "summary": {"competition_rate": {"mean": 11.2}},
                "rows": [dict(row, id=i) for i in range(120)],
            }
        ],
    }


def test_the_result_stays_valid_json() -> None:
    """구조가 살아 있어야 모델이 값을 꺼내 쓸 수 있다."""
    dropped: list[int] = []
    capped = _cap_lists(_big_lookup(), 6, dropped)
    text = json.dumps(capped, ensure_ascii=False)
    assert json.loads(text) == capped
    assert sum(dropped) > 0


def test_the_summary_survives_the_cut() -> None:
    """자르는 것은 **행**이지 근거가 아니다.

    요약(평균 경쟁률·연도)까지 날아가면 답의 뼈대가 없어져서, 모델은 남은 한 줄로
    전체를 말하거나 기억으로 메운다.
    """
    capped = _cap_lists(_big_lookup(), 3, [])
    target = capped["targets"][0]
    assert target["summary"] == {"competition_rate": {"mean": 11.2}}
    assert target["target_label"] == "경희대학교 컴퓨터공학과"
    assert len(target["rows"]) == 3


def test_a_tight_cap_gets_under_the_budget() -> None:
    """예산이 있다는 것 자체가 지켜져야 한다 — 안 그러면 컨텍스트가 밀린다."""
    capped = _cap_lists(_big_lookup(), 3, [])
    assert len(json.dumps(capped, ensure_ascii=False)) <= _RESULT_MAX_CHARS


def test_render_only_blobs_are_dropped() -> None:
    """자비스는 위젯을 그릴 곳이 없다. 이 하나가 수 KB 다."""
    shrunk = _shrink({"ok": True, "widget_html": "<div>" * 900, "probability": 0.62})
    assert "widget_html" not in shrunk
    assert shrunk["probability"] == 0.62
