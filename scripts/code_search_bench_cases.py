"""「어디를 고쳐야 하나」를 찾는 능력의 고정 눈금.

24과제 벤치는 고칠 파일이 사실상 지목된 판만 잰다. 실제 일감의 대부분은
**자리를 먼저 찾는 것**인데 그 능력은 한 번도 안 쟀다. 여기서는 코드를 고치지
않는다 — 증상만 주고 정답 파일이 상위 K에 들어오는지만 본다. LLM 없이도 돌아서
반복이 빠르고, 색인을 바꿀 때마다 개선폭이 바로 숫자로 나온다.

두 티어를 섞는다:

* ``documented`` — 그 파일 첫 줄 설명을 사람 말로 바꾼 질의. 본문(독스트링)을
  색인하면 잡히고, 이름만 색인하면 못 잡는다.
* ``symptom`` — 문서 어디에도 안 적힌 증상. 2026-08-27 하루 동안 실제로 찾아야
  했던 자리들이다. 이쪽이 진짜 시험이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SearchCase:
    key: str
    tier: str
    query: str
    answers: tuple[str, ...]
    # 정답 파일 안에 실제로 있어야 하는 문자열. 정답이 낡으면 눈금이 조용히
    # 거짓말을 하므로, 매 실행 전에 이 앵커로 정답 자체를 검증한다.
    anchors: tuple[str, ...] = field(default_factory=tuple)


_SRC = "src/alture_jarvis"


def _case(key, tier, query, answers, anchors=()):
    return SearchCase(
        key=key,
        tier=tier,
        query=query,
        answers=tuple(f"{_SRC}/{name}" for name in answers),
        anchors=tuple(anchors),
    )


CASES: tuple[SearchCase, ...] = (
    # ── documented: 첫 줄 설명을 사람 말로 ──────────────────────────────
    _case("doc_transcript", "documented",
          "모델 창에 무엇을 남기고 무엇을 버릴지 정하는 곳",
          ("transcript.py",), ("def bounded(",)),
    _case("doc_attention", "documented",
          "사람이 화면을 봐야 하는 순간을 알려 주는 부분",
          ("attention.py",)),
    _case("doc_watch", "documented",
          "자비스가 사람에게 먼저 말을 거는 자리",
          ("watch.py", "watch_service.py")),
    _case("doc_sandbox", "documented",
          "버려도 되는 상자를 만들어 그 안에서 코드를 돌리는 곳",
          ("sandbox.py",)),
    _case("doc_plan", "documented",
          "시킨 일을 하나씩 세어 두었다가 끝에 대조하는 장부",
          ("plan.py",)),
    _case("doc_site_atlas", "documented",
          "사람이 부르는 가게 이름을 실제 주소로 바꿔 주는 곳",
          ("site_atlas.py",)),
    _case("doc_shell_probe", "documented",
          "아무것도 못 바꾸는 읽기 전용 셸",
          ("shell_probe.py",)),
    _case("doc_peer_guard", "documented",
          "누가 이 API에 닿을 수 있는지 막아 주는 문지기",
          ("peer_guard.py",)),
    _case("doc_proof", "documented",
          "승인한 작업을 실행 전 대상과 실행 후 증거에 묶는 계약",
          ("proof.py",)),
    _case("doc_fact_extract", "documented",
          "대화에서 기억할 사실을 뽑아내는 부분",
          ("fact_extract.py", "memory.py")),
    _case("doc_self_care", "documented",
          "자비스가 자기 몸 상태를 살피고 정해진 것만 고치는 곳",
          ("self_care.py",)),
    _case("doc_serp", "documented",
          "검색 결과 화면을 브라우저 없이 목록으로 바꾸는 곳",
          ("serp.py",)),
    _case("doc_updater", "documented",
          "노트북에 있는 위성을 본체에서 갱신하는 부분",
          ("updater.py",)),
    _case("doc_mission", "documented",
          "긴 작업이 판을 건너가도 잃으면 안 되는 임무 장부",
          ("mission.py",)),

    # ── symptom: 문서에 없다. 오늘 실제로 찾아야 했던 자리들 ────────────
    _case("sym_prefix_cache", "symptom",
          "코딩이 느리다. 매 걸음마다 프롬프트를 통째로 다시 읽는 것 같다",
          ("transcript.py",), ("keep_recent_tools",)),
    _case("sym_model_evicted", "symptom",
          "코드 작업 중에 다른 모델이 GPU에서 코더를 밀어낸다",
          ("ollama.py", "runtime.py"), ("pin_role",)),
    _case("sym_multifile_delegated", "symptom",
          "파일 두 개를 고치라고 하면 로컬이 시도도 안 하고 밖으로 넘긴다",
          ("claude_code.py",), ("initial_delegation_reason",)),
    _case("sym_edit_approval", "symptom",
          "파일을 고칠 때 승인 카드가 뜰지 말지를 정하는 판정",
          ("local_computer.py",), ("_mutation_risk",)),
    _case("sym_job_waiting", "symptom",
          "잡이 승인 대기 상태로 바뀌어 멈추는 자리",
          ("jobs.py",), ("WAITING_APPROVAL",)),
    _case("sym_approval_ttl", "symptom",
          "승인 창이 너무 빨리 닫혀서 오래 걸리는 작업을 되살릴 수 없다",
          ("config.py", "tool_gateway.py"), ("approval_ttl_sec",)),
    _case("sym_scout_rank", "symptom",
          "보조 모델이 후보 경로를 지어내면 버리고 원래 순위로 돌아가는 곳",
          ("code_scout.py",), ("normalize_scout_report",)),
    _case("sym_tool_risk_gate", "symptom",
          "도구를 실행하기 전에 위험 등급을 보고 승인을 요구하는 관문",
          ("tool_gateway.py",), ("effective_risk",)),
    _case("sym_which_model_role", "symptom",
          "코드 작업일 때 어떤 모델 태그를 쓸지 고르는 곳",
          ("config.py", "ollama.py"), ("model_for",)),
    _case("sym_undo_offer", "symptom",
          "방금 한 쓰기를 되돌릴 수 있게 걸어 두는 장치",
          ("tool_gateway.py", "local_computer.py"), ("InverseSpec",)),
)


def verify_ground_truth(root: Path) -> list[str]:
    """정답이 아직 사실인가. 낡은 정답은 눈금을 조용히 거짓말시킨다."""
    problems: list[str] = []
    for case in CASES:
        for answer in case.answers:
            if not (root / answer).is_file():
                problems.append(f"{case.key}: 정답 파일 없음 {answer}")
        if not case.anchors:
            continue
        blob = "\n".join(
            (root / answer).read_text(encoding="utf-8", errors="replace")
            for answer in case.answers
            if (root / answer).is_file()
        )
        for anchor in case.anchors:
            if anchor not in blob:
                problems.append(f"{case.key}: 앵커가 사라졌다 {anchor!r}")
    return problems


assert len({case.key for case in CASES}) == len(CASES)
