"""**성공했다는데 산출물이 빈** 자리를 매일 찾아내는가.

## 왜 필요한가 — 상업화의 최소 조건

2026-08-23 하루에 조용한 실패를 넷 밟았고, 전부 같은 모양이었다:

    빈 메일   `gmail_send ok=True` · 본문 0자 — **이틀간 아무도 몰랐다**
    축출      워치독 프로브 성공 · 그런데 자비스 모델을 GPU 에서 밀어냄
    위성      정상 동작 · 그런데 본체를 느리게 만듦(표시 0)
    창작      답이 나옴 · 그런데 도구 0걸음

**어느 층도 에러를 안 냈다.** 그래서 "실패를 잡는" 검사로는 안 잡힌다. 반대쪽으로
잡아야 한다 — **성공 기록을 열어 산출물이 비었는지 본다.**

사용자님 집에서는 사용자님이 눈치챈다. **고객 자리에서는 아무도 로그를 안 본다.**
그래서 이 기관은 매일 07:00 자기점검 메일에 실려 나간다.

실측(2026-08-23, 진짜 장부): 빈 커밋 1건(그날 아침 빈 메일) · 도구 없이 긴 답 9건.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from alture_jarvis.self_care import SelfCare


def _seed(db_path: Path, *, empty_commit: bool, fabricated: bool) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "create table if not exists external_actions "
        "(action_id text, kind text, payload_json text, status text, created_at real)"
    )
    conn.execute(
        "create table if not exists jobs "
        "(id text, status text, result_json text, created_at real)"
    )
    now = time.time()
    body = "" if empty_commit else "오늘 아침 자기점검: 다섯 기관 모두 정상."
    conn.execute(
        "insert into external_actions values (?,?,?,?,?)",
        ("a1", "gmail_send", json.dumps({"body_text": body}, ensure_ascii=False), "committed", now),
    )
    trace = {"steps": [] if fabricated else [{"tool": "browser_extract", "ok": True}]}
    conn.execute(
        "insert into jobs values (?,?,?,?)",
        ("j1", "completed", json.dumps({"agent_trace": trace, "answer": "가" * 500},
                                       ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()


def _probe(tmp_path: Path, **seed) -> dict:
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          output_dir=tmp_path / "out",
                          # ★ 2026-09-20: 이 기관의 ③번(축출)은 **이 PC 의 진짜 Ollama** 에 물어본다. 벤치하느라
                          #   다른 모델을 올려 둔 날에는 「남의 모델이 GPU 를 차지함」이 나와 「조용한 실패 없음」
                          #   시험이 깨졌다 — 눈금이 기계 상태를 읽은 것이다. 죽은 포트로 돌려 판을 고정하고,
                          #   축출 판정 자체는 아래 `test_a_foreign_model_on_the_gpu_is_reported` 가 따로 잰다.
                          ollama_base_url="http://127.0.0.1:1",
                          # 코더를 따로 둔 설치(운영 PC) — 공개 기본값은 코드 모델이 비어 대화 모델을 쓴다.
                          model_roles={"chat": "gemma4:26b-a4b-it-qat", "code": "qwen3.8:27b-mtp-q4_K_M",
                                       "vision": "gemma4:26b-a4b-it-qat"})
    _seed(config.data_dir / "jarvis.db", **seed)
    care = SelfCare(config, EventBus())
    return care._check_silent()


def test_an_empty_commit_is_reported(tmp_path: Path) -> None:
    """★ 그날 아침의 빈 메일 그대로 — 보냈다는데 본문이 없다."""
    organ = _probe(tmp_path, empty_commit=True, fabricated=False)

    assert organ["state"] == "down"
    assert "빈 채로" in organ["detail"]
    assert organ["evidence"]["빈_커밋"] == 1


def test_a_long_answer_with_no_tools_is_reported(tmp_path: Path) -> None:
    """도구를 하나도 안 쓰고 길게 답했으면 창작을 의심한다."""
    organ = _probe(tmp_path, empty_commit=False, fabricated=True)

    assert organ["state"] == "down"
    assert "창작 의심" in organ["detail"]


def test_a_healthy_day_says_so(tmp_path: Path) -> None:
    organ = _probe(tmp_path, empty_commit=False, fabricated=False)

    assert organ["state"] == "ok"
    assert "없음" in organ["detail"]


def test_a_missing_ledger_is_unknown_not_ok(tmp_path: Path) -> None:
    """★ 못 본 것을 「이상 없음」으로 적으면 안 된다.

    빈 값 하나가 두 사실을 뜻하는 그 함정이다 — "봤는데 0건"과 "못 봤다"는 다르다.
    """
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "empty",
                          output_dir=tmp_path / "out")
    organ = SelfCare(config, EventBus())._check_silent()

    assert organ["state"] == "unknown"


def test_the_organ_is_wired_into_the_daily_check() -> None:
    """★ 만들어 놓고 안 부르면 없는 것과 같다 — 이 저장소가 여러 번 당한 자리다."""
    assert "silent" in SelfCare._PROBES
    assert SelfCare._PROBES["silent"] == "_check_silent"


@pytest.mark.parametrize("field", ["body_text", "summary", "description", "content"])
def test_any_content_field_counts_as_not_empty(tmp_path: Path, field: str) -> None:
    """커밋 종류마다 본문이 담기는 칸 이름이 다르다 — 하나만 보면 헛경보가 난다."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          output_dir=tmp_path / "out")
    db = config.data_dir / "jarvis.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("create table external_actions "
                 "(action_id text, kind text, payload_json text, status text, created_at real)")
    conn.execute("create table jobs (id text, status text, result_json text, created_at real)")
    conn.execute(
        "insert into external_actions values (?,?,?,?,?)",
        ("a1", "x", json.dumps({field: "내용 있음"}, ensure_ascii=False), "committed", time.time()),
    )
    conn.commit()
    conn.close()

    organ = SelfCare(config, EventBus())._check_silent()
    assert organ["evidence"]["빈_커밋"] == 0, f"{field} 에 내용이 있는데 비었다고 한다"


def _resident(monkeypatch, names: list[str]) -> None:
    """상주 모델 응답을 고정한다.

    이 검사는 예전에 **실제 GPU 에 무엇이 올라와 있는지**에 따라 통과·실패가
    갈렸다. 2026-08-27 코딩 벤치가 도는 동안 코더가 3090 을 차지하자 조용히
    빨간불이 됐다. 기계 상태에 기대는 단위 검사는 검사가 아니다.
    """
    import io
    import urllib.request

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    payload = json.dumps({"models": [{"name": name} for name in names]}).encode("utf-8")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _Response(payload)
    )


def test_our_own_coder_holding_the_gpu_is_not_a_silent_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """Code 잡이 도는 동안 코더가 GPU 를 쥐는 것은 의도된 동작이다."""
    _resident(monkeypatch, ["qwen3.8:27b-mtp-q4_K_M"])

    organ = _probe(tmp_path, empty_commit=False, fabricated=False)

    assert organ["state"] == "ok", organ["detail"]


def test_a_stranger_model_holding_the_gpu_is_still_reported(
    tmp_path: Path, monkeypatch
) -> None:
    _resident(monkeypatch, ["llama3:70b"])

    organ = _probe(tmp_path, empty_commit=False, fabricated=False)

    assert organ["state"] == "down"
    assert "우리 것이 아닌" in organ["detail"]
