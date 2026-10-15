"""원장이 **우리 데이터를 읽는 도구**를 안다.

## 왜 이 파일이 있는가 (2026-09-05)

앞 사람이 원장을 19 → 33 개로 넓히면서 이렇게 적어 두고 갔다:

    남은 50개는 아직 미등록이다. `admission_*` · `career_strategy_lookup` 은
    **자사 데이터 읽기**라 다음 차례다. **키를 추측해서 넣지 마라** —
    출처가 안 잡혀 조용히 무동작이 된다.

그 다음 차례를 했다. 그리고 키를 추측하지 않으려고 실제 트레이스 2,500 판에서
세었더니, **경고했던 함정을 값의 모양 쪽에서 다시 만났다** — 이 도구들 중 둘은
출처를 **리스트로** 준다. `record_for` 는 `isinstance(value, str)` 만 봤으므로,
등록만 하고 이 검사가 없었으면 여전히 조용히 무동작이었을 것이다.

## 이 파일이 지키는 것

아래 증거는 **실제 트레이스에서 그대로 뜬 모양**이다. 도구가 키 이름을 바꾸면
여기서 걸린다 — 원장이 조용히 0 건이 되는 것보다 시험이 빨간 것이 낫다.

## 왜 body_read 인가

웹은 목록을 주고 상세를 따로 열게 한다. 우리 데이터 도구는 **자료 자체를 준다** —
더 열 것이 없다. `listing` 으로 두면 근거 대조(`read_bodies` 는 `body_read` 만
재료로 삼는다)에 원문이 0 건으로 남아, 맞게 답해도 「읽지 않고 적었다」 경고가
선다. 정찰기도 못 지운다 — 지울 근거가 원장에 없으니까.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from alture_jarvis.evidence import (
    MANIFEST,
    TYPE_BODY_READ,
    TYPE_VERIFICATION,
    read_bodies,
    record_for,
)

# ─────────────────────────────────────────────────────────────────────────────
# 실측한 모양 그대로 (2026-09-05, 최근 2,500 판)
# ─────────────────────────────────────────────────────────────────────────────

REAL = {
    "admission_quant_lookup": (
        {"target_labels": ["경희대학교 컴퓨터공학과"]},
        {
            "ok": True,
            "ready": True,
            "source": "jetson_quant_db",
            "target_count": 1,
            "targets": [{"target_label": "경희대학교 컴퓨터공학과", "취업률": 71.2}],
            "_truncated": "목록이 길어 각 목록을 6개까지만 담았다(생략 81건).",
        },
    ),
    "admission_major_profile_lookup": (
        {"target_labels": ["간호학과"]},
        {"ok": True, "target_count": 1, "targets": [{"x": 1}], "evidence_items": [{"title": "간호학과"}]},
    ),
    "admission_major_semantic_search": (
        {"query": "간호학과", "top_k": 8},
        {"ok": True, "query": "간호학과", "evidence_items": [{"title": "'간호학과' 시맨틱 검색 결과 8건"}]},
    ),
    "admission_candidates_by_grade": (
        {"grade": 2.4, "major_query": "컴퓨터공학"},
        {
            "ok": True,
            "returned": 20,
            "total_matched": 131,
            "evidence": [{"kind": "admission_cutoff", "title": "대진대학교 컴퓨터공학전공"}],
        },
    ),
    # 표본 0 이라 못 셌던 것 — 라이브 판에서 키를 세어 넣었다.
    "admission_probability_simulate": (
        {"student_value": 2.4, "target_label": "명지대학교 컴퓨터공학과"},
        {
            "ok": True,
            "target_label": "명지대학교 컴퓨터공학과",
            "probability": 0.0,
            "band": "위험",
            "q70": 843.8,
            "metric": "conversion_score",
            "evidence": [{"year": 2024, "metric": "conversion_score", "q70": 1035.9}],
        },
    ),
    "career_strategy_lookup": (
        {"major": "간호학과"},
        {"ok": True, "evidence_items": [{"kind": "sagyoyuk_db", "title": "간호사 (공식 종목코드 0731)"}]},
    ),
    "local_run_project_command": (
        {"command": ["pytest", "tests/test_facts_drawer.py", "-v"], "path": ".", "timeout_sec": 120},
        {
            "action": "local_run_project_command",
            "command": ["pytest", "tests/test_facts_drawer.py", "-v"],
            "exit_code": 0,
            "verified": True,
            "stdout": "============ test session starts ============",
        },
    ),
}


@pytest.mark.parametrize("tool", sorted(REAL))
def test_등록됐다(tool):
    assert tool in MANIFEST, f"{tool} 이 원장에 없다 — 그 도구를 쓴 걸음은 통째로 안 세어진다"


@pytest.mark.parametrize("tool", sorted(REAL))
def test_출처가_실제로_잡힌다(tool):
    """★ 이게 이 파일의 핵심.

    등록만 하고 키가 안 맞으면 `record_for` 가 **None** 을 준다. 그러면 아무
    에러도 안 나고 그냥 원장에 안 실린다 — 앞 사람이 「조용히 무동작」이라고
    부른 그것이다. 여기서 잡는다.
    """
    arguments, evidence = REAL[tool]
    record = record_for(
        tool, arguments=arguments, evidence=evidence, ok=True, job_id="j", step=1
    )
    assert record is not None, f"{tool}: 출처를 못 잡았다 — 조용한 무동작이다"
    assert record.source_id, f"{tool}: source_id 가 비었다"


def test_리스트로_오는_출처도_잡는다():
    """실측: `target_labels` 와 `command` 는 문자열이 아니라 **목록**으로 온다."""
    record = record_for(
        "admission_quant_lookup",
        arguments={"target_labels": ["경희대학교 컴퓨터공학과", "한양대학교 컴퓨터소프트웨어학부"]},
        evidence={"ok": True, "targets": [{"a": 1}]},
        ok=True,
        job_id="j",
        step=1,
    )
    assert record is not None
    assert "경희대학교" in record.source_id and "한양대학교" in record.source_id


def test_조회가_서로_다른_출처로_남는다():
    """다른 학과를 물었으면 다른 출처다.

    `source` 키(= "jetson_quant_db")를 출처로 썼으면 여기서 둘이 같아진다 —
    그러면 「같은 곳을 또 읽었다」가 되어 두 번째 조회가 안 세어진다.
    """
    def dig(label):
        return record_for(
            "admission_quant_lookup",
            arguments={"target_labels": [label]},
            evidence={"ok": True, "source": "jetson_quant_db", "targets": [{"a": 1}]},
            ok=True, job_id="j", step=1,
        ).source_id

    assert dig("경희대학교 컴퓨터공학과") != dig("한양대학교 컴퓨터소프트웨어학부")


@pytest.mark.parametrize(
    "tool",
    ["admission_quant_lookup", "admission_major_profile_lookup",
     "admission_major_semantic_search", "admission_candidates_by_grade",
     "career_strategy_lookup", "admission_probability_simulate"],
)
def test_자사데이터는_읽은_것으로_센다(tool):
    """자료 자체를 돌려주는 도구다 — 더 열 것이 없으니 목록이 아니라 본문이다."""
    assert MANIFEST[tool].type == TYPE_BODY_READ


def test_명령_실행은_읽은_것이_아니다():
    """`local_run_project_command` 는 검증이다.

    `stdout` 을 본문으로 삼으면 pytest 로그가 근거 대조의 원문이 되어, 답에 적은
    이름이 로그에 우연히 있으면 경고가 지워진다. 돌려서 통과했다는 **사실**이지
    읽은 **자료**가 아니다.
    """
    spec = MANIFEST["local_run_project_command"]
    assert spec.type == TYPE_VERIFICATION
    assert spec.body_keys == (), "검증 결과를 근거 원문으로 쓰면 안 된다"


def test_자사데이터_원문이_근거대조에_실제로_들어간다():
    """★ 이 등록이 실제로 고치는 것.

    등록 전에는 자사 데이터로만 답한 판의 원문이 **0 건**이었다. 그러면 맞게
    답해도 「읽지 않고 적었다」 경고가 서고, 정찰기도 못 지운다(지울 근거가
    원장에 없으니까).
    """
    record = record_for(
        "career_strategy_lookup",
        arguments={"major": "간호학과"},
        evidence={"ok": True, "evidence_items": [{"title": "간호사"}]},
        ok=True, job_id="j", step=3,
    )
    assert record is not None
    # 원장은 dict 로 저장된다(`asdict`). 검사도 같은 모양으로 넘긴다 — 사본을
    # 손으로 만들면 실제 경로와 어긋난다.
    body = read_bodies(
        [asdict(record)],
        lambda job_id, step: "간호사 (공식 종목코드 0731) · 보건교사",
    )
    assert "보건교사" in body, "자사 데이터 원문이 근거 대조에 안 들어간다"
